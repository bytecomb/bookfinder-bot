"""
Internet Archive source — books and texts from archive.org.
Uses advancedsearch.php API for search and archive.org/download for file downloads.
"""

import logging
import os
import re
from typing import Optional, Union

# httpx bug workaround for bracketed IPv6 in no_proxy (e.g. [::1])
for _k in ("no_proxy", "NO_PROXY"):
    _val = os.environ.get(_k)
    if _val and "[" in _val:
        os.environ[_k] = ",".join(
            _p for _p in _val.split(",") if not (_p.startswith("[") and _p.endswith("]"))
        )

import httpx
from bs4 import BeautifulSoup

try:
    from config import MAX_FILE_SIZE_MB
except Exception:
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "100"))

try:
    from config import ENABLE_ARCHIVE
except Exception:
    ENABLE_ARCHIVE = os.getenv("ENABLE_ARCHIVE", "true").lower() == "true"

from .models import BookResult

logger = logging.getLogger(__name__)

SEARCH_API = "https://archive.org/advancedsearch.php"
DOWNLOAD_BASE = "https://archive.org/download"
SERVICES_IMG = "https://archive.org/services/img"


class InternetArchiveSource:
    def __init__(self):
        self._search_client = httpx.AsyncClient(
            headers={"User-Agent": "BookFinderBot/2.0 (educational)"},
            follow_redirects=True,
            timeout=25,
        )
        self._dl_client = httpx.AsyncClient(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "application/pdf,application/epub+zip,*/*",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://archive.org/",
            },
            follow_redirects=True,
            timeout=120,
        )

    async def search(self, query: str, page: int = 1) -> list[BookResult]:
        if not ENABLE_ARCHIVE:
            return []
        if not query or not query.strip():
            return []

        try:
            params = [
                ("q", f"{query.strip()} AND mediatype:texts"),
                ("fl[]", "identifier"),
                ("fl[]", "title"),
                ("fl[]", "creator"),
                ("fl[]", "format"),
                ("rows", "25"),
                ("page", str(max(1, page))),
                ("output", "json"),
            ]
            resp = await self._search_client.get(
                SEARCH_API,
                params=params,
                timeout=20,
            )
            if resp.status_code != 200:
                logger.warning(f"Internet Archive search HTTP {resp.status_code}")
                return []

            data = resp.json()
            docs = data.get("response", {}).get("docs", [])
            results: list[BookResult] = []

            for doc in docs:
                identifier = str(doc.get("identifier") or "").strip()
                if not identifier:
                    continue

                title = str(doc.get("title") or "Unknown").strip()[:120]
                creator = doc.get("creator")
                if isinstance(creator, list):
                    author = ", ".join(str(c) for c in creator if c) or "Unknown"
                elif creator:
                    author = str(creator).strip() or "Unknown"
                else:
                    author = "Unknown"

                formats = doc.get("format", [])
                if isinstance(formats, str):
                    formats = [formats]
                formats_lower = [str(f).lower() for f in formats]

                # Format selection: prefer EPUB, then PDF
                if any("epub" in f for f in formats_lower):
                    chosen_fmt = "epub"
                    dl_url = f"{DOWNLOAD_BASE}/{identifier}/{identifier}.epub"
                elif any("pdf" in f for f in formats_lower):
                    chosen_fmt = "pdf"
                    dl_url = f"{DOWNLOAD_BASE}/{identifier}/{identifier}_text.pdf"
                else:
                    chosen_fmt = "pdf"
                    dl_url = f"{DOWNLOAD_BASE}/{identifier}/{identifier}_text.pdf"

                cover_url = f"{SERVICES_IMG}/{identifier}"

                results.append(
                    BookResult(
                        title=title,
                        author=author,
                        language="English",
                        format=chosen_fmt,
                        size_str="Free",
                        size_bytes=0,
                        book_id=f"ia_{identifier}",
                        download_url=dl_url,
                        cover_url=cover_url,
                        source="Internet Archive",
                        extra={"identifier": identifier, "formats": formats},
                    )
                )

            logger.info(f"Internet Archive: {len(results)} results for '{query}'")
            return results

        except Exception as e:
            logger.warning(f"Internet Archive search error: {e}")
            return []

    async def get_download_url(
        self,
        item_or_id: Union[BookResult, str, None] = None,
        *args,
        **kwargs,
    ) -> Optional[str]:
        try:
            if isinstance(item_or_id, BookResult):
                identifier = item_or_id.extra.get("identifier") or item_or_id.book_id.removeprefix("ia_")
                if item_or_id.download_url and item_or_id.download_url.endswith((".pdf", ".epub", ".txt")):
                    return item_or_id.download_url
            elif isinstance(item_or_id, str):
                s = item_or_id.strip()
                if s.startswith("http"):
                    # e.g. https://archive.org/download/{identifier}/...
                    m = re.search(r"archive\.org/download/([^/]+)", s)
                    identifier = m.group(1) if m else s
                    if s.endswith((".pdf", ".epub", ".txt")):
                        return s
                else:
                    identifier = s.removeprefix("ia_")
            else:
                return None

            if not identifier:
                return None

            # Fetch file list from https://archive.org/download/<identifier>
            listing_url = f"{DOWNLOAD_BASE}/{identifier}"
            resp = await self._search_client.get(listing_url, timeout=15)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                candidates = []
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    lower = href.lower()
                    if lower.endswith((".epub", ".pdf", ".txt")):
                        full_url = href if href.startswith("http") else f"{DOWNLOAD_BASE}/{identifier}/{href.lstrip('/')}"
                        candidates.append((lower, full_url))

                # Prioritize: epub -> text pdf -> pdf -> txt
                for lower, full_url in candidates:
                    if lower.endswith(".epub"):
                        return full_url
                for lower, full_url in candidates:
                    if "text.pdf" in lower:
                        return full_url
                for lower, full_url in candidates:
                    if lower.endswith(".pdf"):
                        return full_url
                if candidates:
                    return candidates[0][1]

            # Fallback
            return f"{DOWNLOAD_BASE}/{identifier}/{identifier}_text.pdf"

        except Exception as e:
            logger.warning(f"Internet Archive get_download_url error: {e}")
            return None

    async def download_file(self, url: str) -> Optional[bytes]:
        try:
            if not url or not url.startswith("http"):
                return None

            # If url is directory or doesn't end with a supported file extension, resolve it first
            if not any(url.lower().endswith(ext) for ext in (".pdf", ".epub", ".txt")):
                resolved = await self.get_download_url(url)
                if resolved:
                    url = resolved

            async with self._dl_client.stream("GET", url, timeout=120) as resp:
                if resp.status_code != 200:
                    logger.warning(f"Internet Archive download HTTP {resp.status_code} for {url}")
                    return None

                ct = resp.headers.get("content-type", "").lower()
                if "html" in ct:
                    logger.warning(f"Internet Archive returned HTML instead of book file for {url}")
                    return None

                cl = int(resp.headers.get("content-length", 0))
                if cl > MAX_FILE_SIZE_MB * 1024 * 1024:
                    logger.warning(f"Internet Archive file too large: {cl} bytes")
                    return None

                chunks: list[bytes] = []
                downloaded = 0
                async for chunk in resp.aiter_bytes(65536):
                    downloaded += len(chunk)
                    if downloaded > MAX_FILE_SIZE_MB * 1024 * 1024:
                        logger.warning(f"Internet Archive download exceeded size limit: {downloaded} bytes")
                        return None
                    chunks.append(chunk)

                return b"".join(chunks)

        except Exception as e:
            logger.error(f"Internet Archive download error: {e}")
            return None

    async def close(self):
        try:
            await self._search_client.aclose()
            await self._dl_client.aclose()
        except Exception:
            pass
