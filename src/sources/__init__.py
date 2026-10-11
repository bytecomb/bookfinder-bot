"""
Unified book search aggregator — public-domain / openly licensed sources only:
  1. Project Gutenberg
  2. Open Library (publicly downloadable items only)
"""

import asyncio
import logging
from typing import Optional

from .models import BookResult
from .gutenberg_source import GutenbergSource
from .openlibrary_source import OpenLibrarySource

logger = logging.getLogger(__name__)

_gutenberg = GutenbergSource()
_openlibrary = OpenLibrarySource()

_book_cache: dict[str, BookResult] = {}


async def search_all_sources(query: str, page: int = 1) -> list[BookResult]:
    tasks = [_gutenberg.search(query), _openlibrary.search(query, page=page)]
    source_order = ["Project Gutenberg", "Open Library"]
    buckets: dict[str, list[BookResult]] = {s: [] for s in source_order}

    gathered = await asyncio.gather(*tasks, return_exceptions=True)
    for label, result in zip(source_order, gathered):
        if isinstance(result, list):
            for book in result:
                buckets.setdefault(book.source, []).append(book)
        elif isinstance(result, Exception):
            logger.warning(f"Source '{label}' exception: {result}")

    seen: set[str] = set()
    deduped: list[BookResult] = []
    for label in buckets:
        for book in buckets[label]:
            key = f"{book.title[:40].lower().strip()}_{book.format}"
            if key not in seen:
                seen.add(key)
                deduped.append(book)
                _book_cache[book.book_id] = book

    logger.info(f"Search '{query}' p={page}: {len(deduped)} results")
    return deduped[:15]


def get_cached_book(book_id: str) -> Optional[BookResult]:
    return _book_cache.get(book_id)


async def download_book(book: BookResult) -> Optional[bytes]:
    try:
        if book.source == "Project Gutenberg":
            return await _gutenberg.download_file(book.download_url)
        if book.source == "Open Library":
            return await _openlibrary.download_file(book.download_url)
    except Exception as e:
        logger.error(f"Download failed {book.book_id} ({book.source}): {e}")
    return None


__all__ = ["search_all_sources", "get_cached_book", "download_book", "BookResult"]
