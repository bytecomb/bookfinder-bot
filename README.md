# BookFinderBot

Telegram bot that searches books across 7 sources and sends the file in chat.

## Book Sources (priority order)
| # | Source | Notes |
|---|---|---|
| 1 | Z-Library | needs `ZLIB_EMAIL` / `ZLIB_PASSWORD` (or `ZLIB_COOKIES`); uses DoH to bypass DNS blocks |
| 2 | Libgen | libgen.is mirrors |
| 3 | Anna's Archive | DoH + multi-mirror fallback; no direct download |
| 4 | Internet Archive | public API, no auth needed |
| 5 | PDFDrive | search page scraping |
| 6 | Project Gutenberg | public domain |
| 7 | Open Library | publicly downloadable items only |

## Environment
| Var | Notes |
|---|---|
| `BOT_TOKEN` | from @BotFather |
| `OWNER_IDS` | comma-separated Telegram numeric user IDs (lock/unlock/broadcast/restart) |
| `ZLIB_EMAIL` / `ZLIB_PASSWORD` | Z-Library login (or use `ZLIB_COOKIES` Netscape format) |
| `ENABLE_ZLIBRARY` / `ENABLE_LIBGEN` / `ENABLE_ANNAS` / `ENABLE_ARCHIVE` / `ENABLE_PDFDRIVE` / `ENABLE_GUTENBERG` / `ENABLE_OPENLIBRARY` | `true`/`false`, all default `true` |
| `REQUEST_GROUP_ID` / `REQUEST_GROUP_LINK` / `REQUEST_GROUP_USERNAME` | optional group for `#request` |
| `USE_WEBHOOK` | `true` on Render (free services sleep, polling would stop) |
| `WEBHOOK_URL` | optional; defaults to Render's `RENDER_EXTERNAL_URL` |
| `MAX_FILE_SIZE_MB` | default 45 (Telegram bot upload limit is 50 MB) |

## Deploy on Render (free)
New → Blueprint → this repo. Fill `BOT_TOKEN` and `OWNER_IDS`. Data in `/app/data` is ephemeral on the free plan.

## Usage
DM or group: `#request pride and prejudice`, then tap `/book_...`.
