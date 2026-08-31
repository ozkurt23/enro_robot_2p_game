"""JSONL session logging and atomic state snapshots outside the repository."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from enum import Enum
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Mapping


def default_state_root() -> Path:
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base) / "enro-v2"
    return Path.home() / ".local" / "state" / "enro-v2"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if is_dataclass(value):
        return _jsonable(asdict(value))
    return value


class SessionStore:
    def __init__(self, root: Path | None = None, *, session_id: str | None = None) -> None:
        self.root = root or default_state_root()
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.session_id = session_id or f"{timestamp}-{os.getpid()}"
        self.session_dir = self.root / "sessions" / self.session_id
        self.runtime_dir = self.root / "runtime"
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        self.events_path = self.session_dir / "events.jsonl"
        self.state_path = self.runtime_dir / "current-state.json"

    def append_event(self, event_type: str, payload: Mapping[str, Any]) -> None:
        record = {
            "schema_version": 1,
            "timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "event_type": event_type,
            "payload": _jsonable(dict(payload)),
        }
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def save_state(self, payload: Mapping[str, Any]) -> None:
        data = json.dumps(
            {"schema_version": 1, "session_id": self.session_id, **_jsonable(dict(payload))},
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ) + "\n"
        fd, temporary = tempfile.mkstemp(prefix="state-", suffix=".tmp", dir=self.runtime_dir)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

