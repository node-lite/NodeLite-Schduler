from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any, Iterable


def read_json(path: Path, default: Any = None) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def append_jsonl(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        json.dump(value, handle, sort_keys=True, ensure_ascii=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    temporary.replace(path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def stable_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def percentile(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * quantile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def summarize(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {
            "sample_count": 0,
            "min_ms": None,
            "median_ms": None,
            "mean_ms": None,
            "p95_ms": None,
            "max_ms": None,
            "stddev_ms": None,
        }
    return {
        "sample_count": len(values),
        "min_ms": min(values),
        "median_ms": statistics.median(values),
        "mean_ms": statistics.fmean(values),
        "p95_ms": percentile(values, 0.95),
        "max_ms": max(values),
        "stddev_ms": statistics.pstdev(values),
    }


def command_version(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=10, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    line = (result.stdout or "").strip().splitlines()
    return line[0] if line else None


def executable(command: str) -> str | None:
    return shutil.which(command)


def environment_record(repo: Path) -> dict[str, Any]:
    stat = os.statvfs(repo)
    node_version = command_version([executable("node") or "node", "--version"])
    npm_version = command_version([executable("npm") or "npm", "--version"])
    try:
        libc_name, libc_version = platform.libc_ver()
        filesystem = subprocess.run(
            ["stat", "-f", "-c", "%T", str(repo)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        ).stdout.strip()
    except OSError:
        libc_name, libc_version, filesystem = "", "", "unknown"
    value = {
        "hostname": platform.node(),
        "os": platform.system().lower(),
        "os_release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "libc": f"{libc_name}-{libc_version}",
        "python": platform.python_version(),
        "node": node_version,
        "npm": npm_version,
        "filesystem": filesystem,
        "filesystem_block_size": stat.f_bsize,
        "cpu_count": os.cpu_count(),
        "container": Path("/.dockerenv").exists(),
        "page_cache_policy": "logical_cold",
        "network_policy": "local-first; explicit network benchmarks allowed",
    }
    value["measurement_environment_id"] = f"env:{stable_hash(value)[:20]}"
    value["captured_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    return value


def temporary_directory(prefix: str, parent: Path | None = None):
    if parent:
        parent.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix=prefix, dir=str(parent) if parent else None)
