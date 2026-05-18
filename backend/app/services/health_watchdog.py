"""Self-healing watchdogs for long-lived backend processes."""
from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path

from app.database import probe_business_database_path


def _env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name, "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, "").strip() or default)
    except ValueError:
        return default


def get_process_rss_bytes() -> int:
    """Return the current process RSS in bytes."""
    status_path = Path("/proc/self/status")
    if status_path.exists():
        for line in status_path.read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                parts = line.split()
                if len(parts) >= 2:
                    return int(parts[1]) * 1024
    return 0


async def business_database_watchdog(
    *,
    interval_seconds: float,
    timeout_seconds: float,
    max_failures: int,
    startup_grace_seconds: float,
    exit_code: int,
    ping: Callable[[], Awaitable[object]] = probe_business_database_path,
    exit_fn: Callable[[int], None] = os._exit,
) -> None:
    """Exit the process when the business database stays unhealthy."""
    failures = 0
    if startup_grace_seconds > 0:
        await asyncio.sleep(startup_grace_seconds)

    while True:
        try:
            await asyncio.wait_for(ping(), timeout=timeout_seconds)
            if failures:
                print(f"[{datetime.utcnow()}] Business database watchdog recovered.")
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            failures += 1
            print(
                f"[{datetime.utcnow()}] Business database watchdog failure "
                f"{failures}/{max_failures}: {exc}"
            )
            if failures >= max_failures:
                print(
                    f"[{datetime.utcnow()}] Business database watchdog exiting process "
                    f"with code {exit_code}."
                )
                exit_fn(exit_code)
                return

        await asyncio.sleep(interval_seconds)


def start_business_database_watchdog() -> asyncio.Task[None] | None:
    """Start the watchdog task when enabled by environment."""
    if not _env_flag("BUSINESS_DB_WATCHDOG_ENABLED", default=False):
        return None

    interval_seconds = _env_float("BUSINESS_DB_WATCHDOG_INTERVAL_SECONDS", 30.0)
    timeout_seconds = _env_float("BUSINESS_DB_WATCHDOG_TIMEOUT_SECONDS", 10.0)
    max_failures = max(1, _env_int("BUSINESS_DB_WATCHDOG_MAX_FAILURES", 3))
    startup_grace_seconds = _env_float("BUSINESS_DB_WATCHDOG_STARTUP_GRACE_SECONDS", 60.0)
    exit_code = _env_int("BUSINESS_DB_WATCHDOG_EXIT_CODE", 12)

    print(
        f"[{datetime.utcnow()}] Business database watchdog enabled "
        f"(interval={interval_seconds}s, timeout={timeout_seconds}s, "
        f"max_failures={max_failures}, startup_grace={startup_grace_seconds}s)."
    )
    return asyncio.create_task(
        business_database_watchdog(
            interval_seconds=interval_seconds,
            timeout_seconds=timeout_seconds,
            max_failures=max_failures,
            startup_grace_seconds=startup_grace_seconds,
            exit_code=exit_code,
        )
    )


async def memory_watchdog(
    *,
    interval_seconds: float,
    limit_bytes: int,
    exit_code: int,
    rss_reader: Callable[[], int] = get_process_rss_bytes,
    exit_fn: Callable[[int], None] = os._exit,
) -> None:
    """Exit the process when resident memory exceeds a configured limit."""
    while True:
        rss_bytes = rss_reader()
        if rss_bytes > limit_bytes:
            print(
                f"[{datetime.utcnow()}] Memory watchdog exiting process with code {exit_code}: "
                f"rss={rss_bytes} bytes, limit={limit_bytes} bytes."
            )
            exit_fn(exit_code)
            return
        await asyncio.sleep(interval_seconds)


def start_memory_watchdog() -> asyncio.Task[None] | None:
    """Start the process memory watchdog when enabled by environment."""
    if not _env_flag("PROCESS_MEMORY_WATCHDOG_ENABLED", default=False):
        return None

    limit_mb = _env_int("PROCESS_MEMORY_WATCHDOG_LIMIT_MB", 384)
    interval_seconds = _env_float("PROCESS_MEMORY_WATCHDOG_INTERVAL_SECONDS", 30.0)
    exit_code = _env_int("PROCESS_MEMORY_WATCHDOG_EXIT_CODE", 13)
    limit_bytes = max(1, limit_mb) * 1024 * 1024

    print(
        f"[{datetime.utcnow()}] Memory watchdog enabled "
        f"(limit={limit_mb}MiB, interval={interval_seconds}s)."
    )
    return asyncio.create_task(
        memory_watchdog(
            interval_seconds=interval_seconds,
            limit_bytes=limit_bytes,
            exit_code=exit_code,
        )
    )


async def stop_watchdog(task: asyncio.Task[None] | None) -> None:
    """Cancel a watchdog task during clean application shutdown."""
    if task is None:
        return

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
