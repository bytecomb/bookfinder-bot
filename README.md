# BookFinderBot (public-domain edition)

Telegram bot that searches **Project Gutenberg** and **Open Library** (public-domain / openly licensed titles only) and sends the file in chat.

## Environment
| Var | Notes |
|---|---|
| `BOT_TOKEN` | from @BotFather |
| `OWNER_IDS` | comma-separated Telegram numeric user IDs (lock/unlock/broadcast/restart) |
| `REQUEST_GROUP_ID` / `REQUEST_GROUP_LINK` / `REQUEST_GROUP_USERNAME` | optional group for `#request` |
| `USE_WEBHOOK` | `true` on Render (free services sleep, polling would stop) |
| `WEBHOOK_URL` | optional; defaults to Render's `RENDER_EXTERNAL_URL` |
| `MAX_FILE_SIZE_MB` | default 45 (Telegram bot upload limit is 50 MB) |

## Deploy on Render (free)
New → Blueprint → this repo. Fill `BOT_TOKEN` and `OWNER_IDS`. Data in `/app/data` is ephemeral on the free plan.

## Usage
DM or group: `#request pride and prejudice`, then tap `/book_...`.
