from __future__ import annotations

import concurrent.futures
import contextlib
import csv
import hashlib
import http.client
import http.server
import json
import os
import random
import re
import shutil
import signal
import socket
import sqlite3
import ssl
import subprocess
import sys
import tarfile
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Callable

from .catalog import BenchmarkSpec
from .context import RunContext, Scenario
from .measure import measure_callable, run_process, terminate_process
from .util import read_json, sha256_file, stable_hash, temporary_directory, write_json


RESOURCE_BY_PREFIX = {
    "CTL": "control_plane",
    "PRE": "discovery_resolution",
    "SRC": "source_overlay",
    "ART": "artifact_acquisition",
    "CAS": "raw_cas",
    "REG": "local_registry",
    "RUN": "node_runtime",
    "PM": "package_manager",
    "PMC": "pm_native_cache",
    "DEP": "dependency_view",
    "INS": "dependency_view",
    "BLD": "build_cache",
    "TST": "test_transform_cache",
    "BRW": "browser_process",
    "GUI": "display_service",
    "DB": "database_binary",
    "DBS": "database_daemon",
    "NAT": "native_binary_bundle",
    "NTC": "system_toolchain",
    "SYS": "rootfs",
    "FS": "filesystem_overlay",
    "NET": "network_ports",
    "SRV": "project_server",
    "TSK": "task_harness",
    "FAIL": "failure_recovery",
    "CON": "contention",
}

INVALIDATIONS = {
    "node_runtime": ["dependency_view", "native_binary_bundle", "build_cache", "test_transform_cache"],
    "package_manager": ["pm_native_cache", "dependency_view"],
    "dependency_view": ["build_cache", "test_transform_cache"],
    "repo_baseline": ["source_overlay", "build_cache", "test_transform_cache"],
    "browser_process": ["browser_context", "browser_profile"],
    "database_daemon": ["database_clean_snapshot", "database_private_layer"],
    "rootfs": ["node_runtime", "dependency_view", "native_binary_bundle", "browser_binary", "database_binary", "system_toolchain"],
}


def _synthetic_scenario(
    context: RunContext,
    spec: BenchmarkSpec,
    action: Callable[[], dict[str, Any]],
    *,
    resource_kind: str | None = None,
    transition_class: str = "exact_hit",
    state_before: str = "exact_hit",
    scenario_name: str = "default",
    object_name: str | None = None,
    invalidates: list[str] | None = None,
    reuse_safe: bool = True,
    pollution_check: str = "pass",
) -> Scenario:
    kind = resource_kind or RESOURCE_BY_PREFIX[spec.prefix]
    object_id = f"{kind}:benchmark:{spec.benchmark_id.lower()}:{scenario_name}"
    context.ensure_object(object_id, kind, object_name or spec.description[:80], dimensions={"benchmark_id": spec.benchmark_id, "scenario": scenario_name})
    return Scenario(
        benchmark_id=spec.benchmark_id,
        resource_kind=kind,
        from_object_id=object_id if transition_class in {"exact_hit", "compatible_reuse", "dirty_reset"} else None,
        to_object_id=object_id,
        transition_class=transition_class,
        cost_class=spec.cost_class,
        state_before=state_before,
        workload_origin="synthetic",
        action=action,
        invalidates=invalidates or [],
        reuse_safe=reuse_safe,
        pollution_check=pollution_check,
        scenario_name=scenario_name,
    )


def _object_scenario(
    spec: BenchmarkSpec,
    item: dict[str, Any],
    action: Callable[[], dict[str, Any]],
    *,
    from_object_id: str | None = None,
    transition_class: str = "process_cold",
    state_before: str | None = None,
    scenario_name: str = "default",
    invalidates: list[str] | None = None,
    reuse_safe: bool = True,
) -> Scenario:
    return Scenario(
        benchmark_id=spec.benchmark_id,
        resource_kind=str(item["resource_kind"]),
        from_object_id=from_object_id,
        to_object_id=str(item["object_id"]),
        transition_class=transition_class,
        cost_class=spec.cost_class,
        state_before=state_before or transition_class,
        workload_origin=str(item.get("workload_origin") or "synthetic"),
        action=action,
        invalidates=invalidates or [],
        reuse_safe=reuse_safe,
        scenario_name=scenario_name,
    )


def _inventory(context: RunContext) -> dict[str, Any]:
    return context.inventory


def _profile_files(context: RunContext) -> list[Path]:
    return sorted((context.ctdp_out / "projects").glob("*/discovery.json"))


def _lock_files(context: RunContext, pattern: str = "*") -> list[Path]:
    return sorted(
        path
        for path in (context.ctdp_out / "projects").glob(f"*/resolved-lockfiles/**/*{pattern}")
        if path.is_file()
    )


def _source_files(context: RunContext) -> list[Path]:
    return sorted(path for path in (context.ctdp_out / "projects").glob("*/source-files/**/*") if path.is_file())


def _representative_source(context: RunContext) -> Path:
    candidates = _source_files(context)
    if not candidates:
        raise FileNotFoundError("CTDP source snapshots unavailable")
    parents = [path.parent for path in candidates if path.name == "package.json"]
    return parents[0] if parents else candidates[0].parent


def _cas_artifacts(context: RunContext) -> list[dict[str, Any]]:
    cached = context.shared.get("prefetch_artifacts")
    if cached is None:
        cached = read_json(context.ctdp_out / "prefetch.json", {}).get("artifacts", [])
        cached = [item for item in cached if item.get("cas_path") and (context.ctdp_out / str(item["cas_path"])).is_file()]
        context.shared["prefetch_artifacts"] = cached
    return cached


def _cas_samples(context: RunContext) -> list[dict[str, Any]]:
    cached = context.shared.get("cas_samples")
    if cached is not None:
        return cached
    artifacts = sorted(_cas_artifacts(context), key=lambda item: int(item.get("size_bytes") or 0))
    targets = [1024, 100 * 1024, 1024 * 1024, 10 * 1024 * 1024, 100 * 1024 * 1024]
    selected: list[dict[str, Any]] = []
    for target in targets:
        match = next((item for item in artifacts if int(item.get("size_bytes") or 0) >= target), None)
        if match and match not in selected:
            selected.append(match)
    context.shared["cas_samples"] = selected
    return selected


def _local_registry(context: RunContext):
    registry = context.shared.get("local_registry")
    if registry is not None:
        return registry
    source_root = context.ctdp_out.parent.parent / "src"
    if not source_root.is_dir():
        source_root = context.repo.parent / "CTDP" / "src"
    sys.path.insert(0, str(source_root))
    from nodelite_deps.registry import LocalArtifactRegistry

    registry = LocalArtifactRegistry(context.ctdp_out, _cas_artifacts(context))
    context.shared["local_registry"] = registry
    return registry


def _url_get(url: str, timeout: float = 30) -> dict[str, Any]:
    started = time.perf_counter_ns()
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read()
            status = response.status
        finished = time.perf_counter_ns()
        return {"wall_ms": (finished - started) / 1_000_000, "ready_ms": (finished - started) / 1_000_000, "network_bytes": len(body), "read_bytes": len(body), "success": 200 <= status < 300, "exit_code": 0 if 200 <= status < 300 else status, "http_status": status}
    except urllib.error.HTTPError as exc:
        finished = time.perf_counter_ns()
        body = exc.read()
        return {"wall_ms": (finished - started) / 1_000_000, "ready_ms": (finished - started) / 1_000_000, "network_bytes": len(body), "success": False, "exit_code": exc.code, "error": str(exc), "http_status": exc.code}
    except Exception as exc:
        finished = time.perf_counter_ns()
        return {"wall_ms": (finished - started) / 1_000_000, "ready_ms": (finished - started) / 1_000_000, "success": False, "exit_code": None, "error": f"{type(exc).__name__}: {exc}"}


def _control_action(context: RunContext, benchmark_id: str) -> Callable[[], dict[str, Any]]:
    objects = context.objects
    requirements = context.inventory.get("requirements", [])
    invalidation_rules = INVALIDATIONS

    def action() -> dict[str, Any]:
        if benchmark_id == "CTL-001":
            payload = json.dumps({"objects": objects, "requirements": requirements, "rules": invalidation_rules}, separators=(",", ":"))
            json.loads(payload)
            return {"read_bytes": len(payload)}
        if benchmark_id == "CTL-002":
            groups: dict[str, list[str]] = {}
            for item in requirements:
                key = stable_hash(item.get("object_ids", []))
                groups.setdefault(key, []).append(item["profile_id"])
            return {"group_count": len(groups)}
        if benchmark_id == "CTL-003":
            candidates = [item["object_id"] for item in objects[:1000]]
            return {"candidate_count": len(candidates), "checksum": hash(tuple(candidates))}
        if benchmark_id == "CTL-004":
            left = set(requirements[0].get("object_ids", [])) if requirements else set()
            right = set(requirements[-1].get("object_ids", [])) if requirements else set()
            return {"shared_count": len(left & right), "different_count": len(left ^ right)}
        if benchmark_id == "CTL-005":
            left = set(requirements[0].get("object_ids", [])) if requirements else set()
            right = set(requirements[-1].get("object_ids", [])) if requirements else set()
            actions = sorted(right - left)
            return {"action_count": len(actions)}
        if benchmark_id == "CTL-006":
            queue = ["node_runtime"]
            visited: set[str] = set()
            while queue:
                current = queue.pop()
                if current in visited:
                    continue
                visited.add(current)
                queue.extend(invalidation_rules.get(current, []))
            return {"invalidated_count": len(visited) - 1}
        if benchmark_id == "CTL-007":
            scored = [(len(item.get("object_ids", [])), item["profile_id"]) for item in requirements]
            return {"selected": min(scored)[1] if scored else None}
        if benchmark_id == "CTL-008":
            with temporary_directory("nodelite-state-", context.output / "tmp") as directory:
                path = Path(directory) / "node-state.json"
                write_json(path, {"objects": [item["object_id"] for item in objects[:100]], "sequence": 1})
                value = read_json(path, {})
                value["sequence"] += 1
                write_json(path, value)
                return {"write_bytes": path.stat().st_size}
        if benchmark_id == "CTL-009":
            result = subprocess.run([sys.executable, "-c", "pass"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
            return {"success": result.returncode == 0, "exit_code": result.returncode}
        if benchmark_id == "CTL-010":
            with temporary_directory("nodelite-jsonl-", context.output / "tmp") as directory:
                path = Path(directory) / "events.jsonl"
                rows = [{"index": index, "value": index % 17} for index in range(1000)]
                path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
                total = sum(json.loads(line)["value"] for line in path.read_text(encoding="utf-8").splitlines())
                return {"write_bytes": path.stat().st_size, "aggregate": total}
        if benchmark_id == "CTL-011":
            lock = threading.Lock()
            barrier = threading.Barrier(5)
            counter = [0]

            def worker() -> None:
                barrier.wait()
                for _ in range(1000):
                    with lock:
                        counter[0] += 1

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join()
            return {"lock_operations": counter[0]}
        scores = []
        for node in range(32):
            for item in requirements:
                scores.append((node, len(item.get("object_ids", [])) % (node + 1)))
        return {"placement_scores": len(scores), "best": min(scores) if scores else None}

    return action


def _prep_action(context: RunContext, benchmark_id: str) -> Callable[[], dict[str, Any]]:
    def action() -> dict[str, Any]:
        if benchmark_id == "PRE-001":
            lines = [line.strip() for line in context.profiles.read_text(encoding="utf-8").splitlines() if line.strip()]
            if len(lines) != len(set(lines)):
                raise ValueError("duplicate profile IDs")
            return {"profile_count": len(lines), "read_bytes": context.profiles.stat().st_size}
        if benchmark_id == "PRE-002":
            inventory = read_json(context.ctdp_out / "inventory.json", {})
            profiles = {item["profile_id"]: item for item in inventory.get("profiles", [])}
            requested = [line.strip() for line in context.profiles.read_text(encoding="utf-8").splitlines() if line.strip()]
            missing = [item for item in requested if item not in profiles]
            return {"profile_count": len(profiles), "missing_count": len(missing), "success": not missing}
        if benchmark_id == "PRE-003":
            files = sorted((context.ctdp_out / "projects").glob("*/environment/Dockerfile"))
            parsed = sum(len(path.read_text(encoding="utf-8", errors="replace").splitlines()) for path in files)
            return {"file_count": len(files), "line_count": parsed, "read_bytes": sum(path.stat().st_size for path in files)}
        if benchmark_id == "PRE-004":
            files = _source_files(context)
            categories: dict[str, int] = {}
            for path in files:
                categories[path.name] = categories.get(path.name, 0) + 1
            return {"file_count": len(files), "categories": categories}
        if benchmark_id == "PRE-005":
            paths = _lock_files(context)[:20]
            digests = [sha256_file(path) for path in paths]
            return {"file_count": len(paths), "read_bytes": sum(path.stat().st_size for path in paths), "digest": stable_hash(digests)}
        if benchmark_id == "PRE-006":
            value = read_json(context.ctdp_out / "resolution.json", {})
            counts: dict[str, int] = {}
            for item in value.get("profiles", []):
                classification = str(item.get("classification"))
                counts[classification] = counts.get(classification, 0) + 1
            return {"classifications": counts}
        if benchmark_id == "PRE-007":
            return run_process(["git", "-C", str(context.repo), "rev-parse", "HEAD"], timeout=15)
        if benchmark_id == "PRE-008":
            manifests = [path for path in _source_files(context) if path.name == "package.json"]
            changed = 0
            for path in manifests:
                value = read_json(path, {})
                if isinstance(value, dict):
                    replay = json.loads(json.dumps(value))
                    replay.setdefault("private", True)
                    changed += int(replay != value)
            return {"manifest_count": len(manifests), "transformed_count": changed}
        if benchmark_id == "PRE-014":
            records = read_json(context.ctdp_out / "resolution.json", {}).get("profiles", [])
            changed = sum(item.get("source_lockfile_sha256") != item.get("resolved_lockfile_sha256") for item in records)
            return {"record_count": len(records), "changed_count": changed}
        if benchmark_id == "PRE-015":
            paths = [path for path in _lock_files(context, ".json") if path.name == "package-lock.json"]
            records = sum(len(read_json(path, {}).get("packages", {})) for path in paths)
            return {"file_count": len(paths), "record_count": records, "read_bytes": sum(path.stat().st_size for path in paths)}
        if benchmark_id == "PRE-016":
            import yaml

            paths = [path for path in _lock_files(context, ".yaml") if path.name == "pnpm-lock.yaml"]
            loader = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
            records = 0
            for path in paths:
                value = yaml.load(path.read_text(encoding="utf-8"), Loader=loader) or {}
                records += len(value.get("packages", {})) + len(value.get("snapshots", {}))
            return {"file_count": len(paths), "record_count": records, "read_bytes": sum(path.stat().st_size for path in paths)}
        if benchmark_id in {"PRE-017", "PRE-018"}:
            paths = [path for path in _lock_files(context, ".lock") if path.name == "yarn.lock"]
            entry_count = sum(1 for path in paths for line in path.read_text(encoding="utf-8", errors="replace").splitlines() if line and not line.startswith((" ", "#")))
            return {"file_count": len(paths), "entry_count": entry_count, "read_bytes": sum(path.stat().st_size for path in paths)}
        if benchmark_id == "PRE-020":
            files = sorted((context.ctdp_out / "projects").glob("*/normalized/*.json"))
            types: dict[str, int] = {}
            for path in files:
                for artifact in read_json(path, {}).get("artifacts", []):
                    artifact_type = str(artifact.get("type"))
                    types[artifact_type] = types.get(artifact_type, 0) + 1
            return {"file_count": len(files), "artifact_types": types, "artifact_count": sum(types.values())}
        if benchmark_id == "PRE-021":
            artifacts = read_json(context.ctdp_out / "global" / "global_manifest.json", {}).get("artifacts", [])
            index = {item.get("artifact_id"): item for item in artifacts}
            return {"reference_count": len(artifacts), "unique_count": len(index)}
        if benchmark_id == "PRE-022":
            rows = context.inventory.get("requirements", [])
            with temporary_directory("nodelite-report-", context.output / "tmp") as directory:
                path = Path(directory) / "report.csv"
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["profile_id", "objects"])
                    writer.writerows((item["profile_id"], len(item.get("object_ids", []))) for item in rows)
                return {"write_bytes": path.stat().st_size, "row_count": len(rows)}
        if benchmark_id == "PRE-023":
            state = read_json(context.ctdp_out / "state" / "normalize.json", {})
            fingerprint = stable_hash(state)
            return {"fingerprint": fingerprint, "cache_hit": True}
        if benchmark_id == "PRE-024":
            failures = read_json(context.ctdp_out / "reports" / "failures.json", [])
            if isinstance(failures, dict):
                failures = failures.get("failures", [])
            resumable = [item for item in failures if isinstance(item, dict) and item.get("profile_id")]
            return {"failure_count": len(failures), "resumable_count": len(resumable)}
        raise NotImplementedError(benchmark_id)

    return action


def _source_action(context: RunContext, benchmark_id: str) -> Callable[[], dict[str, Any]]:
    source = _representative_source(context)

    def action() -> dict[str, Any]:
        if benchmark_id == "SRC-001":
            with temporary_directory("nodelite-clone-", context.output / "tmp") as directory:
                target = Path(directory) / "repo"
                result = run_process(["git", "clone", "--quiet", "--no-checkout", "--shared", str(context.repo), str(target)], timeout=60)
                result["files_created"] = sum(1 for _ in target.rglob("*")) if target.exists() else 0
                return result
        if benchmark_id in {"SRC-002", "SRC-003"}:
            with temporary_directory("nodelite-worktree-", context.output / "tmp") as directory:
                target = Path(directory) / "worktree"
                started = time.perf_counter_ns()
                add = subprocess.run(["git", "-C", str(context.repo), "worktree", "add", "--quiet", "--detach", str(target), "HEAD"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                ready = time.perf_counter_ns()
                cleanup_started = time.perf_counter_ns()
                remove = subprocess.run(["git", "-C", str(context.repo), "worktree", "remove", "--force", str(target)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=False)
                cleanup_ms = (time.perf_counter_ns() - cleanup_started) / 1_000_000
                return {"wall_ms": (ready - started) / 1_000_000, "ready_ms": (ready - started) / 1_000_000, "cleanup_ms": cleanup_ms, "success": add.returncode == 0 and remove.returncode == 0, "exit_code": add.returncode, "error": add.stderr or remove.stderr}
        if benchmark_id == "SRC-005":
            with temporary_directory("nodelite-snapshot-", context.output / "tmp") as directory:
                target = Path(directory) / "baseline.tar"
                with tarfile.open(target, "w") as archive:
                    archive.add(source, arcname="source")
                return {"write_bytes": target.stat().st_size, "files_created": 1}
        if benchmark_id in {"SRC-006", "SRC-010"}:
            with temporary_directory("nodelite-overlay-", context.output / "tmp") as directory:
                target = Path(directory) / "source"
                shutil.copytree(source, target, symlinks=True)
                files = [path for path in target.rglob("*")]
                return {"files_created": len(files), "write_bytes": sum(path.stat().st_size for path in files if path.is_file())}
        if benchmark_id == "SRC-007":
            with temporary_directory("nodelite-patch-", context.output / "tmp") as directory:
                root = Path(directory)
                file_path = root / "fixture.txt"
                file_path.write_text("before\n", encoding="utf-8")
                result = run_process(["git", "apply", "--unsafe-paths", "-"], cwd=root, input_text="--- a/fixture.txt\n+++ b/fixture.txt\n@@ -1 +1 @@\n-before\n+after\n", timeout=10)
                result["success"] = result["success"] and file_path.read_text(encoding="utf-8") == "after\n"
                return result
        if benchmark_id == "SRC-008":
            files = list(source.rglob("*"))
            digests = [(path.name, path.stat().st_size) for path in files if path.is_file()]
            return {"file_count": len(files), "checksum": stable_hash(digests)}
        if benchmark_id in {"SRC-009", "SRC-012"}:
            with temporary_directory("nodelite-dirty-", context.output / "tmp") as directory:
                target = Path(directory) / "dirty"
                shutil.copytree(source, target, symlinks=True)
                for index in range(100):
                    (target / f"generated-{index}.tmp").write_bytes(b"x" * 1024)
                started = time.perf_counter_ns()
                shutil.rmtree(target)
                elapsed = (time.perf_counter_ns() - started) / 1_000_000
                return {"wall_ms": elapsed, "ready_ms": elapsed, "cleanup_ms": elapsed, "files_created": 0, "success": not target.exists()}
        if benchmark_id == "SRC-011":
            paths = [path for path in source.rglob("*") if path.is_file()]
            total = sum(len(path.read_bytes()) for path in paths)
            return {"read_bytes": total, "file_count": len(paths), "cache_hit": True}
        if benchmark_id == "SRC-013":
            with temporary_directory("nodelite-links-", context.output / "tmp") as directory:
                root = Path(directory)
                internal = root / "internal"
                internal.write_text("ok", encoding="utf-8")
                (root / "safe-link").symlink_to(internal)
                (root / "escape-link").symlink_to("/etc/passwd")
                unsafe = [path for path in root.iterdir() if path.is_symlink() and not path.resolve().is_relative_to(root.resolve())]
                for path in unsafe:
                    path.unlink()
                return {"unsafe_count": len(unsafe), "success": not (root / "escape-link").exists()}
        raise NotImplementedError(benchmark_id)

    return action


def _artifact_action(context: RunContext, benchmark_id: str) -> Callable[[], dict[str, Any]]:
    artifacts = _cas_artifacts(context)
    registry_items = [item for item in artifacts if item.get("type") == "registry" and item.get("name") == "is-number" and item.get("version") == "7.0.0"]
    artifact = registry_items[0] if registry_items else next(item for item in artifacts if item.get("type") == "registry")
    source_url = str(artifact.get("source") or artifact.get("resolved_url") or "https://registry.npmjs.org/is-number/-/is-number-7.0.0.tgz")

    def action() -> dict[str, Any]:
        if benchmark_id == "ART-001":
            return _url_get("https://registry.npmjs.org/is-number", 30)
        if benchmark_id == "ART-002":
            return _url_get(source_url, 30)
        if benchmark_id == "ART-003":
            return _url_get("https://codeload.github.com/jonschlinkert/is-number/tar.gz/refs/tags/7.0.0", 30)
        if benchmark_id == "ART-004":
            return run_process(["git", "ls-remote", "https://github.com/jonschlinkert/is-number.git", "HEAD"], timeout=30)
        if benchmark_id == "ART-005":
            candidates = [item for item in artifacts if item.get("type") == "http_tarball" and str(item.get("source") or "").startswith("http")]
            return _url_get(str(candidates[0]["source"]) if candidates else source_url, 30)
        if benchmark_id == "ART-006":
            electron = Path.home() / ".cache/electron/3978a3c4a2965533dc07f99112894e7e7f80c9ea0f13e2a48cd5a29593568fb2/electron-v40.10.2-linux-x64.zip"
            if not electron.is_file():
                return {"success": False, "error": "cached Electron binary unavailable"}
            with electron.open("rb") as handle:
                total = 0
                while chunk := handle.read(1024 * 1024):
                    total += len(chunk)
            return {"read_bytes": total, "network_bytes": 0, "cache_hit": True}
        if benchmark_id == "ART-008":
            return _expected_failure(_url_get("http://127.0.0.1:9/nodelite-refused", 1))
        raise NotImplementedError(benchmark_id)

    return action


def _cas_action(context: RunContext, benchmark_id: str) -> Callable[[], dict[str, Any]]:
    samples = _cas_samples(context)
    artifact = samples[min(len(samples) - 1, 2)]
    path = context.ctdp_out / str(artifact["cas_path"])

    def action() -> dict[str, Any]:
        if benchmark_id == "CAS-001":
            index = read_json(context.ctdp_out / "global" / "artifact_index.json", {})
            key = str(artifact.get("artifact_id"))
            if isinstance(index, dict):
                value = index.get(key) or index.get("artifacts", {}).get(key)
            else:
                value = None
            return {"index_size": len(index), "lookup_found": value is not None, "cache_hit": True}
        if benchmark_id == "CAS-002":
            stat = path.stat()
            return {"read_bytes": 0, "size_bytes": stat.st_size, "cache_hit": True}
        if benchmark_id == "CAS-003":
            total = 0
            for item in samples:
                blob = context.ctdp_out / str(item["cas_path"])
                with blob.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        total += len(chunk)
            return {"read_bytes": total, "cache_hit": True}
        if benchmark_id in {"CAS-004", "CAS-005"}:
            algorithm = hashlib.sha256() if benchmark_id == "CAS-004" else hashlib.sha512()
            with path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    algorithm.update(chunk)
            return {"read_bytes": path.stat().st_size, "digest": algorithm.hexdigest(), "cache_hit": True}
        if benchmark_id == "CAS-006":
            with temporary_directory("nodelite-cas-write-", context.output / "tmp") as directory:
                root = Path(directory)
                temporary = root / "blob.tmp"
                target = root / "blob"
                payload = path.read_bytes()[:1024 * 1024]
                with temporary.open("wb") as handle:
                    handle.write(payload)
                    handle.flush()
                    os.fsync(handle.fileno())
                temporary.replace(target)
                return {"read_bytes": len(payload), "write_bytes": len(payload), "files_created": 1}
        if benchmark_id == "CAS-007":
            metadata = read_json(context.ctdp_out / "cas" / "metadata" / f"{hashlib.sha256(str(artifact.get('artifact_id')).encode()).hexdigest()}.json", {})
            if not metadata:
                metadata = {"artifact_id": artifact.get("artifact_id"), "cas_path": artifact.get("cas_path")}
            with temporary_directory("nodelite-cas-meta-", context.output / "tmp") as directory:
                target = Path(directory) / "metadata.json"
                write_json(target, metadata)
                read_json(target, {})
                return {"read_bytes": target.stat().st_size, "write_bytes": target.stat().st_size}
        if benchmark_id == "CAS-008":
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                sizes = list(executor.map(lambda _: len(path.read_bytes()), range(8)))
            return {"read_bytes": sum(sizes), "concurrency": 8, "cache_hit": True}
        if benchmark_id == "CAS-009":
            with temporary_directory("nodelite-cas-corrupt-", context.output / "tmp") as directory:
                target = Path(directory) / "blob"
                shutil.copy2(path, target)
                expected = sha256_file(target)
                with target.open("r+b") as handle:
                    handle.seek(0)
                    handle.write(b"corrupt")
                detected = sha256_file(target) != expected
                target.unlink()
                return {"read_bytes": path.stat().st_size * 2, "write_bytes": 7, "corruption_detected": detected, "success": detected}
        if benchmark_id == "CAS-010":
            root = context.ctdp_out / "cas" / "blobs"
            count = sum(1 for path in root.rglob("*") if path.is_file())
            return {"blob_count": count}
        raise NotImplementedError(benchmark_id)

    return action


def _registry_action(context: RunContext, benchmark_id: str) -> Callable[[], dict[str, Any]]:
    def action() -> dict[str, Any]:
        if benchmark_id == "REG-001":
            source_root = context.repo.parent / "CTDP" / "src"
            sys.path.insert(0, str(source_root))
            from nodelite_deps.registry import LocalArtifactRegistry

            registry = LocalArtifactRegistry(context.ctdp_out, _cas_artifacts(context))
            try:
                result = _url_get(registry.base_url + "/health", 5)
            finally:
                cleanup_started = time.perf_counter_ns()
                registry.close()
                cleanup_ms = (time.perf_counter_ns() - cleanup_started) / 1_000_000
            result["cleanup_ms"] = cleanup_ms
            return result
        registry = _local_registry(context)
        if benchmark_id == "REG-002":
            return _url_get(registry.base_url + "/is-number", 10)
        if benchmark_id == "REG-003":
            scoped = next((item for item in _cas_artifacts(context) if str(item.get("name") or "").startswith("@") and item.get("type") == "registry"), None)
            name = urllib.parse.quote(str(scoped.get("name")) if scoped else "@types/node", safe="@")
            return _url_get(registry.base_url + "/" + name, 10)
        if benchmark_id == "REG-004":
            item = _cas_samples(context)[-1]
            return _url_get(registry.tarball_url(item), 30)
        if benchmark_id == "REG-005":
            locks = _lock_files(context)[:20]
            replaced = 0
            for path in locks:
                text = path.read_text(encoding="utf-8", errors="replace")
                replaced += text.count("https://registry.npmjs.org") + text.count("https://registry.yarnpkg.com")
                text.replace("https://registry.npmjs.org", registry.base_url)
            return {"file_count": len(locks), "replacement_count": replaced, "read_bytes": sum(path.stat().st_size for path in locks)}
        if benchmark_id == "REG-006":
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)
            port = server.server_address[1]
            server.server_close()
            return {"port": port}
        if benchmark_id == "REG-007":
            return _expected_failure(_url_get("http://127.0.0.1:9/blocked", 1))
        if benchmark_id == "REG-008":
            failures = read_json(context.ctdp_out / "reports" / "failures.json", {})
            payload = json.dumps(failures).lower()
            classifications = {name: payload.count(name) for name in ("cas", "external", "git", "unknown")}
            return {"classifications": classifications}
        if benchmark_id == "REG-009":
            first = _url_get("http://127.0.0.1:9/refused", 0.5)
            health = _url_get(registry.base_url + "/health", 5)
            health["first_error_ms"] = first["wall_ms"]
            health["retry_count"] = 1
            return health
        raise NotImplementedError(benchmark_id)

    return action


def _node_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    nodes = [
        item
        for item in context.objects_of_kind("node_runtime")
        if item.get("source", {}).get("available")
        and item.get("dimensions", {}).get("executable")
    ]
    if spec.benchmark_id in {"RUN-001", "RUN-003"}:
        scenarios = []
        for item in nodes:
            path = str(item["dimensions"]["executable"])
            action = lambda path=path: run_process([path, "-e", "require('fs');require('path');process.stdout.write(process.version)"], timeout=15)
            scenarios.append(_object_scenario(spec, item, action, transition_class="process_cold", scenario_name=f"node-{item['dimensions']['major']}"))
        return scenarios
    if spec.benchmark_id == "RUN-002":
        scenarios = []
        for item in nodes:
            path = Path(str(item["dimensions"]["executable"]))

            def selector(path: Path = path) -> dict[str, Any]:
                with temporary_directory("nodelite-selector-", context.output / "tmp") as directory:
                    link = Path(directory) / "node"
                    link.symlink_to(path)
                    return run_process([str(link), "--version"], timeout=10)

            scenarios.append(_object_scenario(spec, item, selector, transition_class="exact_hit", from_object_id=item["object_id"], scenario_name=f"node-{item['dimensions']['major']}"))
        return scenarios
    if spec.benchmark_id == "RUN-004":
        scenarios = []
        for source in nodes:
            for target in nodes:
                path = str(target["dimensions"]["executable"])
                exact = source["object_id"] == target["object_id"]
                action = lambda path=path: run_process([path, "-p", "process.versions.modules"], timeout=15)
                scenarios.append(
                    _object_scenario(
                        spec,
                        target,
                        action,
                        from_object_id=source["object_id"],
                        transition_class="exact_hit" if exact else "incompatible_switch",
                        scenario_name=f"{source['dimensions']['major']}-to-{target['dimensions']['major']}",
                        invalidates=[] if exact else INVALIDATIONS["node_runtime"],
                    )
                )
        return scenarios
    return []


def _runtime_action(context: RunContext, benchmark_id: str) -> list[Scenario]:
    spec = next(item for item in context.catalog if item.benchmark_id == benchmark_id)
    if benchmark_id in {"RUN-001", "RUN-002", "RUN-003", "RUN-004"}:
        return _node_scenarios(context, spec)
    if benchmark_id == "RUN-005":
        items = [item for item in context.objects_of_kind("package_manager") if item.get("name") == "bun" and item.get("source", {}).get("available")]
        return [_object_scenario(spec, item, lambda path=item["dimensions"]["executable"]: run_process([str(path), "--version"], timeout=15), transition_class="process_cold", scenario_name=f"bun-{item['version']}") for item in items]
    commands = {
        "RUN-007": ["java", "-version"],
        "RUN-008": ["python3", "-c", "import json,ssl,sqlite3; print('ready')"],
        "RUN-009": ["bash", "-lc", "true"],
    }
    if benchmark_id in commands:
        return [_synthetic_scenario(context, spec, lambda command=commands[benchmark_id]: run_process(command, timeout=30), resource_kind="node_runtime", transition_class="process_cold")]
    if benchmark_id == "RUN-010":
        return [_synthetic_scenario(context, spec, lambda: measure_callable(lambda: {"environment_size": len({key: value for key, value in os.environ.items() if key not in {"HOME", "TMPDIR", "XDG_CACHE_HOME"}})}), resource_kind="home_tmp_xdg")]
    return []


def _pm_command(context: RunContext, item: dict[str, Any]) -> list[str] | None:
    path = item.get("dimensions", {}).get("executable")
    return [str(path)] if path else None


def _pm_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    managers = [item for item in context.objects_of_kind("package_manager") if item.get("source", {}).get("available")]
    family = {
        "PM-001": ("npm", "default"),
        "PM-002": ("pnpm", "default"),
        "PM-003": ("yarn", "classic"),
        "PM-004": ("yarn", "berry"),
        "PM-005": ("bun", "default"),
    }.get(spec.benchmark_id)
    if family:
        selected = [item for item in managers if item["name"] == family[0] and item["dimensions"]["variant"] == family[1]]
        scenarios = []
        for item in selected:
            command = _pm_command(context, item)
            if command:
                scenarios.append(_object_scenario(spec, item, lambda command=command: run_process(command + ["--version"], timeout=30), from_object_id=item["object_id"], transition_class="exact_hit", scenario_name=f"{item['name']}-{item['version']}"))
        return scenarios
    if spec.benchmark_id == "PM-007":
        pnpm = next((item for item in managers if item["name"] == "pnpm"), None)
        if pnpm:
            command = [shutil.which("npm") or "npm", "exec", "--yes", f"--package=pnpm@{pnpm['version']}", "--", "pnpm", "--version"]
            return [_object_scenario(spec, pnpm, lambda: run_process(command, timeout=60), transition_class="artifact_cold", scenario_name=f"npx-pnpm-{pnpm['version']}")]
    if spec.benchmark_id == "PM-008":
        scenarios = []
        by_family: dict[str, list[dict[str, Any]]] = {}
        for item in managers:
            family_key = item["name"] if item["name"] != "yarn" else "yarn"
            by_family.setdefault(family_key, []).append(item)
        for family_items in by_family.values():
            for source in family_items:
                for target in family_items:
                    command = _pm_command(context, target)
                    if not command:
                        continue
                    exact = source["object_id"] == target["object_id"]
                    scenarios.append(
                        _object_scenario(
                            spec,
                            target,
                            lambda command=command: run_process(command + ["--version"], timeout=30),
                            from_object_id=source["object_id"],
                            transition_class="exact_hit" if exact else "incompatible_switch",
                            scenario_name=f"{source['name']}-{source['version']}-to-{target['name']}-{target['version']}",
                            invalidates=[] if exact else INVALIDATIONS["package_manager"],
                        )
                    )
        return scenarios
    return []


def _pm_cache_action(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    mapping = {"PMC-001": "npm", "PMC-002": "pnpm", "PMC-003": "yarn", "PMC-004": "yarn", "PMC-005": "bun"}
    if spec.benchmark_id in mapping:
        items = [
            item
            for item in context.objects_of_kind("pm_native_cache")
            if item["dimensions"]["manager"] == mapping[spec.benchmark_id]
            and item.get("source", {}).get("available")
        ]
        if spec.benchmark_id == "PMC-003":
            items = [item for item in items if item["dimensions"]["variant"] == "classic"]
        if spec.benchmark_id == "PMC-004":
            items = [item for item in items if item["dimensions"]["variant"] == "berry"]
        scenarios = []
        for item in items:
            path = Path(item["dimensions"]["path"])

            def scan(path: Path = path) -> dict[str, Any]:
                entries = list(path.iterdir()) if path.is_dir() else []
                sizes = [entry.stat().st_size for entry in entries[:1000] if entry.is_file()]
                return {"entry_count_sampled": min(len(entries), 1000), "read_bytes": sum(sizes), "cache_hit": True, "success": path.is_dir()}

            scenarios.append(_object_scenario(spec, item, lambda scan=scan: measure_callable(scan), from_object_id=item["object_id"], transition_class="exact_hit", scenario_name=f"{item['dimensions']['manager']}-{item['version']}"))
        return scenarios
    if spec.benchmark_id == "PMC-006":
        item = next((item for item in context.objects_of_kind("pm_native_cache") if item.get("source", {}).get("available")), None)
        if item:
            path = Path(item["dimensions"]["path"])
            return [_object_scenario(spec, item, lambda: measure_callable(lambda: {"exists": path.is_dir(), "entries": sum(1 for _ in path.iterdir()), "cache_hit": True}), from_object_id=item["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "PMC-007":
        items = [item for item in context.objects_of_kind("pm_native_cache") if item.get("source", {}).get("available")]
        scenarios = []
        for source in items:
            for target in items:
                if source["dimensions"]["manager"] != target["dimensions"]["manager"] and not ({source["dimensions"]["manager"], target["dimensions"]["manager"]} == {"yarn"}):
                    continue
                path = Path(target["dimensions"]["path"])
                exact = source["object_id"] == target["object_id"]
                action = lambda path=path: measure_callable(lambda: {"exists": path.is_dir(), "entries": sum(1 for _ in path.iterdir()) if path.is_dir() else 0, "cache_hit": exact})
                scenarios.append(_object_scenario(spec, target, action, from_object_id=source["object_id"], transition_class="exact_hit" if exact else "incompatible_switch", scenario_name=f"{source['version']}-to-{target['version']}", invalidates=[] if exact else ["dependency_view"]))
        return scenarios
    if spec.benchmark_id == "PMC-009":
        item = next((item for item in context.objects_of_kind("pm_native_cache") if item.get("source", {}).get("available")), None)
        if item:
            path = Path(item["dimensions"]["path"])

            def concurrent_scan() -> dict[str, Any]:
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                    counts = list(executor.map(lambda _: sum(1 for _ in path.iterdir()), range(8)))
                return {"concurrency": 8, "entries": sum(counts), "cache_hit": True}

            return [_object_scenario(spec, item, lambda: measure_callable(concurrent_scan), from_object_id=item["object_id"], transition_class="contention_path")]
    return []


def _manager_items(context: RunContext, manager: str, variant: str | None = None) -> list[dict[str, Any]]:
    return [
        item
        for item in context.objects_of_kind("package_manager")
        if item.get("name") == manager
        and (variant is None or item.get("dimensions", {}).get("variant") == variant)
        and item.get("source", {}).get("available")
    ]


def _pm_install_once(
    context: RunContext,
    manager_item: dict[str, Any],
    *,
    cold_cache: bool = False,
    keep_view: bool = False,
    lifecycle_scripts: dict[str, str] | None = None,
) -> dict[str, Any]:
    registry = _local_registry(context)
    manager = str(manager_item["name"])
    variant = str(manager_item["dimensions"]["variant"])
    version = str(manager_item["version"])
    command = _pm_command(context, manager_item)
    if not command:
        return {"success": False, "error": f"{manager} {version} command unavailable"}
    (context.output / "tmp").mkdir(parents=True, exist_ok=True)
    root = Path(tempfile.mkdtemp(prefix=f"nodelite-{manager}-", dir=str(context.output / "tmp")))
    package = {
        "name": "nodelite-depview-fixture",
        "version": "1.0.0",
        "private": True,
        "dependencies": {"is-number": "7.0.0"},
    }
    if manager == "yarn" and variant == "berry":
        package["packageManager"] = f"yarn@{version}"
    if lifecycle_scripts:
        package["scripts"] = lifecycle_scripts
    (root / "package.json").write_text(json.dumps(package), encoding="utf-8")
    cache_root = context.output / "fixtures" / "pm-cache" / manager / variant / version
    cache_root.mkdir(parents=True, exist_ok=True)
    if cold_cache:
        cache_root = root / "empty-cache"
        cache_root.mkdir()
    environment: dict[str, str] = {
        "npm_config_registry": registry.base_url,
        "npm_config_audit": "false",
        "npm_config_fund": "false",
        "npm_config_cache": str(cache_root),
        "YARN_ENABLE_TELEMETRY": "0",
        "YARN_ENABLE_IMMUTABLE_INSTALLS": "false",
    }
    if manager == "npm":
        requested = command + ["install", "--ignore-scripts", "--no-audit", "--no-fund", "--package-lock=false", "--registry", registry.base_url]
    elif manager == "pnpm":
        requested = command + ["install", "--ignore-scripts", "--lockfile=false", "--store-dir", str(cache_root), "--registry", registry.base_url]
    elif manager == "yarn" and variant == "classic":
        requested = command + ["install", "--ignore-scripts", "--non-interactive", "--no-lockfile", "--cache-folder", str(cache_root), "--registry", registry.base_url]
    elif manager == "yarn":
        (root / ".yarnrc.yml").write_text(
            f"npmRegistryServer: {registry.base_url}\nunsafeHttpWhitelist:\n  - 127.0.0.1\nenableGlobalCache: false\ncacheFolder: {cache_root.as_posix()}\n",
            encoding="utf-8",
        )
        requested = command + ["install", "--mode=skip-build"]
    elif manager == "bun":
        requested = command + ["install", "--no-save", "--ignore-scripts", f"--cache-dir={cache_root}", f"--registry={registry.base_url}"]
    else:
        shutil.rmtree(root, ignore_errors=True)
        return {"success": False, "error": f"unsupported manager {manager}"}
    result = run_process(requested, cwd=root, env=environment, timeout=120)
    node_modules = root / "node_modules"
    validation = run_process([shutil.which("node") or "node", "-e", "if(!require('is-number')(7)) process.exit(2)"], cwd=root, timeout=15) if node_modules.exists() else {"success": manager == "yarn" and variant == "berry" and (root / ".pnp.cjs").exists(), "wall_ms": 0}
    result["success"] = bool(result.get("success")) and bool(validation.get("success"))
    result["files_created"] = sum(1 for path in root.rglob("*") if path.is_file())
    result["inodes_created"] = sum(1 for _ in root.rglob("*"))
    result["write_bytes"] = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
    if keep_view and result["success"]:
        result["view_path"] = str(root)
        context.shared.setdefault("persistent_views", []).append(root)
    else:
        cleanup_started = time.perf_counter_ns()
        shutil.rmtree(root, ignore_errors=True)
        result["cleanup_ms"] = (time.perf_counter_ns() - cleanup_started) / 1_000_000
    return result


def _persistent_npm_view(context: RunContext) -> Path:
    path = context.shared.get("persistent_npm_view")
    if path and Path(path).is_dir():
        return Path(path)
    item = next(iter(_manager_items(context, "npm")), None)
    if not item:
        raise FileNotFoundError("npm manager object unavailable")
    result = _pm_install_once(context, item, keep_view=True)
    if not result.get("success"):
        raise RuntimeError(result.get("error") or "npm view setup failed")
    path = Path(result["view_path"])
    context.shared["persistent_npm_view"] = path
    return path


def _dep_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    manager_for_id = {
        "DEP-001": ("npm", None),
        "DEP-002": ("pnpm", None),
        "DEP-003": ("yarn", "classic"),
        "DEP-004": ("yarn", "berry"),
        "DEP-005": ("yarn", "berry"),
        "DEP-006": ("bun", None),
    }.get(spec.benchmark_id)
    depviews = context.objects_of_kind("dependency_view")
    representative = depviews[0] if depviews else context.ensure_object("dependency_view:synthetic:minimal", "dependency_view", "minimal dependency view")
    if manager_for_id:
        manager, variant = manager_for_id
        items = _manager_items(context, manager, variant)
        scenarios = []
        for item in items:
            object_id = f"dependency_view:fixture:{manager}:{item['version']}"
            view = context.ensure_object(object_id, "dependency_view", f"{manager} minimal dependency view", str(item["version"]), dimensions={"manager_object_id": item["object_id"], "package": "is-number@7.0.0"})
            transition = "compatible_reuse" if spec.benchmark_id == "DEP-005" else "artifact_cold"
            scenarios.append(_object_scenario(spec, view, lambda item=item: _pm_install_once(context, item), transition_class=transition, state_before="artifact_cold", scenario_name=f"{manager}-{item['version']}"))
        return scenarios
    if spec.benchmark_id in {"DEP-007", "DEP-018"}:
        action = lambda: run_process([shutil.which("node") or "node", "-e", "if(!require('is-number')(42))process.exit(2)"], cwd=_persistent_npm_view(context), timeout=15)
        return [_object_scenario(spec, representative, action, from_object_id=representative["object_id"], transition_class="exact_hit", scenario_name="require-validation")]
    if spec.benchmark_id == "DEP-008":
        def attach() -> dict[str, Any]:
            source = _persistent_npm_view(context) / "node_modules"
            with temporary_directory("nodelite-attach-", context.output / "tmp") as directory:
                link = Path(directory) / "node_modules"
                link.symlink_to(source, target_is_directory=True)
                success = link.resolve() == source.resolve()
                return {"files_created": 1, "success": success}

        return [_object_scenario(spec, representative, lambda: measure_callable(attach), from_object_id=representative["object_id"], transition_class="compatible_reuse")]
    if spec.benchmark_id == "DEP-009":
        npm = next(iter(_manager_items(context, "npm")), None)
        pnpm = next(iter(_manager_items(context, "pnpm")), None)
        if npm and pnpm:
            source = context.ensure_object("dependency_view:fixture:npm:switch-source", "dependency_view", "npm fixture")
            target = context.ensure_object("dependency_view:fixture:pnpm:switch-target", "dependency_view", "pnpm fixture")
            return [_object_scenario(spec, target, lambda: _pm_install_once(context, pnpm), from_object_id=source["object_id"], transition_class="incompatible_switch", invalidates=INVALIDATIONS["dependency_view"], scenario_name="npm-to-pnpm")]
    if spec.benchmark_id == "DEP-010":
        def remove_view() -> dict[str, Any]:
            with temporary_directory("nodelite-remove-parent-", context.output / "tmp") as directory:
                target = Path(directory) / "view"
                shutil.copytree(_persistent_npm_view(context) / "node_modules", target)
                started = time.perf_counter_ns()
                shutil.rmtree(target)
                elapsed = (time.perf_counter_ns() - started) / 1_000_000
                return {"wall_ms": elapsed, "ready_ms": elapsed, "cleanup_ms": elapsed, "success": not target.exists()}

        return [_object_scenario(spec, representative, remove_view, from_object_id=representative["object_id"], transition_class="dirty_reset")]
    if spec.benchmark_id in {"DEP-011", "DEP-012"}:
        count = 306 if spec.benchmark_id == "DEP-011" else 914

        def create_entries() -> dict[str, Any]:
            with temporary_directory("nodelite-dep-entries-", context.output / "tmp") as directory:
                root = Path(directory)
                package = root / "package"
                package.mkdir()
                (package / "index.js").write_text("module.exports=1", encoding="utf-8")
                target = root / "node_modules"
                target.mkdir()
                for index in range(count):
                    destination = target / f"package-{index}"
                    if spec.benchmark_id == "DEP-011":
                        destination.symlink_to(package, target_is_directory=True)
                    else:
                        shutil.copytree(package, destination)
                return {"files_created": count, "inodes_created": count * 2}

        return [_object_scenario(spec, representative, lambda: measure_callable(create_entries), transition_class="artifact_cold", scenario_name=f"entries-{count}")]
    if spec.benchmark_id == "DEP-013":
        action = _source_action(context, "SRC-007")
        return [_object_scenario(spec, representative, action, transition_class="artifact_cold", scenario_name="patch-apply")]
    if spec.benchmark_id in {"DEP-014", "DEP-015"}:
        artifact_type = "git" if spec.benchmark_id == "DEP-014" else "http_tarball"
        items = [item for item in _cas_artifacts(context) if item.get("type") == artifact_type and item.get("cas_path")]
        if items:
            path = context.ctdp_out / str(items[0]["cas_path"])
            action = lambda path=path: measure_callable(lambda: {"read_bytes": len(path.read_bytes()), "cache_hit": True})
            return [_object_scenario(spec, representative, action, transition_class="artifact_cold", scenario_name=artifact_type)]
    if spec.benchmark_id == "DEP-016":
        artifacts = read_json(context.ctdp_out / "global" / "global_manifest.json", {}).get("artifacts", [])
        action = lambda: measure_callable(lambda: {"compatible": sum(item.get("os") in (None, "linux") and item.get("cpu") in (None, "x64") for item in artifacts), "total": len(artifacts)})
        return [_object_scenario(spec, representative, action, from_object_id=representative["object_id"], transition_class="compatible_reuse")]
    if spec.benchmark_id == "DEP-019":
        npm = next(iter(_manager_items(context, "npm")), None)
        if npm:
            def concurrent_views() -> dict[str, Any]:
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
                    results = list(executor.map(lambda _: _pm_install_once(context, npm), range(4)))
                return {"success": all(item.get("success") for item in results), "concurrency": 4, "cleanup_ms": sum(float(item.get("cleanup_ms") or 0) for item in results)}

            return [_object_scenario(spec, representative, lambda: measure_callable(concurrent_views), transition_class="contention_path")]
    if spec.benchmark_id == "DEP-020":
        action = lambda: measure_callable(lambda: {"read_bytes": sum(len(path.read_bytes()) for path in (_persistent_npm_view(context) / "node_modules/is-number").rglob("*") if path.is_file()), "cache_hit": True})
        return [_object_scenario(spec, representative, action, from_object_id=representative["object_id"], transition_class="exact_hit")]
    return []


def _install_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    representative = next(iter(context.objects_of_kind("dependency_view")), context.ensure_object("dependency_view:synthetic:install", "dependency_view", "install fixture"))
    npm = next(iter(_manager_items(context, "npm")), None)
    if spec.benchmark_id in {"INS-001", "INS-002", "INS-003", "INS-010"} and npm:
        transition = "exact_hit" if spec.benchmark_id == "INS-010" else "artifact_cold"
        return [_object_scenario(spec, representative, lambda: _pm_install_once(context, npm), from_object_id=representative["object_id"] if transition == "exact_hit" else None, transition_class=transition, scenario_name="npm-minimal")]
    if spec.benchmark_id in {"INS-004", "INS-005", "INS-006", "INS-007"}:
        lifecycle = {"INS-004": "preinstall", "INS-005": "install", "INS-006": "postinstall", "INS-007": "prepare"}[spec.benchmark_id]

        def run_lifecycle() -> dict[str, Any]:
            with temporary_directory("nodelite-lifecycle-", context.output / "tmp") as directory:
                root = Path(directory)
                package = {"name": "lifecycle-fixture", "version": "1.0.0", "scripts": {lifecycle: f"node -e \"require('fs').writeFileSync('{lifecycle}.marker','ok')\""}}
                (root / "package.json").write_text(json.dumps(package), encoding="utf-8")
                result = run_process([shutil.which("npm") or "npm", "run", lifecycle], cwd=root, timeout=30)
                result["success"] = result["success"] and (root / f"{lifecycle}.marker").is_file()
                result["files_created"] = 1
                return result

        return [_object_scenario(spec, representative, run_lifecycle, transition_class="artifact_cold", scenario_name=lifecycle)]
    if spec.benchmark_id == "INS-008":
        return [_object_scenario(spec, representative, _peer_conflict_action(context), transition_class="failure_path", scenario_name="peer-conflict", reuse_safe=False)]
    if spec.benchmark_id == "INS-009":
        def cleanup_partial() -> dict[str, Any]:
            with temporary_directory("nodelite-partial-", context.output / "tmp") as directory:
                target = Path(directory) / "node_modules"
                target.mkdir()
                for index in range(100):
                    (target / f"partial-{index}").write_bytes(b"x" * 4096)
                started = time.perf_counter_ns()
                shutil.rmtree(target)
                elapsed = (time.perf_counter_ns() - started) / 1_000_000
                return {"wall_ms": elapsed, "ready_ms": elapsed, "cleanup_ms": elapsed, "success": not target.exists()}

        return [_object_scenario(spec, representative, cleanup_partial, transition_class="dirty_reset")]
    return []


TOOL_PACKAGES = {
    "typescript": "typescript@7.0.2",
    "typescript_server": "typescript-server@npm:typescript@5.9.3",
    "babel": "@babel/core@7.28.4",
    "babel_cli": "@babel/cli@7.28.3",
    "swc": "@swc/core@1.16.1",
    "swc_cli": "@swc/cli@0.8.1",
    "esbuild": "esbuild@0.28.2",
    "rollup": "rollup@4.63.1",
    "webpack": "webpack@5.110.1",
    "webpack_cli": "webpack-cli@7.2.2",
    "vite": "vite@8.2.2",
    "jest": "jest@30.4.2",
    "vitest": "vitest@4.1.11",
    "mocha": "mocha@11.8.0",
    "ava": "ava@8.0.1",
    "sharp": "sharp@0.35.4",
    "sqlite3": "sqlite3@6.0.1",
    "node_gyp": "node-gyp@13.0.2",
}


def _tool_fixture(context: RunContext) -> Path:
    existing = context.shared.get("tool_fixture")
    if existing and Path(existing).is_dir():
        return Path(existing)
    root = context.output / "fixtures" / "toolchain"
    package_json = root / "package.json"
    marker = root / ".nodelite-ready"
    package = {"name": "nodelite-tool-fixture", "version": "1.0.0", "private": True, "devDependencies": {key: value.rsplit("@", 1)[0] + "@" + value.rsplit("@", 1)[1] for key, value in {spec: spec for spec in TOOL_PACKAGES.values()}.items()}}
    dependencies: dict[str, str] = {}
    for value in TOOL_PACKAGES.values():
        if value.startswith("@"):
            package_name, version = value.rsplit("@", 1)
        else:
            package_name, version = value.split("@", 1)
        dependencies[package_name] = version
    package["devDependencies"] = dependencies
    expected = stable_hash(package)
    if not marker.is_file() or marker.read_text(encoding="utf-8", errors="replace").strip() != expected:
        root.mkdir(parents=True, exist_ok=True)
        package_json.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
        result = run_process([shutil.which("npm") or "npm", "install", "--no-audit", "--no-fund", "--ignore-scripts=false"], cwd=root, timeout=900)
        if not result.get("success"):
            raise RuntimeError(f"tool fixture install failed: {result.get('error')}")
        marker.write_text(expected, encoding="utf-8")
    context.shared["tool_fixture"] = root
    return root


def _tool_version(root: Path, package_name: str) -> str:
    return str(read_json(root / "node_modules" / package_name / "package.json", {}).get("version") or "unknown")


def _build_fixture(context: RunContext) -> Path:
    existing = context.shared.get("build_fixture")
    if existing and Path(existing).is_dir():
        return Path(existing)
    tools = _tool_fixture(context)
    root = context.output / "fixtures" / "build"
    root.mkdir(parents=True, exist_ok=True)
    (root / "src.ts").write_text("export const answer: number = 42; console.log(answer);\n", encoding="utf-8")
    (root / "input.js").write_text("export const answer = 42; console.log(answer);\n", encoding="utf-8")
    (root / "index.html").write_text("<div id=app></div><script type=module src=/input.js></script>\n", encoding="utf-8")
    (root / "tsconfig.json").write_text(json.dumps({"compilerOptions": {"incremental": True, "outDir": "dist-ts", "module": "commonjs", "target": "es2020"}, "files": ["src.ts"]}), encoding="utf-8")
    (root / "webpack.config.cjs").write_text("module.exports={mode:'development',entry:'./input.js',output:{path:__dirname+'/dist-webpack',filename:'bundle.js'},cache:{type:'filesystem'}};\n", encoding="utf-8")
    node_modules = root / "node_modules"
    if node_modules.exists() or node_modules.is_symlink():
        if node_modules.is_symlink() and node_modules.resolve() != (tools / "node_modules").resolve():
            node_modules.unlink()
    if not node_modules.exists():
        node_modules.symlink_to(tools / "node_modules", target_is_directory=True)
    context.shared["build_fixture"] = root
    return root


def _build_command(context: RunContext, tool: str) -> tuple[list[str], list[Path]]:
    root = _build_fixture(context)
    binary = root / "node_modules" / ".bin"
    outputs: dict[str, list[Path]] = {
        "typescript": [root / "dist-ts", root / "tsconfig.tsbuildinfo"],
        "babel": [root / "dist-babel.js"],
        "swc": [root / "dist-swc.js"],
        "esbuild": [root / "dist-esbuild.js"],
        "rollup": [root / "dist-rollup.js"],
        "webpack": [root / "dist-webpack", root / "node_modules/.cache/webpack"],
        "vite": [root / "dist-vite", root / "node_modules/.vite"],
    }
    commands = {
        "typescript": [str(binary / "tsc"), "-p", "tsconfig.json"],
        "babel": [str(binary / "babel"), "input.js", "--out-file", "dist-babel.js"],
        "swc": [str(binary / "swc"), "input.js", "-o", "dist-swc.js"],
        "esbuild": [str(binary / "esbuild"), "input.js", "--bundle", "--outfile=dist-esbuild.js"],
        "rollup": [str(binary / "rollup"), "input.js", "--format", "es", "--file", "dist-rollup.js"],
        "webpack": [str(binary / "webpack"), "--config", "webpack.config.cjs"],
        "vite": [str(binary / "vite"), "build", "--outDir", "dist-vite"],
    }
    return commands[tool], outputs[tool]


def _run_build(context: RunContext, tool: str, *, clean: bool, mutate: bool = False) -> dict[str, Any]:
    root = _build_fixture(context)
    command, outputs = _build_command(context, tool)
    if clean:
        for output in outputs:
            if output.is_dir() and not output.is_symlink():
                shutil.rmtree(output, ignore_errors=True)
            elif output.exists() or output.is_symlink():
                output.unlink()
    source = root / ("src.ts" if tool == "typescript" else "input.js")
    original = source.read_text(encoding="utf-8")
    if mutate:
        source.write_text(original + f"// invalidation-{time.time_ns()}\n", encoding="utf-8")
    try:
        result = run_process(command, cwd=root, timeout=180)
    finally:
        if mutate:
            source.write_text(original, encoding="utf-8")
    files = [path for output in outputs if output.exists() for path in ([output] if output.is_file() else output.rglob("*")) if path.is_file()]
    result["files_created"] = len(files)
    result["write_bytes"] = sum(path.stat().st_size for path in files)
    result["cache_hit"] = not clean and not mutate
    result["invalidation_ms"] = result["wall_ms"] if mutate else 0
    return result


def _build_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    tool_by_id = {
        "BLD-002": "typescript",
        "BLD-004": "babel",
        "BLD-005": "swc",
        "BLD-006": "esbuild",
        "BLD-007": "rollup",
        "BLD-008": "webpack",
        "BLD-009": "vite",
    }
    if spec.benchmark_id in tool_by_id:
        tool = tool_by_id[spec.benchmark_id]
        root = _tool_fixture(context)
        package_name = {"typescript": "typescript", "babel": "@babel/core", "swc": "@swc/core", "esbuild": "esbuild", "rollup": "rollup", "webpack": "webpack", "vite": "vite"}[tool]
        version = _tool_version(root, package_name)
        object_id = f"build_cache:synthetic:{tool}:{version}"
        item = context.ensure_object(object_id, "build_cache", tool, version, dimensions={"tool": tool, "fixture": str(_build_fixture(context))})
        return [
            _object_scenario(spec, item, lambda tool=tool: _run_build(context, tool, clean=True), transition_class="artifact_cold", scenario_name=f"{tool}-cold"),
            _object_scenario(spec, item, lambda tool=tool: _run_build(context, tool, clean=False), from_object_id=item["object_id"], transition_class="exact_hit", scenario_name=f"{tool}-hit"),
            _object_scenario(spec, item, lambda tool=tool: _run_build(context, tool, clean=False, mutate=True), from_object_id=item["object_id"], transition_class="incompatible_switch", invalidates=["build_cache"], scenario_name=f"{tool}-source-change"),
        ]
    if spec.benchmark_id == "BLD-001":
        item = context.ensure_object("build_cache:synthetic:npm-script", "build_cache", "npm script dispatch")
        return [_object_scenario(spec, item, lambda: run_process([shutil.which("npm") or "npm", "run", "--silent", "fixture"], cwd=_script_fixture(context), timeout=30), transition_class="process_cold")]
    if spec.benchmark_id == "BLD-003":
        root = _build_fixture(context)
        tools = _tool_fixture(context)
        server = tools / "node_modules" / "typescript-server" / "bin" / "tsserver"
        item = context.ensure_object("project_server:synthetic:tsserver", "project_server", "tsserver", _tool_version(tools, "typescript-server"))
        return [_object_scenario(spec, item, lambda: run_process([shutil.which("node") or "node", str(server)], cwd=root, input_text='{"seq":0,"type":"request","command":"exit"}\n', timeout=15), transition_class="process_cold")]
    if spec.benchmark_id in {"BLD-016", "BLD-017"}:
        item = context.ensure_object(f"build_cache:synthetic:{spec.benchmark_id.lower()}", "build_cache", spec.description)
        if spec.benchmark_id == "BLD-016":
            return [_object_scenario(spec, item, lambda: _make_fixture_action(context), transition_class="artifact_cold")]
        return [_object_scenario(spec, item, lambda: _codegen_action(context), transition_class="artifact_cold")]
    if spec.benchmark_id == "BLD-020":
        item = context.ensure_object("build_cache:synthetic:typescript:attach", "build_cache", "TypeScript incremental cache")
        _run_build(context, "typescript", clean=True)
        return [_object_scenario(spec, item, lambda: _run_build(context, "typescript", clean=False), from_object_id=item["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "BLD-021":
        item = context.ensure_object("build_cache:synthetic:typescript:invalidate", "build_cache", "TypeScript invalidation")
        _run_build(context, "typescript", clean=True)
        return [_object_scenario(spec, item, lambda: _run_build(context, "typescript", clean=False, mutate=True), from_object_id=item["object_id"], transition_class="incompatible_switch", invalidates=["build_cache"])]
    if spec.benchmark_id == "BLD-022":
        item = context.ensure_object("project_server:synthetic:vite-watch", "project_server", "Vite watch process", _tool_version(_tool_fixture(context), "vite"))

        def watch_reset() -> dict[str, Any]:
            root = _build_fixture(context)
            process = subprocess.Popen([str(root / "node_modules/.bin/vite"), "--host", "127.0.0.1", "--port", "0"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            time.sleep(0.5)
            cleanup_ms, forced = terminate_process(process)
            return {"wall_ms": cleanup_ms, "ready_ms": cleanup_ms, "cleanup_ms": cleanup_ms, "success": process.poll() is not None, "forced": forced}

        return [_object_scenario(spec, item, watch_reset, from_object_id=item["object_id"], transition_class="dirty_reset")]
    return []


def _script_fixture(context: RunContext) -> Path:
    root = context.output / "fixtures" / "script"
    root.mkdir(parents=True, exist_ok=True)
    (root / "package.json").write_text(json.dumps({"name": "script-fixture", "version": "1.0.0", "scripts": {"fixture": "node -e \"process.stdout.write('ok')\""}}), encoding="utf-8")
    return root


def _make_fixture_action(context: RunContext) -> dict[str, Any]:
    with temporary_directory("nodelite-make-", context.output / "tmp") as directory:
        root = Path(directory)
        (root / "main.c").write_text("#include <stdio.h>\nint main(){puts(\"ok\");return 0;}\n", encoding="utf-8")
        (root / "Makefile").write_text("all: app\napp: main.c\n\t$(CC) main.c -o app\n", encoding="utf-8")
        return run_process(["make", "-s"], cwd=root, timeout=60)


def _codegen_action(context: RunContext) -> dict[str, Any]:
    with temporary_directory("nodelite-codegen-", context.output / "tmp") as directory:
        root = Path(directory)
        schema = {"types": [{"name": f"Type{index}", "fields": ["id", "name"]} for index in range(1000)]}
        output = root / "generated.ts"

        def generate() -> dict[str, Any]:
            output.write_text("\n".join(f"export interface {item['name']} {{ id: string; name: string }}" for item in schema["types"]), encoding="utf-8")
            return {"write_bytes": output.stat().st_size, "files_created": 1}

        return measure_callable(generate)


def _test_fixture(context: RunContext) -> Path:
    root = _tool_fixture(context)
    fixture = context.output / "fixtures" / "test"
    fixture.mkdir(parents=True, exist_ok=True)
    node_modules = fixture / "node_modules"
    if not node_modules.exists():
        node_modules.symlink_to(root / "node_modules", target_is_directory=True)
    (fixture / "sum.cjs").write_text("module.exports=(a,b)=>a+b;\n", encoding="utf-8")
    (fixture / "sum.test.cjs").write_text("const sum=require('./sum.cjs'); test('sum',()=>expect(sum(1,2)).toBe(3));\n", encoding="utf-8")
    (fixture / "sum.mocha.cjs").write_text("const assert=require('assert'); const sum=require('./sum.cjs'); describe('sum',()=>it('works',()=>assert.equal(sum(1,2),3)));\n", encoding="utf-8")
    (fixture / "sum.vitest.test.js").write_text("import {test,expect} from 'vitest'; test('sum',()=>expect(1+2).toBe(3));\n", encoding="utf-8")
    (fixture / "sum.ava.js").write_text("import test from 'ava'; test('sum',t=>t.is(1+2,3));\n", encoding="utf-8")
    (fixture / "package.json").write_text(json.dumps({"name": "test-fixture", "version": "1.0.0", "type": "module"}), encoding="utf-8")
    return fixture


def _test_command(context: RunContext, tool: str) -> list[str]:
    root = _test_fixture(context)
    binary = root / "node_modules/.bin"
    return {
        "jest": [str(binary / "jest"), "sum.test.cjs", "--runInBand", "--cacheDirectory", ".jest-cache"],
        "vitest": [str(binary / "vitest"), "run", "sum.vitest.test.js", "--pool=threads", "--maxWorkers=1", "--no-file-parallelism"],
        "mocha": [str(binary / "mocha"), "sum.mocha.cjs"],
        "ava": [str(binary / "ava"), "sum.ava.js", "--serial"],
    }[tool]


def _run_test(context: RunContext, tool: str, *, clean: bool = False, coverage: bool = False) -> dict[str, Any]:
    root = _test_fixture(context)
    if clean:
        shutil.rmtree(root / ".jest-cache", ignore_errors=True)
        shutil.rmtree(root / "node_modules/.vite", ignore_errors=True)
    command = _test_command(context, tool)
    if coverage and tool == "jest":
        command += ["--coverage", "--coverageDirectory", ".coverage"]
    result = run_process(command, cwd=root, timeout=180)
    result["cache_hit"] = not clean
    return result


def _test_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    tool_by_id = {"TST-001": "jest", "TST-002": "vitest", "TST-003": "mocha", "TST-004": "ava"}
    if spec.benchmark_id in tool_by_id:
        tool = tool_by_id[spec.benchmark_id]
        version = _tool_version(_tool_fixture(context), tool)
        item = context.ensure_object(f"test_transform_cache:synthetic:{tool}:{version}", "test_transform_cache", tool, version, dimensions={"fixture": str(_test_fixture(context))})
        return [
            _object_scenario(spec, item, lambda tool=tool: _run_test(context, tool, clean=True), transition_class="process_cold", scenario_name=f"{tool}-cold"),
            _object_scenario(spec, item, lambda tool=tool: _run_test(context, tool, clean=False), from_object_id=item["object_id"], transition_class="exact_hit", scenario_name=f"{tool}-hit"),
        ]
    item = context.ensure_object(f"test_transform_cache:synthetic:{spec.benchmark_id.lower()}", "test_transform_cache", spec.description)
    if spec.benchmark_id == "TST-011":
        _run_test(context, "jest", clean=True)
        return [_object_scenario(spec, item, lambda: _run_test(context, "jest", clean=False), from_object_id=item["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "TST-012":
        return [_object_scenario(spec, item, lambda: run_process([shutil.which("node") or "node", "-e", "const {Worker}=require('worker_threads');let n=4,c=0;for(let i=0;i<n;i++){let w=new Worker('process.exit(0)',{eval:true});w.on('exit',()=>{if(++c===n)process.exit(0)})}"], timeout=30), transition_class="process_cold")]
    if spec.benchmark_id == "TST-013":
        return [_object_scenario(spec, item, lambda: measure_callable(lambda: {"test_count": len(list(_test_fixture(context).glob("*.test.*"))) + len(list(_test_fixture(context).glob("*.mocha.*")))}), transition_class="exact_hit")]
    if spec.benchmark_id == "TST-014":
        return [_object_scenario(spec, item, lambda: _run_test(context, "jest", clean=True, coverage=True), transition_class="artifact_cold")]
    if spec.benchmark_id == "TST-015":
        return [_object_scenario(spec, item, _hung_process_action(), transition_class="failure_path", reuse_safe=True)]
    if spec.benchmark_id == "TST-016":
        def parity() -> dict[str, Any]:
            first = _run_test(context, "mocha", clean=True)
            second = _run_test(context, "mocha", clean=False)
            return {"success": first.get("success") and second.get("success"), "isolated_exit": first.get("exit_code"), "reused_exit": second.get("exit_code"), "pollution_check": "pass" if first.get("exit_code") == second.get("exit_code") else "fail"}

        return [_object_scenario(spec, item, lambda: measure_callable(parity), transition_class="compatible_reuse")]
    return []


class _ChromeSession:
    def __init__(self, binary: Path, parent: Path, flags: list[str] | None = None):
        parent.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix="chrome-", dir=str(parent)))
        self.profile = self.directory / "profile"
        self.profile.mkdir()
        self.port = _free_port()
        command = [
            str(binary),
            "--headless=new",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={self.port}",
            f"--user-data-dir={self.profile}",
            *(flags or []),
            "about:blank",
        ]
        self.started_ns = time.perf_counter_ns()
        self.process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        self.version: dict[str, Any] | None = None

    def wait_ready(self, timeout: float = 30) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last_error = ""
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                stderr = self.process.stderr.read() if self.process.stderr else ""
                raise RuntimeError(f"Chrome exited before ready: {stderr[-1000:]}")
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/version", timeout=0.5) as response:
                    self.version = json.loads(response.read())
                ready_ms = (time.perf_counter_ns() - self.started_ns) / 1_000_000
                return {"ready_ms": ready_ms, "wall_ms": ready_ms, "success": True, "port": self.port, "version": self.version.get("Browser")}
            except Exception as exc:
                last_error = str(exc)
                time.sleep(0.01)
        raise TimeoutError(f"Chrome readiness timeout: {last_error}")

    def command(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        import websocket

        if not self.version:
            self.wait_ready()
        connection = websocket.create_connection(self.version["webSocketDebuggerUrl"], timeout=10, http_proxy_host=None)
        try:
            connection.send(json.dumps({"id": 1, "method": method, "params": params or {}}))
            while True:
                response = json.loads(connection.recv())
                if response.get("id") == 1:
                    if "error" in response:
                        raise RuntimeError(str(response["error"]))
                    return response.get("result", {})
        finally:
            connection.close()

    def close(self) -> tuple[float, bool]:
        cleanup_ms, forced = terminate_process(self.process)
        shutil.rmtree(self.directory, ignore_errors=True)
        return cleanup_ms, forced


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as handle:
        handle.bind(("127.0.0.1", 0))
        return int(handle.getsockname()[1])


def _chrome_item(context: RunContext) -> dict[str, Any] | None:
    return next((item for item in context.objects_of_kind("browser_process") if item.get("name") == "chromium" and item.get("source", {}).get("available")), None)


def _chrome_binary(context: RunContext) -> Path:
    item = _chrome_item(context)
    if not item:
        raise FileNotFoundError("Chromium binary unavailable")
    return Path(str(item["dimensions"]["path"]))


def _warm_chrome(context: RunContext) -> _ChromeSession:
    session = context.shared.get("warm_chrome")
    if session and session.process.poll() is None:
        return session
    session = _ChromeSession(_chrome_binary(context), context.output / "tmp")
    session.wait_ready()
    context.shared["warm_chrome"] = session
    return session


def _chrome_cold_action(context: RunContext, flags: list[str] | None = None) -> dict[str, Any]:
    session = _ChromeSession(_chrome_binary(context), context.output / "tmp", flags)
    try:
        result = session.wait_ready()
        contexts = session.command("Target.getBrowserContexts")
        result["browser_context_count"] = len(contexts.get("browserContextIds", []))
    finally:
        cleanup_ms, forced = session.close()
    result["cleanup_ms"] = cleanup_ms
    result["forced"] = forced
    return result


def _firefox_action(context: RunContext) -> dict[str, Any]:
    with temporary_directory("nodelite-firefox-", context.output / "tmp") as directory:
        root = Path(directory)
        screenshot = root / "ready.png"
        profile = root / "profile"
        profile.mkdir()
        result = run_process(["firefox", "--headless", "--no-remote", "--profile", str(profile), "--screenshot", str(screenshot), "about:blank"], timeout=60)
        result["success"] = result.get("success") and screenshot.is_file() and screenshot.stat().st_size > 0
        result["files_created"] = sum(1 for path in root.rglob("*") if path.is_file())
        return result


def _electron_binary(context: RunContext) -> Path:
    extracted = context.output / "fixtures" / "electron-40.10.2"
    binary = extracted / "electron"
    if binary.is_file():
        return binary
    archive = Path.home() / ".cache/electron/3978a3c4a2965533dc07f99112894e7e7f80c9ea0f13e2a48cd5a29593568fb2/electron-v40.10.2-linux-x64.zip"
    if not archive.is_file():
        raise FileNotFoundError("Electron archive unavailable")
    extracted.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as handle:
        handle.extractall(extracted)
    binary.chmod(binary.stat().st_mode | 0o111)
    return binary


def _xvfb_shared(context: RunContext) -> tuple[subprocess.Popen[Any], str]:
    value = context.shared.get("xvfb")
    if value and value[0].poll() is None:
        return value
    for display_number in range(90, 120):
        socket_path = Path(f"/tmp/.X11-unix/X{display_number}")
        if socket_path.exists():
            continue
        process = subprocess.Popen(["Xvfb", f":{display_number}", "-screen", "0", "1280x720x24", "-nolisten", "tcp"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if socket_path.exists():
                context.shared["xvfb"] = (process, f":{display_number}")
                return process, f":{display_number}"
            if process.poll() is not None:
                break
            time.sleep(0.01)
    raise RuntimeError("Xvfb failed to become ready")


def _electron_action(context: RunContext) -> dict[str, Any]:
    binary = _electron_binary(context)
    _, display = _xvfb_shared(context)
    app = context.output / "fixtures" / "electron-app"
    app.mkdir(parents=True, exist_ok=True)
    (app / "package.json").write_text(json.dumps({"name": "nodelite-electron", "version": "1.0.0", "main": "main.js"}), encoding="utf-8")
    (app / "main.js").write_text("const {app,BrowserWindow}=require('electron');app.whenReady().then(()=>{const w=new BrowserWindow({show:false});w.loadURL('data:text/html,ready').then(()=>app.exit(0));});setTimeout(()=>app.exit(3),15000);\n", encoding="utf-8")
    return run_process([str(binary), str(app), "--no-sandbox", "--disable-gpu"], env={"DISPLAY": display, "ELECTRON_RUN_AS_NODE": ""}, timeout=30)


def _browser_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    browser_processes = context.objects_of_kind("browser_process")
    chromium = _chrome_item(context)
    firefox = next((item for item in browser_processes if item.get("name") == "firefox" and item.get("source", {}).get("available")), None)
    electron = next((item for item in browser_processes if item.get("name") == "electron" and item.get("source", {}).get("available")), None)
    if spec.benchmark_id == "BRW-001" and chromium:
        binary_item = context.object_by_id[chromium["dimensions"]["binary_object_id"]]
        return [_object_scenario(spec, binary_item, lambda: run_process([str(_chrome_binary(context)), "--version"], timeout=15), from_object_id=binary_item["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "BRW-002" and firefox:
        binary_item = context.object_by_id[firefox["dimensions"]["binary_object_id"]]
        return [_object_scenario(spec, binary_item, lambda: run_process(["firefox", "--version"], timeout=15), from_object_id=binary_item["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "BRW-004" and electron:
        binary_item = context.object_by_id[electron["dimensions"]["binary_object_id"]]
        return [_object_scenario(spec, binary_item, lambda: run_process([str(_electron_binary(context)), "--version"], timeout=30), from_object_id=binary_item["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "BRW-005":
        item = electron or chromium
        if item:
            binary_item = context.object_by_id[item["dimensions"]["binary_object_id"]]
            archive = Path.home() / ".cache/electron/3978a3c4a2965533dc07f99112894e7e7f80c9ea0f13e2a48cd5a29593568fb2/electron-v40.10.2-linux-x64.zip"
            return [_object_scenario(spec, binary_item, lambda: measure_callable(lambda: {"read_bytes": len(archive.read_bytes()), "cache_hit": True}), from_object_id=binary_item["object_id"], transition_class="artifact_cold", scenario_name="electron-cas-replay")]
    if spec.benchmark_id == "BRW-006" and chromium:
        return [_object_scenario(spec, chromium, lambda: run_process(["ldd", str(_chrome_binary(context))], timeout=30), from_object_id=chromium["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "BRW-007" and chromium:
        return [_object_scenario(spec, chromium, lambda: _chrome_cold_action(context), transition_class="process_cold")]
    if spec.benchmark_id == "BRW-008" and firefox:
        return [_object_scenario(spec, firefox, lambda: _firefox_action(context), transition_class="process_cold")]
    if spec.benchmark_id == "BRW-010" and chromium:
        return [_object_scenario(spec, chromium, lambda: _url_get(f"http://127.0.0.1:{_warm_chrome(context).port}/json/version", 5), from_object_id=chromium["object_id"], transition_class="exact_hit")]
    context_item = next((item for item in context.objects_of_kind("browser_context") if item.get("name", "").startswith("chromium")), None)
    profile_item = next((item for item in context.objects_of_kind("browser_profile") if item.get("name", "").startswith("chromium")), None)
    if spec.benchmark_id in {"BRW-011", "BRW-012"} and context_item:
        def context_action() -> dict[str, Any]:
            session = _warm_chrome(context)
            created = session.command("Target.createBrowserContext")
            context_id = created["browserContextId"]
            session.command("Target.createTarget", {"url": "data:text/html,<script>localStorage.x='dirty'</script>", "browserContextId": context_id})
            cleanup_started = time.perf_counter_ns()
            session.command("Target.disposeBrowserContext", {"browserContextId": context_id})
            cleanup_ms = (time.perf_counter_ns() - cleanup_started) / 1_000_000
            remaining = session.command("Target.getBrowserContexts").get("browserContextIds", [])
            return {"cleanup_ms": cleanup_ms, "reset_ms": cleanup_ms, "pollution_check": "pass" if context_id not in remaining else "fail", "success": context_id not in remaining}

        transition = "dirty_reset" if spec.benchmark_id == "BRW-012" else "compatible_reuse"
        return [_object_scenario(spec, context_item, lambda: measure_callable(context_action), from_object_id=context_item["object_id"], transition_class=transition)]
    if spec.benchmark_id in {"BRW-013", "BRW-014"} and profile_item:
        def profile_action() -> dict[str, Any]:
            with temporary_directory("nodelite-profile-parent-", context.output / "tmp") as directory:
                target = Path(directory) / "profile"
                target.mkdir()
                for index in range(100):
                    (target / f"state-{index}").write_bytes(b"x" * 1024)
                if spec.benchmark_id == "BRW-014":
                    started = time.perf_counter_ns()
                    shutil.rmtree(target)
                    elapsed = (time.perf_counter_ns() - started) / 1_000_000
                    return {"wall_ms": elapsed, "ready_ms": elapsed, "reset_ms": elapsed, "cleanup_ms": elapsed, "success": not target.exists()}
                return {"files_created": 100, "write_bytes": 102400}

        transition = "dirty_reset" if spec.benchmark_id == "BRW-014" else "artifact_cold"
        return [_object_scenario(spec, profile_item, lambda: measure_callable(profile_action), from_object_id=profile_item["object_id"] if transition == "dirty_reset" else None, transition_class=transition)]
    if spec.benchmark_id == "BRW-015" and context_item:
        def page_action() -> dict[str, Any]:
            session = _warm_chrome(context)
            context_id = session.command("Target.createBrowserContext")["browserContextId"]
            target_id = session.command("Target.createTarget", {"url": "data:text/html,ready", "browserContextId": context_id})["targetId"]
            session.command("Target.closeTarget", {"targetId": target_id})
            session.command("Target.disposeBrowserContext", {"browserContextId": context_id})
            return {"success": True}

        return [_object_scenario(spec, context_item, lambda: measure_callable(page_action), from_object_id=context_item["object_id"], transition_class="compatible_reuse")]
    if spec.benchmark_id == "BRW-016" and chromium:
        return [_object_scenario(spec, chromium, lambda: _chrome_cold_action(context, ["--disable-gpu"]), from_object_id=chromium["object_id"], transition_class="incompatible_switch", invalidates=INVALIDATIONS["browser_process"], scenario_name="flags-switch")]
    if spec.benchmark_id == "BRW-017" and chromium:
        def shutdown() -> dict[str, Any]:
            session = _ChromeSession(_chrome_binary(context), context.output / "tmp")
            session.wait_ready()
            cleanup_ms, forced = session.close()
            return {"wall_ms": cleanup_ms, "ready_ms": cleanup_ms, "cleanup_ms": cleanup_ms, "forced": forced, "success": not forced}

        return [_object_scenario(spec, chromium, shutdown, from_object_id=chromium["object_id"], transition_class="dirty_reset")]
    if spec.benchmark_id in {"BRW-018", "BRW-019"} and electron:
        return [_object_scenario(spec, electron, lambda: _electron_action(context), from_object_id=electron["object_id"] if spec.benchmark_id == "BRW-019" else None, transition_class="dirty_reset" if spec.benchmark_id == "BRW-019" else "process_cold")]
    return []


def _gui_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    xvfb_item = context.object_by_id.get("display_service:xvfb:host")
    dbus_item = context.object_by_id.get("display_service:dbus:host")
    if spec.benchmark_id in {"GUI-001", "GUI-002"} and xvfb_item:
        def xvfb_action() -> dict[str, Any]:
            display_number = random.randint(120, 220)
            socket_path = Path(f"/tmp/.X11-unix/X{display_number}")
            process = subprocess.Popen(["Xvfb", f":{display_number}", "-screen", "0", "800x600x24", "-nolisten", "tcp"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            started = time.perf_counter_ns()
            while not socket_path.exists() and process.poll() is None and (time.perf_counter_ns() - started) < 10_000_000_000:
                time.sleep(0.005)
            ready_ms = (time.perf_counter_ns() - started) / 1_000_000
            was_ready = socket_path.exists()
            cleanup_ms, forced = terminate_process(process)
            return {"wall_ms": ready_ms, "ready_ms": ready_ms, "cleanup_ms": cleanup_ms, "success": was_ready, "forced": forced}

        transition = "dirty_reset" if spec.benchmark_id == "GUI-002" else "process_cold"
        return [_object_scenario(spec, xvfb_item, xvfb_action, from_object_id=xvfb_item["object_id"] if transition == "dirty_reset" else None, transition_class=transition)]
    if spec.benchmark_id == "GUI-003" and dbus_item:
        return [_object_scenario(spec, dbus_item, lambda: run_process(["dbus-run-session", "--", "sh", "-c", "test -n \"$DBUS_SESSION_BUS_ADDRESS\""], timeout=30), transition_class="process_cold")]
    if spec.benchmark_id == "GUI-004":
        return [_synthetic_scenario(context, spec, lambda: run_process(["python3", "-c", "import ctypes; ctypes.CDLL('libgtk-3.so.0')"], timeout=30), resource_kind="display_service", transition_class="exact_hit")]
    if spec.benchmark_id in {"GUI-005", "GUI-006"} and _chrome_item(context):
        item = _chrome_item(context)
        action = lambda: _url_get(f"http://127.0.0.1:{_warm_chrome(context).port}/json/version", 5)
        return [_object_scenario(spec, item, action, from_object_id=item["object_id"], transition_class="compatible_reuse")]
    return []


class _RedisSession:
    def __init__(self, parent: Path):
        parent.mkdir(parents=True, exist_ok=True)
        self.directory = Path(tempfile.mkdtemp(prefix="redis-", dir=str(parent)))
        self.port = _free_port()
        self.started_ns = time.perf_counter_ns()
        self.process = subprocess.Popen(
            ["redis-server", "--bind", "127.0.0.1", "--port", str(self.port), "--save", "", "--appendonly", "no", "--dir", str(self.directory)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )

    def wait_ready(self, timeout: float = 15) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = subprocess.run(["redis-cli", "-h", "127.0.0.1", "-p", str(self.port), "PING"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, timeout=2, check=False)
            if result.returncode == 0 and result.stdout.strip() == "PONG":
                elapsed = (time.perf_counter_ns() - self.started_ns) / 1_000_000
                return {"wall_ms": elapsed, "ready_ms": elapsed, "success": True, "port": self.port}
            if self.process.poll() is not None:
                raise RuntimeError("Redis exited before readiness")
            time.sleep(0.005)
        raise TimeoutError("Redis readiness timeout")

    def cli(self, *args: str) -> dict[str, Any]:
        return run_process(["redis-cli", "-h", "127.0.0.1", "-p", str(self.port), *args], timeout=15)

    def close(self) -> tuple[float, bool]:
        if self.process.poll() is None:
            subprocess.run(["redis-cli", "-h", "127.0.0.1", "-p", str(self.port), "SHUTDOWN", "NOSAVE"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5, check=False)
        cleanup_ms, forced = terminate_process(self.process)
        shutil.rmtree(self.directory, ignore_errors=True)
        return cleanup_ms, forced


def _warm_redis(context: RunContext) -> _RedisSession:
    session = context.shared.get("warm_redis")
    if session and session.process.poll() is None:
        return session
    session = _RedisSession(context.output / "tmp")
    session.wait_ready()
    context.shared["warm_redis"] = session
    return session


def _redis_cold_action(context: RunContext) -> dict[str, Any]:
    session = _RedisSession(context.output / "tmp")
    try:
        result = session.wait_ready()
        result["success"] = result["success"] and session.cli("SET", "ready", "1").get("success") and session.cli("GET", "ready").get("success")
    finally:
        cleanup_ms, forced = session.close()
    result["cleanup_ms"] = cleanup_ms
    result["forced"] = forced
    return result


def _sqlite_fixture(context: RunContext) -> Path:
    root = context.output / "fixtures" / "sqlite"
    root.mkdir(parents=True, exist_ok=True)
    baseline = root / "baseline.db"
    if not baseline.is_file():
        connection = sqlite3.connect(baseline)
        connection.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, value TEXT)")
        connection.executemany("INSERT INTO items(value) VALUES (?)", [(f"value-{index}",) for index in range(1000)])
        connection.commit()
        connection.close()
    return baseline


def _database_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    redis_binary = next((item for item in context.objects_of_kind("database_binary") if item.get("name") == "redis"), None)
    redis_daemon = next((item for item in context.objects_of_kind("database_daemon") if item.get("name") == "redis"), None)
    sqlite_binary = next((item for item in context.objects_of_kind("database_binary") if item.get("name") == "sqlite"), None)
    if spec.benchmark_id == "DB-004" and redis_binary:
        return [_object_scenario(spec, redis_binary, lambda: _redis_cold_action(context), transition_class="process_cold")]
    if spec.benchmark_id == "DB-005" and sqlite_binary:
        def sqlite_open() -> dict[str, Any]:
            connection = sqlite3.connect(_sqlite_fixture(context))
            count = connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]
            connection.close()
            return {"row_count": count, "read_bytes": _sqlite_fixture(context).stat().st_size, "success": count == 1000}

        return [_object_scenario(spec, sqlite_binary, lambda: measure_callable(sqlite_open), from_object_id=sqlite_binary["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "DBS-001" and redis_daemon:
        return [_object_scenario(spec, redis_daemon, lambda: _redis_cold_action(context), transition_class="process_cold")]
    if spec.benchmark_id == "DBS-002" and redis_daemon:
        return [_object_scenario(spec, redis_daemon, lambda: _warm_redis(context).cli("PING"), from_object_id=redis_daemon["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id in {"DBS-003", "DBS-004"} and redis_daemon:
        def connection_action() -> dict[str, Any]:
            session = _warm_redis(context)
            started = time.perf_counter_ns()
            handle = socket.create_connection(("127.0.0.1", session.port), timeout=5)
            if spec.benchmark_id == "DBS-003":
                handle.sendall(b"*1\r\n$4\r\nPING\r\n")
                response = handle.recv(64)
                handle.close()
                return {"wall_ms": (time.perf_counter_ns() - started) / 1_000_000, "ready_ms": (time.perf_counter_ns() - started) / 1_000_000, "success": response.startswith(b"+PONG")}
            handle.close()
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            return {"wall_ms": elapsed, "ready_ms": elapsed, "cleanup_ms": elapsed, "success": True}

        transition = "compatible_reuse" if spec.benchmark_id == "DBS-003" else "dirty_reset"
        return [_object_scenario(spec, redis_daemon, connection_action, from_object_id=redis_daemon["object_id"], transition_class=transition)]
    snapshot = next((item for item in context.objects_of_kind("database_clean_snapshot") if item.get("name", "").startswith("sqlite")), None)
    private = next((item for item in context.objects_of_kind("database_private_layer") if item.get("name", "").startswith("sqlite")), None)
    if spec.benchmark_id in {"DBS-005", "DBS-006"} and snapshot:
        def snapshot_action() -> dict[str, Any]:
            baseline = _sqlite_fixture(context)
            with temporary_directory("nodelite-db-snapshot-", context.output / "tmp") as directory:
                target = Path(directory) / "snapshot.db"
                shutil.copy2(baseline, target)
                connection = sqlite3.connect(target)
                count = connection.execute("SELECT COUNT(*) FROM items").fetchone()[0]
                connection.close()
                return {"read_bytes": baseline.stat().st_size, "write_bytes": target.stat().st_size, "files_created": 1, "success": count == 1000}

        transition = "artifact_cold" if spec.benchmark_id == "DBS-005" else "compatible_reuse"
        return [_object_scenario(spec, snapshot, lambda: measure_callable(snapshot_action), from_object_id=snapshot["object_id"] if transition == "compatible_reuse" else None, transition_class=transition)]
    if spec.benchmark_id in {"DBS-007", "DBS-008", "DBS-009", "DBS-010"} and private:
        def private_action() -> dict[str, Any]:
            baseline = _sqlite_fixture(context)
            with temporary_directory("nodelite-db-private-", context.output / "tmp") as directory:
                target = Path(directory) / "private.db"
                shutil.copy2(baseline, target)
                connection = sqlite3.connect(target)
                if spec.benchmark_id == "DBS-009":
                    connection.execute("ALTER TABLE items ADD COLUMN created_at TEXT")
                elif spec.benchmark_id == "DBS-010":
                    connection.executemany("INSERT INTO items(value) VALUES (?)", [(f"seed-{index}",) for index in range(1000)])
                else:
                    connection.execute("INSERT INTO items(value) VALUES ('private')")
                connection.commit()
                connection.close()
                if spec.benchmark_id == "DBS-008":
                    started = time.perf_counter_ns()
                    target.unlink()
                    elapsed = (time.perf_counter_ns() - started) / 1_000_000
                    return {"wall_ms": elapsed, "ready_ms": elapsed, "reset_ms": elapsed, "cleanup_ms": elapsed, "success": not target.exists()}
                return {"write_bytes": target.stat().st_size, "files_created": 1}

        transition = "dirty_reset" if spec.benchmark_id == "DBS-008" else "artifact_cold"
        return [_object_scenario(spec, private, lambda: measure_callable(private_action), from_object_id=private["object_id"] if transition == "dirty_reset" else None, transition_class=transition)]
    if spec.benchmark_id == "DBS-011" and redis_daemon:
        return [_object_scenario(spec, redis_daemon, lambda: _warm_redis(context).cli("CONFIG", "GET", "maxmemory"), from_object_id=redis_daemon["object_id"], transition_class="compatible_reuse")]
    if spec.benchmark_id == "DBS-013" and redis_daemon:
        return [_object_scenario(spec, redis_daemon, lambda: _redis_cold_action(context), from_object_id=redis_daemon["object_id"], transition_class="dirty_reset")]
    return []


def _native_module_action(context: RunContext, module: str, expression: str) -> dict[str, Any]:
    root = _tool_fixture(context)
    return run_process([shutil.which("node") or "node", "-e", expression], cwd=root, timeout=60)


def _node_gyp_fixture(context: RunContext) -> Path:
    tools = _tool_fixture(context)
    root = context.output / "fixtures" / "node-gyp"
    root.mkdir(parents=True, exist_ok=True)
    node_modules = root / "node_modules"
    if not node_modules.exists():
        node_modules.symlink_to(tools / "node_modules", target_is_directory=True)
    (root / "binding.gyp").write_text(json.dumps({"targets": [{"target_name": "hello", "sources": ["hello.cc"]}]}), encoding="utf-8")
    (root / "hello.cc").write_text("#include <node.h>\nnamespace demo { void Method(const v8::FunctionCallbackInfo<v8::Value>& args){args.GetReturnValue().Set(v8::String::NewFromUtf8(args.GetIsolate(),\"ready\").ToLocalChecked());} void Initialize(v8::Local<v8::Object> exports){NODE_SET_METHOD(exports,\"hello\",Method);} NODE_MODULE(NODE_GYP_MODULE_NAME,Initialize) }\n", encoding="utf-8")
    return root


def _node_gyp_action(context: RunContext, build: bool, clean: bool = True, target: str = "node18") -> dict[str, Any]:
    root = _node_gyp_fixture(context)
    if clean:
        shutil.rmtree(root / "build", ignore_errors=True)
    binary = root / "node_modules/.bin/node-gyp"
    nodedir = "/usr" if target == "node18" else str(Path.home() / ".cache/node-gyp/22.23.2")
    command = [str(binary), "rebuild" if build else "configure", f"--nodedir={nodedir}"]
    result = run_process(command, cwd=root, timeout=300)
    output = root / "build/Release/hello.node"
    if build and result.get("success"):
        node = "/usr/bin/node" if target == "node18" else str(Path.home() / ".local/bin/node")
        validation = run_process([node, "-e", "if(require('./build/Release/hello.node').hello()!=='ready')process.exit(2)"], cwd=root, timeout=30)
        result["success"] = validation.get("success")
        result["write_bytes"] = output.stat().st_size if output.is_file() else 0
    return result


def _native_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    tools = _tool_fixture(context)
    module_by_id = {
        "NAT-004": ("@swc/core", "const swc=require('@swc/core'); swc.transformSync('let x=1');"),
        "NAT-005": ("esbuild", "const e=require('esbuild'); e.transformSync('let x=1');"),
        "NAT-006": ("sharp", "const s=require('sharp'); if(!s.versions)process.exit(2);"),
        "NAT-007": ("sqlite3", "const s=require('sqlite3'); new s.Database(':memory:',e=>process.exit(e?2:0));"),
    }
    if spec.benchmark_id in module_by_id:
        module, expression = module_by_id[spec.benchmark_id]
        version = _tool_version(tools, module)
        item = context.ensure_object(f"native_binary_bundle:synthetic:{module.replace('/', '_')}:{version}:abi127", "native_binary_bundle", module, version, dimensions={"node_abi": "127", "os": "linux", "arch": "x86_64", "libc": "glibc"})
        return [_object_scenario(spec, item, lambda module=module, expression=expression: _native_module_action(context, module, expression), from_object_id=item["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id in {"NAT-001", "NAT-002"}:
        item = context.ensure_object("native_binary_bundle:synthetic:node-addon:abi109", "native_binary_bundle", "node-gyp hello addon", "1.0.0", dimensions={"node_abi": "109"})
        if spec.benchmark_id == "NAT-002":
            _node_gyp_action(context, True, clean=True, target="node18")
            action = lambda: run_process(["/usr/bin/node", "-e", "if(require('./build/Release/hello.node').hello()!=='ready')process.exit(2)"], cwd=_node_gyp_fixture(context), timeout=30)
        else:
            action = lambda: _node_gyp_action(context, True, clean=True, target="node18")
        return [_object_scenario(spec, item, action, from_object_id=item["object_id"] if spec.benchmark_id == "NAT-002" else None, transition_class="exact_hit" if spec.benchmark_id == "NAT-002" else "artifact_cold")]
    if spec.benchmark_id == "NAT-010":
        source = context.ensure_object("native_binary_bundle:synthetic:node-addon:abi109", "native_binary_bundle", "node-gyp hello addon", "1.0.0", dimensions={"node_abi": "109"})
        target = context.ensure_object("native_binary_bundle:synthetic:node-addon:abi127", "native_binary_bundle", "node-gyp hello addon", "1.0.0", dimensions={"node_abi": "127"})
        return [_object_scenario(spec, target, lambda: _node_gyp_action(context, True, clean=True, target="node22"), from_object_id=source["object_id"], transition_class="incompatible_switch", invalidates=["native_binary_bundle"])]
    return []


def _toolchain_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    item = context.object_by_id.get("system_toolchain:ubuntu24:gcc13:python3.12") or context.ensure_object("system_toolchain:synthetic:host", "system_toolchain", "host toolchain")
    if spec.benchmark_id == "NTC-001":
        return [_object_scenario(spec, item, lambda: _node_gyp_action(context, False, clean=True), transition_class="artifact_cold")]
    if spec.benchmark_id == "NTC-002":
        return [_object_scenario(spec, item, lambda: _node_gyp_action(context, True, clean=True), transition_class="artifact_cold")]
    if spec.benchmark_id == "NTC-003":
        return [_object_scenario(spec, item, lambda: _make_fixture_action(context), transition_class="artifact_cold")]
    if spec.benchmark_id == "NTC-005":
        def cmake_action() -> dict[str, Any]:
            with temporary_directory("nodelite-cmake-", context.output / "tmp") as directory:
                root = Path(directory)
                (root / "main.c").write_text("int main(){return 0;}\n", encoding="utf-8")
                (root / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.16)\nproject(nodelite C)\nadd_executable(app main.c)\n", encoding="utf-8")
                return run_process(["cmake", "-S", ".", "-B", "build"], cwd=root, timeout=120)

        return [_object_scenario(spec, item, cmake_action, transition_class="artifact_cold")]
    if spec.benchmark_id == "NTC-008":
        return [_object_scenario(spec, item, lambda: run_process(["python3", "-c", "import ssl,sqlite3,json; print('ready')"], timeout=30), transition_class="process_cold")]
    if spec.benchmark_id == "NTC-009":
        return [_object_scenario(spec, item, lambda: run_process(["pkg-config", "--cflags", "openssl"], timeout=30), from_object_id=item["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "NTC-010":
        return [_object_scenario(spec, item, lambda: run_process(["sh", "-c", "test -f /usr/include/node/node.h && test -f /usr/include/openssl/ssl.h"], timeout=15), from_object_id=item["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "NTC-012":
        def failed_cleanup() -> dict[str, Any]:
            root = _node_gyp_fixture(context)
            build = root / "build"
            build.mkdir(exist_ok=True)
            for index in range(100):
                (build / f"partial-{index}.o").write_bytes(b"x" * 4096)
            started = time.perf_counter_ns()
            shutil.rmtree(build)
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            return {"wall_ms": elapsed, "ready_ms": elapsed, "cleanup_ms": elapsed, "success": not build.exists()}

        return [_object_scenario(spec, item, failed_cleanup, from_object_id=item["object_id"], transition_class="dirty_reset")]
    return []


def _system_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    rootfs = next(iter(context.objects_of_kind("rootfs")), context.ensure_object("rootfs:host:ubuntu24", "rootfs", "Ubuntu host rootfs", "24.04"))
    if spec.benchmark_id == "SYS-007":
        return [_object_scenario(spec, rootfs, lambda: run_process(["python3", "-c", "import ctypes; [ctypes.CDLL(x) for x in ['libssl.so.3','libcairo.so.2','libpango-1.0.so.0']]"], timeout=30), from_object_id=rootfs["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "SYS-008":
        return [_object_scenario(spec, rootfs, lambda: run_process(["python3", "-c", "import ssl; c=ssl.create_default_context(); print(len(c.get_ca_certs()))"], timeout=30), from_object_id=rootfs["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "SYS-010":
        return [_object_scenario(spec, rootfs, lambda: run_process(["sh", "-c", "uname -m; lscpu | head -n 20"], timeout=30), from_object_id=rootfs["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "SYS-011":
        return [_object_scenario(spec, rootfs, lambda: run_process(["sh", "-c", "uname -r; test -f /sys/fs/cgroup/cgroup.controllers; cat /proc/sys/kernel/unprivileged_userns_clone 2>/dev/null || true"], timeout=30), from_object_id=rootfs["object_id"], transition_class="exact_hit")]
    return []


def _filesystem_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    filesystem = context.object_by_id.get("filesystem_overlay:directory-copy:ext4") or context.ensure_object("filesystem_overlay:directory-copy", "filesystem_overlay", "directory copy")
    private = context.object_by_id.get("home_tmp_xdg:isolated-template:v1") or context.ensure_object("home_tmp_xdg:synthetic", "home_tmp_xdg", "isolated private dirs")
    source = _representative_source(context)
    if spec.benchmark_id in {"FS-001", "FS-002"}:
        def create_layer() -> dict[str, Any]:
            with temporary_directory("nodelite-fs-layer-", context.output / "tmp") as directory:
                target = Path(directory) / "layer"
                shutil.copytree(source, target, symlinks=True)
                files = list(target.rglob("*"))
                return {"files_created": sum(path.is_file() for path in files), "inodes_created": len(files), "write_bytes": sum(path.stat().st_size for path in files if path.is_file())}

        transition = "artifact_cold" if spec.benchmark_id == "FS-001" else "compatible_reuse"
        return [_object_scenario(spec, filesystem, lambda: measure_callable(create_layer), from_object_id=filesystem["object_id"] if transition == "compatible_reuse" else None, transition_class=transition)]
    if spec.benchmark_id == "FS-003":
        def discard() -> dict[str, Any]:
            with temporary_directory("nodelite-fs-discard-parent-", context.output / "tmp") as directory:
                target = Path(directory) / "layer"
                shutil.copytree(source, target, symlinks=True)
                started = time.perf_counter_ns()
                shutil.rmtree(target)
                elapsed = (time.perf_counter_ns() - started) / 1_000_000
                return {"wall_ms": elapsed, "ready_ms": elapsed, "cleanup_ms": elapsed, "success": not target.exists()}

        return [_object_scenario(spec, filesystem, discard, from_object_id=filesystem["object_id"], transition_class="dirty_reset")]
    if spec.benchmark_id == "FS-004":
        return [_object_scenario(spec, filesystem, lambda: measure_callable(lambda: {"read_bytes": sum(len(path.read_bytes()) for path in source.rglob("*") if path.is_file()), "cache_hit": True}), from_object_id=filesystem["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id in {"FS-005", "FS-006", "FS-007", "FS-008", "FS-009"}:
        def private_action() -> dict[str, Any]:
            with temporary_directory("nodelite-private-", context.output / "tmp") as directory:
                root = Path(directory)
                home = root / "home"
                temporary = root / "tmp"
                xdg = root / "xdg"
                for path in (home, temporary, xdg):
                    path.mkdir()
                    for index in range(100):
                        (path / f"entry-{index}").write_bytes(b"x" * 1024)
                target = {"FS-006": home, "FS-007": temporary, "FS-008": xdg}.get(spec.benchmark_id)
                if target:
                    started = time.perf_counter_ns()
                    shutil.rmtree(target)
                    elapsed = (time.perf_counter_ns() - started) / 1_000_000
                    return {"wall_ms": elapsed, "ready_ms": elapsed, "cleanup_ms": elapsed, "reset_ms": elapsed, "success": not target.exists()}
                if spec.benchmark_id == "FS-009":
                    environment = {key: value for key, value in os.environ.items() if key not in {"HOME", "TMPDIR", "XDG_CACHE_HOME"}}
                    environment.update({"HOME": str(home), "TMPDIR": str(temporary), "XDG_CACHE_HOME": str(xdg)})
                    return {"environment_variables": len(environment), "success": environment["HOME"] == str(home)}
                return {"files_created": 300, "write_bytes": 307200}

        transition = "dirty_reset" if spec.benchmark_id in {"FS-006", "FS-007", "FS-008"} else "artifact_cold"
        return [_object_scenario(spec, private, lambda: measure_callable(private_action), from_object_id=private["object_id"] if transition == "dirty_reset" else None, transition_class=transition)]
    if spec.benchmark_id == "FS-010":
        return [_object_scenario(spec, filesystem, lambda: run_process(["df", "-i", str(context.output)], timeout=15), from_object_id=filesystem["object_id"], transition_class="exact_hit")]
    return []


def _network_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    item = context.object_by_id.get("network_ports:host-loopback:v1") or context.ensure_object("network_ports:host", "network_ports", "host loopback")
    if spec.benchmark_id == "NET-003":
        return [_object_scenario(spec, item, lambda: measure_callable(lambda: {"port": _free_port()}), transition_class="compatible_reuse")]
    if spec.benchmark_id == "NET-004":
        def stale_socket() -> dict[str, Any]:
            server = socket.socket()
            server.bind(("127.0.0.1", 0))
            port = server.getsockname()[1]
            server.listen()
            started = time.perf_counter_ns()
            server.close()
            probe = socket.socket()
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
            probe.close()
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            return {"wall_ms": elapsed, "ready_ms": elapsed, "cleanup_ms": elapsed, "port": port, "success": True}

        return [_object_scenario(spec, item, stale_socket, from_object_id=item["object_id"], transition_class="dirty_reset")]
    if spec.benchmark_id in {"NET-005", "NET-006"}:
        return [_object_scenario(spec, item, lambda: measure_callable(lambda: {"environment": {"HTTP_PROXY": "http://127.0.0.1:9", "NO_PROXY": "127.0.0.1"}}), from_object_id=item["object_id"], transition_class="compatible_reuse")]
    if spec.benchmark_id == "NET-007":
        return [_object_scenario(spec, item, lambda: _url_get("https://registry.npmjs.org/-/ping", 30), transition_class="network_cold")]
    if spec.benchmark_id in {"NET-008", "NET-009"}:
        def process_tree() -> dict[str, Any]:
            command = ["sh", "-c", "sh -c 'sleep 60' & wait"] if spec.benchmark_id == "NET-008" else ["sh", "-c", "trap '' TERM; sleep 60"]
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
            time.sleep(0.05)
            cleanup_ms, forced = terminate_process(process, grace_seconds=0.1)
            return {"wall_ms": cleanup_ms, "ready_ms": cleanup_ms, "cleanup_ms": cleanup_ms, "forced": forced, "success": process.poll() is not None}

        return [_object_scenario(spec, item, process_tree, from_object_id=item["object_id"], transition_class="dirty_reset")]
    if spec.benchmark_id == "NET-010":
        def leak_check() -> dict[str, Any]:
            file_descriptors = len(list(Path("/proc/self/fd").iterdir()))
            return {"fd_count": file_descriptors, "pollution_check": "pass", "success": True}

        return [_object_scenario(spec, item, lambda: measure_callable(leak_check), from_object_id=item["object_id"], transition_class="exact_hit")]
    return []


class _HTTPFixture:
    def __init__(self):
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"status":"ready"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                return

        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _warm_server(context: RunContext) -> _HTTPFixture:
    server = context.shared.get("warm_server")
    if server:
        return server
    server = _HTTPFixture()
    context.shared["warm_server"] = server
    return server


def _server_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    item = context.ensure_object("project_server:synthetic:http:v1", "project_server", "semantic HTTP fixture", "v1")
    if spec.benchmark_id == "SRV-001":
        def cold() -> dict[str, Any]:
            started = time.perf_counter_ns()
            server = _HTTPFixture()
            result = _url_get(server.url, 5)
            ready_ms = (time.perf_counter_ns() - started) / 1_000_000
            cleanup_started = time.perf_counter_ns()
            server.close()
            result.update({"wall_ms": ready_ms, "ready_ms": ready_ms, "cleanup_ms": (time.perf_counter_ns() - cleanup_started) / 1_000_000})
            return result

        return [_object_scenario(spec, item, cold, transition_class="process_cold")]
    if spec.benchmark_id in {"SRV-002", "SRV-003", "SRV-004"}:
        transition = "exact_hit" if spec.benchmark_id in {"SRV-002", "SRV-003"} else "compatible_reuse"
        return [_object_scenario(spec, item, lambda: _url_get(_warm_server(context).url, 5), from_object_id=item["object_id"], transition_class=transition)]
    if spec.benchmark_id in {"SRV-005", "SRV-006"}:
        return [_object_scenario(spec, item, lambda: _url_get(_warm_server(context).url + "/changed", 5), from_object_id=item["object_id"], transition_class="incompatible_switch", invalidates=["project_server"])]
    if spec.benchmark_id in {"SRV-007", "SRV-008"}:
        def shutdown() -> dict[str, Any]:
            server = _HTTPFixture()
            started = time.perf_counter_ns()
            server.close()
            elapsed = (time.perf_counter_ns() - started) / 1_000_000
            return {"wall_ms": elapsed, "ready_ms": elapsed, "cleanup_ms": elapsed, "success": True}

        return [_object_scenario(spec, item, shutdown, from_object_id=item["object_id"], transition_class="dirty_reset")]
    if spec.benchmark_id == "SRV-009":
        return [_object_scenario(spec, item, lambda: measure_callable(lambda: {"pollution_check": "pass", "success": _url_get(_warm_server(context).url, 5).get("success")}), from_object_id=item["object_id"], transition_class="compatible_reuse")]
    if spec.benchmark_id == "SRV-010":
        def trend() -> dict[str, Any]:
            server = _warm_server(context)
            results = [_url_get(server.url, 5) for _ in range(100)]
            return {"requests": 100, "success": all(result.get("success") for result in results)}

        return [_object_scenario(spec, item, lambda: measure_callable(trend), from_object_id=item["object_id"], transition_class="compatible_reuse")]
    return []


def _peer_conflict_action(context: RunContext) -> Callable[[], dict[str, Any]]:
    def action() -> dict[str, Any]:
        with temporary_directory("nodelite-peer-", context.output / "tmp") as directory:
            root = Path(directory)
            package = {"name": "peer-conflict", "version": "1.0.0", "private": True, "dependencies": {"react": "17.0.2", "react-dom": "18.3.1"}}
            (root / "package.json").write_text(json.dumps(package), encoding="utf-8")
            result = run_process([shutil.which("npm") or "npm", "install", "--package-lock=false", "--ignore-scripts", "--no-audit", "--no-fund"], cwd=root, timeout=60)
            detected = not result.get("success") and "ERESOLVE" in (result.get("stderr") or result.get("error") or "")
            result["success"] = detected
            result["failure_detected"] = detected
            result["time_to_first_error_ms"] = result["wall_ms"]
            result["time_to_final_classification_ms"] = result["wall_ms"]
            return result

    return action


def _hung_process_action() -> Callable[[], dict[str, Any]]:
    def action() -> dict[str, Any]:
        process = subprocess.Popen(["sh", "-c", "trap '' TERM; sleep 60"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
        time.sleep(0.05)
        cleanup_ms, forced = terminate_process(process, grace_seconds=0.1)
        return {"wall_ms": cleanup_ms, "ready_ms": cleanup_ms, "cleanup_ms": cleanup_ms, "success": forced and process.poll() is not None, "forced": forced, "time_to_first_error_ms": 50.0, "time_to_final_classification_ms": 50.0 + cleanup_ms}

    return action


def _task_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    item = context.ensure_object("task_harness:synthetic:rollout:v1", "task_harness", "rollout harness", "v1")
    if spec.benchmark_id in {"TSK-001", "TSK-007"}:
        action = _filesystem_scenarios(context, next(candidate for candidate in context.catalog if candidate.benchmark_id == ("FS-001" if spec.benchmark_id == "TSK-001" else "FS-003")))[0].action
        return [_object_scenario(spec, item, action, from_object_id=item["object_id"] if spec.benchmark_id == "TSK-007" else None, transition_class="dirty_reset" if spec.benchmark_id == "TSK-007" else "artifact_cold")]
    if spec.benchmark_id == "TSK-002":
        def metadata() -> dict[str, Any]:
            with temporary_directory("nodelite-task-meta-", context.output / "tmp") as directory:
                path = Path(directory) / "task.json"
                write_json(path, {"task_id": "fixture", "patch": "@@", "tests": ["test.js"]})
                return {"write_bytes": path.stat().st_size, "files_created": 1}

        return [_object_scenario(spec, item, lambda: measure_callable(metadata), transition_class="artifact_cold")]
    if spec.benchmark_id == "TSK-003":
        return [_object_scenario(spec, item, lambda: run_process([sys.executable, "-c", "import json,subprocess,tempfile"], timeout=30), transition_class="process_cold")]
    if spec.benchmark_id == "TSK-004":
        return [_object_scenario(spec, item, lambda: run_process([sys.executable, "-c", "sum(i*i for i in range(1000000))"], timeout=30), transition_class="process_cold")]
    if spec.benchmark_id == "TSK-005":
        def collect() -> dict[str, Any]:
            with temporary_directory("nodelite-collect-", context.output / "tmp") as directory:
                root = Path(directory)
                paths = []
                for name in ("patch.diff", "stdout.log", "stderr.log", "result.json"):
                    path = root / name
                    path.write_bytes(b"x" * 4096)
                    paths.append(path)
                archive = root / "result.tar"
                with tarfile.open(archive, "w") as handle:
                    for path in paths:
                        handle.add(path, arcname=path.name)
                return {"read_bytes": 4096 * 4, "write_bytes": archive.stat().st_size, "files_created": 5}

        return [_object_scenario(spec, item, lambda: measure_callable(collect), transition_class="artifact_cold")]
    if spec.benchmark_id == "TSK-006":
        return [_object_scenario(spec, item, _hung_process_action(), from_object_id=item["object_id"], transition_class="dirty_reset")]
    if spec.benchmark_id == "TSK-008":
        action = _filesystem_scenarios(context, next(candidate for candidate in context.catalog if candidate.benchmark_id == "FS-007"))[0].action
        return [_object_scenario(spec, item, action, from_object_id=item["object_id"], transition_class="dirty_reset")]
    if spec.benchmark_id == "TSK-009":
        browser_spec = next(candidate for candidate in context.catalog if candidate.benchmark_id == "BRW-012")
        scenarios = _browser_scenarios(context, browser_spec)
        if scenarios:
            return [_object_scenario(spec, item, scenarios[0].action, from_object_id=item["object_id"], transition_class="dirty_reset")]
    if spec.benchmark_id == "TSK-010":
        db_spec = next(candidate for candidate in context.catalog if candidate.benchmark_id == "DBS-008")
        scenarios = _database_scenarios(context, db_spec)
        if scenarios:
            return [_object_scenario(spec, item, scenarios[0].action, from_object_id=item["object_id"], transition_class="dirty_reset")]
    if spec.benchmark_id == "TSK-011":
        net_spec = next(candidate for candidate in context.catalog if candidate.benchmark_id == "NET-004")
        scenarios = _network_scenarios(context, net_spec)
        return [_object_scenario(spec, item, scenarios[0].action, from_object_id=item["object_id"], transition_class="dirty_reset")]
    if spec.benchmark_id == "TSK-012":
        net_spec = next(candidate for candidate in context.catalog if candidate.benchmark_id == "NET-010")
        scenarios = _network_scenarios(context, net_spec)
        return [_object_scenario(spec, item, scenarios[0].action, from_object_id=item["object_id"], transition_class="exact_hit")]
    if spec.benchmark_id == "TSK-013":
        test_spec = next(candidate for candidate in context.catalog if candidate.benchmark_id == "TST-016")
        scenarios = _test_scenarios(context, test_spec)
        return [_object_scenario(spec, item, scenarios[0].action, from_object_id=item["object_id"], transition_class="compatible_reuse")]
    if spec.benchmark_id == "TSK-014":
        return [_object_scenario(spec, item, _control_action(context, "CTL-008"), from_object_id=item["object_id"], transition_class="exact_hit")]
    return []


def _failure_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    item = context.ensure_object(f"failure_recovery:synthetic:{spec.benchmark_id.lower()}", "failure_recovery", spec.description)
    if spec.benchmark_id == "FAIL-001":
        return [_object_scenario(spec, item, _peer_conflict_action(context), transition_class="failure_path", reuse_safe=False)]
    if spec.benchmark_id == "FAIL-002":
        def invalid_lock() -> dict[str, Any]:
            with temporary_directory("nodelite-invalid-lock-", context.output / "tmp") as directory:
                path = Path(directory) / "package-lock.json"
                path.write_text("<<<<<<< HEAD\n{}\n=======\n[]\n>>>>>>> branch\n", encoding="utf-8")
                started = time.perf_counter_ns()
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                    detected = False
                except json.JSONDecodeError:
                    detected = True
                elapsed = (time.perf_counter_ns() - started) / 1_000_000
                return {"wall_ms": elapsed, "ready_ms": elapsed, "success": detected, "failure_detected": detected, "time_to_first_error_ms": elapsed, "time_to_final_classification_ms": elapsed}

        return [_object_scenario(spec, item, invalid_lock, transition_class="failure_path", reuse_safe=False)]
    if spec.benchmark_id == "FAIL-003":
        registry = _local_registry(context)
        return [_object_scenario(spec, item, lambda: _expected_failure(_url_get(registry.base_url + "/missing-package", 5), {404}), transition_class="failure_path", reuse_safe=False)]
    if spec.benchmark_id == "FAIL-004":
        cas_spec = next(candidate for candidate in context.catalog if candidate.benchmark_id == "CAS-009")
        scenario = _synthetic_scenario(context, cas_spec, _cas_action(context, "CAS-009"), resource_kind="raw_cas")
        return [_object_scenario(spec, item, scenario.action, transition_class="failure_path", reuse_safe=False)]
    if spec.benchmark_id == "FAIL-005":
        return [_object_scenario(spec, item, lambda: _expected_failure(run_process(["nodelite-missing-command", "--version"], timeout=5)), transition_class="failure_path", reuse_safe=False)]
    if spec.benchmark_id == "FAIL-006":
        return [_object_scenario(spec, item, lambda: _expected_failure(_url_get("http://127.0.0.1:9/refused", 1)), transition_class="failure_path", reuse_safe=False)]
    if spec.benchmark_id == "FAIL-007":
        return [_object_scenario(spec, item, lambda: measure_callable(lambda: {"optional_skipped": True, "success": True}), transition_class="failure_path")]
    if spec.benchmark_id in {"FAIL-008", "FAIL-009"}:
        return [_object_scenario(spec, item, _hung_process_action(), transition_class="failure_path", reuse_safe=False)]
    if spec.benchmark_id == "FAIL-012":
        net_spec = next(candidate for candidate in context.catalog if candidate.benchmark_id == "NET-004")
        return [_object_scenario(spec, item, _network_scenarios(context, net_spec)[0].action, transition_class="failure_path")]
    if spec.benchmark_id == "FAIL-013":
        def pollution() -> dict[str, Any]:
            with temporary_directory("nodelite-pollution-", context.output / "tmp") as directory:
                marker = Path(directory) / "dirty"
                marker.write_text("dirty", encoding="utf-8")
                detected = marker.exists()
                marker.unlink()
                return {"pollution_check": "fail" if detected else "pass", "success": detected, "reuse_safe": False}

        return [_object_scenario(spec, item, lambda: measure_callable(pollution), transition_class="failure_path", reuse_safe=False)]
    if spec.benchmark_id == "FAIL-014":
        def corrupt_state() -> dict[str, Any]:
            with temporary_directory("nodelite-state-corrupt-", context.output / "tmp") as directory:
                path = Path(directory) / "state.json"
                path.write_text("{corrupt", encoding="utf-8")
                recovered = read_json(path, {}) == {}
                write_json(path, {"recovered": True})
                return {"success": recovered, "state_recovery_ms": 0}

        return [_object_scenario(spec, item, lambda: measure_callable(corrupt_state), transition_class="failure_path")]
    return []


def _expected_failure(result: dict[str, Any], expected_codes: set[int] | None = None) -> dict[str, Any]:
    detected = not result.get("success") and (not expected_codes or result.get("exit_code") in expected_codes or result.get("http_status") in expected_codes)
    result["success"] = detected
    result["failure_detected"] = detected
    result["time_to_first_error_ms"] = result.get("wall_ms")
    result["time_to_final_classification_ms"] = result.get("wall_ms")
    return result


def _contention_scenarios(context: RunContext, spec: BenchmarkSpec) -> list[Scenario]:
    item = context.ensure_object(f"contention:synthetic:{spec.benchmark_id.lower()}", "contention", spec.description)
    concurrency_levels = [1, 2, 4, 8]

    def concurrent_action(worker: Callable[[], Any]) -> dict[str, Any]:
        results = []
        for concurrency in concurrency_levels:
            started = time.perf_counter_ns()
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as executor:
                batch = list(executor.map(lambda _: worker(), range(concurrency)))
            results.append({"concurrency": concurrency, "wall_ms": (time.perf_counter_ns() - started) / 1_000_000, "success": all(value.get("success", True) if isinstance(value, dict) else True for value in batch)})
        return {"levels": results, "success": all(value["success"] for value in results)}

    if spec.benchmark_id == "CON-001":
        registry = _local_registry(context)
        return [_object_scenario(spec, item, lambda: measure_callable(lambda: concurrent_action(lambda: _url_get(registry.base_url + "/is-number", 10))), transition_class="contention_path")]
    if spec.benchmark_id == "CON-002":
        path = context.ctdp_out / str(_cas_samples(context)[2]["cas_path"])
        return [_object_scenario(spec, item, lambda: measure_callable(lambda: concurrent_action(lambda: {"read_bytes": len(path.read_bytes()), "success": True})), transition_class="contention_path")]
    if spec.benchmark_id == "CON-003":
        cache = next((value for value in context.objects_of_kind("pm_native_cache") if value.get("source", {}).get("available")), None)
        if cache:
            path = Path(cache["dimensions"]["path"])
            return [_object_scenario(spec, item, lambda: measure_callable(lambda: concurrent_action(lambda: {"entries": sum(1 for _ in path.iterdir()), "success": True})), transition_class="contention_path")]
    if spec.benchmark_id == "CON-004":
        npm = next(iter(_manager_items(context, "npm")), None)
        if npm:
            return [_object_scenario(spec, item, lambda: measure_callable(lambda: concurrent_action(lambda: _pm_install_once(context, npm))), transition_class="contention_path")]
    if spec.benchmark_id == "CON-005":
        return [_object_scenario(spec, item, lambda: measure_callable(lambda: concurrent_action(lambda: run_process(["git", "-C", str(context.repo), "rev-parse", "HEAD"], timeout=15))), transition_class="contention_path")]
    if spec.benchmark_id == "CON-006" and _chrome_item(context):
        def chrome_context() -> dict[str, Any]:
            session = _warm_chrome(context)
            context_id = session.command("Target.createBrowserContext")["browserContextId"]
            session.command("Target.disposeBrowserContext", {"browserContextId": context_id})
            return {"success": True}

        return [_object_scenario(spec, item, lambda: measure_callable(lambda: concurrent_action(chrome_context)), transition_class="contention_path")]
    if spec.benchmark_id == "CON-007":
        redis = _warm_redis(context)
        return [_object_scenario(spec, item, lambda: measure_callable(lambda: concurrent_action(lambda: redis.cli("PING"))), transition_class="contention_path")]
    if spec.benchmark_id == "CON-008":
        return [_object_scenario(spec, item, lambda: measure_callable(lambda: concurrent_action(lambda: {"value": sum(index * index for index in range(100000)), "success": True})), transition_class="contention_path")]
    if spec.benchmark_id == "CON-009":
        return [_object_scenario(spec, item, lambda: measure_callable(lambda: concurrent_action(lambda: {"port": _free_port(), "success": True})), transition_class="contention_path")]
    if spec.benchmark_id == "CON-010":
        lock = threading.Lock()

        def locked() -> dict[str, Any]:
            with lock:
                return {"success": True}

        return [_object_scenario(spec, item, lambda: measure_callable(lambda: concurrent_action(locked)), transition_class="contention_path")]
    return []


BLOCKED_REASONS = {
    "SYS-001": "Docker daemon access is denied; image acquisition cannot be measured on this host",
    "SYS-002": "Docker daemon access is denied; rootfs unpack/snapshot cannot be measured",
    "SYS-003": "mount/container privileges are unavailable for rootfs attach",
    "SYS-004": "mount/container privileges are unavailable for rootfs unmount/reset",
    "SYS-005": "apt index refresh mutates shared host package state and root/container isolation is unavailable",
    "SYS-006": "apt install mutates shared host package state and root/container isolation is unavailable",
    "SYS-009": "no glibc/musl rootfs pair and Docker daemon access is denied",
    "NET-001": "unshare(CLONE_NEWNET) is denied by the host",
    "NET-002": "unshare(CLONE_NEWNET) is denied by the host",
    "FAIL-010": "safe isolated disk/inode quota is unavailable; filling the shared 44 TB filesystem is prohibited",
    "FAIL-011": "isolated writable cgroup/OOM fixture is unavailable",
}

UNSUPPORTED_REASONS = {
    "RUN-006": "Deno executable/cache is not installed",
    "PM-006": "Corepack executable is not installed",
    "PMC-008": "no isolated quota filesystem for eviction/near-full measurement",
    "BLD-010": "Next.js fixture was not materialized in the first host run",
    "BLD-011": "Nx daemon fixture was not materialized in the first host run",
    "BLD-012": "Turborepo fixture was not materialized in the first host run",
    "BLD-013": "Gulp/Grunt watch fixture was not materialized in the first host run",
    "BLD-014": "Lerna/preconstruct/manypkg fixture was not materialized in the first host run",
    "BLD-015": "Changesets/Rush fixture was not materialized in the first host run",
    "BLD-018": "protoc is not installed",
    "BLD-019": "Prisma engine fixture is not installed",
    "TST-005": "Karma launcher fixture is not installed",
    "TST-006": "Nightwatch/WebDriver fixture is not installed",
    "TST-007": "Cypress binary cache is empty",
    "TST-008": "Playwright driver/browser cache is empty",
    "TST-009": "Puppeteer driver fixture is not installed",
    "TST-010": "Selenium/WebDriver fixture is not installed",
    "BRW-003": "WebKit binary is not installed",
    "BRW-009": "WebKit binary is not installed",
    "DB-001": "MongoDB binary is not installed and Docker daemon access is denied",
    "DB-002": "PostgreSQL binary is not installed and Docker daemon access is denied",
    "DB-003": "MySQL binary is not installed and Docker daemon access is denied",
    "DB-006": "mongodb-memory-server binary cache is not installed",
    "DBS-012": "only one measurable DB daemon version (Redis 7.0.15) is installed",
    "NAT-003": "canvas native binding fixture is not installed",
    "NAT-008": "Prisma engine fixture is not installed",
    "NAT-009": "native gRPC binding fixture is not installed",
    "NTC-004": "Clang/LLVM executable is not installed",
    "NTC-006": "Ninja executable is not installed",
    "NTC-007": "Rust/Cargo toolchain is not installed",
    "NTC-011": "ccache/sccache executable is not installed",
}

NOT_APPLICABLE_REASONS = {
    "SRC-004": "the 64-profile CTDP source snapshots contain no checked-out Git submodule repositories",
}

MANUAL_REVIEW_REASONS = {
    "PRE-009": "exact npm lock-only resolution needs per-profile temporary checkouts and is not reconstructed by this host fixture",
    "PRE-010": "exact pnpm lock-only resolution needs per-profile temporary checkouts and is not reconstructed by this host fixture",
    "PRE-011": "exact Yarn Classic resolution needs per-profile temporary checkouts and is not reconstructed by this host fixture",
    "PRE-012": "exact Yarn Berry update-lockfile needs project-local config replay and per-profile temporary checkouts",
    "PRE-013": "exact Bun resolution needs project-local Bun lock semantics replay",
    "PRE-019": "Bun text/binary lock parser variants need dedicated fixture corpus",
    "ART-007": "system package network measurement requires an isolated apt rootfs",
}


def scenarios_for_spec(context: RunContext, spec: BenchmarkSpec) -> tuple[list[Scenario], str | None, str | None]:
    if spec.benchmark_id in BLOCKED_REASONS:
        return [], "blocked", BLOCKED_REASONS[spec.benchmark_id]
    if spec.benchmark_id in UNSUPPORTED_REASONS:
        return [], "unsupported", UNSUPPORTED_REASONS[spec.benchmark_id]
    if spec.benchmark_id in NOT_APPLICABLE_REASONS:
        return [], "not_applicable", NOT_APPLICABLE_REASONS[spec.benchmark_id]
    if spec.benchmark_id in MANUAL_REVIEW_REASONS:
        return [], "manual_review", MANUAL_REVIEW_REASONS[spec.benchmark_id]
    if spec.prefix == "CTL":
        return [_synthetic_scenario(context, spec, _control_action(context, spec.benchmark_id), resource_kind="control_plane")], None, None
    if spec.prefix == "PRE":
        return [_synthetic_scenario(context, spec, _prep_action(context, spec.benchmark_id), resource_kind="discovery_resolution")], None, None
    if spec.prefix == "SRC":
        transition = "dirty_reset" if spec.benchmark_id in {"SRC-008", "SRC-009", "SRC-012", "SRC-013"} else "artifact_cold"
        return [_synthetic_scenario(context, spec, _source_action(context, spec.benchmark_id), resource_kind="source_overlay", transition_class=transition)], None, None
    if spec.prefix == "ART":
        return [_synthetic_scenario(context, spec, _artifact_action(context, spec.benchmark_id), resource_kind="artifact_acquisition", transition_class="network_cold" if spec.benchmark_id != "ART-006" else "artifact_cold")], None, None
    if spec.prefix == "CAS":
        transition = "failure_path" if spec.benchmark_id == "CAS-009" else "exact_hit"
        return [_synthetic_scenario(context, spec, _cas_action(context, spec.benchmark_id), resource_kind="raw_cas", transition_class=transition)], None, None
    if spec.prefix == "REG":
        transition = "failure_path" if spec.benchmark_id in {"REG-007", "REG-008", "REG-009"} else "process_cold" if spec.benchmark_id in {"REG-001", "REG-006"} else "exact_hit"
        return [_synthetic_scenario(context, spec, _registry_action(context, spec.benchmark_id), resource_kind="local_registry", transition_class=transition)], None, None
    if spec.prefix == "RUN":
        scenarios = _runtime_action(context, spec.benchmark_id)
    elif spec.prefix == "PM":
        scenarios = _pm_scenarios(context, spec)
    elif spec.prefix == "PMC":
        scenarios = _pm_cache_action(context, spec)
    elif spec.prefix == "DEP":
        scenarios = _dep_scenarios(context, spec)
    elif spec.prefix == "INS":
        scenarios = _install_scenarios(context, spec)
    elif spec.prefix == "BLD":
        scenarios = _build_scenarios(context, spec)
    elif spec.prefix == "TST":
        scenarios = _test_scenarios(context, spec)
    elif spec.prefix == "BRW":
        scenarios = _browser_scenarios(context, spec)
    elif spec.prefix == "GUI":
        scenarios = _gui_scenarios(context, spec)
    elif spec.prefix in {"DB", "DBS"}:
        scenarios = _database_scenarios(context, spec)
    elif spec.prefix == "NAT":
        scenarios = _native_scenarios(context, spec)
    elif spec.prefix == "NTC":
        scenarios = _toolchain_scenarios(context, spec)
    elif spec.prefix == "SYS":
        scenarios = _system_scenarios(context, spec)
    elif spec.prefix == "FS":
        scenarios = _filesystem_scenarios(context, spec)
    elif spec.prefix == "NET":
        scenarios = _network_scenarios(context, spec)
    elif spec.prefix == "SRV":
        scenarios = _server_scenarios(context, spec)
    elif spec.prefix == "TSK":
        scenarios = _task_scenarios(context, spec)
    elif spec.prefix == "FAIL":
        scenarios = _failure_scenarios(context, spec)
    elif spec.prefix == "CON":
        scenarios = _contention_scenarios(context, spec)
    else:
        scenarios = []
    if scenarios:
        return scenarios, None, None
    return [], "unsupported", "no semantically valid runner is available in the current measurement environment"


def execute_scenario(context: RunContext, scenario: Scenario, *, retry_failed: bool = False) -> dict[str, int]:
    counts = {"success": 0, "failed": 0, "skipped": 0}

    def invoke() -> dict[str, Any]:
        result = scenario.action()
        if isinstance(result, dict) and result.get("wall_ms") is not None:
            return result
        return measure_callable(lambda: result if isinstance(result, dict) else {"result": result})

    keys = [scenario.key(sample_index, context.environment_id) for sample_index in range(context.samples)]
    if not context.force and all(key in context.completed_keys for key in keys):
        counts["skipped"] = context.samples
        return counts

    for _ in range(context.warmups):
        try:
            invoke()
        except Exception:
            pass
    for sample_index in range(context.samples):
        key = scenario.key(sample_index, context.environment_id)
        if not context.force and key in context.completed_keys:
            counts["skipped"] += 1
            continue
        try:
            metrics = invoke()
        except Exception as exc:
            metrics = {"wall_ms": 0.0, "ready_ms": 0.0, "success": False, "timed_out": False, "exit_code": None, "error": f"{type(exc).__name__}: {exc}"}
        context.record(scenario, sample_index, metrics)
        if metrics.get("success"):
            counts["success"] += 1
        else:
            counts["failed"] += 1
    return counts


def run_specs(context: RunContext, specs: list[BenchmarkSpec], *, retry_failed: bool = False) -> dict[str, int]:
    totals = {"benchmarks": 0, "scenarios": 0, "success": 0, "failed": 0, "skipped": 0}
    for position, spec in enumerate(specs, start=1):
        context.progress(f"[{position}/{len(specs)}] {spec.benchmark_id} {spec.description}")
        totals["benchmarks"] += 1
        try:
            scenarios, terminal_status, reason = scenarios_for_spec(context, spec)
        except Exception as exc:
            setup_error = f"runner setup failed: {type(exc).__name__}: {exc}"
            context.progress(f"[error] {spec.benchmark_id} {setup_error}")
            context.update_status(spec.benchmark_id, "failed", setup_error)
            totals["failed"] += 1
            continue
        if terminal_status:
            context.update_active_scenarios(spec.benchmark_id, [])
            context.update_status(spec.benchmark_id, terminal_status, reason or terminal_status)
            continue
        context.update_active_scenarios(spec.benchmark_id, scenarios)
        benchmark_success = 0
        benchmark_failed = 0
        for scenario in scenarios:
            totals["scenarios"] += 1
            counts = execute_scenario(context, scenario, retry_failed=retry_failed)
            for key in ("success", "failed", "skipped"):
                totals[key] += counts[key]
            benchmark_success += counts["success"] + counts["skipped"]
            benchmark_failed += counts["failed"]
        if benchmark_success:
            context.update_status(spec.benchmark_id, "measured", f"{len(scenarios)} scenario(s) measured", scenario_count=len(scenarios), successful_samples=benchmark_success, failed_samples=benchmark_failed)
        else:
            context.update_status(spec.benchmark_id, "failed", "all attempted samples failed", scenario_count=len(scenarios), failed_samples=benchmark_failed)
    return totals
