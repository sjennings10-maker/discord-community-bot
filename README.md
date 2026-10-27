# Discord Community Bot — beginner setup

One bot with AI chat, automatic welcome messages, basic moderation, and slash commands.

## Features
- `/ask question:` — AI chat, limited to 3 requests/member/minute by default
- Welcome message when a new member joins
- Deletes configured blocked phrases, bursts of spam, or messages with 5+ links
- `/rules`, `/help`, `/ping`
- Staff-only `/announce`, `/timeout`, `/kick`
- Private moderation log channel

**Important:** Moderation is basic, not a substitute for Discord AutoMod or human moderators. This bot does not automatically ban members. AI is opt-in by using `/ask`, not passive reading of all messages.

## 1. Create your bot in Discord
1. Visit https://discord.com/developers/applications and click **New Application**.
2. Choose a name. In **Bot**, create/configure the bot and copy/reset its token.
3. Under **Bot > Privileged Gateway Intents**, enable **Server Members Intent** and **Message Content Intent**.
4. Under **Installation**, enable **Guild Install** and select `bot` and `applications.commands`.
5. Authorize these permissions: **View Channels**, **Send Messages**, **Read Message History**, **Manage Messages**, **Moderate Members**, and **Kick Members**. No Administrator permission needed.
6. Open the install link, choose your server, and approve.
7. In **Server Settings > Roles**, move the bot role ABOVE the ordinary member roles it may need to moderate. Keep it below trusted administrators.
8. For each channel the bot uses, verify the bot has channel access. Allow it to post in your read-only announcements channel if using `/announce` there.

**Never share your bot token or AI key.** If a token leaks, reset it immediately.

## 2. Set up channels
Suggested: `#welcome`, `#rules`, `#announcements`, `#ai-chat`, `#mod-logs`, `#general-chat`.
Make `#mod-logs` private to staff and the bot.
Right-click a channel > **Copy Channel ID** (enable Developer Mode under Discord Settings > Advanced if necessary).
Right-click your server > **Copy Server ID** for GUILD_ID.

## 3. Get an AI key (optional, required for /ask)
1. Visit https://platform.openai.com/api-keys .
2. Create an API key and configure API billing and spending limits as needed.
3. Store it as OPENAI_API_KEY in hosting environment variables.
4. API use is billed separately from ChatGPT subscriptions. The default model is `gpt-4.1-mini`; change OPENAI_MODEL if needed.

## 4. Host online with Railway (GitHub method)
1. Create a **private** repository at https://github.com/new .
2. Upload `bot.py`, `requirements.txt`, `Dockerfile`, `railway.json`, `.gitignore`, and this README.
   Do **not** upload `.env` or any keys. You may upload `.env.example` (it contains placeholders only).
3. Go to https://railway.com and sign in.
4. Create a new project > **Deploy from GitHub repo** > choose the repository.
5. In the Railway service **Variables** section, add:
   - `DISCORD_TOKEN` (required)
   - `OPENAI_API_KEY` (required for AI)
   - `GUILD_ID` (your test server ID; recommended)
   - `WELCOME_CHANNEL_ID`
   - `MOD_LOG_CHANNEL_ID`
   - `AI_CHANNEL_ID`
   - `RULES_CHANNEL_ID`
   - `BLOCKED_PHRASES` (optional, comma-separated)
   - `OPENAI_MODEL` = `gpt-4.1-mini` (optional)
6. Deploy/redeploy the service. The Dockerfile runs `python bot.py` as a persistent worker. **No public web domain or port is needed.**
7. Open **Logs**. Look for `Logged in as ...` and `Synced commands ...`.
8. Check `/ping`, `/rules`, `/ask` and welcome messages in Discord.

Railway hosting may cost money and pricing/menus can change. Ensure your plan supports a continuously running service. Only run one replica to avoid duplicate event handling.

## 5. Local testing instead (optional)
Install Python 3.12+, open a terminal in this folder, and run:

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your real secrets and IDs; do not share it
python bot.py
```

## 6. Customize
- Welcome text: change the message in `on_member_join` in `bot.py`.
- Rules: change the `/rules` response in `bot.py`.
- AI personality: edit the `instructions` string in `/ask`.
- Spam thresholds: adjust the `on_message` checks.
- AI-only channel: set `AI_CHANNEL_ID`. Leave blank to permit `/ask` in all accessible channels.
- For an owner-only announcement channel, deny `@everyone` Send Messages and allow the bot role. The `/announce` command requires **Manage Server** permission, so ordinary members cannot invoke it.

## 7. Troubleshooting
- Bot offline: inspect Railway logs and verify `DISCORD_TOKEN`.
- Commands missing: check `applications.commands` scope, `GUILD_ID`, and bot logs; global commands may take time to appear.
- No welcome messages: enable **Server Members Intent**, set `WELCOME_CHANNEL_ID`, and check Send Messages permissions.
- No moderation: enable **Message Content Intent**, allow Manage Messages, and ensure the bot can view the channel.
- `/kick` or `/timeout` fails: check bot role hierarchy and granted permissions.
- AI error: check OPENAI_API_KEY, API billing, model availability, and Railway logs.
- Discord's own AutoMod is recommended in addition to this bot.

## Security and privacy
- Never paste secrets into Discord messages, screenshots, GitHub commits, or chat.
- `/ask` sends the user's question to the configured AI provider; tell your community.
- This bot reads message content for moderation and keeps short-lived timestamps in memory.
- No message database is used. Moderation logs record usernames, IDs, channel names, and reasons, not deleted message text.
- Keep dependencies updated, restrict bot permissions, and configure API spending limits.
