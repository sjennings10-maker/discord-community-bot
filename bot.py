import asyncio
import logging
import os
import re
import time
from collections import defaultdict, deque

import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from openai import AsyncOpenAI

load_dotenv()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("community-bot")

def integer_env(name, default=0):
    value = os.getenv(name, "").strip()
    try:
        return int(value) if value else default
    except ValueError:
        raise RuntimeError(f"{name} must be a numeric Discord ID.")

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
OPENAI_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")
GUILD_ID = integer_env("GUILD_ID")
WELCOME_CHANNEL_ID = integer_env("WELCOME_CHANNEL_ID")
MOD_LOG_CHANNEL_ID = integer_env("MOD_LOG_CHANNEL_ID")
AI_CHANNEL_ID = integer_env("AI_CHANNEL_ID")
RULES_CHANNEL_ID = integer_env("RULES_CHANNEL_ID")
BLOCKED_PHRASES = [
    phrase.strip().casefold()
    for phrase in os.getenv("BLOCKED_PHRASES", "").split(",")
    if phrase.strip()
]
AI_LIMIT = max(1, integer_env("AI_REQUESTS_PER_MINUTE", 3))

if not TOKEN:
    raise RuntimeError("Set DISCORD_TOKEN in your environment variables.")

intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
ai_client = AsyncOpenAI(api_key=OPENAI_KEY, timeout=30.0) if OPENAI_KEY else None

# These limits are stored in memory and reset when the bot restarts.
recent_ai = defaultdict(deque)
recent_messages = defaultdict(deque)
last_moderation = {}
url_re = re.compile(r"https?://\S+", re.IGNORECASE)

async def log_mod(guild, message):
    channel = guild.get_channel(MOD_LOG_CHANNEL_ID) if MOD_LOG_CHANNEL_ID else None
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(message[:1900], allowed_mentions=discord.AllowedMentions.none())
        except discord.DiscordException:
            log.exception("Unable to post moderation log")

@bot.event
async def on_ready():
    log.info("Logged in as %s (%s)", bot.user, bot.user.id)

@bot.event
async def on_member_join(member):
    channel = member.guild.get_channel(WELCOME_CHANNEL_ID) if WELCOME_CHANNEL_ID else None
    if isinstance(channel, discord.TextChannel):
        try:
            await channel.send(
                f"🎉 Welcome to **{discord.utils.escape_markdown(member.guild.name)}**, "
                f"{member.mention}! Please read the rules and say hello!",
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.DiscordException:
            log.exception("Unable to send welcome message")

@bot.event
async def on_message(message):
    if message.author.bot or not message.guild or not isinstance(message.author, discord.Member):
        return
    # Moderation applies only to non-staff members.
    if message.author.guild_permissions.manage_messages:
        return
    content = message.content.casefold()
    now = time.monotonic()
    key = (message.guild.id, message.author.id)
    timestamps = recent_messages[key]
    while timestamps and now - timestamps[0] > 8:
        timestamps.popleft()
    timestamps.append(now)

    reason = None
    if BLOCKED_PHRASES and any(phrase in content for phrase in BLOCKED_PHRASES):
        reason = "blocked phrase"
    elif len(timestamps) >= 7:
        reason = "message spam (7 messages in 8 seconds)"
    elif len(url_re.findall(message.content)) >= 5:
        reason = "excessive links"

    if reason:
        try:
            await message.delete()
            # Prevent repeated public warnings
            if now - last_moderation.get(key, 0) > 15:
                last_moderation[key] = now
                await message.channel.send(
                    f"{message.author.mention}, your message was removed ({reason}).",
                    delete_after=8,
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
            await log_mod(
                message.guild,
                f"🛡️ Removed a message by {message.author} ({message.author.id}) "
                f"in #{message.channel}: {reason}.",
            )
        except discord.Forbidden:
            log.warning("Missing Manage Messages permission in %s", message.channel)
        except discord.DiscordException:
            log.exception("Moderation action failed")

@bot.event
async def setup_hook():
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
        log.info("Synced commands to test server %s", GUILD_ID)
    else:
        await bot.tree.sync()
        log.info("Synced global commands (may take time to appear)")

@bot.tree.command(name="ask", description="Ask the AI assistant a question")
@app_commands.describe(question="Your question for the AI")
@app_commands.checks.cooldown(1, 10.0, key=lambda i: (i.guild_id, i.user.id))
async def ask(interaction: discord.Interaction, question: str):
    if not interaction.guild:
        await interaction.response.send_message("Use this command in the server.", ephemeral=True)
        return
    if AI_CHANNEL_ID and interaction.channel_id != AI_CHANNEL_ID:
        await interaction.response.send_message(
            f"Please use <#{AI_CHANNEL_ID}> for AI questions.", ephemeral=True
        )
        return
    if not ai_client:
        await interaction.response.send_message(
            "AI is not configured yet. An admin needs to add OPENAI_API_KEY.", ephemeral=True
        )
        return
    if len(question) > 1500:
        await interaction.response.send_message("Keep your question under 1,500 characters.", ephemeral=True)
        return
    key = (interaction.guild_id, interaction.user.id)
    now = time.monotonic()
    history = recent_ai[key]
    while history and now - history[0] >= 60:
        history.popleft()
    if len(history) >= AI_LIMIT:
        await interaction.response.send_message("You're sending questions too quickly. Try again in a minute.", ephemeral=True)
        return
    history.append(now)
    await interaction.response.defer(thinking=True)
    try:
        response = await ai_client.responses.create(
            model=OPENAI_MODEL,
            instructions=(
                "You are a helpful, friendly Discord community assistant. "
                "Be concise and respectful. Do not claim to be a human or server moderator. "
                "Do not reveal secrets or pretend to have Discord permissions you lack."
            ),
            input=question,
            max_output_tokens=450,
        )
        answer = response.output_text.strip() or "I couldn't generate a response."
        # Discord message limit; split safely into multiple replies.
        for start in range(0, len(answer), 1900):
            await interaction.followup.send(
                answer[start:start+1900],
                allowed_mentions=discord.AllowedMentions.none(),
            )
    except Exception:
        log.exception("AI request failed")
        await interaction.followup.send(
            "Sorry, the AI service is unavailable right now. Try again later.",
            ephemeral=True,
        )

@ask.error
async def ask_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.CommandOnCooldown):
        if not interaction.response.is_done():
            await interaction.response.send_message(
                f"Wait {error.retry_after:.0f} seconds before asking again.", ephemeral=True
            )
    else:
        log.error("Ask command failed: %s", error)
        if not interaction.response.is_done():
            await interaction.response.send_message("Something went wrong.", ephemeral=True)

@bot.tree.command(name="ping", description="Check whether the bot is online")
async def ping(interaction: discord.Interaction):
    await interaction.response.send_message(f"🏓 Pong! {round(bot.latency * 1000)} ms")

@bot.tree.command(name="help", description="Show available commands")
async def help_command(interaction: discord.Interaction):
    await interaction.response.send_message(
        "**Community Bot Commands**\n"
        "🤖 `/ask` — Ask the AI a question\n"
        "📌 `/rules` — View server rules\n"
        "🏓 `/ping` — Check bot status\n"
        "📣 `/announce` — Staff announcement\n"
        "🕒 `/timeout` — Staff timeout\n"
        "🦶 `/kick` — Staff kick\n"
        "❓ `/help` — Show this list",
        ephemeral=True,
    )

@bot.tree.command(name="rules", description="Display the community rules")
async def rules(interaction: discord.Interaction):
    channel = f" Read the full rules in <#{RULES_CHANNEL_ID}>." if RULES_CHANNEL_ID else ""
    await interaction.response.send_message(
        "**Community Rules**\n"
        "1. Be respectful; no harassment or hate.\n"
        "2. No spam, scams, or malicious links.\n"
        "3. Keep content appropriate for the channel.\n"
        "4. Respect staff decisions and Discord's rules."
        + channel,
        allowed_mentions=discord.AllowedMentions.none(),
    )

@bot.tree.command(name="announce", description="Post a staff announcement in this channel")
@app_commands.default_permissions(manage_guild=True)
@app_commands.checks.has_permissions(manage_guild=True)
@app_commands.describe(message="Announcement text")
async def announce(interaction: discord.Interaction, message: str):
    if not interaction.guild or not isinstance(interaction.channel, discord.TextChannel):
        await interaction.response.send_message("Use this in a server text channel.", ephemeral=True)
        return
    if len(message) > 1750:
        await interaction.response.send_message("Announcement must be 1,750 characters or fewer.", ephemeral=True)
        return
    try:
        await interaction.channel.send(
            "📣 **Announcement**\n" + message,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        await interaction.response.send_message("Announcement posted.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("I can't post in this channel.", ephemeral=True)

@bot.tree.command(name="timeout", description="Temporarily mute a member (staff only)")
@app_commands.default_permissions(moderate_members=True)
@app_commands.checks.has_permissions(moderate_members=True)
@app_commands.describe(member="Member to timeout", minutes="Duration, 1–10080 minutes", reason="Reason")
async def timeout(interaction: discord.Interaction, member: discord.Member, minutes: app_commands.Range[int, 1, 10080], reason: str = "Rule violation"):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    if member.id == interaction.user.id or member.id == interaction.guild.owner_id:
        await interaction.response.send_message("You cannot timeout yourself or the owner.", ephemeral=True)
        return
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("That member has an equal or higher role.", ephemeral=True)
        return
    try:
        await member.timeout(discord.utils.utcnow() + __import__("datetime").timedelta(minutes=minutes), reason=reason[:400])
        await interaction.response.send_message(f"Timed out {member.mention} for {minutes} minutes.", ephemeral=True)
        await log_mod(interaction.guild, f"🕒 {interaction.user} timed out {member} for {minutes} min. Reason: {reason[:300]}")
    except discord.Forbidden:
        await interaction.response.send_message("I lack permission or my role is too low.", ephemeral=True)

@bot.tree.command(name="kick", description="Remove a member from the server (staff only)")
@app_commands.default_permissions(kick_members=True)
@app_commands.checks.has_permissions(kick_members=True)
@app_commands.describe(member="Member to kick", reason="Reason")
async def kick(interaction: discord.Interaction, member: discord.Member, reason: str = "Rule violation"):
    if not interaction.guild or not isinstance(interaction.user, discord.Member):
        await interaction.response.send_message("Use this in a server.", ephemeral=True)
        return
    if member.id == interaction.user.id or member.id == interaction.guild.owner_id:
        await interaction.response.send_message("You cannot kick yourself or the owner.", ephemeral=True)
        return
    if member.top_role >= interaction.user.top_role and interaction.user.id != interaction.guild.owner_id:
        await interaction.response.send_message("That member has an equal or higher role.", ephemeral=True)
        return
    try:
        await member.kick(reason=reason[:400])
        await interaction.response.send_message(f"Kicked {member}.", ephemeral=True)
        await log_mod(interaction.guild, f"🦶 {interaction.user} kicked {member}. Reason: {reason[:300]}")
    except discord.Forbidden:
        await interaction.response.send_message("I lack permission or my role is too low.", ephemeral=True)

@announce.error
@timeout.error
@kick.error
async def staff_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        message = "You don't have permission to use this command."
    else:
        log.error("Staff command error: %s", error)
        message = "The command failed. Check permissions and role hierarchy."
    if not interaction.response.is_done():
        await interaction.response.send_message(message, ephemeral=True)

if __name__ == "__main__":
    bot.run(TOKEN, log_handler=None)
