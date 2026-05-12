from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol


def resolve_common_files_dir() -> Path:
    override = os.getenv("MT5_COMMON_FILES_DIR", "").strip()
    if override:
        return Path(override)
    appdata = os.getenv("APPDATA", "").strip()
    if appdata:
        return Path(appdata) / "MetaQuotes" / "Terminal" / "Common" / "Files"
    return Path.cwd() / "runtime"


@dataclass(slots=True)
class NotificationEvent:
    title: str
    message: str
    priority: int = 1
    symbol: str | None = None
    kind: str = "info"
    created_at: str = ""

    def to_json(self) -> str:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        return json.dumps(
            {
                "title": self.title,
                "message": self.message,
                "priority": self.priority,
                "symbol": self.symbol,
                "kind": self.kind,
                "created_at": self.created_at,
            },
            ensure_ascii=True,
        )

    def to_line(self) -> str:
        if not self.created_at:
            self.created_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        return (
            f"[{self.created_at}] "
            f"P{self.priority} "
            f"{self.kind.upper()} "
            f"{self.title} | {self.message}"
        )


class NotificationSink(Protocol):
    def emit(self, event: NotificationEvent) -> None: ...


class ConsoleSink:
    def emit(self, event: NotificationEvent) -> None:
        print(f"[{event.kind.upper()}] {event.title} | {event.message}")


class MT5QueueSink:
    def __init__(self, queue_file: str):
        base_dir = resolve_common_files_dir()
        base_dir.mkdir(parents=True, exist_ok=True)
        self.path = Path(queue_file)
        if not self.path.is_absolute():
            self.path = base_dir / queue_file
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: NotificationEvent) -> None:
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(event.to_line() + "\n")


class NotificationBus:
    def __init__(self, sinks: list[NotificationSink] | None = None, *, min_priority: int = 1):
        self.sinks = sinks or []
        self.min_priority = min_priority

    def publish(self, event: NotificationEvent) -> None:
        if event.priority < self.min_priority:
            return
        for sink in self.sinks:
            sink.emit(event)

    def info(self, title: str, message: str, *, symbol: str | None = None, priority: int = 1) -> None:
        self.publish(NotificationEvent(title=title, message=message, priority=priority, symbol=symbol, kind="info"))

    def warn(self, title: str, message: str, *, symbol: str | None = None, priority: int = 2) -> None:
        self.publish(NotificationEvent(title=title, message=message, priority=priority, symbol=symbol, kind="warn"))

    def error(self, title: str, message: str, *, symbol: str | None = None, priority: int = 0) -> None:
        self.publish(NotificationEvent(title=title, message=message, priority=priority, symbol=symbol, kind="error"))
