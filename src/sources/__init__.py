"""
Unified book search aggregator.

Priority order:
  1. Z-Library        — primary, uses DoH to bypass Render DNS block (needs ZLIB_* env creds)
  2. Libgen           — libgen.is mirrors
  3. Anna's Archive   — DoH + multi-mirror fallback
  4. Internet Archive — public advancedsearch API
  5. PDFDrive         — search page scraping
  6. Project Gutenberg — public domain
  7. Open Library     — publicly downloadable only (403 items skipped)
"""

import asyncio
import logging
from typing import Optional

from .models import BookResult
from .zlibrary_source import ZLibrarySource
from .libgen_source import LibgenSource
from .annas_source import AnnasArchiveSource
from .archive_source import InternetArchiveSource
from .pdfdrive_source import PDFDriveSource
from .gutenberg_source import GutenbergSource
from .openlibrary_source import OpenLibrarySource

logger = logging.getLogger(__name__)

_zlib = ZLibrarySource()
_libgen = LibgenSource()
_annas = AnnasArchiveSource()
_archive = InternetArchiveSource()
_pdfdrive = PDFDriveSource()
_gutenberg = GutenbergSource()
_openlibrary = OpenLibrarySource()

_book_cache: dict[str, BookResult] = {}


async def search_all_sources(query: str, page: int = 1) -> list[BookResult]:
    """Search all sources concurrently. Higher-priority sources shown first."""
    tasks = [
        _zlib.search(query, page=page),
        _libgen.search(query, page=page),
        _annas.search(query, page=page),
        _archive.search(query, page=page),
        _pdfdrive.search(query, page=page),
        _gutenberg.search(query),
        _openlibrary.search(query, page=page),
    ]
    source_order = [
        "Z-Library",
        "Libgen",
        "Anna's Archive",
        "Internet Archive",
        "PDFDrive",
        "Project Gutenberg",
        "Open Library",
    ]
    buckets: dict[str, list[BookResult]] = {s: [] for s in source_order}

    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    for label, result in zip(source_order, gathered):
        if isinstance(result, list):
            for book in result:
                buckets.setdefault(book.source, []).append(book)
        elif isinstance(result, Exception):
            logger.warning(f"Source '{label}' exception: {result}")

    # Merge in priority order
    seen: set[str] = set()
    deduped: list[BookResult] = []
    for label in source_order:
        for book in buckets.get(label, []):
            key = f"{book.title[:40].lower().strip()}_{book.format}"
            if key not in seen:
                seen.add(key)
                deduped.append(book)
                _book_cache[book.book_id] = book

    counts = {s: len(buckets.get(s, [])) for s in source_order}
    annas_count = counts.get("Anna's Archive", 0)
    logger.info(
        f"Search '{query}' p={page}: {len(deduped)} results | "
        f"zlib={counts['Z-Library']} libgen={counts['Libgen']} "
        f"annas={annas_count} ia={counts['Internet Archive']} "
        f"pdfdrive={counts['PDFDrive']} gutenberg={counts['Project Gutenberg']} "
        f"openlibrary={counts['Open Library']}"
    )
    return deduped[:15]


def get_cached_book(book_id: str) -> Optional[BookResult]:
    return _book_cache.get(book_id)


async def download_book(book: BookResult) -> Optional[bytes]:
    source = book.source
    try:
        if source == "Z-Library":
            url = book.download_url or await _zlib.get_download_url(book, book.extra)
            if url:
                return await _zlib.download_file(url)

        elif source == "Libgen":
            md5 = book.extra.get("md5", "")
            mirror = book.extra.get("mirror")
            url = book.download_url or await _libgen.get_download_url(book, mirror)
            if url:
                return await _libgen.download_file(url)

        elif source == "Anna's Archive":
            # No direct download; user follows the Annas link instead.
            return None

        elif source == "Internet Archive":
            url = book.download_url or await _archive.get_download_url(book)
            if url:
                return await _archive.download_file(url)

        elif source == "PDFDrive":
            url = book.download_url or await _pdfdrive.get_download_url(book)
            if url:
                return await _pdfdrive.download_file(url)

        elif source == "Project Gutenberg":
            return await _gutenberg.download_file(book.download_url)

        elif source == "Open Library":
            return await _openlibrary.download_file(book.download_url)

    except Exception as e:
        logger.error(f"Download failed {book.book_id} ({source}): {e}")

    return None


__all__ = ["search_all_sources", "get_cached_book", "download_book", "BookResult"]
