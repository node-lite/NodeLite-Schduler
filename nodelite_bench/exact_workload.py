from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .reporting import SUMMARY_FIELDS, build_direct_ms, build_summaries
from .util import append_jsonl, read_json, read_jsonl, sha256_file, write_csv, write_json


EXACT_ACTIONS = [
    {
        "benchmark_id": "EXACT-DEP-MATERIALIZE",
        "resource_kind": "dependency_view",
        "transition_class": "artifact_cold",
        "description": "Materialize an exact profile dependency view from its resolved lock and CTDP cache/CAS",
    },
    {
        "benchmark_id": "EXACT-DEP-ATTACH",
        "resource_kind": "dependency_view",
        "transition_class": "exact_hit",
        "description": "Attach to and verify an already materialized exact profile dependency view",
    },
    {
        "benchmark_id": "EXACT-DEP-RESET",
        "resource_kind": "dependency_view",
        "transition_class": "dirty_reset",
        "description": "Discard a task-local mutation from an exact profile dependency view",
    },
    {
        "benchmark_id": "EXACT-NATIVE-LOAD",
        "resource_kind": "native_binary_bundle",
        "transition_class": "artifact_cold",
        "description": "Resolve and load an exact profile native package under its required Node ABI",
    },
]

SOURCE_REQUIRED_KINDS = {
    "repo_baseline",
    "source_overlay",
    "build_cache",
    "test_transform_cache",
}


def _root_slug(root: str) -> str:
    return "root" if root == "." else root.replace("/", "__")


def _safe_profile_id(item: dict[str, Any]) -> str | None:
    profiles = item.get("profile_ids") or []
    if not profiles:
        return None
    return str(profiles[0]).removeprefix("swesmith/")


def _version_matches(actual: str, expected: str) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        match = re.search(r"(?:^|\s)v?(\d+(?:\.\d+){0,3})", value)
        return tuple(int(part) for part in match.group(1).split(".")) if match else ()

    actual_parts = parts(actual)
    expected_parts = parts(expected)
    return bool(actual_parts and expected_parts and actual_parts[: len(expected_parts)] == expected_parts)


def _tool_command(manager: str, version: str, variant: str, cache: dict[tuple[str, str, str], list[str] | None]) -> list[str] | None:
    key = manager, variant, version
    if key in cache:
        return cache[key]
    installed = shutil.which(manager)
    candidates: list[list[str]] = []
    if installed:
        candidates.append([installed])
    package = f"@yarnpkg/cli-dist@{version}" if manager == "yarn" and variant == "berry" else f"{manager}@{version}"
    candidates.append(["npx", "--offline", "--yes", "--package", package, manager])
    for candidate in candidates:
        try:
            result = subprocess.run(
                [*candidate, "--version"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        actual = result.stdout.strip()
        if result.returncode == 0 and _version_matches(actual, version):
            cache[key] = candidate
            return candidate
    cache[key] = None
    return None


def _artifact_maps(ctdp_out: Path) -> tuple[dict[str, Path], dict[tuple[str, str], Path]]:
    by_url: dict[str, Path] = {}
    by_package: dict[tuple[str, str], Path] = {}
    for item in read_json(ctdp_out / "prefetch.json", {}).get("artifacts", []):
        relative = item.get("cas_path")
        if item.get("status") not in {"downloaded", "reused"} or not relative:
            continue
        path = ctdp_out / str(relative)
        if not path.is_file():
            continue
        source = item.get("source_url") or item.get("source")
        if isinstance(source, str):
            by_url[source.split("#", 1)[0]] = path
        name, version = item.get("name"), item.get("version")
        if item.get("type") == "registry" and isinstance(name, str) and isinstance(version, str):
            by_package.setdefault((name, version), path)
            basename = name.rsplit("/", 1)[-1]
            for host in ("https://registry.npmjs.org", "https://registry.yarnpkg.com"):
                by_url.setdefault(f"{host}/{name}/-/{basename}-{version}.tgz", path)
    return by_url, by_package


def _rewrite_npm_lock(lock_path: Path, link_root: Path, by_url: dict[str, Path], by_package: dict[tuple[str, str], Path]) -> list[dict[str, Any]]:
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    links: dict[Path, str] = {}
    missing: list[dict[str, Any]] = []

    def local_uri(path: Path) -> str:
        if path not in links:
            link = link_root / f"{len(links):06d}.tgz"
            link.symlink_to(path)
            links[path] = link.as_uri()
        return links[path]

    def rewrite_entry(name: str | None, entry: Any) -> None:
        if not isinstance(entry, dict):
            return
        resolved = entry.get("resolved")
        version = entry.get("version")
        if isinstance(resolved, str):
            artifact = by_url.get(resolved.split("#", 1)[0])
            if artifact is None and isinstance(name, str) and isinstance(version, str):
                artifact = by_package.get((name, version))
            if artifact is None and resolved.startswith(("http://", "https://")):
                missing.append({"name": name, "version": version, "resolved": resolved})
            elif artifact is not None:
                entry["resolved"] = local_uri(artifact)
        dependencies = entry.get("dependencies")
        if isinstance(dependencies, dict):
            for child_name, child in dependencies.items():
                rewrite_entry(str(child_name), child)

    packages = lock.get("packages")
    if isinstance(packages, dict):
        for package_path, entry in packages.items():
            name = package_path.rsplit("node_modules/", 1)[-1] if "node_modules/" in package_path else entry.get("name") if isinstance(entry, dict) else None
            rewrite_entry(name, entry)
    dependencies = lock.get("dependencies")
    if isinstance(dependencies, dict):
        for name, entry in dependencies.items():
            rewrite_entry(str(name), entry)
    lock_path.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return missing


def _rewrite_text_lock(lock_path: Path, link_root: Path, by_url: dict[str, Path]) -> list[str]:
    text = lock_path.read_text(encoding="utf-8", errors="replace")
    links: dict[Path, str] = {}

    def local_uri(path: Path) -> str:
        if path not in links:
            link = link_root / f"{len(links):06d}.tgz"
            link.symlink_to(path)
            links[path] = link.as_uri()
        return links[path]

    for source, artifact in sorted(by_url.items(), key=lambda item: len(item[0]), reverse=True):
        if source in text:
            text = text.replace(source, local_uri(artifact))
    lock_path.write_text(text, encoding="utf-8")
    return sorted(set(re.findall(r"https?://[^\s\"']+", text)))


def _copy_dependency_snapshot(ctdp_out: Path, safe_id: str, root_name: str, record: dict[str, Any], destination: Path) -> Path:
    project = ctdp_out / "projects" / safe_id
    source = project / "source-files" / _root_slug(root_name)
    if not source.is_dir():
        raise FileNotFoundError(f"dependency source snapshot missing: {source}")
    root = destination if root_name == "." else destination / root_name
    shutil.copytree(source, root, dirs_exist_ok=True)
    resolved = record.get("resolved_lockfile")
    source_lock = record.get("source_lockfile")
    if not resolved:
        raise FileNotFoundError("resolved lockfile metadata is unavailable")
    resolved_path = project / str(resolved)
    if not resolved_path.is_file():
        raise FileNotFoundError(f"resolved lockfile missing: {resolved_path}")
    lock_name = Path(str(source_lock or resolved)).name
    lock_path = root / lock_name
    shutil.copy2(resolved_path, lock_path)
    return lock_path


def _install_command(manager: str, variant: str, tool: list[str], lock_path: Path, cache_root: Path) -> tuple[list[str], dict[str, str]]:
    environment = {
        **os.environ,
        "COREPACK_ENABLE_PROJECT_SPEC": "0",
        "npm_config_offline": "true",
        "npm_config_unsafe_perm": "true",
        "YARN_ENABLE_NETWORK": "0",
        "YARN_IGNORE_PATH": "1",
    }
    if manager == "npm":
        return [*tool, "ci", "--offline", "--ignore-scripts", "--no-audit", "--no-fund", "--cache", str(cache_root)], environment
    if manager == "pnpm":
        return [*tool, "install", "--offline", "--ignore-scripts", "--store-dir", str(cache_root), "--frozen-lockfile"], environment
    if manager == "yarn" and variant == "classic":
        return [*tool, "install", "--offline", "--ignore-scripts", "--non-interactive", "--cache-folder", str(cache_root), "--frozen-lockfile"], environment
    if manager == "yarn":
        bootstrap = lock_path.parent / ".nodelite-yarnrc.yml"
        original = lock_path.parent / ".yarnrc.yml"
        original_text = original.read_text(encoding="utf-8", errors="replace") if original.is_file() else ""
        linker = "node-modules" if "nodeLinker: node-modules" in original_text else "pnp"
        bootstrap.write_text(
            f"nodeLinker: {linker}\ncacheFolder: {json.dumps(str(cache_root))}\nenableGlobalCache: false\nenableNetwork: false\n",
            encoding="utf-8",
        )
        environment["YARN_RC_FILENAME"] = bootstrap.name
        return [*tool, "install", "--immutable", "--mode=skip-build"], environment
    if manager == "bun":
        return [*tool, "install", "--offline", "--ignore-scripts", f"--cache-dir={cache_root}"], environment
    raise ValueError(f"unsupported package manager: {manager}")


def _observation(
    *,
    environment_id: str,
    run_id: str,
    benchmark_id: str,
    item: dict[str, Any],
    sample_index: int,
    wall_ms: float,
    success: bool,
    transition_class: str,
    scenario_name: str,
    from_object_id: str | None,
    details: dict[str, Any],
    error: str | None = None,
    invalidates: list[str] | None = None,
) -> dict[str, Any]:
    object_id = str(item["object_id"])
    identity = "|".join([environment_id, benchmark_id, scenario_name, from_object_id or "cold", object_id, transition_class])
    return {
        "schema_version": 1,
        "observation_key": f"{identity}|{sample_index}",
        "benchmark_id": benchmark_id,
        "resource_kind": item["resource_kind"],
        "from_object_id": from_object_id,
        "to_object_id": object_id,
        "transition_class": transition_class,
        "cost_class": "ENV_PREP",
        "state_before": transition_class,
        "sample_index": sample_index,
        "measurement_run_id": run_id,
        "measurement_environment_id": environment_id,
        "wall_ms": round(wall_ms, 6),
        "ready_ms": round(wall_ms, 6),
        "switch_ms": 0,
        "reset_ms": round(wall_ms, 6) if transition_class == "dirty_reset" else 0,
        "cleanup_ms": 0,
        "invalidation_ms": 0,
        "user_cpu_ms": None,
        "system_cpu_ms": None,
        "rss_mb": None,
        "peak_rss_mb": None,
        "read_bytes": 0,
        "write_bytes": 0,
        "network_bytes": 0,
        "files_created": details.get("files_created", 0),
        "inodes_created": details.get("files_created", 0),
        "cache_hit": transition_class in {"exact_hit", "dirty_reset"},
        "success": success,
        "timed_out": details.get("timed_out", False),
        "exit_code": details.get("exit_code"),
        "reuse_safe": success,
        "pollution_check": details.get("pollution_check", "pass" if success else "not_run"),
        "invalidates": invalidates or [],
        "workload_origin": "real",
        "scenario_name": scenario_name,
        "error": error,
        "details": details,
    }


def _network_probe() -> dict[str, Any]:
    command = ["git", "ls-remote", "https://github.com/Automattic/mongoose.git", "HEAD"]
    try:
        result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        return {
            "attempted": True,
            "available": result.returncode == 0,
            "command": command,
            "exit_code": result.returncode,
            "error": result.stderr.strip() or None,
        }
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"attempted": True, "available": False, "command": command, "exit_code": None, "error": f"{type(exc).__name__}: {exc}"}


class ExactWorkloadRunner:
    def __init__(
        self,
        *,
        inventory_path: Path,
        gap_path: Path,
        ctdp_out: Path,
        output: Path,
        environment: dict[str, Any],
        samples: int,
        warmups: int,
        force: bool,
    ) -> None:
        self.inventory = read_json(inventory_path, {})
        self.gaps = read_json(gap_path, {})
        self.ctdp_out = ctdp_out
        self.output = output
        self.output.mkdir(parents=True, exist_ok=True)
        self.environment = environment
        self.environment_id = str(environment["measurement_environment_id"])
        self.samples = samples
        self.warmups = warmups
        self.force = force
        self.run_id = f"exact:{uuid.uuid4().hex}"
        self.observations_path = output / "object_observations.jsonl"
        self.status_path = output / "object_status.json"
        self.progress_path = output / "progress.json"
        self.objects = {str(item["object_id"]): item for item in self.inventory.get("objects", [])}
        prior_status_document = read_json(self.status_path, {})
        prior_statuses = prior_status_document.get("objects", {})
        if prior_statuses:
            self.targets = [self.objects[object_id] for object_id in prior_statuses if object_id in self.objects]
        else:
            self.targets = [item for item in self.gaps.get("objects", []) if item.get("status") != "measured"]
        self.statuses = prior_statuses if not force else {}
        observations = read_jsonl(self.observations_path) if not force else []
        self.completed = {str(item.get("observation_key")) for item in observations if item.get("success")}
        self.ctdp_inventory = read_json(ctdp_out / "inventory.json", {})
        self.resolution = read_json(ctdp_out / "resolution.json", {})
        self.profile_by_id = {str(item["profile_id"]): item for item in self.ctdp_inventory.get("profiles", [])}
        self.record_by_root = {
            (str(item.get("profile_id")), str(item.get("dependency_root"))): item
            for item in self.resolution.get("profiles", [])
        }
        self.artifacts_by_url, self.artifacts_by_package = _artifact_maps(ctdp_out)
        self.tool_cache: dict[tuple[str, str, str], list[str] | None] = {}
        self.native_by_root: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for item in self.objects.values():
            if item.get("resource_kind") == "native_binary_bundle":
                safe_id = _safe_profile_id(item)
                root = str(item.get("dimensions", {}).get("dependency_root") or ".")
                if safe_id:
                    self.native_by_root[(safe_id, root)].append(item)
        self.network = _network_probe()
        write_json(output / "measurement_environment.json", environment)
        write_json(output / "action_registry.json", EXACT_ACTIONS)
        write_json(output / "capabilities.json", {"source_download": self.network, "docker": shutil.which("docker"), "mount": shutil.which("mount")})

    def _set_status(self, item: dict[str, Any], status: str, reason: str, **evidence: Any) -> None:
        self.statuses[str(item["object_id"])] = {
            "object_id": item["object_id"],
            "resource_kind": item["resource_kind"],
            "status": status,
            "reason": reason,
            "measurement_environment_id": self.environment_id,
            "evidence": evidence,
        }
        counts = Counter(value["status"] for value in self.statuses.values())
        write_json(
            self.status_path,
            {
                "schema_version": 1,
                "target_count": len(self.targets),
                "accounted_count": len(self.statuses),
                "status_counts": dict(sorted(counts.items())),
                "objects": self.statuses,
            },
        )

    def _record(self, observation: dict[str, Any]) -> None:
        key = str(observation["observation_key"])
        if not self.force and key in self.completed:
            return
        append_jsonl(self.observations_path, observation)
        if observation.get("success"):
            self.completed.add(key)

    def _source_block(self, item: dict[str, Any]) -> None:
        reason = "exact commit source checkout is unavailable"
        if self.network.get("attempted") and not self.network.get("available"):
            reason += f"; download failed: {self.network.get('error') or 'network unavailable'}"
        self._set_status(
            item,
            "blocked",
            reason,
            download_attempted=self.network.get("attempted"),
            source_snapshot_scope="dependency manifests and lockfiles only",
        )

    def _static_status(self, item: dict[str, Any]) -> bool:
        kind = str(item["resource_kind"])
        if kind in SOURCE_REQUIRED_KINDS:
            self._source_block(item)
            return True
        if kind == "rootfs":
            self._set_status(item, "blocked", "Docker/container runtime and rootfs mount capability are unavailable", docker=shutil.which("docker"), image=item.get("name"))
            return True
        if kind == "node_runtime":
            self._set_status(item, "manual_review", "profile metadata does not identify an exact Node version or ABI", version=item.get("version"))
            return True
        return False

    def _dependency_inputs(self, item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str, str] | tuple[None, str]:
        profile_ids = item.get("profile_ids") or []
        if len(profile_ids) != 1:
            return None, "dependency object does not map to exactly one RepoProfile"
        profile_id = str(profile_ids[0])
        profile = self.profile_by_id.get(profile_id)
        root_name = str(item.get("dimensions", {}).get("dependency_root") or ".")
        record = self.record_by_root.get((profile_id, root_name))
        if profile is None or record is None:
            return None, "CTDP profile/root resolution evidence is unavailable"
        if record.get("classification") == "unsupported_or_manual_review":
            return None, "CTDP classified this dependency root as unsupported_or_manual_review"
        expected_hash = str(item.get("dimensions", {}).get("lock_hash") or "")
        actual_hash = str(record.get("resolved_lockfile_sha256") or record.get("source_lockfile_sha256") or "")
        if not expected_hash or expected_hash != actual_hash:
            return None, f"target lock hash {expected_hash or 'missing'} does not match available CTDP snapshot {actual_hash or 'missing'}"
        expected_abi = str(item.get("dimensions", {}).get("node_abi") or "unknown")
        current_abi = subprocess.run(["node", "-p", "process.versions.modules"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30).stdout.strip()
        if expected_abi != current_abi:
            return None, f"required Node ABI {expected_abi} is unavailable; current host provides ABI {current_abi}"
        return profile, record, profile_id, root_name

    def _materialize_once(self, item: dict[str, Any], profile: dict[str, Any], record: dict[str, Any], root_name: str, sample_index: int, measured: bool) -> tuple[bool, str | None]:
        dimensions = item.get("dimensions", {})
        manager = str(dimensions.get("manager") or record.get("package_manager") or "")
        variant = str(dimensions.get("variant") or ("classic" if manager == "yarn" else "default"))
        version = str(dimensions.get("manager_version") or record.get("tool_version") or "")
        tool = _tool_command(manager, version, variant, self.tool_cache)
        if tool is None:
            return False, f"exact package manager {manager} {version} ({variant}) is unavailable in installed tools and offline npx cache"
        temporary = Path(tempfile.mkdtemp(prefix="nodelite-exact-dep-", dir="/tmp"))
        started = time.perf_counter_ns()
        try:
            lock_path = _copy_dependency_snapshot(self.ctdp_out, str(profile["safe_profile_id"]), root_name, record, temporary)
            root = temporary if root_name == "." else temporary / root_name
            if sha256_file(lock_path) != str(dimensions.get("lock_hash")):
                return False, "copied lockfile failed exact hash verification"
            if manager == "npm":
                link_root = root / ".nodelite-cas"
                link_root.mkdir(parents=True, exist_ok=True)
                missing = _rewrite_npm_lock(lock_path, link_root, self.artifacts_by_url, self.artifacts_by_package)
                if missing:
                    example = missing[0]
                    return False, f"CTDP CAS lacks {len(missing)} lockfile artifacts; first missing={example}"
            elif manager == "yarn" and variant == "classic":
                link_root = root / ".nodelite-cas"
                link_root.mkdir(parents=True, exist_ok=True)
                missing_urls = _rewrite_text_lock(lock_path, link_root, self.artifacts_by_url)
                if missing_urls:
                    return False, f"CTDP CAS lacks {len(missing_urls)} Yarn lock URLs; first missing={missing_urls[0]}"
            cache_kind = f"yarn-{variant}" if manager == "yarn" else manager
            cache_root = self.ctdp_out / "native-cache" / cache_kind / version
            command, environment = _install_command(manager, variant, tool, lock_path, cache_root)
            try:
                result = subprocess.run(
                    command,
                    cwd=root,
                    env=environment,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=180,
                )
                timed_out = False
            except subprocess.TimeoutExpired as exc:
                result = subprocess.CompletedProcess(command, 124, exc.stdout or "", exc.stderr or "")
                timed_out = True
            materialize_ms = (time.perf_counter_ns() - started) / 1_000_000
            modules = root / "node_modules"
            success = result.returncode == 0 and modules.is_dir()
            details = {
                "command": command,
                "exit_code": result.returncode,
                "timed_out": timed_out,
                "manager": manager,
                "manager_version": version,
                "lock_hash": dimensions.get("lock_hash"),
                "files_created": sum(1 for _ in modules.iterdir()) if modules.is_dir() else 0,
                "stdout_tail": str(result.stdout)[-2000:],
                "stderr_tail": str(result.stderr)[-2000:],
            }
            if measured:
                self._record(
                    _observation(
                        environment_id=self.environment_id,
                        run_id=self.run_id,
                        benchmark_id="EXACT-DEP-MATERIALIZE",
                        item=item,
                        sample_index=sample_index,
                        wall_ms=materialize_ms,
                        success=success,
                        transition_class="artifact_cold",
                        scenario_name="ctdp-cas-offline-install",
                        from_object_id=None,
                        details=details,
                        error=None if success else details["stderr_tail"] or details["stdout_tail"] or f"exit {result.returncode}",
                        invalidates=["build_cache", "test_transform_cache"],
                    )
                )
            if not success:
                return False, details["stderr_tail"] or details["stdout_tail"] or f"package manager exited {result.returncode}"

            attach_started = time.perf_counter_ns()
            entries = sum(1 for _ in modules.iterdir())
            package_json_present = (root / "package.json").is_file()
            attach_ms = (time.perf_counter_ns() - attach_started) / 1_000_000
            marker = root / ".nodelite-exact-dirty"
            marker.write_text("dirty\n", encoding="utf-8")
            reset_started = time.perf_counter_ns()
            marker.unlink()
            clean = not marker.exists()
            reset_ms = (time.perf_counter_ns() - reset_started) / 1_000_000
            if measured:
                self._record(
                    _observation(
                        environment_id=self.environment_id,
                        run_id=self.run_id,
                        benchmark_id="EXACT-DEP-ATTACH",
                        item=item,
                        sample_index=sample_index,
                        wall_ms=attach_ms,
                        success=package_json_present and entries > 0,
                        transition_class="exact_hit",
                        scenario_name="node-modules-readiness",
                        from_object_id=str(item["object_id"]),
                        details={"top_level_entries": entries, "package_json_present": package_json_present},
                    )
                )
                self._record(
                    _observation(
                        environment_id=self.environment_id,
                        run_id=self.run_id,
                        benchmark_id="EXACT-DEP-RESET",
                        item=item,
                        sample_index=sample_index,
                        wall_ms=reset_ms,
                        success=clean,
                        transition_class="dirty_reset",
                        scenario_name="task-marker-discard",
                        from_object_id=str(item["object_id"]),
                        details={"pollution_check": "pass" if clean else "fail"},
                    )
                )
                self._measure_native(root, str(profile["safe_profile_id"]), root_name, sample_index)
            return True, None
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return False, f"{type(exc).__name__}: {exc}"
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def _measure_native(self, root: Path, safe_id: str, root_name: str, sample_index: int) -> None:
        for item in self.native_by_root.get((safe_id, root_name), []):
            package = str(item.get("dimensions", {}).get("package") or item.get("name"))
            started = time.perf_counter_ns()
            result = subprocess.run(
                ["node", "-e", "const p=process.argv[1]; require.resolve(p); require(p)", package],
                cwd=root,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            wall_ms = (time.perf_counter_ns() - started) / 1_000_000
            success = result.returncode == 0
            self._record(
                _observation(
                    environment_id=self.environment_id,
                    run_id=self.run_id,
                    benchmark_id="EXACT-NATIVE-LOAD",
                    item=item,
                    sample_index=sample_index,
                    wall_ms=wall_ms,
                    success=success,
                    transition_class="artifact_cold",
                    scenario_name="resolve-and-require",
                    from_object_id=None,
                    details={"package": package, "exit_code": result.returncode, "stderr_tail": result.stderr[-2000:]},
                    error=None if success else result.stderr[-2000:] or f"exit {result.returncode}",
                )
            )

    def _run_dependency(self, item: dict[str, Any]) -> None:
        inputs = self._dependency_inputs(item)
        if inputs[0] is None:
            self._set_status(item, "manual_review" if "lock hash" in inputs[1] or "manual_review" in inputs[1] else "blocked", inputs[1])
            return
        profile, record, _profile_id, root_name = inputs
        for _ in range(self.warmups):
            success, reason = self._materialize_once(item, profile, record, root_name, -1, False)
            if not success:
                self._set_status(item, "blocked", "exact dependency view materialization probe failed", error=reason)
                return
        failures: list[str] = []
        for sample_index in range(self.samples):
            success, reason = self._materialize_once(item, profile, record, root_name, sample_index, True)
            if not success:
                failures.append(reason or "unknown failure")
        materialize_keys = {
            "|".join([self.environment_id, "EXACT-DEP-MATERIALIZE", "ctdp-cas-offline-install", "cold", str(item["object_id"]), "artifact_cold", str(index)])
            for index in range(self.samples)
        }
        complete = materialize_keys.issubset(self.completed)
        if complete:
            self._set_status(item, "measured", f"exact CTDP-CAS offline materialization completed with {self.samples}/{self.samples} successful samples", sample_count=self.samples)
        else:
            self._set_status(item, "failed", f"exact materialization did not complete {self.samples} successful samples", failures=failures)

    def _finalize_native_statuses(self) -> None:
        observations = read_jsonl(self.observations_path)
        successful: Counter[str] = Counter(
            str(item.get("to_object_id"))
            for item in observations
            if item.get("benchmark_id") == "EXACT-NATIVE-LOAD" and item.get("success") and item.get("measurement_environment_id") == self.environment_id
        )
        for target in self.targets:
            if target.get("resource_kind") != "native_binary_bundle":
                continue
            item = self.objects.get(str(target["object_id"]), target)
            count = successful[str(item["object_id"])]
            if count >= self.samples:
                self._set_status(item, "measured", f"exact native package resolved and loaded in {self.samples}/{self.samples} samples", sample_count=self.samples)
            elif str(item["object_id"]) not in self.statuses:
                expected_abi = item.get("dimensions", {}).get("node_abi")
                self._set_status(item, "blocked", "exact dependency view or required Node ABI was unavailable, so native load/rebuild could not run", required_node_abi=expected_abi, successful_samples=count)

    def _write_reports(self) -> dict[str, Any]:
        observations = read_jsonl(self.observations_path)
        latest = {str(item.get("observation_key")): item for item in observations if item.get("observation_key")}
        active = list(latest.values())
        summaries = build_summaries(active, self.objects)
        csv_rows = []
        for item in summaries:
            row = dict(item)
            row["invalidation_targets"] = ";".join(item.get("invalidation_targets", []))
            csv_rows.append(row)
        write_csv(self.output / "object_action_summary.csv", SUMMARY_FIELDS, csv_rows)
        direct = build_direct_ms(summaries, list(self.objects.values()), self.environment)
        write_json(self.output / "direct_ms.json", direct)
        counts = Counter(value["status"] for value in self.statuses.values())
        by_kind: dict[str, Counter[str]] = defaultdict(Counter)
        for value in self.statuses.values():
            by_kind[str(value["resource_kind"])][str(value["status"])] += 1
        summary = {
            "schema_version": 1,
            "measurement_environment_id": self.environment_id,
            "target_count": len(self.targets),
            "accounted_count": len(self.statuses),
            "status_counts": dict(sorted(counts.items())),
            "status_counts_by_resource_kind": {kind: dict(sorted(values.items())) for kind, values in sorted(by_kind.items())},
            "observation_count": len(active),
            "transition_summary_count": len(summaries),
            "direct_ms_object_count": direct.get("measured_object_count", 0),
            "samples": self.samples,
            "warmups": self.warmups,
        }
        write_json(self.output / "summary.json", summary)
        return summary

    def run(self) -> dict[str, Any]:
        for position, target in enumerate(self.targets, start=1):
            item = self.objects.get(str(target["object_id"]), target)
            object_id = str(item["object_id"])
            if not self.force and object_id in self.statuses:
                print(f"[{position}/{len(self.targets)}] skip {object_id}: {self.statuses[object_id]['status']}", flush=True)
                continue
            print(f"[{position}/{len(self.targets)}] {object_id}", flush=True)
            if self._static_status(item):
                write_json(self.progress_path, {"completed": len(self.statuses), "total": len(self.targets), "current_object_id": object_id})
                continue
            if item.get("resource_kind") == "dependency_view":
                self._run_dependency(item)
            elif item.get("resource_kind") == "native_binary_bundle":
                write_json(self.progress_path, {"completed": len(self.statuses), "total": len(self.targets), "current_object_id": object_id})
                continue
            else:
                self._set_status(item, "unsupported", "no exact workload runner is defined for this resource kind")
            write_json(self.progress_path, {"completed": len(self.statuses), "total": len(self.targets), "current_object_id": object_id})
        self._finalize_native_statuses()
        for target in self.targets:
            object_id = str(target["object_id"])
            if object_id not in self.statuses:
                item = self.objects.get(object_id, target)
                self._set_status(item, "blocked", "prerequisite exact dependency view was unavailable")
        write_json(self.progress_path, {"completed": len(self.targets), "total": len(self.targets), "current_object_id": None})
        return self._write_reports()


def run_exact_workload(
    *,
    inventory_path: Path,
    gap_path: Path,
    ctdp_out: Path,
    output: Path,
    environment: dict[str, Any],
    samples: int,
    warmups: int,
    force: bool,
) -> dict[str, Any]:
    return ExactWorkloadRunner(
        inventory_path=inventory_path,
        gap_path=gap_path,
        ctdp_out=ctdp_out,
        output=output,
        environment=environment,
        samples=samples,
        warmups=warmups,
        force=force,
    ).run()
