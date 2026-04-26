"""logs/ artifact helpers."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


def _kst_timestamp_for_filename() -> str:
    return datetime.now(ZoneInfo("Asia/Seoul")).strftime("%Y%m%dT%H%M%S%z")


def _normalize_logs_dir(logs_dir: str | Path) -> Path:
    return Path(logs_dir)


def reserve_log_path(logs_dir: str | Path, kind: str) -> Path:
    """Reserve the next log path for a kind without writing it."""

    kind_dir = _normalize_logs_dir(logs_dir) / kind
    kind_dir.mkdir(parents=True, exist_ok=True)
    timestamp = _kst_timestamp_for_filename()
    candidate = kind_dir / f"{timestamp}.json"
    sequence = 1
    while candidate.exists():
        candidate = kind_dir / f"{timestamp}-{sequence:02d}.json"
        sequence += 1
    return candidate


def log_ref_for_path(logs_dir: str | Path, path: str | Path) -> str:
    """Return a task-relative log ref for a concrete log path."""

    logs_path = _normalize_logs_dir(logs_dir)
    return str(Path(path).relative_to(logs_path.parent))


def _append_log(logs_dir: str | Path, kind: str, content: str) -> str:
    path = reserve_log_path(logs_dir, kind)
    rendered = content if content.endswith("\n") else content + "\n"
    path.write_text(rendered, encoding="utf-8")
    return log_ref_for_path(logs_dir, path)


def _resolve_latest_ref(logs_dir: str | Path, kind: str) -> str | None:
    kind_dir = _normalize_logs_dir(logs_dir) / kind
    if not kind_dir.is_dir():
        return None
    refs = sorted((path for path in kind_dir.glob("*.json") if path.is_file()), key=_log_sort_key)
    if not refs:
        return None
    return log_ref_for_path(logs_dir, refs[-1])


def _log_sort_key(path: Path) -> tuple[str, int]:
    stem = path.stem
    timestamp, separator, sequence_text = stem.partition("-")
    if not separator:
        return timestamp, 0
    try:
        return timestamp, int(sequence_text)
    except ValueError:
        return timestamp, 0


def append_checkpoint_log(logs_dir: str | Path, content: str) -> str:
    """Append a checkpoint log entry and return its ref."""

    return _append_log(logs_dir, "checkpoints", content)


def append_verification_log(logs_dir: str | Path, content: str) -> str:
    """Append a verification log entry and return its ref."""

    return _append_log(logs_dir, "verification", content)


def append_review_log(logs_dir: str | Path, content: str) -> str:
    """Append a review log entry and return its ref."""

    return _append_log(logs_dir, "review", content)


def resolve_latest_checkpoint_ref(logs_dir: str | Path) -> str | None:
    """Resolve the latest checkpoint ref from logs."""

    return _resolve_latest_ref(logs_dir, "checkpoints")


def resolve_latest_verification_ref(logs_dir: str | Path) -> str | None:
    """Resolve the latest verification ref from logs."""

    return _resolve_latest_ref(logs_dir, "verification")


def resolve_latest_review_ref(logs_dir: str | Path) -> str | None:
    """Resolve the latest review ref from logs."""

    return _resolve_latest_ref(logs_dir, "review")
