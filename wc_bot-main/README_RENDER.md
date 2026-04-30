# Deploy WordCounter DSC on Render (Free)

## 1) Push to GitHub
- Ensure `.env`, `.venv/`, and `word_counts.db` are NOT committed (see `.gitignore`).

## 2) Create on Render
- New → **Blueprint** (recommended) and select this repo.
- Render will read `render.yaml` and create:
  - a **worker** service
  - a **Postgres** database

## 3) Set secrets
In the service → Environment:
- `DISCORD_TOKEN` = your Bot Token (keep it secret)

Render will auto-wire `DATABASE_URL` from the created Postgres.

## 4) Discord Developer Portal settings
- Bot → **Privileged Gateway Intents** → enable **Message Content Intent** (needed for counting messages)

## 5) Invite the bot to your server
OAuth2 URL Generator scopes:
- `bot`
- `applications.commands`

Recommended permissions:
- View Channels
- Send Messages
- Embed Links
- Read Message History (needed for backfill)
- Use Application Commands

## 6) Start
Render will automatically deploy on push.

## Notes
- Free services can restart; Postgres keeps your data.
- If commands don’t appear immediately, wait 1–2 minutes or restart the service to re-sync.
