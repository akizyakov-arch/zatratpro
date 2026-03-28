from contextlib import contextmanager
import logging
from pathlib import Path
from typing import Iterator


logger = logging.getLogger(__name__)


def safe_unlink(path: str | Path | None) -> None:
    if path is None:
        return

    target = Path(path)
    try:
        target.unlink(missing_ok=True)
    except FileNotFoundError:
        return
    except Exception:
        logger.warning("Failed to delete temp file: %s", target, exc_info=True)


@contextmanager
def temporary_files(*paths: str | Path | None) -> Iterator[tuple[str | Path | None, ...]]:
    try:
        yield paths
    finally:
        for path in paths:
            safe_unlink(path)
