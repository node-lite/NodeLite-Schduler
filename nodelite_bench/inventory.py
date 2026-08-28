from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from collections import defaultdict
from pathlib import Path
from typing import Any

from .util import command_version, read_json, sha256_file, stable_hash, write_json


BUILD_TOOLS = {
    "typescript": ("tsc", "tsserver"),
    "babel": ("babel",),
    "swc": ("swc",),
    "esbuild": ("esbuild",),
    "rollup": ("rollup",),
    "webpack": ("webpack",),
    "vite": ("vite",),
    "next": ("next",),
    "nx": ("nx",),
    "turbo": ("turbo",),
    "lerna": ("lerna",),
    "gulp": ("gulp",),
    "changesets": ("changeset", "changesets"),
}

TEST_TOOLS = {
    "jest": ("jest",),
    "vitest": ("vitest",),
    "mocha": ("mocha",),
    "ava": ("ava",),
    "karma": ("karma",),
    "nightwatch": ("nightwatch",),
    "cypress": ("cypress",),
    "playwright": ("playwright",),
    "puppeteer": ("puppeteer",),
    "selenium": ("selenium", "webdriver"),
}

NATIVE_NAMES = {
    "canvas",
    "@swc/core",
    "esbuild",
    "sharp",
    "sqlite3",
    "@vscode/sqlite3",
    "@prisma/engines",
    "prisma",
    "grpc",
    "@grpc/grpc-js",
    "node-gyp",
}

DATABASE_TERMS = {
    "mongodb": "mongodb",
    "mongoose": "mongodb",
    "postgres": "postgresql",
    "pg": "postgresql",
    "mysql": "mysql",
    "mysql2": "mysql",
    "redis": "redis",
    "sqlite": "sqlite",
    "sqlite3": "sqlite",
}

BROWSER_TERMS = {
    "playwright": "chromium",
    "puppeteer": "chromium",
    "cypress": "chromium",
    "nightwatch": "chromium",
    "selenium": "chromium",
    "electron": "electron",
    "firefox": "firefox",
    "webkit": "webkit",
    "chromium": "chromium",
    "chrome": "chromium",
}


def _object(
    object_id: str,
    resource_kind: str,
    name: str,
    version: str,
    compatibility_key: str,
    workload_origin: str,
    *,
    scope: str = "node",
    profile_ids: list[str] | None = None,
    dimensions: dict[str, Any] | None = None,
    source: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "object_id": object_id,
        "resource_kind": resource_kind,
        "name": name,
        "version": version,
        "scope": scope,
        "compatibility_key": compatibility_key,
        "dimensions": dimensions or {},
        "workload_origin": workload_origin,
        "profile_ids": sorted(set(profile_ids or [])),
        "source": source or {},
    }


def _node_details(path: Path) -> dict[str, str] | None:
    if not path.is_file() or not os.access(path, os.X_OK):
        return None
    try:
        result = subprocess.run(
            [str(path), "-p", "JSON.stringify({version:process.version,abi:process.versions.modules,arch:process.arch,platform:process.platform})"],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=True,
        )
        value = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    value["path"] = str(path.resolve())
    return value


def discover_node_paths() -> dict[str, dict[str, str]]:
    candidates = [
        Path("/usr/bin/node"),
        Path.home() / ".local/bin/node",
        Path.home() / ".hermes/node/bin/node",
    ]
    npx_root = Path.home() / ".npm/_npx"
    if npx_root.is_dir():
        candidates.extend(npx_root.glob("*/node_modules/node/bin/node"))
    found: dict[str, dict[str, str]] = {}
    for candidate in candidates:
        details = _node_details(candidate)
        if not details:
            continue
        major = details["version"].lstrip("v").split(".", 1)[0]
        current = found.get(major)
        if current is None or candidate.as_posix().startswith("/usr/bin"):
            found[major] = details
    return found


def discover_pm_commands() -> dict[tuple[str, str, str], dict[str, Any]]:
    commands: dict[tuple[str, str, str], dict[str, Any]] = {}
    npm = shutil.which("npm")
    if npm:
        version = command_version([npm, "--version"])
        if version:
            commands[("npm", "default", version)] = {"command": [npm], "path": npm}
    npx_root = Path.home() / ".npm/_npx"
    if not npx_root.is_dir():
        return commands
    for package_json in npx_root.glob("*/node_modules/**/package.json"):
        if len(package_json.parts) - len(npx_root.parts) > 5:
            continue
        value = read_json(package_json, {})
        name = value.get("name")
        version = value.get("version")
        if not isinstance(version, str):
            continue
        bin_value = value.get("bin")
        if name == "pnpm":
            relative = bin_value.get("pnpm") if isinstance(bin_value, dict) else None
            if relative:
                script = package_json.parent / relative
                commands[("pnpm", "default", version)] = {"command": [str(script)], "path": str(script)}
        elif name == "yarn":
            relative = bin_value.get("yarn") if isinstance(bin_value, dict) else bin_value
            if relative:
                script = package_json.parent / relative
                commands[("yarn", "classic", version)] = {"command": [str(script)], "path": str(script)}
        elif name == "@yarnpkg/cli-dist":
            relative = bin_value.get("yarn") if isinstance(bin_value, dict) else None
            if relative:
                script = package_json.parent / relative
                commands[("yarn", "berry", version)] = {"command": [str(script)], "path": str(script)}
        elif name == "bun":
            relative = bin_value.get("bun") if isinstance(bin_value, dict) else None
            if relative:
                script = package_json.parent / relative
                commands[("bun", "default", version)] = {"command": [str(script)], "path": str(script)}
    return commands


def _manager_variant(manager: str, version: str | None) -> str:
    if manager != "yarn":
        return "default"
    return "classic" if str(version or "").startswith("1.") else "berry"


def _manifest_tool_evidence(manifest: dict[str, Any]) -> tuple[set[str], set[str], set[str], set[str]]:
    scripts = manifest.get("scripts") if isinstance(manifest.get("scripts"), dict) else {}
    dependencies: dict[str, str] = {}
    for field in ("dependencies", "devDependencies", "optionalDependencies"):
        value = manifest.get(field)
        if isinstance(value, dict):
            dependencies.update({str(key): str(spec) for key, spec in value.items()})
    command_text = "\n".join(str(value).lower() for value in scripts.values())
    build: set[str] = set()
    test: set[str] = set()
    database: set[str] = set()
    browser: set[str] = set()
    for tool, tokens in BUILD_TOOLS.items():
        if any(re.search(rf"(^|[^a-z0-9_-]){re.escape(token)}([^a-z0-9_-]|$)", command_text) for token in tokens):
            build.add(tool)
    for tool, tokens in TEST_TOOLS.items():
        if any(token in command_text for token in tokens):
            test.add(tool)
    evidence_text = " ".join([command_text, *[name.lower() for name in dependencies]])
    for token, engine in DATABASE_TERMS.items():
        if token in evidence_text:
            database.add(engine)
    for token, engine in BROWSER_TERMS.items():
        if token in evidence_text:
            browser.add(engine)
    return build, test, database, browser


def build_inventory(profiles_path: Path, ctdp_out: Path, output: Path) -> dict[str, Any]:
    requested_ids = [line.strip() for line in profiles_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    inventory = read_json(ctdp_out / "inventory.json", {})
    resolution = read_json(ctdp_out / "resolution.json", {})
    prefetch = read_json(ctdp_out / "prefetch.json", {})
    profiles = inventory.get("profiles", [])
    profile_by_id = {item.get("profile_id"): item for item in profiles if item.get("profile_id")}
    missing_profiles = sorted(set(requested_ids) - set(profile_by_id))
    extra_profiles = sorted(set(profile_by_id) - set(requested_ids))
    node_paths = discover_node_paths()
    pm_commands = discover_pm_commands()
    objects: dict[str, dict[str, Any]] = {}
    requirements: list[dict[str, Any]] = []
    root_records = {(item.get("profile_id"), item.get("dependency_root")): item for item in resolution.get("profiles", [])}

    node_profiles: dict[str, list[str]] = defaultdict(list)
    for profile in profiles:
        node_profiles[str(profile.get("node_version") or "unknown")].append(profile["profile_id"])
    for major, profile_ids in sorted(node_profiles.items()):
        details = node_paths.get(major)
        exact = details["version"].lstrip("v") if details else f"{major}.x-unavailable"
        abi = details["abi"] if details else "unknown"
        key = f"node|{exact}|abi-{abi}|linux|x86_64|glibc"
        object_id = f"node_runtime:{exact}:linux:x86_64:glibc:abi{abi}"
        objects[object_id] = _object(
            object_id,
            "node_runtime",
            "Node.js",
            exact,
            key,
            "real",
            profile_ids=profile_ids,
            dimensions={"major": major, "abi": abi, "os": "linux", "arch": "x86_64", "libc": "glibc", "executable": details.get("path") if details else None},
            source={"evidence": "CTDP inventory node_version", "available": bool(details)},
        )

    manager_profiles: dict[tuple[str, str, str], list[str]] = defaultdict(list)
    for record in resolution.get("profiles", []):
        manager = str(record.get("package_manager") or "unknown")
        version = str(record.get("tool_version") or record.get("package_manager_version") or "unknown")
        variant = _manager_variant(manager, version)
        manager_profiles[(manager, variant, version)].append(str(record.get("profile_id")))
    for (manager, variant, version), profile_ids in sorted(manager_profiles.items()):
        command = pm_commands.get((manager, variant, version))
        key = f"pm|{manager}|{variant}|{version}|node22|linux|x86_64"
        object_id = f"package_manager:{manager}:{variant}:{version}:linux:x86_64"
        objects[object_id] = _object(
            object_id,
            "package_manager",
            manager,
            version,
            key,
            "real",
            profile_ids=profile_ids,
            dimensions={"manager": manager, "variant": variant, "executable": command.get("path") if command else None},
            source={"evidence": "CTDP resolution tool_version", "available": bool(command)},
        )
        cache_dir = manager if manager != "yarn" else f"yarn-{variant}"
        cache_path = ctdp_out / "native-cache" / cache_dir / version
        cache_key = f"pm-cache|{manager}|{variant}|{version}|{stable_hash(str(cache_path))[:16]}"
        cache_id = f"pm_native_cache:{manager}:{variant}:{version}"
        objects[cache_id] = _object(
            cache_id,
            "pm_native_cache",
            f"{manager} native cache",
            version,
            cache_key,
            "real",
            profile_ids=profile_ids,
            dimensions={"manager": manager, "variant": variant, "path": str(cache_path), "format": version.split(".", 1)[0]},
            source={"evidence": "CTDP warm-cache policy", "available": cache_path.is_dir()},
        )

    manifest_evidence: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for profile in profiles:
        profile_id = profile["profile_id"]
        safe_id = profile["safe_profile_id"]
        profile_requirements: list[str] = []
        node_major = str(profile.get("node_version") or "unknown")
        for object_id, item in objects.items():
            if item["resource_kind"] == "node_runtime" and profile_id in item["profile_ids"]:
                profile_requirements.append(object_id)
        dockerfile = ctdp_out / "projects" / safe_id / "environment" / "Dockerfile"
        docker_hash = sha256_file(dockerfile) if dockerfile.is_file() else "missing"
        image_values = [str(item.get("value")) for item in profile.get("discovery_evidence", []) if item.get("kind") == "node_image"]
        image = image_values[0] if image_values else "unknown"
        distro = "debian" if any(token in image for token in ("bullseye", "bookworm", "slim")) else "unknown"
        rootfs_id = f"rootfs:{image.replace('/', '_').replace(':', '_')}"
        if rootfs_id not in objects:
            objects[rootfs_id] = _object(
                rootfs_id,
                "rootfs",
                image,
                image,
                f"rootfs|{image}|{docker_hash}",
                "real",
                profile_ids=[profile_id],
                dimensions={"image": image, "distro": distro, "dockerfile_sha256": docker_hash},
                source={"evidence": str(dockerfile), "available": False},
            )
        elif profile_id not in objects[rootfs_id]["profile_ids"]:
            objects[rootfs_id]["profile_ids"].append(profile_id)
        profile_requirements.append(rootfs_id)
        repo_key = f"repo|{profile.get('owner')}/{profile.get('repo')}|{profile.get('commit')}"
        repo_id = f"repo_baseline:{profile.get('owner')}__{profile.get('repo')}:{profile.get('commit')}"
        objects[repo_id] = _object(
            repo_id,
            "repo_baseline",
            f"{profile.get('owner')}/{profile.get('repo')}",
            str(profile.get("commit")),
            repo_key,
            "real",
            profile_ids=[profile_id],
            dimensions={"commit": profile.get("commit"), "submodules": []},
            source={"evidence": profile.get("profile_source"), "available": False},
        )
        profile_requirements.append(repo_id)
        for root in profile.get("dependency_roots", []):
            root_name = str(root.get("dependency_root") or ".")
            record = root_records.get((profile_id, root_name), {})
            lock_hash = str(record.get("resolved_lockfile_sha256") or record.get("source_lockfile_sha256") or "missing")
            manager = str(root.get("package_manager") or profile.get("package_manager") or "unknown")
            version = str(record.get("tool_version") or root.get("package_manager_version") or "unknown")
            variant = _manager_variant(manager, version)
            node_abi = node_paths.get(node_major, {}).get("abi", "unknown")
            dep_key = f"depview|{lock_hash}|{manager}|{variant}|{version}|abi-{node_abi}|linux|x86_64|glibc"
            root_slug = "root" if root_name == "." else re.sub(r"[^A-Za-z0-9_.-]+", "_", root_name)
            dep_id = f"dependency_view:{safe_id}:{root_slug}:{lock_hash[:16]}"
            objects[dep_id] = _object(
                dep_id,
                "dependency_view",
                f"{profile_id}:{root_name}",
                lock_hash[:16],
                dep_key,
                "real",
                scope="node",
                profile_ids=[profile_id],
                dimensions={"dependency_root": root_name, "manager": manager, "variant": variant, "manager_version": version, "node_abi": node_abi, "lock_hash": lock_hash},
                source={"evidence": record, "available": True},
            )
            profile_requirements.append(dep_id)
            overlay_id = f"source_overlay:{safe_id}:{root_slug}"
            objects[overlay_id] = _object(
                overlay_id,
                "source_overlay",
                f"{profile_id}:{root_name}",
                str(profile.get("commit"))[:12],
                f"overlay|{repo_key}|{root_name}|directory-copy",
                "real",
                scope="task",
                profile_ids=[profile_id],
                dimensions={"dependency_root": root_name, "backend": "directory-copy"},
                source={"evidence": str(ctdp_out / "projects" / safe_id / "source-files" / root_slug), "available": True},
            )
            profile_requirements.append(overlay_id)
            manifest_path = ctdp_out / "projects" / safe_id / "source-files" / root_slug / "package.json"
            manifest = read_json(manifest_path, {})
            build, test, databases, browsers = _manifest_tool_evidence(manifest)
            manifest_hash = sha256_file(manifest_path) if manifest_path.is_file() else "missing"
            manifest_dependencies: dict[str, str] = {}
            for dependency_field in ("dependencies", "devDependencies", "optionalDependencies"):
                dependency_values = manifest.get(dependency_field)
                if isinstance(dependency_values, dict):
                    manifest_dependencies.update({str(name): str(specifier) for name, specifier in dependency_values.items()})
            for native_name in sorted(set(manifest_dependencies) & NATIVE_NAMES):
                native_version = manifest_dependencies[native_name]
                native_id = f"native_binary_bundle:{safe_id}:{root_slug}:{native_name.replace('/', '_')}:{node_abi}"
                objects[native_id] = _object(
                    native_id,
                    "native_binary_bundle",
                    native_name,
                    native_version,
                    f"native|{native_name}|{native_version}|abi-{node_abi}|linux|x86_64|glibc|toolchain-unknown",
                    "real",
                    profile_ids=[profile_id],
                    dimensions={"package": native_name, "specifier": native_version, "node_abi": node_abi, "os": "linux", "arch": "x86_64", "libc": "glibc"},
                    source={"evidence": str(manifest_path), "available": False},
                )
                profile_requirements.append(native_id)
            for tool in build:
                manifest_evidence[profile_id]["build"].add(tool)
                object_id = f"build_cache:{safe_id}:{root_slug}:{tool}:{manifest_hash[:12]}"
                objects[object_id] = _object(
                    object_id,
                    "build_cache",
                    tool,
                    "manifest-derived",
                    f"build|{profile.get('commit')}|{lock_hash}|{tool}|{manifest_hash}",
                    "real",
                    profile_ids=[profile_id],
                    dimensions={"tool": tool, "manifest_hash": manifest_hash, "command_evidence": manifest.get("scripts", {})},
                    source={"evidence": str(manifest_path), "available": False},
                )
                profile_requirements.append(object_id)
            for tool in test:
                manifest_evidence[profile_id]["test"].add(tool)
                object_id = f"test_transform_cache:{safe_id}:{root_slug}:{tool}:{manifest_hash[:12]}"
                objects[object_id] = _object(
                    object_id,
                    "test_transform_cache",
                    tool,
                    "manifest-derived",
                    f"test|{profile.get('commit')}|{lock_hash}|{tool}|{manifest_hash}",
                    "real",
                    profile_ids=[profile_id],
                    dimensions={"tool": tool, "manifest_hash": manifest_hash, "command_evidence": manifest.get("scripts", {})},
                    source={"evidence": str(manifest_path), "available": False},
                )
                profile_requirements.append(object_id)
            manifest_evidence[profile_id]["database"].update(databases)
            manifest_evidence[profile_id]["browser"].update(browsers)
        requirements.append({"profile_id": profile_id, "object_ids": sorted(set(profile_requirements)), "accounted": True})

    artifact_count = 0
    for artifact in prefetch.get("artifacts", []):
        if artifact.get("status") not in {"downloaded", "reused"} or not artifact.get("cas_path"):
            continue
        artifact_id = str(artifact.get("artifact_id"))
        object_id = f"raw_cas:{hashlib.sha256(artifact_id.encode()).hexdigest()[:24]}"
        objects[object_id] = _object(
            object_id,
            "raw_cas",
            str(artifact.get("name") or artifact.get("type") or "artifact"),
            str(artifact.get("version") or artifact.get("content_sha256") or "content-addressed"),
            f"cas|{artifact_id}",
            "real",
            scope="global",
            profile_ids=[str(item) for item in artifact.get("profile_ids", [])],
            dimensions={"artifact_id": artifact_id, "artifact_type": artifact.get("type"), "size_bytes": artifact.get("size_bytes"), "cas_path": str(ctdp_out / str(artifact.get("cas_path")))},
            source={"evidence": artifact.get("source"), "available": True},
        )
        artifact_count += 1

    host_objects = [
        _object("filesystem_overlay:directory-copy:ext4", "filesystem_overlay", "directory-copy on ext4", "ext4", "fs|directory-copy|ext4", "synthetic", dimensions={"backend": "directory-copy", "native_overlay": False}, source={"available": True}),
        _object("home_tmp_xdg:isolated-template:v1", "home_tmp_xdg", "isolated HOME/tmp/XDG", "v1", "home-tmp-xdg|v1", "synthetic", scope="task", source={"available": True}),
        _object("network_ports:host-loopback:v1", "network_ports", "host loopback ports", "v1", "network|host|loopback", "synthetic", source={"available": True, "network_namespace": False}),
        _object("system_toolchain:ubuntu24:gcc13:python3.12", "system_toolchain", "Ubuntu build toolchain", "gcc13-python3.12", "toolchain|ubuntu24|gcc13|python3.12|cmake3.28", "synthetic", dimensions={"gcc": command_version(["gcc", "--version"]), "python": command_version(["python3", "--version"]), "cmake": command_version(["cmake", "--version"])}, source={"available": True}),
        _object("display_service:xvfb:host", "display_service", "Xvfb", "host", "display|xvfb|host", "synthetic", source={"available": bool(shutil.which("Xvfb"))}),
        _object("display_service:dbus:host", "display_service", "D-Bus session", "host", "display|dbus|host", "synthetic", source={"available": bool(shutil.which("dbus-daemon"))}),
    ]
    for item in host_objects:
        objects[item["object_id"]] = item

    browser_candidates = [
        ("chromium", Path.home() / ".agent-browser/browsers/chrome-151.0.7922.77/chrome", "151.0.7922.77"),
        ("firefox", Path("/usr/bin/firefox"), command_version(["firefox", "--version"]) or "unknown"),
    ]
    electron_zip = Path.home() / ".cache/electron/3978a3c4a2965533dc07f99112894e7e7f80c9ea0f13e2a48cd5a29593568fb2/electron-v40.10.2-linux-x64.zip"
    if electron_zip.is_file():
        browser_candidates.append(("electron", electron_zip, "40.10.2"))
    for browser, path, version in browser_candidates:
        profiles_with_evidence = sorted(profile_id for profile_id, evidence in manifest_evidence.items() if browser in evidence.get("browser", set()) or (browser == "chromium" and evidence.get("browser")))
        origin = "real" if profiles_with_evidence else "synthetic"
        binary_id = f"browser_binary:{browser}:{version}:linux:x86_64"
        objects[binary_id] = _object(binary_id, "browser_binary", browser, version, f"browser-binary|{browser}|{version}|linux|x86_64", origin, profile_ids=profiles_with_evidence, dimensions={"path": str(path)}, source={"available": path.exists()})
        process_id = f"browser_process:{browser}:{version}:headless"
        objects[process_id] = _object(process_id, "browser_process", browser, version, f"browser-process|{browser}|{version}|headless|default-flags", origin, profile_ids=profiles_with_evidence, dimensions={"binary_object_id": binary_id, "path": str(path), "flags": "headless"}, source={"available": path.exists()})
        context_id = f"browser_context:{browser}:{version}:default"
        objects[context_id] = _object(context_id, "browser_context", f"{browser} context", version, f"browser-context|{process_id}|default", origin, scope="task", profile_ids=profiles_with_evidence, dimensions={"process_object_id": process_id}, source={"available": path.exists()})
        profile_id = f"browser_profile:{browser}:{version}:ephemeral"
        objects[profile_id] = _object(profile_id, "browser_profile", f"{browser} profile", version, f"browser-profile|{browser}|{version}|ephemeral", origin, scope="task", profile_ids=profiles_with_evidence, dimensions={"process_object_id": process_id}, source={"available": path.exists()})

    database_candidates = [
        ("redis", command_version(["redis-server", "--version"]) or "unknown", bool(shutil.which("redis-server"))),
        ("sqlite", "python-stdlib", True),
        ("mongodb", "unavailable", False),
        ("postgresql", "unavailable", False),
        ("mysql", "unavailable", False),
    ]
    for engine, version, available in database_candidates:
        profile_ids = sorted(profile_id for profile_id, evidence in manifest_evidence.items() if engine in evidence.get("database", set()))
        origin = "real" if profile_ids else "synthetic"
        binary_id = f"database_binary:{engine}:{version}"
        objects[binary_id] = _object(binary_id, "database_binary", engine, version, f"db-binary|{engine}|{version}|linux|x86_64", origin, profile_ids=profile_ids, source={"available": available})
        if engine != "sqlite":
            daemon_id = f"database_daemon:{engine}:{version}:default"
            objects[daemon_id] = _object(daemon_id, "database_daemon", engine, version, f"db-daemon|{engine}|{version}|default", origin, profile_ids=profile_ids, dimensions={"binary_object_id": binary_id}, source={"available": available})
        snapshot_id = f"database_clean_snapshot:{engine}:{version}:minimal"
        objects[snapshot_id] = _object(snapshot_id, "database_clean_snapshot", f"{engine} clean snapshot", version, f"db-snapshot|{engine}|{version}|minimal-schema", origin, scope="node", profile_ids=profile_ids, source={"available": available})
        private_id = f"database_private_layer:{engine}:{version}:task"
        objects[private_id] = _object(private_id, "database_private_layer", f"{engine} private layer", version, f"db-private|{snapshot_id}", origin, scope="task", profile_ids=profile_ids, source={"available": available})

    for item in objects.values():
        item["profile_ids"] = sorted(set(item.get("profile_ids", [])))
    result = {
        "schema_version": 1,
        "profile_input_count": len(requested_ids),
        "profile_inventory_count": len(profiles),
        "profile_coverage_count": len(set(requested_ids) & set(profile_by_id)),
        "missing_profiles": missing_profiles,
        "extra_profiles": extra_profiles,
        "dependency_root_count": sum(len(item.get("dependency_roots", [])) for item in profiles),
        "objects": sorted(objects.values(), key=lambda item: item["object_id"]),
        "requirements": requirements,
        "node_paths": node_paths,
        "pm_commands": {"|".join(key): value for key, value in pm_commands.items()},
        "raw_cas_object_count": artifact_count,
        "manifest_evidence": {profile: {kind: sorted(values) for kind, values in kinds.items()} for profile, kinds in manifest_evidence.items()},
    }
    write_json(output / "costdb" / "objects.json", result["objects"])
    write_json(output / "inventory.json", result)
    write_json(output / "graph" / "profile_requirements.json", requirements)
    return result
