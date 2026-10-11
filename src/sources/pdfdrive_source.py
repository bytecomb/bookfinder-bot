"""
PDFDrive source — PDF search engine.
Scrapes pdfdrive.com search results and resolves download links.
"""

import logging
import os
import re
from typing import Optional, Union
from urllib.parse import urlparse

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
    from config import ENABLE_PDFDRIVE
except Exception:
    ENABLE_PDFDRIVE = os.getenv("ENABLE_PDFDRIVE", "true").lower() == "true"

from .models import BookResult

logger = logging.getLogger(__name__)

BASE_URL = "https://www.pdfdrive.com"
SEARCH_URL = "https://www.pdfdrive.com/search"


def _parse_size(s: str) -> int:
    try:
        s = str(s).strip().upper().replace(",", "")
        m = re.search(r"([\d.]+)\s*(GB|MB|KB|B)?", s)
        if not m:
            return 0
        val = float(m.group(1))
        unit = m.group(2) or "MB"
        if unit == "GB":
            return int(val * 1024**3)
        if unit == "MB":
            return int(val * 1024**2)
        if unit == "KB":
            return int(val * 1024)
        if unit == "B":
            return int(val)
    except Exception:
        pass
    return 0


def _is_direct_file(u: str) -> bool:
    try:
        path = urlparse(u).path.lower()
        return path.endswith((".pdf", ".epub")) or "/download.pdf" in u.lower()
    except Exception:
        return False


class PDFDriveSource:
    def __init__(self):
        self._client = httpx.AsyncClient(
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": "https://www.pdfdrive.com/",
            },
            follow_redirects=True,
            timeout=25,
        )

    async def search(self, query: str, page: int = 1) -> list[BookResult]:
        if not ENABLE_PDFDRIVE:
            return []
        if not query or not query.strip():
            return []

        try:
            params: dict[str, Union[str, int]] = {"q": query.strip()}
            if page > 1:
                params["page"] = page

            resp = await self._client.get(
                SEARCH_URL,
                params=params,
                timeout=20,
            )
            if resp.status_code != 200:
                logger.warning(f"PDFDrive search HTTP {resp.status_code} for '{query}'")
                return []

            soup = BeautifulSoup(resp.text, "html.parser")
            cards = soup.select(".files-new ul li, .files-new li")
            if not cards:
                # Fallback selector for alternative layout
                cards = [
                    el.find_parent("li") or el.find_parent("div", class_="row") or el
                    for el in soup.select(".file-right")
                ]

            results: list[BookResult] = []
            for card in cards:
                try:
                    # Title
                    title_el = (
                        card.select_one(".file-right a h2")
                        or card.select_one(".file-right h2")
                        or card.select_one("h2")
                        or card.select_one(".file-right a")
                    )
                    title = title_el.get_text(strip=True)[:120] if title_el else ""
                    if not title:
                        continue

                    # Detail page link
                    link_el = (
                        card.select_one(".file-right a[href]")
                        or card.select_one(".file-left a[href]")
                        or card.select_one("a[href]")
                    )
                    if not link_el:
                        continue
                    href = link_el["href"].strip()
                    if href.startswith("/"):
                        detail_url = f"{BASE_URL}{href}"
                    elif not href.startswith("http"):
                        detail_url = f"{BASE_URL}/{href}"
                    else:
                        detail_url = href

                    # ID
                    id_match = re.search(r"[ed](\d+)", href)
                    raw_id = id_match.group(1) if id_match else card.get("data-id", "")
                    if not raw_id:
                        raw_id = href.rstrip("/").split("/")[-1].replace(".html", "")

                    # Info: page count and size
                    pagecount = ""
                    size_str = "Unknown"
                    size_bytes = 0

                    info_el = card.select_one(".file-info")
                    if info_el:
                        pc_el = info_el.select_one(".fi-pagecount")
                        if pc_el:
                            pagecount = pc_el.get_text(strip=True)

                        sz_el = info_el.select_one(".fi-size")
                        if sz_el:
                            size_str = sz_el.get_text(strip=True)
                            size_bytes = _parse_size(size_str)
                        else:
                            txt = info_el.get_text()
                            sm = re.search(r"(\d+(?:\.\d+)?\s*(?:GB|MB|KB))", txt, re.I)
                            if sm:
                                size_str = sm.group(1).strip()
                                size_bytes = _parse_size(size_str)

                    # Cover
                    img_el = card.select_one("img.file-img, img")
                    cover_url = ""
                    if img_el:
                        c_src = img_el.get("data-original") or img_el.get("src") or ""
                        if c_src:
                            if c_src.startswith("//"):
                                cover_url = f"https:{c_src}"
                            elif c_src.startswith("/"):
                                cover_url = f"{BASE_URL}{c_src}"
                            else:
                                cover_url = c_src

                    results.append(
                        BookResult(
                            title=title,
                            author="Unknown",
                            language="English",
                            format="pdf",
                            size_str=size_str,
                            size_bytes=size_bytes,
                            book_id=f"pdfdrive_{raw_id}",
                            download_url="",  # resolved later via get_download_url; detail_url is a page
                            cover_url=cover_url,
                            source="PDFDrive",
                            extra={"detail_url": detail_url, "pages": pagecount},
                        )
                    )
                except Exception as card_err:
                    logger.debug(f"PDFDrive card parse error: {card_err}")
                    continue

            logger.info(f"PDFDrive: {len(results)} results for '{query}'")
            return results

        except Exception as e:
            logger.warning(f"PDFDrive search error: {e}")
            return []

    async def get_download_url(
        self,
        item_or_url: Union[BookResult, str, None] = None,
        *args,
        **kwargs,
    ) -> Optional[str]:
        try:
            if isinstance(item_or_url, BookResult):
                url = item_or_url.download_url or item_or_url.extra.get("detail_url", "")
            elif isinstance(item_or_url, str):
                url = item_or_url.strip()
            else:
                return None

            if not url or not url.startswith("http"):
                return None

            # Direct PDF url check
            if _is_direct_file(url):
                return url

            resp = await self._client.get(url, timeout=20)
            if resp.status_code != 200:
                logger.warning(f"PDFDrive detail page HTTP {resp.status_code} for {url}")
                return None

            soup = BeautifulSoup(resp.text, "html.parser")
            btn = (
                soup.find(id="download-button-link")
                or soup.find(id="download-button")
                or soup.find("a", href=re.compile(r"-[dD]\d+"))
                or soup.find(id="download-button-pro")
                or soup.find("a", class_=re.compile(r"btn.*download", re.I))
                or soup.find("a", href=re.compile(r"/download\.pdf\?"))
            )

            if not btn or not btn.get("href"):
                return None

            dl_href = btn["href"].strip()
            if dl_href.startswith("/"):
                dl_url = f"{BASE_URL}{dl_href}"
            elif not dl_href.startswith("http"):
                dl_url = f"{BASE_URL}/{dl_href}"
            else:
                dl_url = dl_href

            # If it leads to a download page (-d<id>), attempt to find direct link
            if re.search(r"-[dD]\d+", dl_url) and not _is_direct_file(dl_url):
                try:
                    dresp = await self._client.get(dl_url, timeout=15)
                    if dresp.status_code == 200:
                        dsoup = BeautifulSoup(dresp.text, "html.parser")
                        for a in dsoup.find_all("a", href=True):
                            ah = a["href"].strip()
                            if _is_direct_file(ah):
                                if ah.startswith("/"):
                                    return f"{BASE_URL}{ah}"
                                if ah.startswith("http"):
                                    return ah
                                return f"{BASE_URL}/{ah}"
                except Exception:
                    pass

            return dl_url

        except Exception as e:
            logger.warning(f"PDFDrive get_download_url error: {e}")
            return None

    async def download_file(self, url: str) -> Optional[bytes]:
        try:
            if not url or not url.startswith("http"):
                return None

            # If url is detail page (e.g. -e<id>), try resolving download url
            if re.search(r"-[eE]\d+", url) and not _is_direct_file(url):
                resolved = await self.get_download_url(url)
                if resolved:
                    url = resolved

            async with self._client.stream("GET", url, timeout=120) as resp:
                if resp.status_code != 200:
                    logger.warning(f"PDFDrive download HTTP {resp.status_code} for {url}")
                    return None

                ct = resp.headers.get("content-type", "").lower()
                if "html" in ct:
                    # Might be an intermediate download page; try resolving one level deeper
                    body_text = await resp.aread()
                    soup = BeautifulSoup(body_text.decode("utf-8", errors="ignore"), "html.parser")
                    for a in soup.find_all("a", href=True):
                        ah = a["href"].strip()
                        if _is_direct_file(ah):
                            direct_url = ah if ah.startswith("http") else f"{BASE_URL}/{ah.lstrip('/')}"
                            return await self.download_file(direct_url)
                    logger.warning(f"PDFDrive returned HTML instead of PDF for {url}")
                    return None

                cl = int(resp.headers.get("content-length", 0))
                if cl > MAX_FILE_SIZE_MB * 1024 * 1024:
                    logger.warning(f"PDFDrive file too large: {cl} bytes")
                    return None

                chunks: list[bytes] = []
                downloaded = 0
                async for chunk in resp.aiter_bytes(65536):
                    downloaded += len(chunk)
                    if downloaded > MAX_FILE_SIZE_MB * 1024 * 1024:
                        logger.warning(f"PDFDrive download exceeded size limit: {downloaded} bytes")
                        return None
                    chunks.append(chunk)

                return b"".join(chunks)

        except Exception as e:
            logger.error(f"PDFDrive download error: {e}")
            return None

    async def close(self):
        try:
            await self._client.aclose()
        except Exception:
            pass
