"""Minimal spawn targets: no application imports, services, or credentials."""

import os
import time
from pathlib import Path
from typing import Any


def blocking_operation(_send: Any, run_id: str, _trace_id: str) -> None:
    Path(run_id).write_text("entered blocking operation", encoding="utf-8")
    time.sleep(60)


def abrupt_exit(_send: Any, _run_id: str, _trace_id: str) -> None:
    os._exit(1)
