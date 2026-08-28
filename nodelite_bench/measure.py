from __future__ import annotations

import os
import resource
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Callable

try:
    import psutil
except ImportError:
    psutil = None


def _rusage() -> resource.struct_rusage:
    return resource.getrusage(resource.RUSAGE_CHILDREN)


def measure_callable(action: Callable[[], dict[str, Any] | None]) -> dict[str, Any]:
    usage_before = resource.getrusage(resource.RUSAGE_SELF)
    started = time.perf_counter_ns()
    try:
        details = action() or {}
        success = bool(details.pop("success", True))
        error = details.pop("error", None)
    except Exception as exc:
        details = {}
        success = False
        error = f"{type(exc).__name__}: {exc}"
    finished = time.perf_counter_ns()
    usage_after = resource.getrusage(resource.RUSAGE_SELF)
    return {
        "wall_ms": (finished - started) / 1_000_000,
        "ready_ms": details.pop("ready_ms", (finished - started) / 1_000_000),
        "user_cpu_ms": (usage_after.ru_utime - usage_before.ru_utime) * 1000,
        "system_cpu_ms": (usage_after.ru_stime - usage_before.ru_stime) * 1000,
        "rss_mb": details.pop("rss_mb", None),
        "peak_rss_mb": details.pop("peak_rss_mb", None),
        "success": success,
        "timed_out": False,
        "exit_code": 0 if success else None,
        "error": error,
        **details,
    }


def run_process(
    command: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    timeout: float = 60,
    input_text: str | None = None,
) -> dict[str, Any]:
    usage_before = _rusage()
    started = time.perf_counter_ns()
    timed_out = False
    peak_rss = 0
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd) if cwd else None,
            env={**os.environ, **(env or {})},
            stdin=subprocess.PIPE if input_text is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
    except OSError as exc:
        finished = time.perf_counter_ns()
        return {
            "wall_ms": (finished - started) / 1_000_000,
            "ready_ms": (finished - started) / 1_000_000,
            "user_cpu_ms": 0.0,
            "system_cpu_ms": 0.0,
            "rss_mb": None,
            "peak_rss_mb": None,
            "success": False,
            "timed_out": False,
            "exit_code": None,
            "error": f"{type(exc).__name__}: {exc}",
            "command": command,
        }

    stop_poll = threading.Event()

    def poll_memory() -> None:
        nonlocal peak_rss
        if psutil is None:
            return
        try:
            root = psutil.Process(process.pid)
            while not stop_poll.wait(0.005):
                processes = [root, *root.children(recursive=True)]
                peak_rss = max(peak_rss, sum(item.memory_info().rss for item in processes if item.is_running()))
        except (psutil.Error, OSError):
            return

    poller = threading.Thread(target=poll_memory, daemon=True)
    poller.start()
    try:
        stdout, stderr = process.communicate(input=input_text, timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
    finally:
        stop_poll.set()
        poller.join(timeout=1)
    finished = time.perf_counter_ns()
    usage_after = _rusage()
    return {
        "wall_ms": (finished - started) / 1_000_000,
        "ready_ms": (finished - started) / 1_000_000,
        "user_cpu_ms": (usage_after.ru_utime - usage_before.ru_utime) * 1000,
        "system_cpu_ms": (usage_after.ru_stime - usage_before.ru_stime) * 1000,
        "rss_mb": None,
        "peak_rss_mb": peak_rss / (1024 * 1024) if peak_rss else None,
        "success": process.returncode == 0 and not timed_out,
        "timed_out": timed_out,
        "exit_code": process.returncode,
        "error": None if process.returncode == 0 and not timed_out else (stderr or stdout)[-2000:],
        "stdout": stdout[-2000:],
        "stderr": stderr[-2000:],
        "command": command,
    }


def terminate_process(process: subprocess.Popen[Any], grace_seconds: float = 1.0) -> tuple[float, bool]:
    started = time.perf_counter_ns()
    forced = False
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            forced = True
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
    return (time.perf_counter_ns() - started) / 1_000_000, forced
