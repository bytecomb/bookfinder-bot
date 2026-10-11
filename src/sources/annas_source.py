"""
Anna's Archive source — aiohttp + DoH DNS resolver with Cloudflare degradation.

Searches Anna's Archive catalog (annas-archive.org and mirrors) using DNS-over-HTTPS
to bypass network/DNS restrictions while retaining proper SNI for TLS handshakes.
Gracefully degrades if blocked by Cloudflare / DDoS-Guard challenges.
"""

import asyncio
import logging
import os
import re
import socket
from typing import Optional

import aiohttp
from bs4 import BeautifulSoup

from .models import BookResult

try:
    from config import MAX_FILE_SIZE_MB
except Exception:
    MAX_FILE_SIZE_MB = int(os.getenv("MAX_FILE_SIZE_MB", "100"))

try:
    from config import ENABLE_ANNAS
except Exception:
    ENABLE_ANNAS = os.getenv("ENABLE_ANNAS", "true").lower() == "true"

logger = logging.getLogger(__name__)

ANNAS_DOMAINS = [
    "annas-archive.org",
    "annas-archive.is",
    "annas-archive.li",
    "annas-archive.se",
]

DOH_URLS = [
    "https://dns.google/resolve",
    "https://cloudflare-dns.com/dns-query",
]


def _parse_size(s: str) -> int:
    try:
        s = str(s).strip().upper().replace(",", "")
        if "KB" in s:
            return int(float(s.replace("KB", "").strip()) * 1024)
        if "MB" in s:
            return int(float(s.replace("MB", "").strip()) * 1024**2)
        if "GB" in s:
            return int(float(s.replace("GB", "").strip()) * 1024**3)
        if s.endswith("B"):
            return int(float(s[:-1].strip()))
    except Exception:
        pass
    return 0


# ── Custom aiohttp resolver using DNS-over-HTTPS ─────────────────────────────

class _DoHResolver(aiohttp.abc.AbstractResolver):
    """
    aiohttp resolver that resolves via DNS-over-HTTPS (Google / Cloudflare).
    Returns the DoH-resolved IP while keeping original host for SNI verification.
    """

    def __init__(self):
        self._cache: dict[str, str] = {}

    async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET):
        if host in self._cache:
            ip = self._cache[host]
            return [{
                "hostname": host,
                "host": ip,
                "port": port,
                "family": family,
                "proto": 0,
                "flags": 0,
            }]

        # Check if already an IP
        try:
            socket.inet_aton(host)
            return [{
                "hostname": host,
                "host": host,
                "port": port,
                "family": family,
                "proto": 0,
                "flags": 0,
            }]
        except OSError:
            pass

        # Handle local sandbox proxy / loopback hostnames
        if host in ("localhost", "hatch-egress-proxy") or host.endswith(".local"):
            try:
                infos = socket.getaddrinfo(host, port, family=family)
                return [{
                    "hostname": host,
                    "host": info[4][0],
                    "port": port,
                    "family": family,
                    "proto": 0,
                    "flags": 0,
                } for info in infos[:1]]
            except OSError:
                pass

        # Query DoH endpoints
        for doh_url in DOH_URLS:
            try:
                async with aiohttp.ClientSession(trust_env=True) as s:
                    async with s.get(
                        doh_url,
                        params={"name": host, "type": "A"},
                        headers={"Accept": "application/dns-json"},
                        timeout=aiohttp.ClientTimeout(total=5),
                        ssl=True,
                    ) as r:
                        data = await r.json(content_type=None)
                        for ans in data.get("Answer", []):
                            if ans.get("type") == 1:
                                ip = ans["data"].strip()
                                self._cache[host] = ip
                                logger.debug(f"DoH: {host} -> {ip}")
                                return [{
                                    "hostname": host,
                                    "host": ip,
                                    "port": port,
                                    "family": family,
                                    "proto": 0,
                                    "flags": 0,
                                }]
            except Exception as e:
                logger.debug(f"DoH {doh_url} failed for {host}: {e}")
                continue

        # Fallback to system resolver
        try:
            infos = socket.getaddrinfo(host, port, family=family)
            return [{
                "hostname": host,
                "host": info[4][0],
                "port": port,
                "family": family,
                "proto": 0,
                "flags": 0,
            } for info in infos[:1]]
        except OSError:
            pass

        raise OSError(f"DoH resolution failed for {host} (all DoH servers tried)")

    async def close(self):
        pass


# ── AnnasArchiveSource ───────────────────────────────────────────────────────

class AnnasArchiveSource:
    """
    Anna's Archive source — searches catalog via DoH + aiohttp.
    No direct downloads; returns [] on failure or Cloudflare challenges without crashing.
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None

    def _headers(self, domain: str) -> dict:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate",
            "Referer": f"https://{domain}/",
        }

    async def _make_session(self) -> aiohttp.ClientSession:
        if self._session and not self._session.closed:
            return self._session
        resolver = _DoHResolver()
        connector = aiohttp.TCPConnector(
            resolver=resolver,
            ssl=True,
            limit=10,
            ttl_dns_cache=300,
        )
        self._session = aiohttp.ClientSession(
            connector=connector,
            trust_env=True,
            timeout=aiohttp.ClientTimeout(total=20),
        )
        return self._session

    def _parse_html(self, html: str, domain: str) -> list[BookResult]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[BookResult] = []

        # 1. Card layout (div.bg-white containing h3 and /books/ or /md5/ link)
        cards = soup.find_all("div", class_=lambda c: c and "bg-white" in c and "rounded-lg" in c)
        for card in cards:
            book_link = card.find("a", href=lambda h: h and ("/books/" in h or "/md5/" in h))
            if not book_link:
                continue
            h3 = card.find("h3")
            title = h3.get_text(strip=True) if h3 else (book_link.get_text(strip=True) or "Unknown")

            href = book_link["href"].strip()
            if href.startswith("/"):
                href = f"https://{domain}{href}"

            img = card.find("img")
            cover_url = img["src"].strip() if img and img.get("src") else ""
            if cover_url.startswith("/"):
                cover_url = f"https://{domain}{cover_url}"

            meta_div = card.find("div", class_=lambda c: c and "text-sm" in c and "text-[#666]" in c)
            meta_text = meta_div.get_text(" ", strip=True) if meta_div else ""
            parts = [p.strip() for p in meta_text.split("·")]

            raw_author = parts[0] if parts and parts[0] else ""
            if not raw_author or raw_author.lower() in ("unknown author", "unknown"):
                author = "Unknown"
            else:
                author = raw_author

            fmt = "pdf"
            size_str = "Unknown"
            size_bytes = 0
            for part in parts[1:]:
                p_low = part.lower()
                if p_low in ["pdf", "epub", "mobi", "djvu", "fb2", "azw3", "cbr", "cbz", "txt", "doc"]:
                    fmt = p_low
                elif any(u in part.upper() for u in ["KB", "MB", "GB", " B"]):
                    size_str = part
                    size_bytes = _parse_size(part)

            if size_bytes > MAX_FILE_SIZE_MB * 1024 * 1024:
                continue

            md5 = ""
            m = re.search(r"([a-fA-F0-9]{32})", href + " " + cover_url)
            if m:
                md5 = m.group(1).lower()

            raw_id = md5 or re.sub(r"[^a-zA-Z0-9_-]", "", href.rstrip("/").split("/")[-1])
            book_id = f"annas_{raw_id}"

            results.append(BookResult(
                title=title[:120],
                author=author,
                language="English",
                format=fmt,
                size_str=size_str,
                size_bytes=size_bytes,
                book_id=book_id,
                download_url=href,
                cover_url=cover_url,
                source="Anna's Archive",
                extra={"md5": md5, "domain": domain},
            ))

        # 2. Classic layout (a[href*="/md5/"])
        if not results:
            items = soup.select('a[href*="/md5/"]')
            for item in items:
                href = item.get("href", "").strip()
                if not href:
                    continue
                m = re.search(r"([a-fA-F0-9]{32})", href)
                md5 = m.group(1).lower() if m else ""

                title_el = item.select_one("h3, .text-xl, .font-bold")
                title = title_el.get_text(strip=True) if title_el else "Unknown"

                author_el = item.select_one(".author, .italic")
                author = author_el.get_text(strip=True) if author_el else "Unknown"

                full_text = item.get_text(" ", strip=True)
                parts = [p.strip() for p in full_text.split("·")]
                fmt = "pdf"
                size_str = "Unknown"
                size_bytes = 0
                for part in parts:
                    p_low = part.lower()
                    if p_low in ["pdf", "epub", "mobi", "djvu", "fb2", "azw3", "cbr", "cbz", "txt", "doc"]:
                        fmt = p_low
                    elif any(u in part.upper() for u in ["KB", "MB", "GB"]):
                        size_str = part
                        size_bytes = _parse_size(part)

                if size_bytes > MAX_FILE_SIZE_MB * 1024 * 1024:
                    continue

                if href.startswith("/"):
                    href = f"https://{domain}{href}"

                bid = md5 or re.sub(r"[^a-zA-Z0-9_-]", "", href.rstrip("/").split("/")[-1])
                results.append(BookResult(
                    title=title[:120],
                    author=author,
                    language="English",
                    format=fmt,
                    size_str=size_str,
                    size_bytes=size_bytes,
                    book_id=f"annas_{bid}",
                    download_url=href,
                    cover_url="",
                    source="Anna's Archive",
                    extra={"md5": md5, "domain": domain},
                ))

        return results

    async def search(self, query: str, page: int = 1) -> list[BookResult]:
        if not ENABLE_ANNAS:
            return []

        try:
            session = await self._make_session()
            params: dict[str, str] = {"q": query}
            if page > 1:
                params["page"] = str(page)

            for domain in ANNAS_DOMAINS:
                try:
                    async with session.get(
                        f"https://{domain}/search",
                        params=params,
                        headers=self._headers(domain),
                        timeout=aiohttp.ClientTimeout(total=15),
                    ) as r:
                        if r.status != 200:
                            logger.debug(f"Anna's Archive {domain} status {r.status}")
                            continue

                        text = await r.text()
                        # Cloudflare / DDoS-Guard challenge check
                        t_lower = text.lower()
                        if any(c in t_lower for c in ("ddos-guard", "just a moment", "challenge-running", "turnstile")):
                            logger.info(f"Anna's Archive {domain} presented bot challenge, skipping")
                            continue

                        books = self._parse_html(text, domain)
                        if books:
                            logger.info(f"Anna's Archive: found {len(books)} books via {domain}")
                            return books
                except Exception as e:
                    logger.debug(f"Anna's Archive search error on {domain}: {e}")
                    continue
        except Exception as e:
            logger.warning(f"Anna's Archive search error: {e}")

        return []

    async def get_download_url(self, *args, **kwargs) -> Optional[str]:
        return None

    async def download_file(self, *args, **kwargs) -> Optional[bytes]:
        return None

    async def close(self):
        if self._session and not self._session.closed:
            await self._session.close()
