from __future__ import annotations

import os
from concurrent.futures import Future, ThreadPoolExecutor
from threading import Lock
from typing import Callable, Protocol


class ArchiveDispatcher(Protocol):
    def submit(self, operation: Callable[[], None]) -> str: ...


class BoundedThreadDispatcher:
    """Small-process fallback. Production may replace this with the durable worker queue."""

    def __init__(self, max_workers: int | None = None) -> None:
        workers = max_workers or int(os.getenv("ARCHIVE_LOCAL_WORKERS", "1"))
        if workers < 1 or workers > 4:
            raise ValueError("ARCHIVE_LOCAL_WORKERS must be between 1 and 4")
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="archive")
        self._futures: set[Future[None]] = set()
        self._lock = Lock()

    def submit(self, operation: Callable[[], None]) -> str:
        future = self._executor.submit(operation)
        with self._lock:
            self._futures.add(future)
        future.add_done_callback(self._discard)
        return f"local-thread:{id(future)}"

    def _discard(self, future: Future[None]) -> None:
        with self._lock:
            self._futures.discard(future)


_dispatcher: ArchiveDispatcher | None = None


def get_archive_dispatcher() -> ArchiveDispatcher:
    global _dispatcher
    if _dispatcher is None:
        _dispatcher = BoundedThreadDispatcher()
    return _dispatcher
