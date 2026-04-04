"""Session integrity validation and lightweight repair helpers."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from guild_scroll.config import PARTS_DIR_NAME, SESSION_LOG_NAME
from guild_scroll.integrity import load_session_key, verify_event_hmac, should_sign


@dataclass
class ValidationReport:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)
    repaired: list[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return not self.errors

    def format(self) -> str:
        lines: list[str] = []
        for message in self.errors:
            lines.append(f"- error: {message}")
        for message in self.warnings:
            lines.append(f"~ warning: {message}")
        for message in self.repaired:
            lines.append(f"+ repaired: {message}")
        for message in self.info:
            lines.append(f"+ info: {message}")
        if not lines:
            lines.append("+ info: no validation issues found")
        return "\n".join(lines)


def _relative_to_session(sess_dir: Path, candidate: Path) -> str:
    return candidate.relative_to(sess_dir).as_posix()


def _parse_jsonl(log_path: Path, sess_dir: Path, report: ValidationReport) -> list[dict]:
    if not log_path.exists():
        report.errors.append(f"missing log file: {_relative_to_session(sess_dir, log_path)}")
        return []

    from guild_scroll.crypto import read_plaintext
    try:
        content = read_plaintext(log_path)
    except Exception:
        content = log_path.read_text(encoding="utf-8")

    records: list[dict] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            report.errors.append(
                f"{_relative_to_session(sess_dir, log_path)}:{line_number} has invalid JSONL"
            )
            continue
        if not isinstance(record, dict):
            report.errors.append(
                f"{_relative_to_session(sess_dir, log_path)}:{line_number} must contain a JSON object"
            )
            continue
        records.append(record)
    return records


def _collect_log_records(sess_dir: Path, report: ValidationReport) -> tuple[list[Path], list[dict], dict | None]:
    log_paths: list[Path] = []
    all_records: list[dict] = []

    main_log = sess_dir / "logs" / SESSION_LOG_NAME
    main_records = _parse_jsonl(main_log, sess_dir, report)
    log_paths.append(main_log)
    all_records.extend(main_records)

    meta = next((record for record in main_records if record.get("type") == "session_meta"), None)
    if meta is None:
        report.errors.append("logs/session.jsonl is missing a session_meta record")
        return log_paths, all_records, None

    try:
        parts_count = max(int(meta.get("parts_count") or 1), 1)
    except (TypeError, ValueError):
        report.errors.append("session_meta.parts_count must be an integer")
        parts_count = 1
    parts_dir = sess_dir / PARTS_DIR_NAME
    declared_parts = {part_num for part_num in range(2, parts_count + 1)}
    existing_parts = set()
    if parts_dir.exists():
        existing_parts = {
            int(part_dir.name)
            for part_dir in parts_dir.iterdir()
            if part_dir.is_dir() and part_dir.name.isdigit()
        }

    for part_num in sorted(declared_parts):
        part_log = parts_dir / str(part_num) / "logs" / SESSION_LOG_NAME
        if not part_log.exists():
            report.errors.append(f"missing declared part log: {_relative_to_session(sess_dir, part_log)}")
            continue
        log_paths.append(part_log)
        all_records.extend(_parse_jsonl(part_log, sess_dir, report))

    for part_num in sorted(existing_parts - declared_parts):
        part_log = parts_dir / str(part_num) / "logs" / SESSION_LOG_NAME
        if part_log.exists():
            report.warnings.append(
                f"undeclared part log present: {_relative_to_session(sess_dir, part_log)}"
            )
            log_paths.append(part_log)
            all_records.extend(_parse_jsonl(part_log, sess_dir, report))
        else:
            report.errors.append(f"missing log file: {_relative_to_session(sess_dir, part_log)}")

    return log_paths, all_records, meta


def _resolve_event_path(sess_dir: Path, raw_path: str, label: str, report: ValidationReport) -> Path | None:
    candidate = Path(raw_path)
    if candidate.is_absolute():
        report.errors.append(f"{label} path must stay inside the session directory: {raw_path}")
        return None

    resolved = (sess_dir / candidate).resolve()
    try:
        resolved.relative_to(sess_dir.resolve())
    except ValueError:
        report.errors.append(f"{label} path escapes the session directory: {raw_path}")
        return None

    if not resolved.exists():
        report.errors.append(f"{label} missing file: {raw_path}")
        return None

    return resolved


def _iter_orphan_candidates(sess_dir: Path) -> list[Path]:
    candidates: list[Path] = []
    for root in [sess_dir / "assets", sess_dir / "screenshots"]:
        if root.exists():
            candidates.extend(path for path in root.rglob("*") if path.is_file())

    parts_dir = sess_dir / PARTS_DIR_NAME
    if parts_dir.exists():
        for part_dir in parts_dir.iterdir():
            if part_dir.is_dir() and part_dir.name.isdigit():
                assets_dir = part_dir / "assets"
                if assets_dir.exists():
                    candidates.extend(path for path in assets_dir.rglob("*") if path.is_file())
    return candidates


def validate_session(sess_dir: Path) -> ValidationReport:
    report = ValidationReport()
    log_paths, records, meta = _collect_log_records(sess_dir, report)

    command_count = sum(1 for record in records if record.get("type") == "command")
    if meta is not None and meta.get("command_count", 0) != command_count:
        report.warnings.append(
            f"session_meta.command_count is {meta.get('command_count', 0)}, found {command_count} command event(s)"
        )
    if meta is not None and not meta.get("end_time"):
        report.warnings.append("session_meta.end_time is missing")

    # HMAC integrity check
    hmac_key = load_session_key(sess_dir)
    session_mode = meta.get("mode") if meta is not None else None
    if hmac_key is not None:
        for record in records:
            if not should_sign(record):
                continue
            if not verify_event_hmac(hmac_key, record):
                event_type = record.get("type", "unknown")
                seq = record.get("seq", "?")
                report.errors.append(
                    f"HMAC mismatch for {event_type} event (seq={seq}): record may have been tampered with"
                )
            # Assessment mode: unsigned events are errors
            if session_mode == "assessment" and record.get("event_hmac") is None:
                event_type = record.get("type", "unknown")
                seq = record.get("seq", "?")
                report.errors.append(
                    f"unsigned {event_type} event (seq={seq}): assessment mode requires HMAC on all events"
                )
    else:
        signed_count = sum(
            1 for r in records if should_sign(r) and r.get("event_hmac") is not None
        )
        if signed_count:
            report.warnings.append(
                f"{signed_count} event(s) carry event_hmac but session.key is missing — cannot verify integrity"
            )
        # Assessment mode without key is an error
        if session_mode == "assessment":
            report.errors.append(
                "assessment mode session is missing session.key — integrity cannot be verified"
            )

    referenced_paths: set[Path] = set()
    for record in records:
        record_type = record.get("type")
        if record_type == "asset" and record.get("captured_path"):
            resolved = _resolve_event_path(sess_dir, record["captured_path"], "asset", report)
            if resolved is not None:
                referenced_paths.add(resolved)
        elif record_type == "screenshot" and record.get("screenshot_path"):
            resolved = _resolve_event_path(sess_dir, record["screenshot_path"], "screenshot", report)
            if resolved is not None:
                referenced_paths.add(resolved)

    for file_path in _iter_orphan_candidates(sess_dir):
        if file_path.resolve() not in referenced_paths:
            report.warnings.append(
                f"unreferenced file on disk: {_relative_to_session(sess_dir, file_path)}"
            )

    # Assessment mode: check file/directory permissions
    if session_mode == "assessment":
        _check_assessment_permissions(sess_dir, report)

    report.info.append(f"checked {len(set(log_paths))} log file(s)")
    report.info.append(f"parsed {len(records)} JSONL record(s)")
    if session_mode:
        report.info.append(f"session mode: {session_mode}")
    report.info.append(
        f"found {len(report.errors)} error(s) and {len(report.warnings)} warning(s)"
    )
    return report

def _check_assessment_permissions(sess_dir: Path, report: ValidationReport) -> None:
    """Check that assessment mode sessions have strict file/directory permissions."""
    try:
        dir_mode = sess_dir.stat().st_mode & 0o777
        if dir_mode & 0o077:
            report.warnings.append(
                f"session directory has loose permissions ({oct(dir_mode)}); "
                f"assessment mode recommends 0o700"
            )
    except OSError:
        pass

    key_path = sess_dir / "session.key"
    if key_path.exists():
        try:
            key_mode = key_path.stat().st_mode & 0o777
            if key_mode & 0o077:
                report.errors.append(
                    f"session.key has loose permissions ({oct(key_mode)}); "
                    f"assessment mode requires 0o600"
                )
        except OSError:
            pass

    sig_path = sess_dir / "logs" / "session.sig"
    if not sig_path.exists():
        report.warnings.append(
            "assessment mode session is not signed — run 'gscroll sign' to create a signature"
        )


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _latest_event_timestamp(records: list[dict], meta: dict) -> str:
    candidates: list[tuple[datetime, str]] = []

    start_time = meta.get("start_time", "")
    parsed_start = _parse_timestamp(start_time)
    if parsed_start is not None:
        candidates.append((parsed_start, start_time))

    for record in records:
        record_type = record.get("type")
        if record_type == "command":
            timestamps = [record.get("timestamp_end", ""), record.get("timestamp_start", "")]
        elif record_type in {"asset", "note", "screenshot"}:
            timestamps = [record.get("timestamp", "")]
        else:
            timestamps = []

        for timestamp in timestamps:
            parsed = _parse_timestamp(timestamp)
            if parsed is not None:
                candidates.append((parsed, timestamp))

    if not candidates:
        return start_time
    return max(candidates, key=lambda item: item[0])[1]


def repair_session(sess_dir: Path) -> ValidationReport:
    report = ValidationReport()
    _, records, meta = _collect_log_records(sess_dir, report)
    if meta is None:
        return report

    updated_fields: list[str] = []
    command_count = sum(1 for record in records if record.get("type") == "command")
    if meta.get("command_count", 0) != command_count:
        old_value = meta.get("command_count", 0)
        meta["command_count"] = command_count
        updated_fields.append(f"session_meta.command_count {old_value} -> {command_count}")

    if not meta.get("end_time"):
        end_time = _latest_event_timestamp(records, meta)
        meta["end_time"] = end_time
        updated_fields.append(f"session_meta.end_time -> {end_time}")

    if not updated_fields:
        report.info.append("no repairable session_meta fields needed updates")
        return report

    log_path = sess_dir / "logs" / SESSION_LOG_NAME
    from guild_scroll.crypto import read_plaintext, is_encrypted, load_encryption_key, encrypt_data
    content = read_plaintext(log_path)
    rewritten: list[str] = []
    for line in content.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            rewritten.append(stripped)
            continue
        if record.get("type") == "session_meta":
            record.update(
                command_count=meta["command_count"],
                end_time=meta["end_time"],
            )
        rewritten.append(json.dumps(record, ensure_ascii=False))

    new_content = "\n".join(rewritten) + "\n"
    if is_encrypted(log_path):
        enc_key = load_encryption_key(sess_dir)
        if enc_key is not None:
            log_path.write_bytes(encrypt_data(enc_key, new_content.encode("utf-8")))
        else:
            log_path.write_text(new_content, encoding="utf-8")
    else:
        log_path.write_text(new_content, encoding="utf-8")
    report.repaired.extend(updated_fields)
    return report
