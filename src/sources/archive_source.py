"""
Internet Archive source — books and texts from archive.org.
Uses advancedsearch.php API for search and archive.org/metadata + /download for file downloads.
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
METADATA_BASE = "https://archive.org/metadata"
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
                elif any("pdf" in f for f in formats_lower):
                    chosen_fmt = "pdf"
                else:
                    chosen_fmt = "pdf"

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
                        download_url="",
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
            identifier = None
            if isinstance(item_or_id, BookResult):
                if item_or_id.extra and item_or_id.extra.get("identifier"):
                    identifier = str(item_or_id.extra["identifier"]).strip()
                elif item_or_id.book_id:
                    identifier = item_or_id.book_id.removeprefix("ia_").strip()
            elif isinstance(item_or_id, str):
                s = item_or_id.strip()
                if s.startswith("http"):
                    # e.g. https://archive.org/download/{identifier}/... or https://archive.org/details/{identifier}
                    m = re.search(r"archive\.org/(?:download|details|metadata)/([^/?#]+)", s)
                    identifier = m.group(1) if m else s
                else:
                    identifier = s.removeprefix("ia_").strip()

            if not identifier:
                return None

            # Fetch file list from https://archive.org/metadata/<identifier>
            metadata_url = f"{METADATA_BASE}/{identifier}"
            resp = await self._search_client.get(metadata_url, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"Internet Archive metadata HTTP {resp.status_code} for {identifier}")
                return None

            data = resp.json()
            if not isinstance(data, dict):
                return None

            meta = data.get("metadata") or {}
            restricted = meta.get("access-restricted-item")
            if restricted is True or str(restricted).strip().lower() == "true":
                logger.info(f"Internet Archive item {identifier} is access-restricted")
                return None

            files = data.get("files") or []
            if not isinstance(files, list):
                return None

            epub_files: list[str] = []
            pdf_files: list[tuple[bool, str]] = []  # (is_text_pdf, filename)
            txt_files: list[str] = []

            for f in files:
                if not isinstance(f, dict):
                    continue
                name = str(f.get("name") or "").strip()
                fmt = str(f.get("format") or "").strip()
                if not name:
                    continue

                name_lower = name.lower()
                fmt_lower = fmt.lower()

                # Filter out encrypted or metadata / system files
                if "encrypted" in fmt_lower or name_lower.endswith(("_encrypted.pdf", "_lcp.epub", ".lcpdf")):
                    continue
                if fmt_lower == "metadata" or name_lower.endswith(("_meta.txt", "_meta.xml", "_files.xml")):
                    continue

                if name_lower.endswith(".epub") or fmt_lower == "epub":
                    epub_files.append(name)
                elif name_lower.endswith(".pdf") or "pdf" in fmt_lower:
                    is_text = "text" in name_lower or "text" in fmt_lower
                    pdf_files.append((is_text, name))
                elif (
                    not name_lower.endswith((".gz", ".zip"))
                    and (name_lower.endswith(".txt") or fmt_lower in ("text", "djvutxt") or "txt" in fmt_lower)
                ):
                    txt_files.append(name)

            chosen_name: Optional[str] = None
            if epub_files:
                chosen_name = epub_files[0]
            elif pdf_files:
                pdf_files.sort(key=lambda x: not x[0])
                chosen_name = pdf_files[0][1]
            elif txt_files:
                chosen_name = txt_files[0]

            if not chosen_name:
                logger.info(f"Internet Archive item {identifier} has no suitable epub/pdf/txt files")
                return None

            dl_url = f"{DOWNLOAD_BASE}/{identifier}/{chosen_name.lstrip('/')}"
            if isinstance(item_or_id, BookResult):
                item_or_id.download_url = dl_url
            return dl_url

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
