"""Local file stores (machine-side persistence).

- HistoryLog: append-only JSONL audit log per user. Written on every
  inbound/outbound message, but NEVER loaded back into prompts.
- PendingStore: single-slot per-user cache for answers that outlived the
  LINE reply token. Status moves thinking -> ready; the user fetches the
  ready answer with the fetch keyword (or by re-asking) without re-running
  generation.
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

THINKING = "thinking"
READY = "ready"


def _safe_id(user_id: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", user_id or "unknown")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HistoryLog:
    """Append-only per-user JSONL log. Audit trail only."""

    def __init__(self, data_dir: str | Path) -> None:
        self.dir = Path(data_dir) / "history"
        self._lock = threading.Lock()

    def _path(self, user_id: str | None) -> Path:
        return self.dir / f"{_safe_id(user_id)}.jsonl"

    def append(self, user_id: str | None, role: str, text: str) -> None:
        """role: user | bot | system. Never raises (logging must not break replies)."""
        record = {"ts": _now_iso(), "role": role, "text": text}
        try:
            with self._lock:
                path = self._path(user_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                with path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("HistoryLog append failed")


class PendingStore:
    """Single-slot per-user pending answer with compare-and-set guard.

    The guard prevents a stale worker (started before a newer question
    overwrote the slot) from clobbering the current slot.
    """

    def __init__(self, data_dir: str | Path) -> None:
        self.dir = Path(data_dir) / "pending"
        self._lock = threading.Lock()

    def _path(self, user_id: str | None) -> Path:
        return self.dir / f"{_safe_id(user_id)}.json"

    def read(self, user_id: str | None) -> dict[str, Any] | None:
        path = self._path(user_id)
        try:
            if not path.exists():
                return None
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("PendingStore read failed")
            return None

    def save_thinking(self, user_id: str | None, question: str) -> None:
        self._write(user_id, {"question": question, "answer": None, "status": THINKING, "updated_at": _now_iso()})

    def save_ready(self, user_id: str | None, question: str, answer: str) -> bool:
        """Write the answer only if the slot still holds this question as thinking."""
        with self._lock:
            current = self.read(user_id)
            if current is None or current.get("question") != question or current.get("status") != THINKING:
                logger.warning("Pending slot changed, dropping stale answer for question: %s", question)
                return False
            path = self._path(user_id)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(
                    {"question": question, "answer": answer, "status": READY, "updated_at": _now_iso()},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            return True

    def clear(self, user_id: str | None) -> None:
        try:
            with self._lock:
                self._path(user_id).unlink(missing_ok=True)
        except Exception:
            logger.exception("PendingStore clear failed")

    def _write(self, user_id: str | None, record: dict[str, Any]) -> None:
        try:
            with self._lock:
                path = self._path(user_id)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        except Exception:
            logger.exception("PendingStore write failed")
