from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import PositionLifecycle


class PositionStateStore:
    def __init__(self, path: str | Path = "runtime/position_state.json"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, PositionLifecycle] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self._items = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            self._items = {}
            return
        items: dict[str, PositionLifecycle] = {}
        if isinstance(raw, dict):
            for key, payload in raw.items():
                if not isinstance(payload, dict):
                    continue
                try:
                    items[str(key)] = PositionLifecycle(**payload)
                except Exception:
                    continue
        self._items = items

    def save(self) -> None:
        payload = {ticket: asdict(item) for ticket, item in self._items.items()}
        self.path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")

    def upsert(self, item: PositionLifecycle) -> None:
        self._items[str(item.ticket)] = item
        self.save()

    def get(self, ticket: int) -> PositionLifecycle | None:
        return self._items.get(str(ticket))

    def remove(self, ticket: int) -> None:
        self._items.pop(str(ticket), None)
        self.save()

    def items(self) -> list[PositionLifecycle]:
        return list(self._items.values())

    def active_items(self, symbol: str | None = None) -> list[PositionLifecycle]:
        items = self.items()
        if symbol:
            return [item for item in items if item.symbol == symbol and item.remaining_volume > 0]
        return [item for item in items if item.remaining_volume > 0]

    def mark_action(
        self,
        ticket: int,
        *,
        partial_done: bool | None = None,
        breakeven_done: bool | None = None,
        trailing_done: bool | None = None,
        remaining_volume: float | None = None,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> None:
        item = self.get(ticket)
        if item is None:
            return
        if partial_done is not None:
            item.partial_done = partial_done
        if breakeven_done is not None:
            item.breakeven_done = breakeven_done
        if trailing_done is not None:
            item.trailing_done = trailing_done
        if remaining_volume is not None:
            item.remaining_volume = remaining_volume
        if stop_loss is not None:
            item.stop_loss = stop_loss
        if take_profit is not None:
            item.take_profit = take_profit
        item.updated_at = datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
        self.upsert(item)
