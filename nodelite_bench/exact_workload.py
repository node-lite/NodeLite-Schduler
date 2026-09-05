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
    {
        "benchmark_id": "EXACT-REPO-MATERIALIZE",
        "resource_kind": "repo_baseline",
        "transition_class": "artifact_cold",
        "description": "Materialize an exact Git commit from a locally prepared source archive",
    },
    {
        "benchmark_id": "EXACT-REPO-ATTACH",
        "resource_kind": "repo_baseline",
        "transition_class": "exact_hit",
        "description": "Verify an exact materialized Git commit source tree",
    },
    {
        "benchmark_id": "EXACT-SOURCE-MATERIALIZE",
        "resource_kind": "source_overlay",
        "transition_class": "artifact_cold",
        "description": "Create a writable exact source view from the repository baseline",
    },
    {
        "benchmark_id": "EXACT-SOURCE-RESET",
        "resource_kind": "source_overlay",
        "transition_class": "dirty_reset",
        "description": "Discard a task-local source mutation without polluting the baseline",
    },
    {
        "benchmark_id": "EXACT-BUILD-CACHE-COLD",
        "resource_kind": "build_cache",
        "transition_class": "artifact_cold",
        "description": "Run an exact project build command after clearing its project cache paths",
    },
    {
        "benchmark_id": "EXACT-BUILD-CACHE-HIT",
        "resource_kind": "build_cache",
        "transition_class": "exact_hit",
        "description": "Repeat the exact project build command against its warm cache",
    },
    {
        "benchmark_id": "EXACT-TEST-CACHE-COLD",
        "resource_kind": "test_transform_cache",
        "transition_class": "artifact_cold",
        "description": "Run an exact project test command after clearing its project cache paths",
    },
    {
        "benchmark_id": "EXACT-TEST-CACHE-HIT",
        "resource_kind": "test_transform_cache",
        "transition_class": "exact_hit",
        "description": "Repeat the exact project test command against its warm cache",
    },
    {
        "benchmark_id": "EXACT-ROOTFS-CREATE",
        "resource_kind": "rootfs",
        "transition_class": "artifact_cold",
        "description": "Create a stopped container from an exact pulled rootfs image",
    },
    {
        "benchmark_id": "EXACT-ROOTFS-ATTACH",
        "resource_kind": "rootfs",
        "transition_class": "exact_hit",
        "description": "Inspect an already created exact rootfs container",
    },
    {
        "benchmark_id": "EXACT-ROOTFS-RESET",
        "resource_kind": "rootfs",
        "transition_class": "dirty_reset",
        "description": "Remove a task-local exact rootfs container",
    },
]

SOURCE_REQUIRED_KINDS = {"repo_baseline", "source_overlay", "build_cache", "test_transform_cache"}
SOURCE_KIND_ORDER = {"repo_baseline": 0, "source_overlay": 1, "build_cache": 2, "test_transform_cache": 3}
TOOLCHAIN_ROOT = Path.home() / ".local" / "share" / "nodelite" / "toolchains"
NODE_BY_ABI = {
    "109": ("18.19.1", Path(shutil.which("node") or "node")),
    "115": ("20.19.1", TOOLCHAIN_ROOT / "node-v20.19.1-linux-x64" / "bin" / "node"),
    "127": ("22.23.2", TOOLCHAIN_ROOT / "node-v22.23.2-linux-x64" / "bin" / "node"),
}


def _root_slug(root: str) -> str:
    return "root" if root == "." else root.replace("/", "__")


def _safe_profile_id(item: dict[str, Any]) -> str | None:
    profiles = item.get("profile_ids") or []
    if not profiles:
        return None
    return str(profiles[0]).removeprefix("swesmith/")


def _profile_sort_key(item: dict[str, Any]) -> tuple[str, int, str]:
    return (_safe_profile_id(item) or "~", SOURCE_KIND_ORDER.get(str(item.get("resource_kind")), 10), str(item.get("object_id")))


def _node_for_abi(abi: str) -> tuple[Path, str] | None:
    details = NODE_BY_ABI.get(abi)
    if details is None:
        return None
    version, executable = details
    if not executable.is_file() and shutil.which(str(executable)) is None:
        return None
    try:
        result = subprocess.run(
            [str(executable), "-p", "process.version+' '+process.versions.modules"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0 or result.stdout.strip() != f"v{version} {abi}":
        return None
    return executable, version


def _version_matches(actual: str, expected: str) -> bool:
    def parts(value: str) -> tuple[int, ...]:
        match = re.search(r"(?:^|\s)v?(\d+(?:\.\d+){0,3})", value)
        return tuple(int(part) for part in match.group(1).split(".")) if match else ()

    actual_parts = parts(actual)
    expected_parts = parts(expected)
    return bool(actual_parts and expected_parts and actual_parts[: len(expected_parts)] == expected_parts)


def _cached_npx_tool(manager: str, version: str) -> list[str] | None:
    cache_root = Path.home() / ".npm" / "_npx"
    candidates = list(cache_root.glob(f"*/node_modules/.bin/{manager}")) if cache_root.is_dir() else []
    candidates.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    for candidate in candidates:
        try:
            result = subprocess.run(
                [str(candidate), "--version"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if result.returncode == 0 and _version_matches(result.stdout.strip(), version):
            return [str(candidate)]
    return None


def _tool_command(manager: str, version: str, variant: str, cache: dict[tuple[str, str, str], list[str] | None]) -> list[str] | None:
    key = manager, variant, version
    if key in cache:
        return cache[key]
    installed = shutil.which(manager)
    candidates: list[list[str]] = []
    if installed:
        candidates.append([installed])
    cached = _cached_npx_tool(manager, version)
    if cached:
        candidates.append(cached)
    package = f"@yarnpkg/cli-dist@{version}" if manager == "yarn" and variant == "berry" else f"{manager}@{version}"
    candidates.append(["npx", "--offline", "--yes", "--package", package, manager])
    candidates.append(["npx", "--yes", "--package", package, manager])
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
            resolved = _cached_npx_tool(manager, version) if candidate[0] == "npx" else candidate
            cache[key] = resolved or candidate
            return cache[key]
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
            by_url[source] = path
            by_url[source.split("#", 1)[0]] = path
            github = re.match(r"git\+(?:https://|ssh://git@)github\.com/([^/]+)/([^#]+?)(?:\.git)?#([0-9a-f]{7,40})$", source)
            if github:
                owner, repo, commit = github.groups()
                repo = repo.removesuffix(".git")
                by_url[f"https://codeload.github.com/{owner}/{repo}/tar.gz/{commit}"] = path
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
    local_by_name: dict[str, str] = {}
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
                local = local_uri(artifact)
                entry["resolved"] = local
                if isinstance(name, str):
                    local_by_name[name] = local
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

    def rewrite_specs(document: dict[str, Any]) -> None:
        for field in ("dependencies", "devDependencies", "optionalDependencies"):
            values = document.get(field)
            if not isinstance(values, dict):
                continue
            for name, specifier in list(values.items()):
                if name in local_by_name and isinstance(specifier, str) and specifier.startswith(("git+", "http://", "https://")):
                    values[name] = local_by_name[name]

    root_package = packages.get("") if isinstance(packages, dict) else None
    if isinstance(root_package, dict):
        rewrite_specs(root_package)
    manifest_path = lock_path.parent / "package.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        rewrite_specs(manifest)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
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
        retry_failed: bool,
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
        self.retry_failed = retry_failed
        self.run_id = f"exact:{uuid.uuid4().hex}"
        self.observations_path = output / "object_observations.jsonl"
        self.status_path = output / "object_status.json"
        self.progress_path = output / "progress.json"
        self.objects = {str(item["object_id"]): item for item in self.inventory.get("objects", [])}
        prior_status_document = read_json(self.status_path, {})
        prior_statuses = prior_status_document.get("objects", {})
        gap_targets = [
            item
            for item in self.gaps.get("objects", [])
            if item.get("status") != "measured" or item.get("measurement_environment_id") == self.environment_id
        ]
        self.targets = gap_targets or [self.objects[object_id] for object_id in prior_statuses if object_id in self.objects]
        self.targets.sort(key=_profile_sort_key)
        self.statuses = dict(prior_statuses) if not force else {}
        if retry_failed and not force:
            self.statuses = {
                object_id: value
                for object_id, value in self.statuses.items()
                if value.get("status") not in {"blocked", "failed", "unsupported"}
            }
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
        self.source_state: dict[str, Any] | None = None
        self.docker = shutil.which("docker")
        self.node_runtimes = {
            abi: {"path": str(details[0]), "version": details[1]}
            for abi in NODE_BY_ABI
            if (details := _node_for_abi(abi)) is not None
        }
        write_json(output / "measurement_environment.json", environment)
        write_json(output / "action_registry.json", EXACT_ACTIONS)
        write_json(
            output / "capabilities.json",
            {"source_download": self.network, "docker": self.docker, "mount": shutil.which("mount"), "node_runtimes": self.node_runtimes},
        )

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

    def _static_status(self, item: dict[str, Any]) -> bool:
        kind = str(item["resource_kind"])
        if kind in SOURCE_REQUIRED_KINDS and not self.network.get("available"):
            self._set_status(
                item,
                "blocked",
                "exact commit source download is unavailable",
                download_attempted=self.network.get("attempted"),
                error=self.network.get("error"),
            )
            return True
        if kind == "rootfs" and not self.docker:
            self._set_status(item, "blocked", "Docker executable is unavailable", docker=self.docker, image=item.get("name"))
            return True
        if kind == "node_runtime":
            self._set_status(item, "manual_review", "profile metadata does not identify an exact Node version or ABI", version=item.get("version"))
            return True
        return False

    def _dependency_inputs(self, item: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], str, str, Path, str] | tuple[None, str]:
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
        runtime = _node_for_abi(expected_abi)
        if runtime is None:
            return None, f"required exact Node ABI {expected_abi} is unavailable"
        node_executable, node_version = runtime
        return profile, record, profile_id, root_name, node_executable, node_version

    def _apply_manifest_edits(self, record: dict[str, Any], root: Path) -> str | None:
        for edit in record.get("manifest_edits_applied", []):
            command = str(edit.get("command") or "").strip()
            if not command:
                continue
            try:
                result = subprocess.run(
                    ["sh", "-c", command],
                    cwd=root,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                return f"manifest edit {type(exc).__name__}: {exc}"
            if result.returncode != 0:
                return result.stderr[-2000:] or result.stdout[-2000:] or f"manifest edit exited {result.returncode}: {command}"
        return None

    def _materialize_once(
        self,
        item: dict[str, Any],
        profile: dict[str, Any],
        record: dict[str, Any],
        root_name: str,
        node_executable: Path,
        node_version: str,
        sample_index: int,
        measured: bool,
    ) -> tuple[bool, str | None]:
        dimensions = item.get("dimensions", {})
        manager = str(dimensions.get("manager") or record.get("package_manager") or "")
        variant = str(dimensions.get("variant") or ("classic" if manager == "yarn" else "default"))
        version = str(dimensions.get("manager_version") or record.get("tool_version") or "")
        tool = _tool_command(manager, version, variant, self.tool_cache)
        if tool is None:
            return False, f"exact package manager {manager} {version} ({variant}) is unavailable after installed, offline, and online probes"
        temporary = Path(tempfile.mkdtemp(prefix="nodelite-exact-dep-", dir="/tmp"))
        try:
            source_state, source_error = self._ensure_source_state(item)
            if source_state is None:
                return False, f"exact source preparation failed: {source_error}"
            source_success, _source_ms, source_extract_error = self._extract_source(source_state, temporary)
            if not source_success:
                return False, f"exact source extraction failed: {source_extract_error}"
            lock_path = _copy_dependency_snapshot(self.ctdp_out, str(profile["safe_profile_id"]), root_name, record, temporary)
            root = temporary if root_name == "." else temporary / root_name
            edit_error = self._apply_manifest_edits(record, root)
            if edit_error:
                return False, edit_error
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
            environment["PATH"] = f"{node_executable.parent}{os.pathsep}{environment.get('PATH', '')}"
            started = time.perf_counter_ns()
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
                "node_executable": str(node_executable),
                "node_version": node_version,
                "node_abi": dimensions.get("node_abi"),
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
                self._measure_native(root, str(profile["safe_profile_id"]), root_name, node_executable, node_version, sample_index)
            return True, None
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return False, f"{type(exc).__name__}: {exc}"
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def _measure_native(self, root: Path, safe_id: str, root_name: str, node_executable: Path, node_version: str, sample_index: int) -> None:
        for item in self.native_by_root.get((safe_id, root_name), []):
            package = str(item.get("dimensions", {}).get("package") or item.get("name"))
            started = time.perf_counter_ns()
            result = subprocess.run(
                [str(node_executable), "-e", "const p=process.argv[1]; require.resolve(p); require(p)", package],
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
                    details={"package": package, "exit_code": result.returncode, "node_version": node_version, "stderr_tail": result.stderr[-2000:]},
                    error=None if success else result.stderr[-2000:] or f"exit {result.returncode}",
                )
            )

    def _run_dependency(self, item: dict[str, Any]) -> None:
        inputs = self._dependency_inputs(item)
        if inputs[0] is None:
            self._set_status(item, "manual_review" if "lock hash" in inputs[1] or "manual_review" in inputs[1] else "blocked", inputs[1])
            return
        profile, record, _profile_id, root_name, node_executable, node_version = inputs
        for _ in range(self.warmups):
            success, reason = self._materialize_once(item, profile, record, root_name, node_executable, node_version, -1, False)
            if not success:
                self._set_status(item, "blocked", "exact dependency view materialization probe failed", error=reason)
                return
        failures: list[str] = []
        for sample_index in range(self.samples):
            success, reason = self._materialize_once(item, profile, record, root_name, node_executable, node_version, sample_index, True)
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

    def _cleanup_source_state(self) -> None:
        if self.source_state is None:
            return
        shutil.rmtree(Path(self.source_state["temporary"]), ignore_errors=True)
        self.source_state = None

    def _ensure_source_state(self, item: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        safe_id = _safe_profile_id(item)
        if safe_id is None:
            return None, "source object does not map to a RepoProfile"
        if self.source_state and self.source_state.get("safe_profile_id") == safe_id:
            return self.source_state, None
        self._cleanup_source_state()
        profile = self.profile_by_id.get(f"swesmith/{safe_id}")
        if profile is None:
            return None, f"CTDP profile metadata is unavailable for {safe_id}"
        owner = str(profile.get("owner") or "")
        repo = str(profile.get("repo") or "")
        commit = str(profile.get("commit") or "")
        if not owner or not repo or not re.fullmatch(r"[0-9a-f]{40}", commit):
            return None, "profile does not contain an exact GitHub owner/repo/commit"
        temporary = Path(tempfile.mkdtemp(prefix=f"nodelite-source-{safe_id[:24]}-", dir="/tmp"))
        checkout = temporary / "checkout"
        archive = temporary / "source.tar"
        checkout.mkdir()
        commands = [
            ["git", "-C", str(checkout), "init", "--quiet"],
            ["git", "-C", str(checkout), "remote", "add", "origin", f"https://github.com/{owner}/{repo}.git"],
            ["git", "-C", str(checkout), "fetch", "--depth=1", "origin", commit],
            ["git", "-C", str(checkout), "checkout", "--quiet", "--detach", "FETCH_HEAD"],
            ["git", "-C", str(checkout), "archive", "--format=tar", f"--output={archive}", "HEAD"],
        ]
        started = time.perf_counter_ns()
        for command in commands:
            try:
                result = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=300)
            except (OSError, subprocess.TimeoutExpired) as exc:
                self._cleanup_source_state()
                shutil.rmtree(temporary, ignore_errors=True)
                return None, f"{type(exc).__name__}: {exc}"
            if result.returncode != 0:
                shutil.rmtree(temporary, ignore_errors=True)
                return None, result.stderr[-2000:] or result.stdout[-2000:] or f"source command exited {result.returncode}"
        actual_commit = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        ).stdout.strip()
        if actual_commit != commit:
            shutil.rmtree(temporary, ignore_errors=True)
            return None, f"downloaded commit {actual_commit or 'missing'} does not match {commit}"
        source_state = {
            "safe_profile_id": safe_id,
            "profile": profile,
            "temporary": temporary,
            "checkout": checkout,
            "archive": archive,
            "archive_sha256": sha256_file(archive),
            "download_ms": round((time.perf_counter_ns() - started) / 1_000_000, 6),
            "commit": commit,
            "tree": subprocess.run(
                ["git", "-C", str(checkout), "rev-parse", "HEAD^{tree}"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            ).stdout.strip(),
            "baseline": None,
            "workspaces": {},
        }
        self.source_state = source_state
        return source_state, None

    def _extract_source(self, state: dict[str, Any], destination: Path) -> tuple[bool, float, str | None]:
        destination.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter_ns()
        try:
            result = subprocess.run(
                ["tar", "-xf", str(state["archive"]), "-C", str(destination)],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, (time.perf_counter_ns() - started) / 1_000_000, f"{type(exc).__name__}: {exc}"
        wall_ms = (time.perf_counter_ns() - started) / 1_000_000
        return result.returncode == 0, wall_ms, result.stderr[-2000:] or None

    def _baseline_directory(self, state: dict[str, Any]) -> tuple[Path | None, str | None]:
        existing = state.get("baseline")
        if existing and Path(existing).is_dir():
            return Path(existing), None
        baseline = Path(state["temporary"]) / "baseline"
        success, _wall_ms, error = self._extract_source(state, baseline)
        if not success:
            shutil.rmtree(baseline, ignore_errors=True)
            return None, error
        state["baseline"] = baseline
        return baseline, None

    def _run_repo_baseline(self, item: dict[str, Any]) -> None:
        state, error = self._ensure_source_state(item)
        if state is None:
            self._set_status(item, "blocked", "exact Git commit acquisition failed", error=error)
            return
        failures: list[str] = []
        total = self.warmups + self.samples
        for iteration in range(total):
            destination = Path(state["temporary"]) / f"repo-sample-{iteration}"
            success, wall_ms, extract_error = self._extract_source(state, destination)
            package_json_present = (destination / "package.json").is_file()
            if iteration >= self.warmups:
                sample_index = iteration - self.warmups
                details = {
                    "commit": state["commit"],
                    "tree": state["tree"],
                    "archive_sha256": state["archive_sha256"],
                    "archive_bytes": Path(state["archive"]).stat().st_size,
                    "download_ms_preparation": state["download_ms"],
                    "package_json_present": package_json_present,
                }
                self._record(_observation(
                    environment_id=self.environment_id,
                    run_id=self.run_id,
                    benchmark_id="EXACT-REPO-MATERIALIZE",
                    item=item,
                    sample_index=sample_index,
                    wall_ms=wall_ms,
                    success=success,
                    transition_class="artifact_cold",
                    scenario_name="git-archive-materialize",
                    from_object_id=None,
                    details=details,
                    error=extract_error,
                    invalidates=["source_overlay", "build_cache", "test_transform_cache"],
                ))
                attach_started = time.perf_counter_ns()
                attached = destination.is_dir() and any(destination.iterdir())
                attach_ms = (time.perf_counter_ns() - attach_started) / 1_000_000
                self._record(_observation(
                    environment_id=self.environment_id,
                    run_id=self.run_id,
                    benchmark_id="EXACT-REPO-ATTACH",
                    item=item,
                    sample_index=sample_index,
                    wall_ms=attach_ms,
                    success=attached,
                    transition_class="exact_hit",
                    scenario_name="source-tree-readiness",
                    from_object_id=str(item["object_id"]),
                    details={"commit": state["commit"], "tree": state["tree"]},
                ))
            if not success:
                failures.append(extract_error or "archive extraction failed")
            shutil.rmtree(destination, ignore_errors=True)
        successful = self._successful_sample_count(str(item["object_id"]), "EXACT-REPO-MATERIALIZE")
        if successful >= self.samples:
            self._set_status(item, "measured", f"exact Git commit baseline materialized in {self.samples}/{self.samples} samples", sample_count=self.samples, commit=state["commit"], tree=state["tree"])
        else:
            self._set_status(item, "failed", "exact Git commit baseline measurement was incomplete", successful_samples=successful, failures=failures)

    def _run_source_overlay(self, item: dict[str, Any]) -> None:
        state, error = self._ensure_source_state(item)
        if state is None:
            self._set_status(item, "blocked", "exact Git commit acquisition failed", error=error)
            return
        baseline, error = self._baseline_directory(state)
        if baseline is None:
            self._set_status(item, "blocked", "exact repository baseline extraction failed", error=error)
            return
        root_name = str(item.get("dimensions", {}).get("dependency_root") or ".")
        root_exists = baseline.is_dir() if root_name == "." else (baseline / root_name).is_dir()
        if not root_exists:
            self._set_status(item, "manual_review", "dependency root is absent from the exact source checkout", dependency_root=root_name)
            return
        failures: list[str] = []
        for iteration in range(self.warmups + self.samples):
            destination = Path(state["temporary"]) / f"overlay-sample-{iteration}"
            started = time.perf_counter_ns()
            try:
                result = subprocess.run(
                    ["cp", "-a", "--reflink=auto", str(baseline), str(destination)],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=300,
                )
                materialize_ms = (time.perf_counter_ns() - started) / 1_000_000
                success = result.returncode == 0
                copy_error = result.stderr[-2000:] or None
            except (OSError, subprocess.TimeoutExpired) as exc:
                materialize_ms = (time.perf_counter_ns() - started) / 1_000_000
                success = False
                copy_error = f"{type(exc).__name__}: {exc}"
            marker_root = destination if root_name == "." else destination / root_name
            marker = marker_root / ".nodelite-source-dirty"
            if success:
                marker.write_text("dirty\n", encoding="utf-8")
            reset_started = time.perf_counter_ns()
            shutil.rmtree(destination, ignore_errors=True)
            reset_ms = (time.perf_counter_ns() - reset_started) / 1_000_000
            clean = not destination.exists() and not (baseline / ".nodelite-source-dirty").exists()
            if iteration >= self.warmups:
                sample_index = iteration - self.warmups
                self._record(_observation(
                    environment_id=self.environment_id,
                    run_id=self.run_id,
                    benchmark_id="EXACT-SOURCE-MATERIALIZE",
                    item=item,
                    sample_index=sample_index,
                    wall_ms=materialize_ms,
                    success=success,
                    transition_class="artifact_cold",
                    scenario_name="directory-copy-reflink-auto",
                    from_object_id=None,
                    details={"backend": "cp-reflink-auto", "dependency_root": root_name, "commit": state["commit"]},
                    error=copy_error,
                ))
                self._record(_observation(
                    environment_id=self.environment_id,
                    run_id=self.run_id,
                    benchmark_id="EXACT-SOURCE-RESET",
                    item=item,
                    sample_index=sample_index,
                    wall_ms=reset_ms,
                    success=clean,
                    transition_class="dirty_reset",
                    scenario_name="discard-private-source-tree",
                    from_object_id=str(item["object_id"]),
                    details={"pollution_check": "pass" if clean else "fail", "dependency_root": root_name},
                ))
            if not success:
                failures.append(copy_error or "source copy failed")
        successful = self._successful_sample_count(str(item["object_id"]), "EXACT-SOURCE-MATERIALIZE")
        if successful >= self.samples:
            self._set_status(item, "measured", f"exact writable source view materialized and reset in {self.samples}/{self.samples} samples", sample_count=self.samples, commit=state["commit"])
        else:
            self._set_status(item, "failed", "exact source overlay measurement was incomplete", successful_samples=successful, failures=failures)

    def _dependency_item_for_source(self, item: dict[str, Any]) -> dict[str, Any] | None:
        profile_ids = item.get("profile_ids") or []
        if len(profile_ids) != 1:
            return None
        explicit_root = item.get("dimensions", {}).get("dependency_root")
        compatibility_key = str(item.get("compatibility_key") or "")
        for candidate in self.objects.values():
            if candidate.get("resource_kind") != "dependency_view":
                continue
            if candidate.get("profile_ids") != profile_ids:
                continue
            candidate_root = str(candidate.get("dimensions", {}).get("dependency_root") or ".")
            lock_hash = str(candidate.get("dimensions", {}).get("lock_hash") or "")
            if explicit_root is not None and candidate_root == str(explicit_root):
                return candidate
            if explicit_root is None and lock_hash and lock_hash in compatibility_key:
                return candidate
        return None

    def _prepare_project_workspace(self, item: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, bool]:
        state, error = self._ensure_source_state(item)
        if state is None:
            return None, error, False
        dependency_item = self._dependency_item_for_source(item)
        if dependency_item is None:
            return None, "matching exact dependency view is unavailable", False
        root_name = str(dependency_item.get("dimensions", {}).get("dependency_root") or ".")
        existing = state["workspaces"].get(root_name)
        if existing:
            return existing, None, False
        inputs = self._dependency_inputs(dependency_item)
        if inputs[0] is None:
            reason = inputs[1]
            return None, reason, "lock hash" in reason or "manual_review" in reason
        profile, record, _profile_id, dependency_root, node_executable, node_version = inputs
        baseline, error = self._baseline_directory(state)
        if baseline is None:
            return None, error, False
        workspace = Path(state["temporary"]) / f"workspace-{_root_slug(root_name)}"
        if workspace.exists():
            shutil.rmtree(workspace, ignore_errors=True)
        copy = subprocess.run(
            ["cp", "-a", "--reflink=auto", str(baseline), str(workspace)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=300,
        )
        if copy.returncode != 0:
            return None, copy.stderr[-2000:] or f"source workspace copy exited {copy.returncode}", False
        try:
            lock_path = _copy_dependency_snapshot(self.ctdp_out, str(profile["safe_profile_id"]), dependency_root, record, workspace)
        except OSError as exc:
            shutil.rmtree(workspace, ignore_errors=True)
            return None, f"dependency snapshot {type(exc).__name__}: {exc}", False
        root = workspace if dependency_root == "." else workspace / dependency_root
        edit_error = self._apply_manifest_edits(record, root)
        if edit_error:
            return None, edit_error, False
        dimensions = dependency_item.get("dimensions", {})
        manager = str(dimensions.get("manager") or record.get("package_manager") or "")
        variant = str(dimensions.get("variant") or ("classic" if manager == "yarn" else "default"))
        version = str(dimensions.get("manager_version") or record.get("tool_version") or "")
        tool = _tool_command(manager, version, variant, self.tool_cache)
        if tool is None:
            return None, f"exact package manager {manager} {version} ({variant}) is unavailable", False
        if manager == "npm":
            link_root = root / ".nodelite-cas"
            link_root.mkdir(parents=True, exist_ok=True)
            try:
                missing = _rewrite_npm_lock(lock_path, link_root, self.artifacts_by_url, self.artifacts_by_package)
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                shutil.rmtree(workspace, ignore_errors=True)
                return None, f"npm lock rewrite {type(exc).__name__}: {exc}", False
            if missing:
                return None, f"CTDP CAS lacks {len(missing)} lockfile artifacts; first missing={missing[0]}", False
        elif manager == "yarn" and variant == "classic":
            link_root = root / ".nodelite-cas"
            link_root.mkdir(parents=True, exist_ok=True)
            try:
                missing_urls = _rewrite_text_lock(lock_path, link_root, self.artifacts_by_url)
            except OSError as exc:
                shutil.rmtree(workspace, ignore_errors=True)
                return None, f"Yarn lock rewrite {type(exc).__name__}: {exc}", False
            if missing_urls:
                return None, f"CTDP CAS lacks {len(missing_urls)} Yarn lock URLs; first missing={missing_urls[0]}", False
        cache_kind = f"yarn-{variant}" if manager == "yarn" else manager
        cache_root = self.ctdp_out / "native-cache" / cache_kind / version
        install_command, environment = _install_command(manager, variant, tool, lock_path, cache_root)
        environment["PATH"] = f"{node_executable.parent}{os.pathsep}{environment.get('PATH', '')}"
        try:
            install = subprocess.run(
                install_command,
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return None, f"dependency preparation {type(exc).__name__}: {exc}", False
        ready = (root / "node_modules").is_dir() or (root / ".pnp.cjs").is_file()
        if install.returncode != 0 or not ready:
            failure = install.stderr[-2000:] or install.stdout[-2000:] or f"dependency preparation exited {install.returncode}"
            shutil.rmtree(workspace, ignore_errors=True)
            return None, failure, False
        result = {
            "root": root,
            "manager": manager,
            "manager_version": version,
            "tool": tool,
            "environment": environment,
            "node_executable": str(node_executable),
            "node_version": node_version,
            "dependency_object_id": dependency_item["object_id"],
            "lock_hash": dimensions.get("lock_hash"),
        }
        state["workspaces"][root_name] = result
        return result, None, False

    def _select_project_script(self, item: dict[str, Any]) -> tuple[str | None, str | None]:
        dimensions = item.get("dimensions", {})
        scripts = dimensions.get("command_evidence")
        if not isinstance(scripts, dict) or not scripts:
            return None, "package manifest contains no scripts"
        tool = str(dimensions.get("tool") or "").strip().lower()
        if not tool:
            return None, "cache object has no identified tool"
        kind = str(item.get("resource_kind"))
        preferred = (
            ["build", "compile", "typecheck", "type-check", "check", "bundle"]
            if kind == "build_cache"
            else ["test", "test:unit", "unit", "test:ci", "test-ci"]
        )
        rejected_tokens = ("watch", "dev", "serve", "publish", "release", "deploy", "e2e", "integration", "docs")
        tool_tokens = {
            "typescript": ("tsc", "typescript"),
            "changesets": ("changeset",),
            "swc": ("swc",),
        }.get(tool, (tool,))
        candidates: list[tuple[int, int, str, str]] = []
        for name, command in scripts.items():
            script_name = str(name)
            script_command = str(command)
            lowered_name = script_name.lower()
            lowered_command = script_command.lower()
            if any(token in lowered_name for token in rejected_tokens):
                continue
            if kind == "build_cache" and not any(token in lowered_name for token in ("build", "compile", "type", "check", "bundle")):
                continue
            if kind == "test_transform_cache" and "test" not in lowered_name and lowered_name != "unit":
                continue
            if not any(token in lowered_command for token in tool_tokens):
                continue
            exact_priority = preferred.index(lowered_name) if lowered_name in preferred else len(preferred)
            candidates.append((0, exact_priority, len(script_command), script_name))
        if not candidates:
            return None, f"no non-interactive project script matches {kind} tool {tool}"
        candidates.sort()
        return candidates[0][3], None

    def _test_target(self, root: Path) -> Path | None:
        patterns = ("*.test.js", "*.test.cjs", "*.test.mjs", "*.test.ts", "*.spec.js", "*.spec.ts")
        candidates: list[Path] = []
        for pattern in patterns:
            for path in root.rglob(pattern):
                relative = path.relative_to(root)
                lowered = str(relative).lower()
                if "node_modules" in relative.parts or any(token in lowered for token in ("browser", "e2e", "integration", "fixture")):
                    continue
                candidates.append(relative)
                if len(candidates) >= 100:
                    break
            if candidates:
                break
        return sorted(candidates, key=lambda path: (len(path.parts), len(str(path)), str(path)))[0] if candidates else None

    def _clear_project_cache(self, root: Path, tool: str) -> list[str]:
        candidates = [
            root / "node_modules" / ".cache",
            root / ".cache",
            root / ".turbo",
            root / ".nx" / "cache",
            root / ".next" / "cache",
            root / ".vite",
            root / "coverage",
        ]
        removed: list[str] = []
        for path in candidates:
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
                removed.append(str(path.relative_to(root)))
            elif path.is_file():
                path.unlink()
                removed.append(str(path.relative_to(root)))
        if tool == "typescript":
            find = subprocess.run(
                ["find", str(root), "-path", str(root / "node_modules"), "-prune", "-o", "-name", "*.tsbuildinfo", "-type", "f", "-delete"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            if find.returncode == 0:
                removed.append("*.tsbuildinfo")
        return removed

    def _run_project_command(self, root: Path, command: list[str], environment: dict[str, str]) -> tuple[bool, float, dict[str, Any]]:
        started = time.perf_counter_ns()
        try:
            result = subprocess.run(
                command,
                cwd=root,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,
            )
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            result = subprocess.CompletedProcess(command, 124, exc.stdout or "", exc.stderr or "")
            timed_out = True
        wall_ms = (time.perf_counter_ns() - started) / 1_000_000
        details = {
            "command": command,
            "exit_code": result.returncode,
            "timed_out": timed_out,
            "stdout_tail": str(result.stdout)[-2000:],
            "stderr_tail": str(result.stderr)[-2000:],
        }
        return result.returncode == 0, wall_ms, details

    def _run_project_cache(self, item: dict[str, Any]) -> None:
        script, script_error = self._select_project_script(item)
        if script is None:
            self._set_status(item, "manual_review", script_error or "project script is unavailable", tool=item.get("dimensions", {}).get("tool"))
            return
        workspace, error, manual_review = self._prepare_project_workspace(item)
        if workspace is None:
            self._set_status(item, "manual_review" if manual_review else "blocked", "exact project workspace preparation failed", error=error, script=script)
            return
        root = Path(workspace["root"])
        manager = str(workspace["manager"])
        command = [*workspace["tool"], "run", script]
        test_target = self._test_target(root) if item.get("resource_kind") == "test_transform_cache" else None
        if test_target is not None:
            if manager == "npm":
                command.append("--")
            command.append(str(test_target))
            if item.get("dimensions", {}).get("tool") == "jest":
                command.append("--runInBand")
        environment = dict(workspace["environment"])
        environment.update({"CI": "1", "NODE_ENV": "test"})
        for _ in range(self.warmups):
            success, _wall_ms, details = self._run_project_command(root, command, environment)
            if not success:
                self._set_status(item, "blocked", "exact project command warmup failed", script=script, error=details["stderr_tail"] or details["stdout_tail"])
                return
        kind = str(item["resource_kind"])
        cold_benchmark = "EXACT-BUILD-CACHE-COLD" if kind == "build_cache" else "EXACT-TEST-CACHE-COLD"
        hit_benchmark = "EXACT-BUILD-CACHE-HIT" if kind == "build_cache" else "EXACT-TEST-CACHE-HIT"
        tool = str(item.get("dimensions", {}).get("tool") or "")
        failures: list[str] = []
        required_samples = self.samples
        for sample_index in range(self.samples):
            removed = self._clear_project_cache(root, tool)
            cold_success, cold_ms, cold_details = self._run_project_command(root, command, environment)
            cold_details.update({
                "script": script,
                "tool": tool,
                "cache_paths_cleared": removed,
                "node_version": workspace["node_version"],
                "dependency_object_id": workspace["dependency_object_id"],
                "lock_hash": workspace["lock_hash"],
                "test_target": str(test_target) if test_target else None,
            })
            self._record(_observation(
                environment_id=self.environment_id,
                run_id=self.run_id,
                benchmark_id=cold_benchmark,
                item=item,
                sample_index=sample_index,
                wall_ms=cold_ms,
                success=cold_success,
                transition_class="artifact_cold",
                scenario_name=f"project-script:{script}",
                from_object_id=None,
                details=cold_details,
                error=None if cold_success else cold_details["stderr_tail"] or cold_details["stdout_tail"],
            ))
            if not cold_success:
                failures.append(cold_details["stderr_tail"] or cold_details["stdout_tail"] or "cold command failed")
                continue
            hit_success, hit_ms, hit_details = self._run_project_command(root, command, environment)
            hit_details.update({"script": script, "tool": tool, "node_version": workspace["node_version"]})
            self._record(_observation(
                environment_id=self.environment_id,
                run_id=self.run_id,
                benchmark_id=hit_benchmark,
                item=item,
                sample_index=sample_index,
                wall_ms=hit_ms,
                success=hit_success,
                transition_class="exact_hit",
                scenario_name=f"project-script:{script}",
                from_object_id=str(item["object_id"]),
                details=hit_details,
                error=None if hit_success else hit_details["stderr_tail"] or hit_details["stdout_tail"],
            ))
            if not hit_success:
                failures.append(hit_details["stderr_tail"] or hit_details["stdout_tail"] or "warm command failed")
            if sample_index == 4 and cold_ms > 30_000 and self.samples > 5:
                required_samples = 5
                break
        cold_count = self._successful_sample_count(str(item["object_id"]), cold_benchmark)
        hit_count = self._successful_sample_count(str(item["object_id"]), hit_benchmark)
        if cold_count >= required_samples and hit_count >= required_samples:
            self._set_status(
                item,
                "measured",
                f"exact project cache cold/hit completed with {required_samples} successful samples per action",
                sample_count=required_samples,
                requested_sample_count=self.samples,
                script=script,
                tool=tool,
            )
        else:
            self._set_status(item, "failed", "exact project cache measurement was incomplete", cold_successful_samples=cold_count, hit_successful_samples=hit_count, failures=failures)

    def _successful_sample_count(self, object_id: str, benchmark_id: str) -> int:
        return len({
            int(item.get("sample_index"))
            for item in read_jsonl(self.observations_path)
            if item.get("to_object_id") == object_id
            and item.get("benchmark_id") == benchmark_id
            and item.get("measurement_environment_id") == self.environment_id
            and item.get("success")
            and isinstance(item.get("sample_index"), int)
            and int(item["sample_index"]) >= 0
        })

    def _run_rootfs(self, item: dict[str, Any]) -> None:
        image_name = str(item.get("dimensions", {}).get("image") or item.get("name") or "")
        if not image_name or image_name == "unknown":
            self._set_status(item, "manual_review", "profile metadata does not identify an exact rootfs image", image=image_name)
            return
        pull_errors: list[str] = []
        pull: subprocess.CompletedProcess[str] | None = None
        for attempt in range(1, 4):
            try:
                pull = subprocess.run(
                    [str(self.docker), "pull", image_name],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=600,
                )
            except (OSError, subprocess.TimeoutExpired) as exc:
                pull_errors.append(f"attempt {attempt}: {type(exc).__name__}: {exc}")
                continue
            if pull.returncode == 0:
                break
            pull_errors.append(f"attempt {attempt}: {pull.stderr[-2000:] or pull.stdout[-2000:] or f'exit {pull.returncode}'}")
        if pull is None or pull.returncode != 0:
            self._set_status(item, "blocked", "exact rootfs image pull failed after 3 attempts", image=image_name, errors=pull_errors)
            return
        inspect = subprocess.run(
            [str(self.docker), "image", "inspect", "--format", "{{.Id}}", image_name],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=60,
        )
        digest = inspect.stdout.strip() if inspect.returncode == 0 else None
        failures: list[str] = []
        for iteration in range(self.warmups + self.samples):
            started = time.perf_counter_ns()
            create = subprocess.run(
                [str(self.docker), "create", "--entrypoint", "/bin/sh", image_name, "-c", "true"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=120,
            )
            create_ms = (time.perf_counter_ns() - started) / 1_000_000
            container_id = create.stdout.strip()
            attached = False
            attach_ms = 0.0
            reset_ms = 0.0
            removed = False
            if create.returncode == 0 and container_id:
                attach_started = time.perf_counter_ns()
                attached_result = subprocess.run(
                    [str(self.docker), "inspect", "--format", "{{.State.Status}}", container_id],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60,
                )
                attach_ms = (time.perf_counter_ns() - attach_started) / 1_000_000
                attached = attached_result.returncode == 0 and attached_result.stdout.strip() == "created"
                reset_started = time.perf_counter_ns()
                remove = subprocess.run(
                    [str(self.docker), "rm", container_id],
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=60,
                )
                reset_ms = (time.perf_counter_ns() - reset_started) / 1_000_000
                removed = remove.returncode == 0
            success = create.returncode == 0 and bool(container_id)
            if iteration >= self.warmups:
                sample_index = iteration - self.warmups
                common = {"image": image_name, "image_id": digest, "container_id": container_id, "exit_code": create.returncode}
                self._record(_observation(
                    environment_id=self.environment_id,
                    run_id=self.run_id,
                    benchmark_id="EXACT-ROOTFS-CREATE",
                    item=item,
                    sample_index=sample_index,
                    wall_ms=create_ms,
                    success=success,
                    transition_class="artifact_cold",
                    scenario_name="docker-create-from-local-image",
                    from_object_id=None,
                    details=common,
                    error=None if success else create.stderr[-2000:] or f"exit {create.returncode}",
                ))
                self._record(_observation(
                    environment_id=self.environment_id,
                    run_id=self.run_id,
                    benchmark_id="EXACT-ROOTFS-ATTACH",
                    item=item,
                    sample_index=sample_index,
                    wall_ms=attach_ms,
                    success=attached,
                    transition_class="exact_hit",
                    scenario_name="docker-container-inspect",
                    from_object_id=str(item["object_id"]),
                    details=common,
                ))
                self._record(_observation(
                    environment_id=self.environment_id,
                    run_id=self.run_id,
                    benchmark_id="EXACT-ROOTFS-RESET",
                    item=item,
                    sample_index=sample_index,
                    wall_ms=reset_ms,
                    success=removed,
                    transition_class="dirty_reset",
                    scenario_name="docker-container-remove",
                    from_object_id=str(item["object_id"]),
                    details=common,
                ))
            if not success:
                failures.append(create.stderr[-2000:] or f"docker create exited {create.returncode}")
        successful = self._successful_sample_count(str(item["object_id"]), "EXACT-ROOTFS-CREATE")
        subprocess.run([str(self.docker), "image", "rm", image_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        if successful >= self.samples:
            self._set_status(item, "measured", f"exact rootfs container lifecycle completed in {self.samples}/{self.samples} samples", sample_count=self.samples, image=image_name, image_id=digest)
        else:
            self._set_status(item, "failed", "exact rootfs lifecycle measurement was incomplete", successful_samples=successful, failures=failures)

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

    def _run_item(self, item: dict[str, Any]) -> None:
        try:
            if self._static_status(item):
                return
            kind = str(item.get("resource_kind"))
            if kind == "dependency_view":
                self._run_dependency(item)
            elif kind == "native_binary_bundle":
                return
            elif kind == "repo_baseline":
                self._run_repo_baseline(item)
            elif kind == "source_overlay":
                self._run_source_overlay(item)
            elif kind in {"build_cache", "test_transform_cache"}:
                self._run_project_cache(item)
            elif kind == "rootfs":
                self._cleanup_source_state()
                self._run_rootfs(item)
            else:
                self._set_status(item, "unsupported", "no exact workload runner is defined for this resource kind")
        except Exception as exc:
            self._set_status(
                item,
                "failed",
                "exact workload runner raised an object-scoped exception",
                exception_type=type(exc).__name__,
                error=str(exc),
            )

    def run(self) -> dict[str, Any]:
        for position, target in enumerate(self.targets, start=1):
            item = self.objects.get(str(target["object_id"]), target)
            object_id = str(item["object_id"])
            if not self.force and object_id in self.statuses:
                print(f"[{position}/{len(self.targets)}] skip {object_id}: {self.statuses[object_id]['status']}", flush=True)
                continue
            print(f"[{position}/{len(self.targets)}] {object_id}", flush=True)
            self._run_item(item)
            write_json(self.progress_path, {"completed": len(self.statuses), "total": len(self.targets), "current_object_id": object_id})
        self._cleanup_source_state()
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
    retry_failed: bool = False,
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
        retry_failed=retry_failed,
    ).run()
