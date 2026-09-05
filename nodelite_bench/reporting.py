from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from .catalog import BenchmarkSpec
from .runners import INVALIDATIONS
from .util import read_json, read_jsonl, stable_hash, summarize, write_csv, write_json


SUMMARY_FIELDS = [
    "resource_kind",
    "object_name",
    "from_version/config",
    "to_version/config",
    "transition_class",
    "cost_class",
    "median_ms",
    "p95_ms",
    "invalidation_targets",
    "reuse_safe",
    "sample_count",
    "success_count",
    "failure_count",
    "timeout_count",
    "measurement_environment_id",
    "workload_origin",
    "benchmark_id",
    "from_object_id",
    "to_object_id",
]

DEFAULT_DIRECT_MS_WINDOW_SIZE = 5


def _latest_observations(observations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    unkeyed: list[dict[str, Any]] = []
    for item in observations:
        key = item.get("observation_key")
        if key:
            latest[str(key)] = item
        else:
            unkeyed.append(item)
    return [*latest.values(), *unkeyed]


def _active_observations(observations: list[dict[str, Any]], active_scenarios: dict[str, Any]) -> list[dict[str, Any]]:
    active = {benchmark_id: {str(identity) for identity in identities} for benchmark_id, identities in active_scenarios.items()}
    current: list[dict[str, Any]] = []
    for item in observations:
        benchmark_id = str(item.get("benchmark_id") or "")
        if benchmark_id not in active:
            current.append(item)
            continue
        key = str(item.get("observation_key") or "")
        identity = key.rsplit("|", 1)[0] if "|" in key else ""
        if identity in active[benchmark_id]:
            current.append(item)
    return current


def invalidation_rules() -> list[dict[str, Any]]:
    return [
        {"rule_id": "node-exact-abi-change", "source_kind": "node_runtime", "change_dimensions": ["version", "abi"], "invalidates": INVALIDATIONS["node_runtime"], "owner": "invalidated objects", "direct_cost_excludes_rebuild": True},
        {"rule_id": "pm-exact-major-change", "source_kind": "package_manager", "change_dimensions": ["manager", "variant", "version"], "invalidates": INVALIDATIONS["package_manager"], "owner": "invalidated objects", "direct_cost_excludes_rebuild": True},
        {"rule_id": "yarn-classic-berry-linker", "source_kind": "package_manager", "change_dimensions": ["variant", "linker"], "invalidates": ["pm_native_cache", "dependency_view", "native_binary_bundle"], "owner": "invalidated objects", "direct_cost_excludes_rebuild": True},
        {"rule_id": "lock-hash-change", "source_kind": "dependency_view", "change_dimensions": ["lock_hash"], "invalidates": ["dependency_view", "build_cache", "test_transform_cache"], "owner": "invalidated objects", "direct_cost_excludes_rebuild": True},
        {"rule_id": "workspace-config-change", "source_kind": "dependency_view", "change_dimensions": ["workspace_config_hash"], "invalidates": ["dependency_view", "build_cache"], "owner": "invalidated objects", "direct_cost_excludes_rebuild": True},
        {"rule_id": "repo-commit-change", "source_kind": "repo_baseline", "change_dimensions": ["commit"], "invalidates": INVALIDATIONS["repo_baseline"], "owner": "invalidated objects", "direct_cost_excludes_rebuild": True},
        {"rule_id": "browser-revision-flags-profile", "source_kind": "browser_process", "change_dimensions": ["version", "flags", "profile_mode"], "invalidates": INVALIDATIONS["browser_process"], "owner": "invalidated objects", "direct_cost_excludes_rebuild": True},
        {"rule_id": "database-version-config-schema", "source_kind": "database_daemon", "change_dimensions": ["version", "config_hash", "schema_hash"], "invalidates": INVALIDATIONS["database_daemon"], "owner": "invalidated objects", "direct_cost_excludes_rebuild": True},
        {"rule_id": "rootfs-libc-arch", "source_kind": "rootfs", "change_dimensions": ["rootfs_digest", "libc", "arch"], "invalidates": INVALIDATIONS["rootfs"], "owner": "invalidated objects", "direct_cost_excludes_rebuild": True},
    ]


def _group_observations(observations: list[dict[str, Any]]) -> dict[tuple[str, ...], list[dict[str, Any]]]:
    grouped: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for item in observations:
        key = (
            str(item.get("benchmark_id")),
            str(item.get("resource_kind")),
            str(item.get("from_object_id") or ""),
            str(item.get("to_object_id") or ""),
            str(item.get("transition_class")),
            str(item.get("cost_class")),
            str(item.get("scenario_name") or "default"),
            str(item.get("measurement_environment_id")),
        )
        grouped[key].append(item)
    return grouped


def build_summaries(observations: list[dict[str, Any]], objects: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for key, rows in _group_observations(observations).items():
        benchmark_id, resource_kind, from_id, to_id, transition_class, cost_class, scenario_name, environment_id = key
        successful = [float(item["wall_ms"]) for item in rows if item.get("success") and isinstance(item.get("wall_ms"), (int, float))]
        stats = summarize(successful)
        from_object = objects.get(from_id, {})
        to_object = objects.get(to_id, {})
        measurement_id = stable_hash(
            [
                {
                    "measurement_run_id": item.get("measurement_run_id"),
                    "observation_key": item.get("observation_key"),
                    "pollution_check": item.get("pollution_check"),
                    "reuse_safe": item.get("reuse_safe"),
                    "success": item.get("success"),
                    "wall_ms": item.get("wall_ms"),
                }
                for item in sorted(rows, key=lambda row: str(row.get("observation_key") or ""))
            ]
        )
        summaries.append(
            {
                "benchmark_id": benchmark_id,
                "resource_kind": resource_kind,
                "from_object_id": from_id or None,
                "to_object_id": to_id,
                "from_version/config": from_object.get("version") if from_object else "cold",
                "to_version/config": to_object.get("version") or to_id,
                "object_name": to_object.get("name") or to_id,
                "transition_class": transition_class,
                "cost_class": cost_class,
                "scenario_name": scenario_name,
                "measurement_environment_id": environment_id,
                "_measurement_id": measurement_id,
                **stats,
                "success_count": sum(bool(item.get("success")) for item in rows),
                "failure_count": sum(not bool(item.get("success")) for item in rows),
                "timeout_count": sum(bool(item.get("timed_out")) for item in rows),
                "reuse_safe": all(bool(item.get("reuse_safe")) for item in rows),
                "pollution_result": "pass" if all(item.get("pollution_check") in {None, "pass"} for item in rows) else "fail",
                "invalidation_targets": sorted({target for item in rows for target in item.get("invalidates", [])}),
                "workload_origin": to_object.get("workload_origin") or rows[0].get("workload_origin"),
            }
        )
    summaries.sort(key=lambda item: (item["resource_kind"], item["benchmark_id"], item["from_object_id"] or "", item["to_object_id"], item["scenario_name"]))
    return summaries


def build_matrix(summaries: list[dict[str, Any]]) -> dict[str, Any]:
    matrix: dict[str, Any] = {}
    for item in summaries:
        if item.get("median_ms") is None:
            continue
        kind = str(item["resource_kind"])
        source = str(item.get("from_object_id") or "__cold__")
        target = str(item["to_object_id"])
        entry = {
            "direct_ms": item["median_ms"],
            "median_ms": item["median_ms"],
            "p95_ms": item["p95_ms"],
            "transition_class": item["transition_class"],
            "cost_class": item["cost_class"],
            "benchmark_id": item["benchmark_id"],
            "scenario_name": item["scenario_name"],
            "invalidates": item["invalidation_targets"],
            "sample_count": item["sample_count"],
            "measurement_environment_id": item["measurement_environment_id"],
        }
        existing = matrix.setdefault(kind, {}).setdefault(source, {}).get(target)
        if existing is None or float(entry["direct_ms"]) < float(existing["direct_ms"]):
            matrix[kind][source][target] = entry
    return matrix


ZERO_START_BENCHMARKS_BY_KIND = {
    "build_cache": {"EXACT-BUILD-CACHE-COLD"},
    "database_private_layer": {"DBS-007"},
    "dependency_view": {"DEP-001", "DEP-002", "DEP-003", "DEP-004", "DEP-006", "INS-001", "EXACT-DEP-MATERIALIZE"},
    "native_binary_bundle": {"EXACT-NATIVE-LOAD"},
    "home_tmp_xdg": {"FS-005"},
    "network_ports": {"NET-003"},
    "node_runtime": {"RUN-003", "RUN-007", "RUN-008", "RUN-009"},
    "package_manager": {"PM-007", "RUN-005"},
    "repo_baseline": {"EXACT-REPO-MATERIALIZE"},
    "rootfs": {"EXACT-ROOTFS-CREATE"},
    "source_overlay": {"EXACT-SOURCE-MATERIALIZE"},
    "system_toolchain": set(),
    "task_harness": {"TSK-003"},
    "test_transform_cache": {"EXACT-TEST-CACHE-COLD"},
}

ZERO_START_TRANSITION_CLASSES = {"artifact_cold", "network_cold", "process_cold"}
ZERO_START_EXCLUDED_BENCHMARKS = {"ART-008"}


def append_sliding_window(values: list[float], value: float, window_size: int) -> list[float]:
    if window_size < 1:
        raise ValueError("direct_ms window size must be positive")
    return [*values, float(value)][-window_size:]


def _numeric_window(value: Any) -> list[float]:
    values = value if isinstance(value, list) else [value]
    return [float(item) for item in values if isinstance(item, (int, float)) and not isinstance(item, bool)]


def _zero_start_detail(item: dict[str, Any], value_key: str) -> dict[str, Any]:
    return {
        "benchmark_id": item["benchmark_id"],
        "scenario_name": item["scenario_name"],
        "resource_kind": item["resource_kind"],
        "object_name": item["object_name"],
        "version_config": item["to_version/config"],
        value_key: float(item["median_ms"]),
        "p95_ms": item["p95_ms"],
        "sample_count": item["sample_count"],
        "success_count": item["success_count"],
        "failure_count": item["failure_count"],
        "workload_origin": item["workload_origin"],
    }


def build_direct_ms(
    summaries: list[dict[str, Any]],
    objects: list[dict[str, Any]],
    environment: dict[str, Any],
    existing: dict[str, Any] | None = None,
    window_size: int = DEFAULT_DIRECT_MS_WINDOW_SIZE,
) -> dict[str, Any]:
    if window_size < 1:
        raise ValueError("direct_ms window size must be positive")
    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    selected: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in summaries:
        if item.get("median_ms") is None or not item.get("reuse_safe") or item.get("pollution_result") == "fail":
            continue
        object_id = str(item["to_object_id"])
        kind = str(item["resource_kind"])
        starts_from_zero = item.get("from_object_id") is None
        is_cold_candidate = (
            starts_from_zero
            and item.get("transition_class") in ZERO_START_TRANSITION_CLASSES
            and item.get("benchmark_id") not in ZERO_START_EXCLUDED_BENCHMARKS
        )
        if is_cold_candidate:
            candidates[object_id].append(item)
        policy = ZERO_START_BENCHMARKS_BY_KIND.get(kind)
        if policy is not None:
            if starts_from_zero and item.get("benchmark_id") in policy:
                selected[object_id].append(item)
        elif is_cold_candidate:
            selected[object_id].append(item)

    current_values: dict[str, float] = {}
    current_details: dict[str, dict[str, Any]] = {}
    current_measurement_ids: dict[str, str] = {}
    ambiguous_objects: dict[str, list[dict[str, Any]]] = {}
    for object_id in sorted(set(candidates) | set(selected)):
        object_candidates = selected.get(object_id, [])
        if len(object_candidates) == 1:
            item = object_candidates[0]
            current_values[object_id] = float(item["median_ms"])
            current_details[object_id] = _zero_start_detail(item, "latest_ms")
            current_measurement_ids[object_id] = str(item["_measurement_id"])
            continue
        ambiguity = object_candidates or candidates.get(object_id, [])
        if ambiguity:
            ambiguous_objects[object_id] = [_zero_start_detail(item, "candidate_ms") for item in ambiguity]

    object_ids = {str(item["object_id"]) for item in objects}
    direct_ms: dict[str, list[float]] = {}
    measurement_ids: dict[str, list[str]] = {}
    existing = existing or {}
    if existing.get("schema_version") == 2:
        existing_windows = existing.get("direct_ms") if isinstance(existing.get("direct_ms"), dict) else {}
        existing_measurement_ids = existing.get("measurement_ids") if isinstance(existing.get("measurement_ids"), dict) else {}
        for object_id, raw_window in existing_windows.items():
            if object_id not in object_ids:
                continue
            values = _numeric_window(raw_window)
            if not values:
                continue
            raw_ids = existing_measurement_ids.get(object_id, [])
            ids = [str(item) for item in raw_ids] if isinstance(raw_ids, list) else []
            if len(ids) != len(values):
                ids = [
                    stable_hash({"legacy_object_id": object_id, "position": index, "value_ms": value})
                    for index, value in enumerate(values)
                ]
            direct_ms[object_id] = values[-window_size:]
            measurement_ids[object_id] = ids[-window_size:]

    details: dict[str, dict[str, Any]] = {}
    for object_id, value in current_values.items():
        values = direct_ms.get(object_id, [])
        ids = measurement_ids.get(object_id, [])
        measurement_id = current_measurement_ids[object_id]
        if measurement_id not in ids:
            values = append_sliding_window(values, value, window_size)
            ids = [*ids, measurement_id][-window_size:]
        direct_ms[object_id] = values
        measurement_ids[object_id] = ids
        details[object_id] = {
            **current_details[object_id],
            "latest_ms": values[-1],
            "window_length": len(values),
        }

    measured_ids = {object_id for object_id, values in direct_ms.items() if values}
    unmeasured_counts = Counter(
        str(item.get("resource_kind") or "unknown")
        for item in objects
        if str(item["object_id"]) not in measured_ids
    )
    return {
        "schema_version": 2,
        "unit": "ms",
        "statistic": "median_per_measurement_batch",
        "definition": "direct_ms[object_id] is an oldest-to-newest sliding window of measured times to bring that object from zero to ready",
        "zero_state": "the object is absent, not running, or not materialized",
        "window_size": window_size,
        "window_order": "oldest_to_newest",
        "window_policy": "append one median for each new measurement batch and evict the oldest value with FIFO when full",
        "measurement_environment_id": environment.get("measurement_environment_id"),
        "object_count": len(object_ids),
        "measured_object_count": len(direct_ms),
        "window_value_count": sum(len(values) for values in direct_ms.values()),
        "ambiguous_object_count": len(ambiguous_objects),
        "unmeasured_object_count": len(object_ids - measured_ids),
        "missing_value_semantics": "missing means unmeasured or not uniquely defined, never zero",
        "transition_costs_path": "object_cost_matrix.json",
        "direct_ms": direct_ms,
        "measurement_ids": measurement_ids,
        "details": details,
        "ambiguous_objects": ambiguous_objects,
        "unmeasured_counts_by_resource_kind": dict(sorted(unmeasured_counts.items())),
    }


def _summary_csv_rows(summaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for item in summaries:
        row = dict(item)
        row["invalidation_targets"] = ";".join(item.get("invalidation_targets", []))
        rows.append(row)
    return rows


def _coverage_markdown(catalog: list[BenchmarkSpec], status: dict[str, Any], observations: list[dict[str, Any]]) -> str:
    counts = Counter(value.get("status", "missing") for value in status.values())
    observed_ids = {item.get("benchmark_id") for item in observations}
    lines = [
        "# NodeLite 第一阶段 Benchmark Coverage",
        "",
        f"- Catalog IDs: {len(catalog)}",
        f"- Accounted IDs: {len(status)}",
        f"- IDs with observations: {len(observed_ids)}",
        f"- Coverage: {len(status) / len(catalog) * 100:.1f}%",
        "- Status counts: " + ", ".join(f"`{key}`={value}" for key, value in sorted(counts.items())),
        "",
        "| Benchmark ID | Group | Priority | Status | Reason |",
        "|---|---|---|---|---|",
    ]
    for spec in catalog:
        value = status.get(spec.benchmark_id, {"status": "missing", "reason": "not accounted"})
        reason = str(value.get("reason") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{spec.benchmark_id}` | {spec.group} | {spec.priority} | `{value['status']}` | {reason} |")
    return "\n".join(lines) + "\n"


def _environment_gaps(status: dict[str, Any], summaries: list[dict[str, Any]], objects: list[dict[str, Any]]) -> str:
    lines = ["# Measurement Environment Gaps", "", "The following benchmark IDs have no fabricated latency value. They remain explicit gaps for a capable host.", "", "| Benchmark ID | Status | Required capability / reason |", "|---|---|---|"]
    for benchmark_id, value in sorted(status.items()):
        if value.get("status") not in {"blocked", "unsupported", "manual_review"}:
            continue
        reason = str(value.get("reason") or "").replace("|", "\\|").replace("\n", " ")
        lines.append(f"| `{benchmark_id}` | `{value['status']}` | {reason} |")
    summarized_objects: set[str] = set()
    for item in summaries:
        if item.get("median_ms") is not None:
            continue
        object_id = str(item.get("to_object_id") or "unknown").replace("|", "\\|")
        summarized_objects.add(str(item.get("to_object_id") or "unknown"))
        lines.append(
            f"| `{item['benchmark_id']}` | `scenario_gap` | `{object_id}` / `{item['scenario_name']}` has no successful sample; exact executable/cache evidence is unavailable or the measured action failed. |"
        )
    for item in objects:
        object_id = str(item.get("object_id") or "unknown")
        if item.get("resource_kind") not in {"package_manager", "pm_native_cache"} or item.get("source", {}).get("available") or object_id in summarized_objects:
            continue
        evidence = str(item.get("source", {}).get("evidence") or "inventory evidence").replace("|", "\\|")
        lines.append(f"| `PM/PMC` | `object_gap` | `{object_id}` is retained from {evidence}, but no exact executable/cache path/version is available for latency measurement. |")
    return "\n".join(lines) + "\n"


def _cost_table(summaries: list[dict[str, Any]], status: dict[str, Any], object_counts: Counter[str]) -> str:
    measured = [item for item in summaries if item.get("median_ms") is not None]
    largest = sorted(measured, key=lambda item: float(item["median_ms"]), reverse=True)[:20]
    reusable_kinds = {
        "browser_context",
        "browser_process",
        "browser_profile",
        "build_cache",
        "database_clean_snapshot",
        "database_daemon",
        "database_private_layer",
        "dependency_view",
        "home_tmp_xdg",
        "native_binary_bundle",
        "package_manager",
        "pm_native_cache",
        "project_server",
        "raw_cas",
        "repo_baseline",
        "rootfs",
        "source_overlay",
        "test_transform_cache",
    }
    lifecycle_families = {"INS": "DEP", "DBS": "DB"}
    cold_by_object: dict[tuple[str, str], dict[str, Any]] = {}
    reuse_by_object: dict[tuple[str, str], dict[str, Any]] = {}
    for item in measured:
        object_id = str(item.get("to_object_id") or "")
        if not object_id or item.get("resource_kind") not in reusable_kinds:
            continue
        prefix = str(item.get("benchmark_id") or "").split("-", 1)[0]
        family = lifecycle_families.get(prefix, prefix)
        key = (object_id, family)
        if item.get("transition_class") in {"artifact_cold", "network_cold", "process_cold"}:
            previous = cold_by_object.get(key)
            if previous is None or float(item["median_ms"]) > float(previous["median_ms"]):
                cold_by_object[key] = item
        if item.get("reuse_safe") and item.get("transition_class") in {"exact_hit", "compatible_reuse", "dirty_reset"}:
            previous = reuse_by_object.get(key)
            if previous is None or float(item["median_ms"]) < float(previous["median_ms"]):
                reuse_by_object[key] = item
    reuse = []
    for object_id, family in sorted(cold_by_object.keys() & reuse_by_object.keys()):
        cold = cold_by_object[(object_id, family)]
        hit = reuse_by_object[(object_id, family)]
        saved_ms = float(cold["median_ms"]) - float(hit["median_ms"])
        if saved_ms > 0:
            reuse.append({"object_id": object_id, "cold": cold, "reuse": hit, "saved_ms": saved_ms})
    reuse.sort(key=lambda item: item["saved_ms"], reverse=True)
    reuse = reuse[:20]
    lines = [
        "# 第一阶段 Object Cost 计算表",
        "",
        "> 所有数值均来自本机实际 observation；缺失能力不填 0，而在 coverage/environment gaps 中标注。Scheduler 查询默认使用 `median_ms`，稳健策略可查询 `p95_ms`。`direct_ms` 只包含 object 自己拥有的动作，不包含 invalidated object 的重建时间。",
        "",
        "## 总览",
        "",
        f"- Measured transition summaries: {len(measured)}",
        f"- Catalog status: " + ", ".join(f"`{key}`={value}" for key, value in sorted(Counter(value.get('status') for value in status.values()).items())),
        f"- Objects by kind: " + ", ".join(f"`{key}`={value}" for key, value in sorted(object_counts.items())),
        "",
        "## 完整 Cost 表",
        "",
        "| Benchmark | Resource kind | Object / transition | Class | Cost class | Median ms | P95 ms | Samples | Reuse safe | Invalidates |",
        "|---|---|---|---|---|---:|---:|---:|---|---|",
    ]
    for item in sorted(measured, key=lambda row: (row["benchmark_id"], row["object_name"], row["from_object_id"] or "")):
        transition = f"{item.get('from_version/config', 'cold')} → {item.get('to_version/config')} ({item.get('object_name')})".replace("|", "\\|")
        invalidates = ", ".join(item.get("invalidation_targets", [])) or "—"
        lines.append(f"| `{item['benchmark_id']}` | `{item['resource_kind']}` | {transition} | `{item['transition_class']}` | `{item['cost_class']}` | {float(item['median_ms']):.3f} | {float(item['p95_ms']):.3f} | {item['sample_count']} | {str(item['reuse_safe']).lower()} | {invalidates} |")
    lines.extend(["", "## 最大的 20 个 Direct Cost", "", "| Rank | Benchmark | Object / transition | Median ms | P95 ms |", "|---:|---|---|---:|---:|"])
    for index, item in enumerate(largest, start=1):
        lines.append(f"| {index} | `{item['benchmark_id']}` | {item.get('from_version/config')} → {item.get('to_version/config')} ({item.get('object_name')}) | {float(item['median_ms']):.3f} | {float(item['p95_ms']):.3f} |")
    lines.extend(["", "## 最值得复用的 20 个 Object（Cold - Reuse/Reset）", "", "| Rank | Object | Cold benchmark / ms | Safe reuse benchmark / ms | Estimated saved ms |", "|---:|---|---:|---:|---:|"])
    for index, item in enumerate(reuse, start=1):
        cold = item["cold"]
        hit = item["reuse"]
        lines.append(f"| {index} | `{item['object_id']}` ({cold.get('object_name')}) | `{cold['benchmark_id']}` / {float(cold['median_ms']):.3f} | `{hit['benchmark_id']}` / {float(hit['median_ms']):.3f} | {item['saved_ms']:.3f} |")
    return "\n".join(lines) + "\n"


def generate_reports(
    output: Path,
    catalog: list[BenchmarkSpec],
    environment: dict[str, Any],
    direct_ms_window_size: int = DEFAULT_DIRECT_MS_WINDOW_SIZE,
) -> dict[str, Any]:
    raw_observations = read_jsonl(output / "costdb" / "object_costs.jsonl")
    latest_observations = _latest_observations(raw_observations)
    active_scenarios = read_json(output / "benchmarks" / "active_scenarios.json", {}) or {}
    observations = _active_observations(latest_observations, active_scenarios)
    object_values = read_json(output / "costdb" / "objects.json", []) or []
    objects = {item["object_id"]: item for item in object_values}
    status = read_json(output / "benchmarks" / "catalog_status.json", {}) or {}
    summaries = build_summaries(observations, objects)
    matrix = build_matrix(summaries)
    direct_ms_path = output / "costdb" / "direct_ms.json"
    existing_direct_ms = read_json(direct_ms_path, {}) or {}
    direct_ms_data = build_direct_ms(
        summaries,
        object_values,
        environment,
        existing=existing_direct_ms,
        window_size=direct_ms_window_size,
    )
    rules = invalidation_rules()
    failures = [item for item in observations if str(item.get("benchmark_id", "")).startswith("FAIL-") or item.get("transition_class") == "failure_path"]
    contention = [item for item in observations if str(item.get("benchmark_id", "")).startswith("CON-") or item.get("transition_class") == "contention_path"]
    write_json(output / "costdb" / "object_cost_matrix.json", matrix)
    write_json(direct_ms_path, direct_ms_data)
    write_json(output / "costdb" / "invalidation_rules.json", rules)
    write_json(
        output / "costdb" / "resource_summaries.json",
        [{key: value for key, value in item.items() if key != "_measurement_id"} for item in summaries],
    )
    write_json(output / "costdb" / "failure_costs.json", failures)
    write_json(output / "costdb" / "contention_costs.json", contention)
    write_json(output / "benchmarks" / "invalidation_rules.json", rules)
    write_json(output / "measurement_environment.json", environment)
    write_csv(output / "reports" / "object_costs.csv", sorted({key for row in observations for key in row if key != "details"}), observations)
    summary_rows = _summary_csv_rows(summaries)
    write_csv(output / "reports" / "object_switch_matrix.csv", SUMMARY_FIELDS, summary_rows)
    write_csv(output / "reports" / "object_latency_summary.csv", SUMMARY_FIELDS, summary_rows)
    (output / "reports" / "coverage.md").write_text(_coverage_markdown(catalog, status, observations), encoding="utf-8")
    (output / "reports" / "environment_gaps.md").write_text(_environment_gaps(status, summaries, object_values), encoding="utf-8")
    object_counts = Counter(item.get("resource_kind") for item in object_values)
    (output / "reports" / "第一阶段_OBJECT_COST_TABLE.md").write_text(_cost_table(summaries, status, object_counts), encoding="utf-8")
    result = {
        "catalog_count": len(catalog),
        "accounted_count": len(status),
        "coverage_percent": len(status) / len(catalog) * 100 if catalog else 0,
        "object_count": len(object_values),
        "object_counts": dict(sorted(object_counts.items())),
        "observation_count": len(observations),
        "raw_observation_count": len(raw_observations),
        "superseded_observation_count": len(latest_observations) - len(observations),
        "directed_transition_count": len(summaries),
        "direct_ms_object_count": direct_ms_data["measured_object_count"],
        "direct_ms_ambiguous_object_count": direct_ms_data["ambiguous_object_count"],
        "direct_ms_window_size": direct_ms_data["window_size"],
        "direct_ms_window_value_count": direct_ms_data["window_value_count"],
        "direct_ms_path": "costdb/direct_ms.json",
        "status_counts": dict(sorted(Counter(value.get("status") for value in status.values()).items())),
        "pollution_failure_count": sum(item.get("pollution_result") == "fail" for item in summaries),
        "measurement_environment_id": environment.get("measurement_environment_id"),
    }
    write_json(output / "reports" / "run_summary.json", result)
    return result
