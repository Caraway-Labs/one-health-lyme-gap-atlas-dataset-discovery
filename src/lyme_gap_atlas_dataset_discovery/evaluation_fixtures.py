"""Explicit offline transport fixture; never opens a database or network connection."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any


@dataclass
class OfflineConnection:
    responses: list[list[tuple[Any, ...]] | Exception]
    calls: list[tuple[str, tuple[object, ...], int | None]] = field(default_factory=list)
    closed_cursors: int = 0

    def cursor(self) -> "OfflineCursor":
        if not self.responses:
            raise AssertionError("offline fixture response budget exhausted")
        return OfflineCursor(self, self.responses.pop(0))


@dataclass
class OfflineCursor:
    connection: OfflineConnection
    response: list[tuple[Any, ...]] | Exception

    def execute(
        self, sql: str, params: Sequence[object] = (), *, timeout: int | None = None
    ) -> "OfflineCursor":
        self.connection.calls.append((sql, tuple(params), timeout))
        if isinstance(self.response, Exception):
            raise self.response
        return self

    def fetchone(self) -> tuple[Any, ...] | None:
        if isinstance(self.response, Exception):
            raise AssertionError("fixture fetched after failed execution")
        return self.response.pop(0) if self.response else None

    def close(self) -> None:
        self.connection.closed_cursors += 1
