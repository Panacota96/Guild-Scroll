"""
Dataclasses for the JSONL log format.
Each class has to_dict() / from_dict() for serialisation.
"""
from __future__ import annotations

import socket
from dataclasses import dataclass, field, asdict
from typing import Any, Optional


@dataclass
class SessionMeta:
    session_name: str
    session_id: str
    start_time: str
    hostname: str = field(default_factory=socket.gethostname)
    type: str = field(default="session_meta", init=False)
    end_time: Optional[str] = None
    command_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Ensure 'type' is first for readability
        return {"type": d.pop("type"), **d}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SessionMeta:
        d = dict(d)
        d.pop("type", None)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class CommandEvent:
    seq: int
    command: str
    timestamp_start: str
    timestamp_end: str
    exit_code: int
    working_directory: str
    type: str = field(default="command", init=False)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {"type": d.pop("type"), **d}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CommandEvent:
        d = dict(d)
        d.pop("type", None)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class AssetEvent:
    seq: int
    trigger_command: str
    asset_type: str          # "download" | "extract" | "clone"
    captured_path: str       # relative path inside session dir
    original_path: str       # where the file appeared
    timestamp: str
    type: str = field(default="asset", init=False)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {"type": d.pop("type"), **d}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AssetEvent:
        d = dict(d)
        d.pop("type", None)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class NoteEvent:
    text: str
    timestamp: str
    tags: list[str] = field(default_factory=list)
    type: str = field(default="note", init=False)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return {"type": d.pop("type"), **d}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> NoteEvent:
        d = dict(d)
        d.pop("type", None)
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
