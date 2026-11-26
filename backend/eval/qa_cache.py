"""Disk cache and error helpers shared by the QA eval scripts.

Cache entries live in backend/eval/cache/<key>.json (gitignored), where the
key is SHA-256 of the model name concatenated with the exact prompt. Keep
this formula unchanged: existing cache entries are only reusable if it is.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

CACHE_DIR = Path(__file__).resolve().parent / "cache"

_QUOTA_MARKERS = ("429", "quota", "resource_exhausted", "rate limit")


def cache_key(model_name: str, prompt: str) -> str:
    return hashlib.sha256(f"{model_name}{prompt}".encode("utf-8")).hexdigest()


def cache_path(key: str, cache_dir: Path = CACHE_DIR) -> Path:
    return cache_dir / f"{key}.json"


def read_cached_answer(key: str, cache_dir: Path = CACHE_DIR) -> str | None:
    """Return the cached answer text, or None if missing or unreadable."""
    path = cache_path(key, cache_dir)
    if not path.is_file():
        return None
    try:
        return str(json.loads(path.read_text(encoding="utf-8"))["answer"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None


def write_cached_answer(
    key: str, model_name: str, answer: str, cache_dir: Path = CACHE_DIR
) -> None:
    """Write atomically so a stop mid-write never leaves a broken entry."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_path(key, cache_dir)
    temporary_path = path.with_suffix(".tmp")
    temporary_path.write_text(
        json.dumps(
            {"model": model_name, "prompt_sha256": key, "answer": answer},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def _error_chain(error: BaseException) -> list[BaseException]:
    chain: list[BaseException] = []
    pending: BaseException | None = error
    seen: set[int] = set()
    while pending is not None and id(pending) not in seen:
        seen.add(id(pending))
        chain.append(pending)
        pending = pending.__cause__ or pending.__context__
    return chain


def is_quota_error(error: BaseException) -> bool:
    """True if any exception in the cause chain looks like a 429 / quota error."""
    for pending in _error_chain(error):
        status = getattr(pending, "status_code", None) or getattr(pending, "code", None)
        message = f"{pending} {getattr(pending, 'detail', '')}".lower()
        if status == 429 or any(marker in message for marker in _QUOTA_MARKERS):
            return True
    return False


def describe_error(error: BaseException) -> dict[str, Any]:
    """Describe the root exception, not qa.py's generic 503 wrapper."""
    root = _error_chain(error)[-1]
    status = getattr(root, "status_code", None) or getattr(root, "code", None)
    return {
        "type": type(root).__name__,
        "status": status if isinstance(status, (int, str)) else None,
        "message": str(root),
        "quota": is_quota_error(error),
    }
