"""
Configuration for BookFinderBot
All sensitive values should be set via environment variables.
Hard-coded owner IDs and defaults are set here.
"""

import os

# ─── BOT CORE ────────────────────────────────────────────────────────────────
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "BookFinderBot")

# ─── OWNERS (comma-separated Telegram user IDs via env) ───────────────────────
OWNER_IDS: list[int] = [int(x) for x in os.getenv("OWNER_IDS", "").replace(" ", "").split(",") if x]

# Only OWNER_IDS may use the bot when true (survives restarts, unlike /lock)
OWNER_ONLY: bool = os.getenv("OWNER_ONLY", "").lower() in ("1", "true", "yes")

# ─── GROUP / CHANNEL ─────────────────────────────────────────────────────────
REQUEST_GROUP_ID: int = int(os.getenv("REQUEST_GROUP_ID", "0"))       # e.g. -1001234567890
REQUEST_GROUP_LINK: str = os.getenv("REQUEST_GROUP_LINK", "https://t.me/your_group")
REQUEST_GROUP_USERNAME: str = os.getenv("REQUEST_GROUP_USERNAME", "your_group")


# ─── START IMAGE ─────────────────────────────────────────────────────────────
START_IMAGE_URL: str = os.getenv(
    "START_IMAGE_URL",
    "https://telegra.ph/file/your-start-image.jpg"   # replace or override via env
)

# ─── LIMITS ──────────────────────────────────────────────────────────────────
MAX_FILE_SIZE_MB: int = int(os.getenv("MAX_FILE_SIZE_MB", "100"))
MAX_SEARCH_RESULTS: int = int(os.getenv("MAX_SEARCH_RESULTS", "10"))
AUTO_DELETE_HOURS: int = int(os.getenv("AUTO_DELETE_HOURS", "24"))

# ─── RENDER / WEBHOOK ────────────────────────────────────────────────────────
WEBHOOK_URL: str = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL", "")).rstrip("/")          # e.g. https://yourapp.onrender.com
PORT: int = int(os.getenv("PORT", "10000"))
USE_WEBHOOK: bool = bool(os.getenv("USE_WEBHOOK", ""))

# ─── TIMEOUTS / RETRY ────────────────────────────────────────────────────────
DOWNLOAD_TIMEOUT: int = int(os.getenv("DOWNLOAD_TIMEOUT", "120"))
REQUEST_TIMEOUT: int = int(os.getenv("REQUEST_TIMEOUT", "30"))

# ─── PRIVACY POLICY URL ──────────────────────────────────────────────────────
PRIVACY_POLICY_URL: str = os.getenv("PRIVACY_POLICY_URL", "https://telegra.ph/BookFinderBot-Privacy-Policy")

# ─── SOURCES (enable/disable) ────────────────────────────────────────────────
ENABLE_ZLIBRARY: bool = os.getenv("ENABLE_ZLIBRARY", "true").lower() == "true"
ENABLE_LIBGEN: bool = os.getenv("ENABLE_LIBGEN", "true").lower() == "true"
ENABLE_ANNAS: bool = os.getenv("ENABLE_ANNAS", "true").lower() == "true"
ENABLE_ARCHIVE: bool = os.getenv("ENABLE_ARCHIVE", "true").lower() == "true"
ENABLE_PDFDRIVE: bool = os.getenv("ENABLE_PDFDRIVE", "false").lower() == "true"  # site largely dead; keep off by default
ENABLE_GUTENBERG: bool = os.getenv("ENABLE_GUTENBERG", "true").lower() == "true"
ENABLE_OPENLIBRARY: bool = os.getenv("ENABLE_OPENLIBRARY", "true").lower() == "true"

# ─── Z-LIBRARY CREDENTIALS (env only — never hard-code) ───────────────────────
ZLIB_EMAIL: str = os.getenv("ZLIB_EMAIL", "")
ZLIB_PASSWORD: str = os.getenv("ZLIB_PASSWORD", "")
ZLIB_COOKIES: str = os.getenv("ZLIB_COOKIES", "")
ZLIB_REMIX_USERID: str = os.getenv("ZLIB_REMIX_USERID", "")
ZLIB_REMIX_USERKEY: str = os.getenv("ZLIB_REMIX_USERKEY", "")

# ─── VALIDATION ──────────────────────────────────────────────────────────────
def validate():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set!")
    if REQUEST_GROUP_ID == 0:
        print("⚠️  WARNING: REQUEST_GROUP_ID not set — group features disabled.")

validate()
