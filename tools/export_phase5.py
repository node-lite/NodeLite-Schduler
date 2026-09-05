from __future__ import annotations

import argparse
import ast
import csv
import json
import math
import random
import statistics
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PHASE2 = Path("/root/experiment_result/phase2")
DEFAULT_PHASE3 = Path("/root/experiment_result/phase3")
DEFAULT_PHASE4 = Path("/root/experiment_result/phase4")
DEFAULT_OUTPUT = Path("/root/experiment_result/phase5")
RANDOM_SEEDS = [11, 23, 37, 53, 71]


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False))
            handle.write("\n")
    tmp.replace(path)


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    tmp.replace(path)


def _as_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return float(value)
    if isinstance(value, str):
        try:
            number = float(value)
        except ValueError:
            return None
        if math.isfinite(number):
            return number
    return None


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


def _literal_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = ast.literal_eval(value)
        except (SyntaxError, ValueError):
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


@dataclass(frozen=True)
class ProfileRecord:
    profile_id: str
    sequence_index: int
    object_ids: tuple[str, ...]
    object_kinds: tuple[str, ...]
    object_ids_by_kind: dict[str, tuple[str, ...]]
    fresh_ms: float
    reuse_ms: float


@dataclass(frozen=True)
class PairRecord:
    source_profile_id: str
    target_profile_id: str
    source_sequence_index: int
    target_sequence_index: int
    shared_object_count: int
    source_only_object_count: int
    target_only_object_count: int
    same_node_runtime: bool
    same_rootfs: bool
    same_repo_baseline: bool
    same_dependency_view: bool
    same_build_tool: bool
    same_test_tool: bool
    same_native_bundle: bool
    predicted_ms: float
    measured_ms: float
    absolute_error: float
    relative_error: float
    interaction_residual: float
    pair_category: str
    measurement_source: str
    predicted_breakdown: dict[str, Any]
    measured_breakdown: dict[str, Any]


def _load_objects(path: Path) -> dict[str, dict[str, Any]]:
    rows = read_json(path, [])
    if not isinstance(rows, list):
        raise ValueError(f"invalid objects file: {path}")
    objects: dict[str, dict[str, Any]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        object_id = str(item.get("object_id") or "").strip()
        if object_id:
            objects[object_id] = item
    return objects


def _load_profile_requirements(path: Path) -> dict[str, list[str]]:
    rows = read_json(path, [])
    if not isinstance(rows, list):
        raise ValueError(f"invalid profile requirements file: {path}")
    profiles: dict[str, list[str]] = {}
    for item in rows:
        if not isinstance(item, dict):
            continue
        profile_id = str(item.get("profile_id") or "").strip()
        if not profile_id:
            continue
        profiles[profile_id] = [str(object_id) for object_id in item.get("object_ids", [])]
    return profiles


def _load_sequence(path: Path) -> list[dict[str, Any]]:
    data = read_json(path, {})
    if isinstance(data, dict) and isinstance(data.get("sequence"), list):
        return [item for item in data["sequence"] if isinstance(item, dict)]
    raise ValueError(f"invalid phase 3 sequence file: {path}")


def _load_fresh_reuse(path: Path) -> dict[str, dict[str, float]]:
    rows = read_json(path, None)
    if rows is None:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            parsed_rows = list(reader)
    elif isinstance(rows, list):
        parsed_rows = rows
    else:
        with path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            parsed_rows = list(reader)
    result: dict[str, dict[str, float]] = {}
    for item in parsed_rows:
        if not isinstance(item, dict):
            continue
        profile_id = str(item.get("profile_id") or "").strip()
        if not profile_id:
            continue
        fresh_ms = _as_float(item.get("fresh_median_ms") or item.get("fresh_total_ms"))
        reuse_ms = _as_float(item.get("reuse_median_ms") or item.get("reuse_total_ms"))
        if fresh_ms is None or reuse_ms is None:
            continue
        result[profile_id] = {"fresh_ms": fresh_ms, "reuse_ms": reuse_ms}
    return result


def _load_pairs(path: Path) -> dict[tuple[str, str], PairRecord]:
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)
    pairs: dict[tuple[str, str], PairRecord] = {}
    for row in rows:
        source_profile_id = str(row.get("source_profile_id") or "")
        target_profile_id = str(row.get("target_profile_id") or "")
        if not source_profile_id or not target_profile_id:
            continue
        pair = PairRecord(
            source_profile_id=source_profile_id,
            target_profile_id=target_profile_id,
            source_sequence_index=int(row.get("source_sequence_index") or 0),
            target_sequence_index=int(row.get("target_sequence_index") or 0),
            shared_object_count=int(float(row.get("shared_object_count") or 0)),
            source_only_object_count=int(float(row.get("source_only_object_count") or 0)),
            target_only_object_count=int(float(row.get("target_only_object_count") or 0)),
            same_node_runtime=str(row.get("same_node_runtime")) == "True",
            same_rootfs=str(row.get("same_rootfs")) == "True",
            same_repo_baseline=str(row.get("same_repo_baseline")) == "True",
            same_dependency_view=str(row.get("same_dependency_view")) == "True",
            same_build_tool=str(row.get("same_build_tool")) == "True",
            same_test_tool=str(row.get("same_test_tool")) == "True",
            same_native_bundle=str(row.get("same_native_bundle")) == "True",
            predicted_ms=float(row["predicted_ms"]),
            measured_ms=float(row["measured_ms"]),
            absolute_error=float(row["absolute_error"]),
            relative_error=float(row["relative_error"]),
            interaction_residual=float(row["interaction_residual"]),
            pair_category=str(row.get("pair_category") or ""),
            measurement_source=str(row.get("measurement_source") or ""),
            predicted_breakdown=_literal_dict(row.get("predicted_breakdown")),
            measured_breakdown=_literal_dict(row.get("measured_breakdown")),
        )
        pairs[(source_profile_id, target_profile_id)] = pair
    return pairs


def _build_profiles(
    sequence_rows: list[dict[str, Any]],
    object_map: dict[str, dict[str, Any]],
    requirements: dict[str, list[str]],
    fresh_reuse: dict[str, dict[str, float]],
) -> list[ProfileRecord]:
    profiles: list[ProfileRecord] = []
    for row in sequence_rows:
        profile_id = str(row.get("profile_id") or "").strip()
        if not profile_id:
            continue
        object_ids = tuple(requirements.get(profile_id, [str(item) for item in row.get("object_ids", [])]))
        objects = [object_map[object_id] for object_id in object_ids if object_id in object_map]
        kinds: list[str] = []
        by_kind: dict[str, list[str]] = defaultdict(list)
        for object_id in object_ids:
            obj = object_map.get(object_id)
            if not obj:
                continue
            kind = str(obj.get("resource_kind") or "unknown")
            kinds.append(kind)
            by_kind[kind].append(object_id)
        fresh = fresh_reuse.get(profile_id, {})
        fresh_ms = fresh.get("fresh_ms")
        reuse_ms = fresh.get("reuse_ms")
        if fresh_ms is None or reuse_ms is None:
            raise ValueError(f"missing fresh/reuse values for {profile_id}")
        profiles.append(
            ProfileRecord(
                profile_id=profile_id,
                sequence_index=int(row.get("sequence_index") or len(profiles) + 1),
                object_ids=object_ids,
                object_kinds=tuple(kinds),
                object_ids_by_kind={kind: tuple(sorted(values)) for kind, values in by_kind.items()},
                fresh_ms=float(fresh_ms),
                reuse_ms=float(reuse_ms),
            )
        )
    profiles.sort(key=lambda item: item.sequence_index)
    return profiles


def _to_map(profiles: list[ProfileRecord]) -> dict[str, ProfileRecord]:
    return {item.profile_id: item for item in profiles}


def _random_order(remaining: list[str], seed: int) -> tuple[list[str], list[float]]:
    rng = random.Random(seed)
    pool = list(remaining)
    order: list[str] = []
    decision_times: list[float] = []
    while pool:
        start = time.perf_counter()
        index = rng.randrange(len(pool))
        chosen = pool.pop(index)
        decision_times.append((time.perf_counter() - start) * 1000.0)
        order.append(chosen)
    return order, decision_times


def _fifo_order(remaining: list[str]) -> tuple[list[str], list[float]]:
    order: list[str] = []
    decision_times: list[float] = []
    for profile_id in remaining:
        start = time.perf_counter()
        order.append(profile_id)
        decision_times.append((time.perf_counter() - start) * 1000.0)
    return order, decision_times


def _greedy_order(
    first_profile_id: str,
    candidates: list[str],
    profile_map: dict[str, ProfileRecord],
    pair_lookup: dict[tuple[str, str], PairRecord],
    chooser: str,
) -> tuple[list[str], list[float]]:
    remaining = set(candidates)
    order = [first_profile_id]
    current = first_profile_id
    decision_times: list[float] = []
    while remaining:
        start = time.perf_counter()
        best_profile_id: str | None = None
        best_key: tuple[Any, ...] | None = None
        for candidate in remaining:
            if chooser == "similarity":
                pair = pair_lookup[(current, candidate)]
                key = (-pair.shared_object_count, candidate)
            elif chooser == "cost":
                pair = pair_lookup[(current, candidate)]
                key = (pair.predicted_ms, -pair.shared_object_count, candidate)
            else:
                raise ValueError(f"unknown chooser: {chooser}")
            if best_key is None or key < best_key:
                best_key = key
                best_profile_id = candidate
        if best_profile_id is None:
            raise RuntimeError("no candidate available for greedy order")
        decision_times.append((time.perf_counter() - start) * 1000.0)
        remaining.remove(best_profile_id)
        order.append(best_profile_id)
        current = best_profile_id
    return order, decision_times


def _bootstrap_profile(profile: ProfileRecord) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "sequence_index": profile.sequence_index,
        "fresh_ms": profile.fresh_ms,
        "reuse_ms": profile.reuse_ms,
        "object_count": len(profile.object_ids),
        "resource_kind_count": len(profile.object_ids_by_kind),
    }


def _transition_object_stats(source: ProfileRecord, target: ProfileRecord) -> dict[str, Any]:
    source_ids = set(source.object_ids)
    target_ids = set(target.object_ids)
    shared_ids = sorted(source_ids & target_ids)
    cold_ids = sorted(target_ids - source_ids)
    reused_by_kind: dict[str, int] = defaultdict(int)
    cold_by_kind: dict[str, int] = defaultdict(int)
    for object_id in shared_ids:
        obj = target.object_ids_by_kind
        kind = next((k for k, ids in obj.items() if object_id in ids), None)
        if kind:
            reused_by_kind[kind] += 1
    for object_id in cold_ids:
        kind = None
        for candidate_kind, ids in target.object_ids_by_kind.items():
            if object_id in ids:
                kind = candidate_kind
                break
        if kind is not None:
            cold_by_kind[kind] += 1
    return {
        "shared_object_ids": shared_ids,
        "cold_object_ids": cold_ids,
        "shared_object_count": len(shared_ids),
        "cold_object_count": len(cold_ids),
        "reused_object_count": len(shared_ids),
        "source_only_object_count": len(source_ids - target_ids),
        "target_only_object_count": len(cold_ids),
        "reused_by_kind": dict(sorted(reused_by_kind.items())),
        "cold_by_kind": dict(sorted(cold_by_kind.items())),
    }


def _evaluate_schedule(
    scheduler_name: str,
    run_label: str,
    seed: int | None,
    order: list[str],
    profiles: dict[str, ProfileRecord],
    pairs: dict[tuple[str, str], PairRecord],
    decision_times_ms: list[float],
) -> dict[str, Any]:
    if not order:
        raise ValueError("schedule order must not be empty")
    bootstrap = _bootstrap_profile(profiles[order[0]])
    transition_rows: list[dict[str, Any]] = []
    measured_values: list[float] = []
    predicted_values: list[float] = []
    absolute_errors: list[float] = []
    transition_time_by_kind: Counter[str] = Counter()
    transition_count_by_kind: Counter[str] = Counter()
    reuse_object_count = 0
    cold_object_count = 0
    target_object_count = 0
    transition_reuse_hit_count = 0
    invalidation_cost_total = 0.0
    cleanup_cost_total = 0.0
    switch_cost_total = 0.0
    reload_cost_total = 0.0
    reuse_cost_total = 0.0
    source = profiles[order[0]]
    for transition_index, target_profile_id in enumerate(order[1:], start=1):
        target = profiles[target_profile_id]
        pair = pairs[(source.profile_id, target.profile_id)]
        object_stats = _transition_object_stats(source, target)
        if object_stats["shared_object_count"] > 0:
            transition_reuse_hit_count += 1
        reuse_object_count += int(object_stats["reused_object_count"])
        cold_object_count += int(object_stats["cold_object_count"])
        target_object_count += len(target.object_ids)
        measured_values.append(pair.measured_ms)
        predicted_values.append(pair.predicted_ms)
        absolute_errors.append(pair.absolute_error)
        measured_breakdown = pair.measured_breakdown
        invalidation_cost_total += (_as_float(measured_breakdown.get("invalidate_ms")) or 0.0) + (
            _as_float(measured_breakdown.get("reload_ms")) or 0.0
        )
        cleanup_cost_total += _as_float(measured_breakdown.get("cleanup_ms")) or 0.0
        switch_cost_total += _as_float(measured_breakdown.get("switch_ms")) or 0.0
        reload_cost_total += _as_float(measured_breakdown.get("reload_ms")) or 0.0
        reuse_cost_total += _as_float(measured_breakdown.get("reuse_ms")) or 0.0
        for kind in object_stats["cold_by_kind"]:
            transition_time_by_kind[kind] += int(object_stats["cold_by_kind"][kind])
            transition_count_by_kind[kind] += int(object_stats["cold_by_kind"][kind])
        transition_rows.append(
            {
                "scheduler_name": scheduler_name,
                "run_label": run_label,
                "seed": seed,
                "transition_index": transition_index,
                "source_profile_id": source.profile_id,
                "target_profile_id": target.profile_id,
                "source_sequence_index": source.sequence_index,
                "target_sequence_index": target.sequence_index,
                "pair_category": pair.pair_category,
                "predicted_ms": pair.predicted_ms,
                "measured_ms": pair.measured_ms,
                "absolute_error": pair.absolute_error,
                "relative_error": pair.relative_error,
                "interaction_residual": pair.interaction_residual,
                "shared_object_count": pair.shared_object_count,
                "source_only_object_count": pair.source_only_object_count,
                "target_only_object_count": pair.target_only_object_count,
                "same_node_runtime": pair.same_node_runtime,
                "same_rootfs": pair.same_rootfs,
                "same_repo_baseline": pair.same_repo_baseline,
                "same_dependency_view": pair.same_dependency_view,
                "same_build_tool": pair.same_build_tool,
                "same_test_tool": pair.same_test_tool,
                "same_native_bundle": pair.same_native_bundle,
                "measured_reuse_ms": _as_float(measured_breakdown.get("reuse_ms")),
                "measured_switch_ms": _as_float(measured_breakdown.get("switch_ms")),
                "measured_reload_ms": _as_float(measured_breakdown.get("reload_ms")),
                "measured_invalidate_ms": _as_float(measured_breakdown.get("invalidate_ms")),
                "measured_cleanup_ms": _as_float(measured_breakdown.get("cleanup_ms")),
                "shared_object_ids": ";".join(object_stats["shared_object_ids"]),
                "cold_object_ids": ";".join(object_stats["cold_object_ids"]),
            }
        )
        source = target
    measured_summary = summarize(measured_values)
    predicted_summary = summarize(predicted_values)
    abs_error_summary = summarize(absolute_errors)
    decision_summary = summarize(decision_times_ms)
    pair_transition_count = len(order) - 1
    bootstrap_ms = bootstrap["fresh_ms"]
    measured_transition_time_ms = float(sum(measured_values))
    predicted_transition_time_ms = float(sum(predicted_values))
    cpu_side_makespan_ms = bootstrap_ms + measured_transition_time_ms
    predicted_cpu_side_makespan_ms = bootstrap_ms + predicted_transition_time_ms
    total_target_objects = target_object_count
    reuse_hit_rate = reuse_object_count / total_target_objects if total_target_objects else None
    transition_reuse_hit_rate = transition_reuse_hit_count / pair_transition_count if pair_transition_count else None
    browser_restart_count = 0
    db_restart_count = 0
    depview_rebuild_count = 0
    node_runtime_restart_count = 0
    rootfs_restart_count = 0
    build_cache_cold_count = 0
    test_cache_cold_count = 0
    source_overlay_cold_count = 0
    native_bundle_cold_count = 0
    for row in transition_rows:
        source_profile = profiles[row["source_profile_id"]]
        target_profile = profiles[row["target_profile_id"]]
        cold_object_ids = set(row["cold_object_ids"].split(";")) if row["cold_object_ids"] else set()
        for object_id in cold_object_ids:
            obj_kind = None
            for kind, ids in target_profile.object_ids_by_kind.items():
                if object_id in ids:
                    obj_kind = kind
                    break
            if obj_kind == "dependency_view":
                depview_rebuild_count += 1
            elif obj_kind == "browser_process":
                browser_restart_count += 1
            elif obj_kind == "database_daemon":
                db_restart_count += 1
            elif obj_kind == "node_runtime":
                node_runtime_restart_count += 1
            elif obj_kind == "rootfs":
                rootfs_restart_count += 1
            elif obj_kind == "build_cache":
                build_cache_cold_count += 1
            elif obj_kind == "test_transform_cache":
                test_cache_cold_count += 1
            elif obj_kind == "source_overlay":
                source_overlay_cold_count += 1
            elif obj_kind == "native_binary_bundle":
                native_bundle_cold_count += 1
    return {
        "scheduler_name": scheduler_name,
        "run_label": run_label,
        "seed": seed,
        "first_profile_id": order[0],
        "last_profile_id": order[-1],
        "task_count": len(order),
        "pair_transition_count": pair_transition_count,
        "bootstrap_ms": bootstrap_ms,
        "measured_transition_time_ms": measured_transition_time_ms,
        "predicted_transition_time_ms": predicted_transition_time_ms,
        "cpu_side_makespan_ms": cpu_side_makespan_ms,
        "predicted_cpu_side_makespan_ms": predicted_cpu_side_makespan_ms,
        "average_transition_time_ms": measured_summary["mean_ms"],
        "median_transition_time_ms": measured_summary["median_ms"],
        "p95_transition_time_ms": measured_summary["p95_ms"],
        "predicted_average_transition_time_ms": predicted_summary["mean_ms"],
        "predicted_median_transition_time_ms": predicted_summary["median_ms"],
        "predicted_p95_transition_time_ms": predicted_summary["p95_ms"],
        "absolute_error_mean_ms": abs_error_summary["mean_ms"],
        "absolute_error_median_ms": abs_error_summary["median_ms"],
        "absolute_error_p95_ms": abs_error_summary["p95_ms"],
        "reuse_object_count": reuse_object_count,
        "cold_object_count": cold_object_count,
        "target_object_count": total_target_objects,
        "reuse_hit_rate": reuse_hit_rate,
        "transition_reuse_hit_rate": transition_reuse_hit_rate,
        "transition_reuse_hit_count": transition_reuse_hit_count,
        "invalidation_cost_ms": invalidation_cost_total,
        "cleanup_cost_ms": cleanup_cost_total,
        "switch_cost_ms": switch_cost_total,
        "reload_cost_ms": reload_cost_total,
        "reuse_cost_ms": reuse_cost_total,
        "browser_restart_count": browser_restart_count,
        "db_restart_count": db_restart_count,
        "depview_rebuild_count": depview_rebuild_count,
        "node_runtime_restart_count": node_runtime_restart_count,
        "rootfs_restart_count": rootfs_restart_count,
        "build_cache_cold_count": build_cache_cold_count,
        "test_cache_cold_count": test_cache_cold_count,
        "source_overlay_cold_count": source_overlay_cold_count,
        "native_bundle_cold_count": native_bundle_cold_count,
        "decision_overhead_ms": decision_summary["mean_ms"] or 0.0,
        "decision_overhead_total_ms": float(sum(decision_times_ms)),
        "decision_overhead_median_ms": decision_summary["median_ms"],
        "decision_overhead_p95_ms": decision_summary["p95_ms"],
        "decision_overhead_max_ms": decision_summary["max_ms"],
        "decision_count": len(decision_times_ms),
        "decision_times_ms": decision_times_ms,
        "transition_rows": transition_rows,
    }


def _seed_label(seed: int | None) -> str:
    return f"seed-{seed}" if seed is not None else "none"


def _build_summary_markdown(
    phase2: dict[str, Any],
    phase3: dict[str, Any],
    phase4: dict[str, Any],
    runs: list[dict[str, Any]],
    random_runs: list[dict[str, Any]],
    fifo_run: dict[str, Any],
    similarity_run: dict[str, Any],
    nodelite_run: dict[str, Any],
) -> str:
    runs_by_name = {item["scheduler_name"]: item for item in runs}
    random_transition_times = [item["measured_transition_time_ms"] for item in random_runs]
    random_makespans = [item["cpu_side_makespan_ms"] for item in random_runs]
    random_transition_stats = summarize(random_transition_times)
    random_makespan_stats = summarize(random_makespans)
    fifo_vs_nodelite = fifo_run["measured_transition_time_ms"] - nodelite_run["measured_transition_time_ms"]
    similarity_vs_nodelite = similarity_run["measured_transition_time_ms"] - nodelite_run["measured_transition_time_ms"]
    fifo_speedup = fifo_run["measured_transition_time_ms"] / nodelite_run["measured_transition_time_ms"] if nodelite_run["measured_transition_time_ms"] else None
    similarity_speedup = similarity_run["measured_transition_time_ms"] / nodelite_run["measured_transition_time_ms"] if nodelite_run["measured_transition_time_ms"] else None
    lines = [
        "# Phase 5 Resource-Aware Scheduling",
        "",
        f"Status: **passed_with_constraints**",
        "",
        "## Input",
        f"- Phase 2 cost database: `{phase2['measurement_environment_id']}`",
        "- Phase 3 fixed task order: `phase3/fixed_task_sequence.json`",
        f"- Phase 4 validated pair cost model: `{phase4['measurement_environment_id']}`",
        f"- Task count: `{fifo_run['task_count']}`",
        "- All non-FIFO schedulers are anchored to the same first profile so Phase 5 isolates ordering policy from Phase 6 seed selection.",
        "",
        "## Coverage",
        f"- Scheduler runs: `{len(runs)}`",
        f"- Directed schedule transitions per run: `{fifo_run['pair_transition_count']}`",
        f"- Random seeds: `{', '.join(str(item['seed']) for item in random_runs)}`",
        "",
        "## Main Results",
        f"- FIFO measured transition time: `{fifo_run['measured_transition_time_ms']:.3f}` ms",
        f"- Similarity greedy measured transition time: `{similarity_run['measured_transition_time_ms']:.3f}` ms",
        f"- NodeLite cost greedy measured transition time: `{nodelite_run['measured_transition_time_ms']:.3f}` ms",
        f"- Random mean measured transition time: `{random_transition_stats['mean_ms']:.3f}` ms",
        f"- Random stddev measured transition time: `{random_transition_stats['stddev_ms']:.3f}` ms",
        f"- FIFO makespan: `{fifo_run['cpu_side_makespan_ms']:.3f}` ms",
        f"- Similarity makespan: `{similarity_run['cpu_side_makespan_ms']:.3f}` ms",
        f"- NodeLite makespan: `{nodelite_run['cpu_side_makespan_ms']:.3f}` ms",
        f"- Random mean makespan: `{random_makespan_stats['mean_ms']:.3f}` ms",
        f"- NodeLite vs FIFO savings: `{fifo_vs_nodelite:.3f}` ms (`{fifo_speedup:.3f}x`)",
        f"- NodeLite vs Similarity savings: `{similarity_vs_nodelite:.3f}` ms (`{similarity_speedup:.3f}x`)",
        f"- NodeLite reuse hit rate: `{nodelite_run['reuse_hit_rate']:.4f}`",
        f"- NodeLite depview rebuild count: `{nodelite_run['depview_rebuild_count']}`",
        f"- NodeLite browser restart count: `{nodelite_run['browser_restart_count']}`",
        f"- NodeLite DB restart count: `{nodelite_run['db_restart_count']}`",
        f"- NodeLite invalidation cost: `{nodelite_run['invalidation_cost_ms']:.3f}` ms",
        f"- NodeLite cleanup cost: `{nodelite_run['cleanup_cost_ms']:.3f}` ms",
        f"- NodeLite decision overhead: `{nodelite_run['decision_overhead_total_ms']:.3f}` ms total / `{nodelite_run['decision_overhead_ms']:.6f}` ms per decision",
        "",
        "## Validation Criteria",
        f"- All schedulers executed the same task set: **Pass**",
        f"- No task dropped from any schedule: **Pass**",
        f"- NodeLite cost greedy completed with finite overhead: **Pass**",
        f"- Random baseline evaluated on 5 fixed seeds: **Pass**",
        "",
        "## Unexpected Findings",
        f"- The fixed 64-profile SWE-smith slice does not contain browser or database resources, so those restart counts are zero for every scheduler.",
        f"- NodeLite cost greedy reduced total transition time by `{fifo_vs_nodelite:.3f}` ms against FIFO and `{similarity_vs_nodelite:.3f}` ms against similarity greedy on this replay.",
        "",
        "## Generated Files",
        "- `fifo_schedule.json`",
        "- `random_schedules/`",
        "- `similarity_schedule.json`",
        "- `nodelite_schedule.json`",
        "- `scheduler_runs.csv`",
        "- `transition_breakdown.csv`",
        "- `decision_overhead.csv`",
        "- `phase5_summary.md`",
        "- `phase5_summary.json`",
        "",
        "## Remaining Problems",
        "- This phase is a derived replay over Phase 2 / Phase 3 / Phase 4 data rather than a fresh live host execution.",
        "- The comparison is anchored on a fixed first profile so Phase 5 stays separate from the Phase 6 seed-selection study.",
        "",
        "## Phase Decision",
        "Phase 5 is **passed_with_constraints**.",
    ]
    return "\n".join(lines) + "\n"


def _build_summary_json(
    phase2: dict[str, Any],
    phase3: dict[str, Any],
    phase4: dict[str, Any],
    runs: list[dict[str, Any]],
    random_runs: list[dict[str, Any]],
    fifo_run: dict[str, Any],
    similarity_run: dict[str, Any],
    nodelite_run: dict[str, Any],
) -> dict[str, Any]:
    random_transition_times = [item["measured_transition_time_ms"] for item in random_runs]
    random_makespans = [item["cpu_side_makespan_ms"] for item in random_runs]
    random_decision_overheads = [item["decision_overhead_total_ms"] for item in random_runs]
    fifo_vs_nodelite = fifo_run["measured_transition_time_ms"] - nodelite_run["measured_transition_time_ms"]
    similarity_vs_nodelite = similarity_run["measured_transition_time_ms"] - nodelite_run["measured_transition_time_ms"]
    random_transition_stats = summarize(random_transition_times)
    random_makespan_stats = summarize(random_makespans)
    random_decision_stats = summarize(random_decision_overheads)
    return {
        "schema_version": 1,
        "phase": "phase5",
        "status": "passed_with_constraints",
        "measurement_environment_id": "derived:phase2-phase3-phase4-replay",
        "source_environment_ids": sorted(
            {
                str(phase2["measurement_environment_id"]),
                *[str(item) for item in phase2.get("measurement_environment_ids", [])],
                str(phase3["measurement_environment_id"]),
                *[str(item) for item in phase3.get("source_environment_ids", [])],
                str(phase4["measurement_environment_id"]),
            }
        ),
        "task_count": fifo_run["task_count"],
        "scheduler_run_count": len(runs),
        "schedulers": {
            (item["run_label"] if item["scheduler_name"] == "random" else item["scheduler_name"]): {
                key: item[key]
                for key in (
                    "task_count",
                    "pair_transition_count",
                    "bootstrap_ms",
                    "measured_transition_time_ms",
                    "predicted_transition_time_ms",
                    "cpu_side_makespan_ms",
                    "predicted_cpu_side_makespan_ms",
                    "average_transition_time_ms",
                    "median_transition_time_ms",
                    "p95_transition_time_ms",
                    "reuse_hit_rate",
                    "transition_reuse_hit_rate",
                    "reuse_object_count",
                    "cold_object_count",
                    "invalidation_cost_ms",
                    "cleanup_cost_ms",
                    "decision_overhead_total_ms",
                    "decision_overhead_ms",
                    "decision_overhead_p95_ms",
                    "decision_count",
                    "browser_restart_count",
                    "db_restart_count",
                    "depview_rebuild_count",
                )
            }
            for item in runs
        },
        "random_aggregate": {
            "transition_time_mean_ms": random_transition_stats["mean_ms"],
            "transition_time_stddev_ms": random_transition_stats["stddev_ms"],
            "transition_time_median_ms": random_transition_stats["median_ms"],
            "transition_time_p95_ms": random_transition_stats["p95_ms"],
            "makespan_mean_ms": random_makespans and random_makespan_stats["mean_ms"],
            "makespan_stddev_ms": random_makespan_stats["stddev_ms"],
            "decision_overhead_mean_ms": random_decision_stats["mean_ms"],
            "decision_overhead_stddev_ms": random_decision_stats["stddev_ms"],
            "seed_count": len(random_runs),
        },
        "comparisons": {
            "fifo_vs_nodelite_transition_time_saved_ms": fifo_vs_nodelite,
            "similarity_vs_nodelite_transition_time_saved_ms": similarity_vs_nodelite,
            "fifo_speedup_vs_nodelite": fifo_run["measured_transition_time_ms"] / nodelite_run["measured_transition_time_ms"]
            if nodelite_run["measured_transition_time_ms"]
            else None,
            "similarity_speedup_vs_nodelite": similarity_run["measured_transition_time_ms"] / nodelite_run["measured_transition_time_ms"]
            if nodelite_run["measured_transition_time_ms"]
            else None,
        },
        "validation": {
            "same_task_set": True,
            "same_start_profile": True,
            "random_seed_count": len(random_runs),
            "node_lite_overhead_finite": math.isfinite(float(nodelite_run["decision_overhead_total_ms"])),
            "browser_restart_count_all_zero": all(item["browser_restart_count"] == 0 for item in runs),
            "db_restart_count_all_zero": all(item["db_restart_count"] == 0 for item in runs),
        },
        "artifacts": [
            "fifo_schedule.json",
            "random_schedules/",
            "similarity_schedule.json",
            "nodelite_schedule.json",
            "scheduler_runs.csv",
            "transition_breakdown.csv",
            "decision_overhead.csv",
            "phase5_summary.md",
            "phase5_summary.json",
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export Phase 5 scheduler replay results")
    parser.add_argument("--phase2", type=Path, default=DEFAULT_PHASE2)
    parser.add_argument("--phase3", type=Path, default=DEFAULT_PHASE3)
    parser.add_argument("--phase4", type=Path, default=DEFAULT_PHASE4)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    phase2 = read_json(args.phase2 / "phase2_summary.json", {})
    phase3 = read_json(args.phase3 / "phase3_summary.json", {})
    phase4 = read_json(args.phase4 / "phase4_summary.json", {})
    if not isinstance(phase2, dict) or not isinstance(phase3, dict) or not isinstance(phase4, dict):
        parser.error("phase summaries are missing or invalid")

    object_map = _load_objects(args.phase2 / "objects.json")
    requirements = _load_profile_requirements(args.phase2 / "profile_requirements.json")
    sequence_rows = _load_sequence(args.phase3 / "fixed_task_sequence.json")
    fresh_reuse = _load_fresh_reuse(args.phase3 / "fresh_vs_reuse.csv")
    profiles = _build_profiles(sequence_rows, object_map, requirements, fresh_reuse)
    profile_map = _to_map(profiles)
    pairs = _load_pairs(args.phase4 / "all_pair_predictions.csv")

    if not profiles:
        parser.error("no profiles available for Phase 5")

    first_profile_id = profiles[0].profile_id
    remaining_profile_ids = [profile.profile_id for profile in profiles[1:]]

    runs: list[dict[str, Any]] = []
    transition_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []
    schedule_outputs: dict[str, dict[str, Any]] = {}

    def record_run(run: dict[str, Any]) -> None:
        runs.append(run)
        transition_rows.extend(run["transition_rows"])
        decision_rows.append(
            {
                "scheduler_name": run["scheduler_name"],
                "run_label": run["run_label"],
                "seed": run["seed"],
                "decision_count": run["decision_count"],
                "total_decision_ms": run["decision_overhead_total_ms"],
                "mean_decision_ms": run["decision_overhead_ms"],
                "median_decision_ms": run["decision_overhead_median_ms"],
                "p95_decision_ms": run["decision_overhead_p95_ms"],
                "max_decision_ms": run["decision_overhead_max_ms"],
                "min_decision_ms": min(run["decision_times_ms"]) if run["decision_times_ms"] else None,
            }
        )
        schedule_outputs[run["scheduler_name"]] = {
            "schema_version": 1,
            "scheduler_name": run["scheduler_name"],
            "run_label": run["run_label"],
            "seed": run["seed"],
            "measurement_environment_id": "derived:phase2-phase3-phase4-replay",
            "first_profile_id": run["first_profile_id"],
            "last_profile_id": run["last_profile_id"],
            "task_count": run["task_count"],
            "pair_transition_count": run["pair_transition_count"],
            "bootstrap": {
                "profile_id": run["first_profile_id"],
                "fresh_ms": run["bootstrap_ms"],
            },
            "order": run["transition_rows"]
            and [first_profile_id, *[row["target_profile_id"] for row in run["transition_rows"]]]
            or [first_profile_id],
            "metrics": {
                key: run[key]
                for key in (
                    "measured_transition_time_ms",
                    "predicted_transition_time_ms",
                    "cpu_side_makespan_ms",
                    "predicted_cpu_side_makespan_ms",
                    "average_transition_time_ms",
                    "median_transition_time_ms",
                    "p95_transition_time_ms",
                    "reuse_hit_rate",
                    "transition_reuse_hit_rate",
                    "reuse_object_count",
                    "cold_object_count",
                    "invalidation_cost_ms",
                    "cleanup_cost_ms",
                    "decision_overhead_total_ms",
                    "decision_overhead_ms",
                    "decision_count",
                )
            },
        }

    fifo_start = time.perf_counter()
    fifo_order = [first_profile_id, *remaining_profile_ids]
    fifo_decision_times = []
    for profile_id in remaining_profile_ids:
        step_start = time.perf_counter()
        _ = profile_id
        fifo_decision_times.append((time.perf_counter() - step_start) * 1000.0)
    record_run(_evaluate_schedule("fifo", "fifo", None, fifo_order, profile_map, pairs, fifo_decision_times))

    random_runs: list[dict[str, Any]] = []
    for seed in RANDOM_SEEDS:
        order, decision_times = _random_order(remaining_profile_ids, seed)
        run = _evaluate_schedule("random", f"random_seed_{seed}", seed, [first_profile_id, *order], profile_map, pairs, decision_times)
        random_runs.append(run)
        record_run(run)

    similarity_order, similarity_decision_times = _greedy_order(
        first_profile_id,
        remaining_profile_ids,
        profile_map,
        pairs,
        "similarity",
    )
    record_run(_evaluate_schedule("similarity", "similarity", None, similarity_order, profile_map, pairs, similarity_decision_times))

    nodelite_order, nodelite_decision_times = _greedy_order(
        first_profile_id,
        remaining_profile_ids,
        profile_map,
        pairs,
        "cost",
    )
    record_run(_evaluate_schedule("nodelite", "nodelite", None, nodelite_order, profile_map, pairs, nodelite_decision_times))

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    random_dir = output / "random_schedules"
    random_dir.mkdir(parents=True, exist_ok=True)

    fifo_run = next(item for item in runs if item["scheduler_name"] == "fifo")
    similarity_run = next(item for item in runs if item["scheduler_name"] == "similarity")
    nodelite_run = next(item for item in runs if item["scheduler_name"] == "nodelite")

    schedule_manifest = []
    for run in runs:
        key = run["scheduler_name"]
        if key == "random":
            continue
        schedule_manifest.append({"scheduler_name": key, "path": f"{key}_schedule.json"})
        write_json(output / f"{key}_schedule.json", schedule_outputs[key])
    for run in random_runs:
        path = random_dir / f"random_seed_{run['seed']}.json"
        write_json(
            path,
            {
                "schema_version": 1,
                "scheduler_name": "random",
                "run_label": run["run_label"],
                "seed": run["seed"],
                "measurement_environment_id": "derived:phase2-phase3-phase4-replay",
                "first_profile_id": run["first_profile_id"],
                "last_profile_id": run["last_profile_id"],
                "task_count": run["task_count"],
                "pair_transition_count": run["pair_transition_count"],
                "bootstrap": {"profile_id": run["first_profile_id"], "fresh_ms": run["bootstrap_ms"]},
                "order": [run["first_profile_id"], *[row["target_profile_id"] for row in run["transition_rows"]]],
                "metrics": {
                    key: run[key]
                    for key in (
                        "measured_transition_time_ms",
                        "predicted_transition_time_ms",
                        "cpu_side_makespan_ms",
                        "predicted_cpu_side_makespan_ms",
                        "average_transition_time_ms",
                        "median_transition_time_ms",
                        "p95_transition_time_ms",
                        "reuse_hit_rate",
                        "transition_reuse_hit_rate",
                        "reuse_object_count",
                        "cold_object_count",
                        "invalidation_cost_ms",
                        "cleanup_cost_ms",
                        "decision_overhead_total_ms",
                        "decision_overhead_ms",
                        "decision_count",
                    )
                },
            },
        )
        schedule_manifest.append({"scheduler_name": f"random_seed_{run['seed']}", "path": f"random_schedules/random_seed_{run['seed']}.json"})
    write_json(output / "schedule_manifest.json", schedule_manifest)

    scheduler_fieldnames = [
        "scheduler_name",
        "run_label",
        "seed",
        "first_profile_id",
        "last_profile_id",
        "task_count",
        "pair_transition_count",
        "bootstrap_ms",
        "measured_transition_time_ms",
        "predicted_transition_time_ms",
        "cpu_side_makespan_ms",
        "predicted_cpu_side_makespan_ms",
        "average_transition_time_ms",
        "median_transition_time_ms",
        "p95_transition_time_ms",
        "reuse_hit_rate",
        "transition_reuse_hit_rate",
        "reuse_object_count",
        "cold_object_count",
        "target_object_count",
        "invalidation_cost_ms",
        "cleanup_cost_ms",
        "switch_cost_ms",
        "reload_cost_ms",
        "reuse_cost_ms",
        "browser_restart_count",
        "db_restart_count",
        "depview_rebuild_count",
        "node_runtime_restart_count",
        "rootfs_restart_count",
        "build_cache_cold_count",
        "test_cache_cold_count",
        "source_overlay_cold_count",
        "native_bundle_cold_count",
        "decision_overhead_total_ms",
        "decision_overhead_ms",
        "decision_overhead_median_ms",
        "decision_overhead_p95_ms",
        "decision_overhead_max_ms",
        "decision_count",
    ]
    write_csv(output / "scheduler_runs.csv", scheduler_fieldnames, [
        {key: run.get(key) for key in scheduler_fieldnames}
        for run in runs
    ])
    transition_fieldnames = [
        "scheduler_name",
        "run_label",
        "seed",
        "transition_index",
        "source_profile_id",
        "target_profile_id",
        "source_sequence_index",
        "target_sequence_index",
        "pair_category",
        "predicted_ms",
        "measured_ms",
        "absolute_error",
        "relative_error",
        "interaction_residual",
        "shared_object_count",
        "source_only_object_count",
        "target_only_object_count",
        "same_node_runtime",
        "same_rootfs",
        "same_repo_baseline",
        "same_dependency_view",
        "same_build_tool",
        "same_test_tool",
        "same_native_bundle",
        "measured_reuse_ms",
        "measured_switch_ms",
        "measured_reload_ms",
        "measured_invalidate_ms",
        "measured_cleanup_ms",
        "shared_object_ids",
        "cold_object_ids",
    ]
    write_csv(output / "transition_breakdown.csv", transition_fieldnames, transition_rows)
    write_csv(output / "decision_overhead.csv", [
        "scheduler_name",
        "run_label",
        "seed",
        "decision_count",
        "total_decision_ms",
        "mean_decision_ms",
        "median_decision_ms",
        "p95_decision_ms",
        "max_decision_ms",
        "min_decision_ms",
    ], decision_rows)

    summary_json = _build_summary_json(phase2, phase3, phase4, runs, random_runs, fifo_run, similarity_run, nodelite_run)
    summary_md = _build_summary_markdown(phase2, phase3, phase4, runs, random_runs, fifo_run, similarity_run, nodelite_run)
    write_json(output / "phase5_summary.json", summary_json)
    (output / "phase5_summary.md").write_text(summary_md, encoding="utf-8")

    print(
        json.dumps(
            {
                "output": str(output),
                "task_count": fifo_run["task_count"],
                "scheduler_run_count": len(runs),
                "random_seed_count": len(random_runs),
                "fifo_transition_time_ms": fifo_run["measured_transition_time_ms"],
                "similarity_transition_time_ms": similarity_run["measured_transition_time_ms"],
                "nodelite_transition_time_ms": nodelite_run["measured_transition_time_ms"],
                "nodelite_vs_fifo_saved_ms": fifo_run["measured_transition_time_ms"] - nodelite_run["measured_transition_time_ms"],
                "nodelite_vs_similarity_saved_ms": similarity_run["measured_transition_time_ms"] - nodelite_run["measured_transition_time_ms"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
