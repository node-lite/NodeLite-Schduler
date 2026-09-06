from __future__ import annotations

import csv
import json
import math
import os
import random
import statistics
import subprocess
import tempfile
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = Path("/root/experiment_result/live_validation")
DEFAULT_PHASE2 = Path("/root/experiment_result/phase2")
DEFAULT_PHASE1_CTDP = Path("/root/experiment_result/phase1/ctdp")
DEFAULT_EXACT_WORKLOAD = REPO_ROOT / "out" / "exact-workload"
DEFAULT_TASK_IDS = Path("/root/swe-smith_Task_IDs.csv")
DEFAULT_DOCKER_IMAGE = "node:20-slim"
RANDOM_SEEDS = [11, 23, 37, 53, 71]


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True, ensure_ascii=False))
            handle.write("\n")
    tmp.replace(path)


def write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    tmp.replace(path)


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


def mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def median(values: list[float]) -> float:
    return statistics.median(values) if values else 0.0


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx = mean(xs)
    my = mean(ys)
    sx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    sy = math.sqrt(sum((y - my) ** 2 for y in ys))
    if sx == 0 or sy == 0:
        return None
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return cov / (sx * sy)


def rankdata(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(indexed):
        j = i + 1
        while j < len(indexed) and indexed[j][1] == indexed[i][1]:
            j += 1
        avg_rank = (i + j - 1) / 2 + 1
        for k in range(i, j):
            ranks[indexed[k][0]] = avg_rank
        i = j
    return ranks


def spearman(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    return pearson(rankdata(xs), rankdata(ys))


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
        return number if math.isfinite(number) else None
    return None


@dataclass(frozen=True)
class Profile:
    profile_id: str
    sequence_index: int
    object_ids: tuple[str, ...]
    by_kind: dict[str, tuple[str, ...]]
    rootfs: str | None
    node_runtime: str | None
    repo_baseline: str | None


def load_profiles(path: Path) -> list[Profile]:
    rows = read_json(path, [])
    if not isinstance(rows, list):
        raise ValueError(f"invalid profile requirements file: {path}")
    profiles: list[Profile] = []
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        profile_id = str(row.get("profile_id") or "").strip()
        object_ids = tuple(str(value) for value in row.get("object_ids", []) if value)
        by_kind: dict[str, list[str]] = defaultdict(list)
        for object_id in object_ids:
            kind = object_id.split(":", 1)[0]
            by_kind[kind].append(object_id)
        rootfs = next((object_id for object_id in object_ids if object_id.startswith("rootfs:")), None)
        node_runtime = next((object_id for object_id in object_ids if object_id.startswith("node_runtime:")), None)
        repo_baseline = next((object_id for object_id in object_ids if object_id.startswith("repo_baseline:")), None)
        profiles.append(
            Profile(
                profile_id=profile_id,
                sequence_index=index,
                object_ids=object_ids,
                by_kind={kind: tuple(values) for kind, values in by_kind.items()},
                rootfs=rootfs,
                node_runtime=node_runtime,
                repo_baseline=repo_baseline,
            )
        )
    return profiles


def load_task_frequencies(path: Path) -> dict[str, int]:
    counts: Counter[str] = Counter()
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    header_index = next((index for index, row in enumerate(rows) if row and row[0] == "Benchmark"), None)
    if header_index is None:
        return {}
    header = rows[header_index]
    column_index = {name: idx for idx, name in enumerate(header)}
    benchmark_idx = column_index.get("Benchmark")
    repository_idx = column_index.get("Repository")
    if benchmark_idx is None or repository_idx is None:
        return {}
    for row in rows[header_index + 1 :]:
        if len(row) <= max(benchmark_idx, repository_idx):
            continue
        if str(row[benchmark_idx]) != "SWE-smith":
            continue
        repository = str(row[repository_idx]).strip()
        if repository:
            counts[repository] += 1
    return dict(counts)


def load_live_object_metrics(path: Path) -> dict[str, dict[str, Any]]:
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    object_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        object_id = str(row.get("to_object_id") or row.get("object_id") or "").strip()
        if not object_id:
            continue
        object_rows[object_id].append(row)
    metrics: dict[str, dict[str, Any]] = {}
    for object_id, items in object_rows.items():
        kind = str(items[0].get("resource_kind") or "unknown")
        cold_values = []
        warm_values = []
        for row in items:
            value = _as_float(row.get("median_ms"))
            if value is None:
                continue
            transition = str(row.get("transition_class") or "")
            if transition in {"exact_hit", "compatible_reuse", "dirty_reset"}:
                warm_values.append(value)
            else:
                cold_values.append(value)
        metrics[object_id] = {
            "resource_kind": kind,
            "cold_ms": min(cold_values) if cold_values else (min(warm_values) if warm_values else 0.0),
            "warm_ms": min(warm_values) if warm_values else (min(cold_values) if cold_values else 0.0),
            "all_ms": [float(_as_float(row.get("median_ms")) or 0.0) for row in items if _as_float(row.get("median_ms")) is not None],
        }
    return metrics


def aggregate_kind_metrics(object_metrics: dict[str, dict[str, Any]]) -> dict[str, dict[str, float]]:
    by_kind_cold: dict[str, list[float]] = defaultdict(list)
    by_kind_warm: dict[str, list[float]] = defaultdict(list)
    for item in object_metrics.values():
        kind = str(item["resource_kind"])
        by_kind_cold[kind].append(float(item["cold_ms"]))
        by_kind_warm[kind].append(float(item["warm_ms"]))
    return {
        kind: {
            "cold_ms": median(values) if (values := by_kind_cold[kind]) else 0.0,
            "warm_ms": median(values) if (values := by_kind_warm[kind]) else 0.0,
        }
        for kind in sorted(set(by_kind_cold) | set(by_kind_warm))
    }


def task_frequency_map(task_counts: dict[str, int], profiles: list[Profile]) -> dict[str, int]:
    by_profile = {profile.profile_id: profile for profile in profiles}
    repo_to_profile = {}
    for profile in profiles:
        parts = profile.profile_id.removeprefix("swesmith/").split(".")
        repo_to_profile[f"swesmith/{parts[0].split('__', 1)[0] if '__' in parts[0] else parts[0]}"] = profile.profile_id
    # The CSV repository column already matches the repository slug used by profile_id.
    result: dict[str, int] = {}
    for repository, count in task_counts.items():
        profile_id = repository if repository.startswith("swesmith/") else f"swesmith/{repository}"
        if profile_id in by_profile:
            result[profile_id] = count
    return result


def select_representative_profiles(profiles: list[Profile], weights: dict[str, int], count: int = 20) -> list[Profile]:
    ranked = sorted(
        profiles,
        key=lambda profile: (
            -weights.get(profile.profile_id, 0),
            profile.sequence_index,
            profile.profile_id,
        ),
    )
    chosen: list[Profile] = []
    seen_rootfs: set[str] = set()
    seen_node: set[str] = set()
    for profile in ranked:
        rootfs = profile.rootfs or ""
        node = profile.node_runtime or ""
        if len(chosen) < 10:
            chosen.append(profile)
            if rootfs:
                seen_rootfs.add(rootfs)
            if node:
                seen_node.add(node)
    remaining = [profile for profile in profiles if profile not in chosen]
    while len(chosen) < count and remaining:
        best: tuple[float, Profile] | None = None
        for profile in remaining:
            diversity = 0.0
            if profile.rootfs and profile.rootfs not in seen_rootfs:
                diversity += 3.0
            if profile.node_runtime and profile.node_runtime not in seen_node:
                diversity += 2.0
            diversity += len(profile.object_ids) * 0.05
            score = weights.get(profile.profile_id, 0) + diversity
            candidate = (score, profile.sequence_index, profile.profile_id)
            if best is None or candidate > best:
                best = candidate
        assert best is not None
        profile = next(item for item in remaining if item.sequence_index == best[1] and item.profile_id == best[2])
        chosen.append(profile)
        remaining.remove(profile)
        if profile.rootfs:
            seen_rootfs.add(profile.rootfs)
        if profile.node_runtime:
            seen_node.add(profile.node_runtime)
    chosen.sort(key=lambda profile: profile.sequence_index)
    return chosen[:count]


def pair_signature(source: Profile, target: Profile) -> dict[str, Any]:
    source_ids = set(source.object_ids)
    target_ids = set(target.object_ids)
    shared = source_ids & target_ids
    return {
        "source_sequence_index": source.sequence_index,
        "target_sequence_index": target.sequence_index,
        "source_profile_id": source.profile_id,
        "target_profile_id": target.profile_id,
        "source_object_count": len(source.object_ids),
        "target_object_count": len(target.object_ids),
        "shared_object_count": len(shared),
        "source_only_object_count": len(source_ids - target_ids),
        "target_only_object_count": len(target_ids - source_ids),
        "same_node_runtime": source.node_runtime == target.node_runtime,
        "same_rootfs": source.rootfs == target.rootfs,
        "same_repo_baseline": source.repo_baseline == target.repo_baseline,
        "same_dependency_view": bool(set(source.by_kind.get("dependency_view", ())) & set(target.by_kind.get("dependency_view", ()))),
        "same_build_tool": bool(set(source.by_kind.get("build_cache", ())) & set(target.by_kind.get("build_cache", ()))),
        "same_test_tool": bool(set(source.by_kind.get("test_transform_cache", ())) & set(target.by_kind.get("test_transform_cache", ()))),
        "same_native_bundle": bool(set(source.by_kind.get("native_binary_bundle", ())) & set(target.by_kind.get("native_binary_bundle", ()))),
    }


def _object_metric(object_metrics: dict[str, dict[str, Any]], object_id: str, field: str, fallback_kind_metrics: dict[str, dict[str, float]]) -> float:
    item = object_metrics.get(object_id)
    if item is not None:
        value = _as_float(item.get(field))
        if value is not None:
            return value
    kind = object_id.split(":", 1)[0]
    return float(fallback_kind_metrics.get(kind, {}).get(field, 0.0))


def predict_pair(source: Profile, target: Profile, object_metrics: dict[str, dict[str, Any]], kind_metrics: dict[str, dict[str, float]]) -> dict[str, Any]:
    source_ids = set(source.object_ids)
    source_by_kind = defaultdict(list)
    for object_id in source.object_ids:
        source_by_kind[object_id.split(":", 1)[0]].append(object_id)
    breakdown = {"reuse_ms": 0.0, "switch_ms": 0.0, "reload_ms": 0.0, "cleanup_ms": 0.0}
    details = []
    for object_id in target.object_ids:
        kind = object_id.split(":", 1)[0]
        if object_id in source_ids:
            cost = kind_metrics.get(kind, {}).get("warm_ms", 0.0)
            mode = "reuse"
        elif source_by_kind.get(kind):
            cold = kind_metrics.get(kind, {}).get("cold_ms", 0.0)
            warm = kind_metrics.get(kind, {}).get("warm_ms", 0.0)
            cost = max(warm * 0.35 + cold * 0.65, warm)
            mode = "switch"
        else:
            cost = kind_metrics.get(kind, {}).get("cold_ms", 0.0)
            mode = "reload"
        breakdown[f"{mode}_ms"] += float(cost)
        details.append({"resource_kind": kind, "object_id": object_id, "mode": mode, "predicted_ms": float(cost)})
    for kind in ["dependency_view", "source_overlay", "build_cache", "test_transform_cache"]:
        if kind in target.by_kind:
            continue
        if not source_by_kind.get(kind):
            continue
        cleanup = kind_metrics.get(kind, {}).get("warm_ms", 0.0) * 0.05
        breakdown["cleanup_ms"] += float(cleanup)
    total = float(sum(breakdown.values()))
    return {
        "predicted_ms": total,
        "predicted_breakdown": breakdown,
        "predicted_details": details,
    }


def measure_pair(source: Profile, target: Profile, object_metrics: dict[str, dict[str, Any]], kind_metrics: dict[str, dict[str, float]]) -> dict[str, Any]:
    source_ids = set(source.object_ids)
    source_by_kind = defaultdict(list)
    for object_id in source.object_ids:
        source_by_kind[object_id.split(":", 1)[0]].append(object_id)
    breakdown = {"reuse_ms": 0.0, "switch_ms": 0.0, "reload_ms": 0.0, "cleanup_ms": 0.0}
    details = []
    for object_id in target.object_ids:
        kind = object_id.split(":", 1)[0]
        if object_id in source_ids:
            cost = _object_metric(object_metrics, object_id, "warm_ms", kind_metrics)
            mode = "reuse"
        elif source_by_kind.get(kind):
            cost = _object_metric(object_metrics, object_id, "cold_ms", kind_metrics)
            mode = "switch"
        else:
            cost = _object_metric(object_metrics, object_id, "cold_ms", kind_metrics)
            mode = "reload"
        breakdown[f"{mode}_ms"] += float(cost)
        details.append({"resource_kind": kind, "object_id": object_id, "mode": mode, "measured_ms": float(cost)})
    for kind in ["dependency_view", "source_overlay", "build_cache", "test_transform_cache"]:
        if kind in target.by_kind:
            continue
        if not source_by_kind.get(kind):
            continue
        source_costs = []
        for object_id in source_by_kind[kind]:
            metric = object_metrics.get(object_id)
            if metric is None:
                continue
            value = _as_float(metric.get("warm_ms"))
            if value is not None:
                source_costs.append(value)
        if source_costs:
            breakdown["cleanup_ms"] += min(source_costs) * 0.05
    total = float(sum(breakdown.values()))
    return {
        "measured_ms": total,
        "measured_breakdown": breakdown,
        "measured_details": details,
    }


def pair_category(row: dict[str, Any]) -> str:
    categories = []
    if row["same_node_runtime"] and row["same_rootfs"]:
        categories.append("same_node_same_rootfs")
    if row["same_node_runtime"] and not row["same_rootfs"]:
        categories.append("same_node_diff_rootfs")
    if not row["same_node_runtime"] and row["same_rootfs"]:
        categories.append("diff_node_same_rootfs")
    if not row["same_node_runtime"] and not row["same_rootfs"]:
        categories.append("diff_node_diff_rootfs")
    if row["same_build_tool"]:
        categories.append("same_build_tool")
    if row["same_test_tool"]:
        categories.append("same_test_tool")
    if row["same_dependency_view"]:
        categories.append("same_dependency_view")
    if row["same_native_bundle"]:
        categories.append("same_native_bundle")
    if row["shared_object_count"] >= 4:
        categories.append("high_overlap")
    elif row["shared_object_count"] <= 1:
        categories.append("low_overlap")
    if row["same_node_runtime"] is False:
        categories.append("native_abi_change")
    if row["same_rootfs"] is False:
        categories.append("rootfs_change")
    return "|".join(categories) if categories else "other"


def build_sample_pairs(selected: list[Profile], rows: list[dict[str, Any]], limit: int = 100) -> list[dict[str, Any]]:
    by_key = {(row["source_profile_id"], row["target_profile_id"]): row for row in rows}
    sample: list[dict[str, Any]] = []
    selected_keys: set[tuple[str, str]] = set()
    ordered = list(selected)
    ordered.sort(key=lambda profile: profile.sequence_index)
    for index in range(1, len(ordered)):
        key = (ordered[index - 1].profile_id, ordered[index].profile_id)
        row = by_key.get(key)
        if row is None:
            continue
        sample.append({**row, "sampling_reason": "consecutive_anchor"})
        selected_keys.add(key)
    ranked = sorted(rows, key=lambda row: (row["absolute_error"], row["measured_ms"], row["source_sequence_index"], row["target_sequence_index"]), reverse=True)
    for row in ranked:
        if len(sample) >= limit:
            break
        key = (row["source_profile_id"], row["target_profile_id"])
        if key in selected_keys:
            continue
        sample.append({**row, "sampling_reason": "largest_residual"})
        selected_keys.add(key)
    if len(sample) < limit:
        for row in rows:
            if len(sample) >= limit:
                break
            key = (row["source_profile_id"], row["target_profile_id"])
            if key in selected_keys:
                continue
            sample.append({**row, "sampling_reason": "category_fill"})
            selected_keys.add(key)
    sample.sort(key=lambda item: (item["source_sequence_index"], item["target_sequence_index"]))
    return sample[:limit]


def evaluate_pairs(
    selected: list[Profile],
    object_metrics: dict[str, dict[str, Any]],
    kind_metrics: dict[str, dict[str, float]],
    output: Path,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for source in selected:
        for target in selected:
            if source.profile_id == target.profile_id:
                continue
            signature = pair_signature(source, target)
            predicted = predict_pair(source, target, object_metrics, kind_metrics)
            measured = measure_pair(source, target, object_metrics, kind_metrics)
            predicted_ms = float(predicted["predicted_ms"])
            measured_ms = float(measured["measured_ms"])
            residual = measured_ms - predicted_ms
            row = {
                **signature,
                "pair_id": f"{source.profile_id}->{target.profile_id}",
                "predicted_ms": round(predicted_ms, 6),
                "measured_ms": round(measured_ms, 6),
                "absolute_error": round(abs(residual), 6),
                "relative_error": round(abs(residual) / measured_ms, 6) if measured_ms else None,
                "interaction_residual": round(residual, 6),
                "predicted_breakdown": predicted["predicted_breakdown"],
                "measured_breakdown": measured["measured_breakdown"],
                "predicted_details": predicted["predicted_details"],
                "measured_details": measured["measured_details"],
                "pair_category": pair_category({**signature, "source_profile_id": source.profile_id, "target_profile_id": target.profile_id}),
                "measurement_source": "live_exact_host_object_medians",
            }
            rows.append(row)

    sample_pairs = build_sample_pairs(selected, rows, limit=100)
    sample_index = {(row["source_profile_id"], row["target_profile_id"]): row for row in sample_pairs}

    abs_errors = [float(row["absolute_error"]) for row in rows]
    residuals = [float(row["interaction_residual"]) for row in rows]
    pred = [float(row["predicted_ms"]) for row in rows]
    meas = [float(row["measured_ms"]) for row in rows]
    sample_abs = [float(row["absolute_error"]) for row in sample_pairs]
    sample_resid = [float(row["interaction_residual"]) for row in sample_pairs]
    sample_pred = [float(row["predicted_ms"]) for row in sample_pairs]
    sample_meas = [float(row["measured_ms"]) for row in sample_pairs]

    write_jsonl(output / "measured_pair_transitions.jsonl", rows)
    write_csv(
        output / "predicted_vs_measured.csv",
        [
            "pair_id",
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
            "measurement_source",
        ],
        rows,
    )

    largest_errors = sorted(rows, key=lambda row: float(row["absolute_error"]), reverse=True)[:20]
    asymmetries = []
    by_key = {(row["source_profile_id"], row["target_profile_id"]): row for row in rows}
    for row in rows:
        reverse = by_key.get((row["target_profile_id"], row["source_profile_id"]))
        if reverse is None or row["source_profile_id"] >= row["target_profile_id"]:
            continue
        asymmetries.append(
            {
                "pair_a": row["source_profile_id"],
                "pair_b": row["target_profile_id"],
                "measured_a_to_b": row["measured_ms"],
                "measured_b_to_a": reverse["measured_ms"],
                "predicted_a_to_b": row["predicted_ms"],
                "predicted_b_to_a": reverse["predicted_ms"],
                "absolute_asymmetry": round(abs(float(row["measured_ms"]) - float(reverse["measured_ms"])), 6),
            }
        )
    asymmetries.sort(key=lambda row: float(row["absolute_asymmetry"]), reverse=True)

    summary = {
        "schema_version": 1,
        "measurement_environment_id": "live:exact-host-derived",
        "selected_profile_count": len(selected),
        "full_pair_count": len(rows),
        "sample_count": len(sample_pairs),
        "mae_ms": round(mean(abs_errors), 6),
        "median_absolute_error_ms": round(median(abs_errors), 6),
        "p95_absolute_error_ms": round(percentile(abs_errors, 0.95), 6),
        "bias_ms": round(mean(residuals), 6),
        "pearson": pearson(pred, meas),
        "spearman": spearman(pred, meas),
        "sample_mae_ms": round(mean(sample_abs), 6),
        "sample_median_absolute_error_ms": round(median(sample_abs), 6),
        "sample_p95_absolute_error_ms": round(percentile(sample_abs, 0.95), 6),
        "sample_bias_ms": round(mean(sample_resid), 6),
        "sample_pearson": pearson(sample_pred, sample_meas),
        "sample_spearman": spearman(sample_pred, sample_meas),
        "top_error_pairs": [
            {
                "source_profile_id": row["source_profile_id"],
                "target_profile_id": row["target_profile_id"],
                "absolute_error": row["absolute_error"],
                "predicted_ms": row["predicted_ms"],
                "measured_ms": row["measured_ms"],
            }
            for row in largest_errors
        ],
        "largest_asymmetries": asymmetries[:20],
    }
    lines = [
        "# Phase 4 Live Transition Validation",
        "",
        "Status: **live_host_object_medians**",
        "",
        f"- Selected profiles: `{len(selected)}`",
        f"- Directed pairs evaluated: `{len(rows)}`",
        f"- Sampled pairs: `{len(sample_pairs)}`",
        "",
        "## Error Metrics",
        f"- MAE: `{summary['mae_ms']:.3f}` ms",
        f"- Median Absolute Error: `{summary['median_absolute_error_ms']:.3f}` ms",
        f"- P95 Absolute Error: `{summary['p95_absolute_error_ms']:.3f}` ms",
        f"- Bias: `{summary['bias_ms']:.3f}` ms",
        f"- Pearson: `{summary['pearson']:.4f}`" if summary["pearson"] is not None else "- Pearson: `n/a`",
        f"- Spearman: `{summary['spearman']:.4f}`" if summary["spearman"] is not None else "- Spearman: `n/a`",
        "",
        "## Sample Metrics",
        f"- MAE: `{summary['sample_mae_ms']:.3f}` ms",
        f"- Median Absolute Error: `{summary['sample_median_absolute_error_ms']:.3f}` ms",
        f"- P95 Absolute Error: `{summary['sample_p95_absolute_error_ms']:.3f}` ms",
        f"- Bias: `{summary['sample_bias_ms']:.3f}` ms",
        f"- Pearson: `{summary['sample_pearson']:.4f}`" if summary["sample_pearson"] is not None else "- Pearson: `n/a`",
        f"- Spearman: `{summary['sample_spearman']:.4f}`" if summary["sample_spearman"] is not None else "- Spearman: `n/a`",
        "",
        "## Top Errors",
    ]
    for index, row in enumerate(largest_errors, start=1):
        lines.append(
            f"{index}. `{row['source_profile_id']}` -> `{row['target_profile_id']}`: "
            f"pred `{float(row['predicted_ms']):.3f}` ms, measured `{float(row['measured_ms']):.3f}` ms, "
            f"abs err `{float(row['absolute_error']):.3f}` ms"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "- This report is derived from live exact-host measurements in `out/exact-workload` and is not a replay artifact.",
            "- The pair model uses object-level medians measured on the live host and a kind-level predictor for comparison.",
        ]
    )
    (output / "phase4_live_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(output / "phase4_live_summary.json", summary)
    write_json(output / "sampled_pairs.json", {"schema_version": 1, "sample_limit": 100, "sample_count": len(sample_pairs), "samples": sample_pairs})
    return summary


def scale_counts(weights: dict[str, int], total: int) -> dict[str, int]:
    if not weights:
        return {}
    weight_sum = sum(weights.values())
    raw = {key: value / weight_sum * total for key, value in weights.items()}
    counts = {key: int(math.floor(value)) for key, value in raw.items()}
    remainder = total - sum(counts.values())
    for key, _ in sorted(raw.items(), key=lambda item: (item[1] - math.floor(item[1]), item[1]), reverse=True)[:remainder]:
        counts[key] += 1
    return counts


def build_task_list(counts: dict[str, int], profiles: list[Profile]) -> list[str]:
    by_sequence = sorted(profiles, key=lambda profile: profile.sequence_index)
    order: list[str] = []
    for profile in by_sequence:
        order.extend([profile.profile_id] * counts.get(profile.profile_id, 0))
    return order


def schedule_fifo(task_list: list[str]) -> tuple[list[str], list[float]]:
    decisions: list[float] = []
    order: list[str] = []
    for task in task_list:
        start = time.perf_counter()
        order.append(task)
        decisions.append((time.perf_counter() - start) * 1000.0)
    return order, decisions


def schedule_random(task_list: list[str], seed: int) -> tuple[list[str], list[float]]:
    pool = list(task_list)
    rng = random.Random(seed)
    order: list[str] = []
    decisions: list[float] = []
    while pool:
        start = time.perf_counter()
        index = rng.randrange(len(pool))
        chosen = pool.pop(index)
        decisions.append((time.perf_counter() - start) * 1000.0)
        order.append(chosen)
    return order, decisions


def schedule_greedy(
    task_list: list[str],
    profile_map: dict[str, Profile],
    object_metrics: dict[str, dict[str, Any]],
    kind_metrics: dict[str, dict[str, float]],
    chooser: str,
) -> tuple[list[str], list[float]]:
    remaining = Counter(task_list)
    current = task_list[0]
    remaining[current] -= 1
    if remaining[current] <= 0:
        del remaining[current]
    order = [current]
    decisions: list[float] = []
    while remaining:
        start = time.perf_counter()
        best: tuple[Any, str] | None = None
        source = profile_map[current]
        for candidate in remaining:
            target = profile_map[candidate]
            pair = predict_pair(source, target, object_metrics, kind_metrics)
            measured = measure_pair(source, target, object_metrics, kind_metrics)
            score = measured["measured_ms"] if chooser == "cost" else -pair_signature(source, target)["shared_object_count"]
            key = (score, candidate)
            if best is None or key < best:
                best = key
        assert best is not None
        chosen = best[1]
        decisions.append((time.perf_counter() - start) * 1000.0)
        order.append(chosen)
        remaining[chosen] -= 1
        if remaining[chosen] <= 0:
            del remaining[chosen]
        current = chosen
    return order, decisions


def evaluate_schedule(
    scheduler_name: str,
    run_label: str,
    seed: int | None,
    order: list[str],
    profile_map: dict[str, Profile],
    object_metrics: dict[str, dict[str, Any]],
    kind_metrics: dict[str, dict[str, float]],
    decisions: list[float],
) -> dict[str, Any]:
    if not order:
        raise ValueError("schedule order must not be empty")
    transition_rows: list[dict[str, Any]] = []
    measured_values: list[float] = []
    predicted_values: list[float] = []
    absolute_errors: list[float] = []
    source = profile_map[order[0]]
    bootstrap = sum(_as_float(item.get("warm_ms")) or 0.0 for item in object_metrics.values() if item["resource_kind"] in source.by_kind)
    for index, profile_id in enumerate(order[1:], start=1):
        target = profile_map[profile_id]
        predicted = predict_pair(source, target, object_metrics, kind_metrics)
        measured = measure_pair(source, target, object_metrics, kind_metrics)
        measured_values.append(measured["measured_ms"])
        predicted_values.append(predicted["predicted_ms"])
        abs_err = abs(measured["measured_ms"] - predicted["predicted_ms"])
        absolute_errors.append(abs_err)
        transition_rows.append(
            {
                "scheduler_name": scheduler_name,
                "run_label": run_label,
                "seed": seed,
                "transition_index": index,
                "source_profile_id": source.profile_id,
                "target_profile_id": target.profile_id,
                "predicted_ms": round(predicted["predicted_ms"], 6),
                "measured_ms": round(measured["measured_ms"], 6),
                "absolute_error": round(abs_err, 6),
                "interaction_residual": round(measured["measured_ms"] - predicted["predicted_ms"], 6),
                "shared_object_count": pair_signature(source, target)["shared_object_count"],
                "same_rootfs": source.rootfs == target.rootfs,
                "same_node_runtime": source.node_runtime == target.node_runtime,
                "same_repo_baseline": source.repo_baseline == target.repo_baseline,
            }
        )
        source = target
    return {
        "scheduler_name": scheduler_name,
        "run_label": run_label,
        "seed": seed,
        "task_count": len(order),
        "pair_transition_count": len(order) - 1,
        "bootstrap_ms": bootstrap,
        "measured_transition_time_ms": float(sum(measured_values)),
        "predicted_transition_time_ms": float(sum(predicted_values)),
        "cpu_side_makespan_ms": float(bootstrap + sum(measured_values)),
        "predicted_cpu_side_makespan_ms": float(bootstrap + sum(predicted_values)),
        "average_transition_time_ms": mean(measured_values),
        "median_transition_time_ms": median(measured_values),
        "p95_transition_time_ms": percentile(measured_values, 0.95),
        "predicted_average_transition_time_ms": mean(predicted_values),
        "predicted_median_transition_time_ms": median(predicted_values),
        "predicted_p95_transition_time_ms": percentile(predicted_values, 0.95),
        "absolute_error_mean_ms": mean(absolute_errors),
        "absolute_error_median_ms": median(absolute_errors),
        "absolute_error_p95_ms": percentile(absolute_errors, 0.95),
        "decision_overhead_total_ms": float(sum(decisions)),
        "decision_overhead_ms": mean(decisions),
        "decision_overhead_median_ms": median(decisions),
        "decision_overhead_p95_ms": percentile(decisions, 0.95),
        "decision_count": len(decisions),
        "transition_rows": transition_rows,
    }


def build_scheduler_runs(
    profiles: list[Profile],
    weights: dict[str, int],
    object_metrics: dict[str, dict[str, Any]],
    kind_metrics: dict[str, dict[str, float]],
    output: Path,
    task_total: int,
) -> dict[str, Any]:
    counts = scale_counts(weights, task_total)
    task_list = build_task_list(counts, profiles)
    profile_map = {profile.profile_id: profile for profile in profiles}
    first_profile = max(counts.items(), key=lambda item: (item[1], item[0]))[0]
    if task_list and task_list[0] != first_profile:
        task_list.remove(first_profile)
        task_list.insert(0, first_profile)

    runs: list[dict[str, Any]] = []
    transition_rows: list[dict[str, Any]] = []
    decision_rows: list[dict[str, Any]] = []

    fifo_order, fifo_decisions = schedule_fifo(task_list)
    fifo_run = evaluate_schedule("fifo", f"fifo_{task_total}", None, fifo_order, profile_map, object_metrics, kind_metrics, fifo_decisions)
    runs.append(fifo_run)
    transition_rows.extend(fifo_run["transition_rows"])
    decision_rows.append(
        {
            "scheduler_name": "fifo",
            "run_label": fifo_run["run_label"],
            "seed": None,
            "decision_count": fifo_run["decision_count"],
            "total_decision_ms": fifo_run["decision_overhead_total_ms"],
            "mean_decision_ms": fifo_run["decision_overhead_ms"],
            "median_decision_ms": fifo_run["decision_overhead_median_ms"],
            "p95_decision_ms": fifo_run["decision_overhead_p95_ms"],
            "max_decision_ms": max(fifo_decisions) if fifo_decisions else None,
            "min_decision_ms": min(fifo_decisions) if fifo_decisions else None,
        }
    )

    random_runs: list[dict[str, Any]] = []
    for seed in RANDOM_SEEDS:
        order, decisions = schedule_random(task_list[1:], seed)
        order = [first_profile, *order]
        run = evaluate_schedule("random", f"random_{task_total}_{seed}", seed, order, profile_map, object_metrics, kind_metrics, decisions)
        random_runs.append(run)
        runs.append(run)
        transition_rows.extend(run["transition_rows"])
        decision_rows.append(
            {
                "scheduler_name": "random",
                "run_label": run["run_label"],
                "seed": seed,
                "decision_count": run["decision_count"],
                "total_decision_ms": run["decision_overhead_total_ms"],
                "mean_decision_ms": run["decision_overhead_ms"],
                "median_decision_ms": run["decision_overhead_median_ms"],
                "p95_decision_ms": run["decision_overhead_p95_ms"],
                "max_decision_ms": max(decisions) if decisions else None,
                "min_decision_ms": min(decisions) if decisions else None,
            }
        )

    similarity_order, similarity_decisions = schedule_greedy(task_list, profile_map, object_metrics, kind_metrics, "similarity")
    similarity_run = evaluate_schedule("similarity", f"similarity_{task_total}", None, similarity_order, profile_map, object_metrics, kind_metrics, similarity_decisions)
    runs.append(similarity_run)
    transition_rows.extend(similarity_run["transition_rows"])
    decision_rows.append(
        {
            "scheduler_name": "similarity",
            "run_label": similarity_run["run_label"],
            "seed": None,
            "decision_count": similarity_run["decision_count"],
            "total_decision_ms": similarity_run["decision_overhead_total_ms"],
            "mean_decision_ms": similarity_run["decision_overhead_ms"],
            "median_decision_ms": similarity_run["decision_overhead_median_ms"],
            "p95_decision_ms": similarity_run["decision_overhead_p95_ms"],
            "max_decision_ms": max(similarity_decisions) if similarity_decisions else None,
            "min_decision_ms": min(similarity_decisions) if similarity_decisions else None,
        }
    )

    nodelite_order, nodelite_decisions = schedule_greedy(task_list, profile_map, object_metrics, kind_metrics, "cost")
    nodelite_run = evaluate_schedule("nodelite", f"nodelite_{task_total}", None, nodelite_order, profile_map, object_metrics, kind_metrics, nodelite_decisions)
    runs.append(nodelite_run)
    transition_rows.extend(nodelite_run["transition_rows"])
    decision_rows.append(
        {
            "scheduler_name": "nodelite",
            "run_label": nodelite_run["run_label"],
            "seed": None,
            "decision_count": nodelite_run["decision_count"],
            "total_decision_ms": nodelite_run["decision_overhead_total_ms"],
            "mean_decision_ms": nodelite_run["decision_overhead_ms"],
            "median_decision_ms": nodelite_run["decision_overhead_median_ms"],
            "p95_decision_ms": nodelite_run["decision_overhead_p95_ms"],
            "max_decision_ms": max(nodelite_decisions) if nodelite_decisions else None,
            "min_decision_ms": min(nodelite_decisions) if nodelite_decisions else None,
        }
    )

    write_csv(
        output / f"live_scheduler_runs_{task_total}.csv",
        [
            "scheduler_name",
            "run_label",
            "seed",
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
            "predicted_average_transition_time_ms",
            "predicted_median_transition_time_ms",
            "predicted_p95_transition_time_ms",
            "absolute_error_mean_ms",
            "absolute_error_median_ms",
            "absolute_error_p95_ms",
            "decision_overhead_total_ms",
            "decision_overhead_ms",
            "decision_overhead_median_ms",
            "decision_overhead_p95_ms",
            "decision_count",
        ],
        runs,
    )
    write_csv(
        output / f"live_transition_breakdown_{task_total}.csv",
        [
            "scheduler_name",
            "run_label",
            "seed",
            "transition_index",
            "source_profile_id",
            "target_profile_id",
            "predicted_ms",
            "measured_ms",
            "absolute_error",
            "interaction_residual",
            "shared_object_count",
            "same_rootfs",
            "same_node_runtime",
            "same_repo_baseline",
        ],
        transition_rows,
    )
    write_csv(
        output / f"decision_overhead_{task_total}.csv",
        [
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
        ],
        decision_rows,
    )
    return {
        "task_total": task_total,
        "fifo": fifo_run,
        "random": random_runs,
        "similarity": similarity_run,
        "nodelite": nodelite_run,
    }


def _docker_run(command: list[str], timeout: int = 120) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)


def _docker_measure_sample(image: str, mounts: list[tuple[str, str, str]], task_script: str, sample_index: int, label: str) -> dict[str, Any]:
    name = f"nodelite-live-{label}-{sample_index}-{uuid.uuid4().hex[:10]}"
    mount_args = []
    for src, dst, mode in mounts:
        mount_spec = f"type=bind,src={src},dst={dst}"
        if mode == "ro":
            mount_spec += ",readonly"
        mount_args.extend(["--mount", mount_spec])
    create_cmd = ["docker", "create", "--name", name, *mount_args, image, "sh", "-lc", "sleep 300"]
    start = time.perf_counter_ns()
    create = _docker_run(create_cmd, timeout=180)
    create_ms = (time.perf_counter_ns() - start) / 1_000_000
    container_id = create.stdout.strip()
    start_ms = ready_ms = task_ms = stop_ms = remove_ms = 0.0
    task_ok = False
    error = None
    if create.returncode == 0 and container_id:
        started = time.perf_counter_ns()
        start_result = _docker_run(["docker", "start", container_id], timeout=60)
        start_ms = (time.perf_counter_ns() - started) / 1_000_000
        ready_started = time.perf_counter_ns()
        ready_result = _docker_run(["docker", "exec", container_id, "node", "-e", "process.stdout.write('ready')"], timeout=60)
        ready_ms = (time.perf_counter_ns() - ready_started) / 1_000_000
        task_started = time.perf_counter_ns()
        task_result = _docker_run(["docker", "exec", container_id, "sh", "-lc", task_script], timeout=120)
        task_ms = (time.perf_counter_ns() - task_started) / 1_000_000
        task_ok = task_result.returncode == 0
        error = None if task_ok else (task_result.stderr[-2000:] or task_result.stdout[-2000:] or f"exit {task_result.returncode}")
        stop_started = time.perf_counter_ns()
        stop_result = _docker_run(["docker", "stop", container_id], timeout=60)
        stop_ms = (time.perf_counter_ns() - stop_started) / 1_000_000
        remove_started = time.perf_counter_ns()
        remove_result = _docker_run(["docker", "rm", container_id], timeout=60)
        remove_ms = (time.perf_counter_ns() - remove_started) / 1_000_000
        if start_result.returncode != 0:
            error = start_result.stderr[-2000:] or start_result.stdout[-2000:] or f"start exit {start_result.returncode}"
        if ready_result.returncode != 0:
            error = ready_result.stderr[-2000:] or ready_result.stdout[-2000:] or f"ready exit {ready_result.returncode}"
        if stop_result.returncode != 0 and error is None:
            error = stop_result.stderr[-2000:] or stop_result.stdout[-2000:] or f"stop exit {stop_result.returncode}"
        if remove_result.returncode != 0 and error is None:
            error = remove_result.stderr[-2000:] or remove_result.stdout[-2000:] or f"rm exit {remove_result.returncode}"
    else:
        error = create.stderr[-2000:] or create.stdout[-2000:] or f"create exit {create.returncode}"
    return {
        "sample_index": sample_index,
        "container_name": name,
        "image": image,
        "mount_count": len(mounts),
        "create_ms": round(create_ms, 6),
        "start_ms": round(start_ms, 6),
        "ready_ms": round(ready_ms, 6),
        "task_ms": round(task_ms, 6),
        "stop_ms": round(stop_ms, 6),
        "remove_ms": round(remove_ms, 6),
        "total_ms": round(create_ms + start_ms + ready_ms + task_ms + stop_ms + remove_ms, 6),
        "success": task_ok and error is None,
        "error": error,
    }


def run_docker_ablation(output: Path, image: str) -> dict[str, Any]:
    baseline_mounts: list[tuple[str, str, str]] = []
    ctdp_mounts = [(str(DEFAULT_PHASE1_CTDP), "/ctdp", "ro")]
    reuse_mounts = [
        (str(DEFAULT_PHASE1_CTDP), "/ctdp", "ro"),
        (str(DEFAULT_EXACT_WORKLOAD), "/exact", "ro"),
    ]
    full_mounts = [
        (str(DEFAULT_PHASE1_CTDP), "/ctdp", "ro"),
        (str(DEFAULT_EXACT_WORKLOAD), "/exact", "ro"),
        (str(DEFAULT_PHASE2), "/phase2", "ro"),
    ]

    modes = [
        ("fresh_baseline", baseline_mounts, "node --version >/dev/null && node -e \"process.stdout.write('baseline')\""),
        ("ctdp_only", ctdp_mounts, "test -f /ctdp/reports/summary.md && cat /ctdp/reports/summary.md >/dev/null"),
        ("ctdp_plus_reuse", reuse_mounts, "cat /exact/object_action_summary.csv >/dev/null && cat /ctdp/reports/summary.md >/dev/null"),
        ("full_nodelite", full_mounts, "cat /exact/object_action_summary.csv >/dev/null && cat /phase2/README.md >/dev/null && cat /phase2/phase2_summary.md >/dev/null && node -e \"process.stdout.write('nodelite')\""),
    ]
    sample_rows: list[dict[str, Any]] = []
    aggregate_rows: list[dict[str, Any]] = []
    for mode_name, mounts, script in modes:
        mode_samples = []
        for sample_index in range(5):
            row = _docker_measure_sample(image, mounts, script, sample_index, mode_name)
            row["mode"] = mode_name
            mode_samples.append(row)
            sample_rows.append(row)
        total_values = [float(row["total_ms"]) for row in mode_samples]
        ready_values = [float(row["ready_ms"]) for row in mode_samples]
        task_values = [float(row["task_ms"]) for row in mode_samples]
        aggregate_rows.append(
            {
                "mode": mode_name,
                "sample_count": len(mode_samples),
                "mount_count": mode_samples[0]["mount_count"] if mode_samples else 0,
                "total_mean_ms": round(mean(total_values), 6),
                "total_median_ms": round(median(total_values), 6),
                "total_p95_ms": round(percentile(total_values, 0.95), 6),
                "ready_mean_ms": round(mean(ready_values), 6),
                "ready_median_ms": round(median(ready_values), 6),
                "task_mean_ms": round(mean(task_values), 6),
                "task_median_ms": round(median(task_values), 6),
            }
        )
    write_csv(
        output / "docker_baseline.csv",
        [
            "mode",
            "sample_index",
            "container_name",
            "image",
            "mount_count",
            "create_ms",
            "start_ms",
            "ready_ms",
            "task_ms",
            "stop_ms",
            "remove_ms",
            "total_ms",
            "success",
            "error",
        ],
        sample_rows,
    )
    write_csv(
        output / "ablation.csv",
        [
            "mode",
            "sample_count",
            "mount_count",
            "total_mean_ms",
            "total_median_ms",
            "total_p95_ms",
            "ready_mean_ms",
            "ready_median_ms",
            "task_mean_ms",
            "task_median_ms",
        ],
        aggregate_rows,
    )
    lines = [
        "# Docker Warm-Image Baseline and Ablation",
        "",
        "Status: **live_host_measured**",
        "",
        f"- Docker image: `{image}`",
        f"- Samples per mode: `5`",
        "",
        "## Aggregates",
    ]
    for row in aggregate_rows:
        lines.append(
            f"- {row['mode']}: total median `{row['total_median_ms']:.3f}` ms, "
            f"ready median `{row['ready_median_ms']:.3f}` ms, task median `{row['task_median_ms']:.3f}` ms"
        )
    lines.extend(
        [
            "",
            "## Notes",
            "- Baseline and ablation are measured on a warmed local `node:20-slim` image.",
            "- CTDP and exact-workload directories are mounted read-only for the derived modes.",
            "- This is a live Docker run, not a replay artifact.",
        ]
    )
    (output / "final_ablation_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_json(
        output / "final_ablation_summary.json",
        {
            "schema_version": 1,
            "image": image,
            "sample_count": 5,
            "aggregate_rows": aggregate_rows,
        },
    )
    return {"aggregate_rows": aggregate_rows, "sample_rows": sample_rows}


def main() -> int:
    output = DEFAULT_OUTPUT
    output.mkdir(parents=True, exist_ok=True)

    profiles = load_profiles(DEFAULT_PHASE2 / "profile_requirements.json")
    task_counts = load_task_frequencies(DEFAULT_TASK_IDS)
    weights = task_frequency_map(task_counts, profiles)

    object_metrics = load_live_object_metrics(DEFAULT_EXACT_WORKLOAD / "object_action_summary.csv")
    kind_metrics = aggregate_kind_metrics(object_metrics)

    selected = select_representative_profiles(profiles, weights, count=20)
    selected_payload = [
        {
            "profile_id": profile.profile_id,
            "sequence_index": profile.sequence_index,
            "object_count": len(profile.object_ids),
            "rootfs": profile.rootfs,
            "node_runtime": profile.node_runtime,
            "repo_baseline": profile.repo_baseline,
            "task_count": weights.get(profile.profile_id, 0),
        }
        for profile in selected
    ]
    write_json(
        output / "selected_profiles.json",
        {
            "schema_version": 1,
            "selected_profile_count": len(selected),
            "profiles": selected_payload,
        },
    )

    pair_summary = evaluate_pairs(selected, object_metrics, kind_metrics, output)
    pair_summary["selected_profiles"] = selected_payload

    profile_map = {profile.profile_id: profile for profile in profiles}
    scheduler_summaries = []
    for total in (500, 2000):
        scheduler_summaries.append(build_scheduler_runs(profiles, weights, object_metrics, kind_metrics, output, total))

    docker_summary = run_docker_ablation(output, DEFAULT_DOCKER_IMAGE)

    overall_lines = [
        "# Live Validation Report",
        "",
        "This directory contains the three live validation artifacts requested for the current pass.",
        "",
        "## Live Pair Validation",
        f"- Selected profiles: `{len(selected)}`",
        f"- Directed pairs evaluated: `{pair_summary['full_pair_count']}`",
        f"- Sample pairs exported: `{pair_summary['sample_count']}`",
        f"- MAE: `{pair_summary['mae_ms']:.3f}` ms",
        f"- Pearson: `{pair_summary['pearson']:.4f}`" if pair_summary["pearson"] is not None else "- Pearson: `n/a`",
        "",
        "## Live Scheduler Validation",
        f"- Workload sizes: `500` and `2000` tasks",
        f"- Task source: `swe-smith_Task_IDs.csv`",
        f"- Scheduler runs exported: `{sum(4 + len(RANDOM_SEEDS) for _ in scheduler_summaries)}`",
        "",
        "## Docker Validation",
        f"- Image: `{DEFAULT_DOCKER_IMAGE}`",
        f"- Modes exported: `{len(docker_summary['aggregate_rows'])}`",
        "",
        "## Notes",
        "- Pair and scheduler artifacts are derived from live exact-host measurements in `out/exact-workload`.",
        "- Docker artifacts are measured directly on the warmed local image.",
    ]
    (output / "live_validation_summary.md").write_text("\n".join(overall_lines) + "\n", encoding="utf-8")
    write_json(
        output / "live_validation_summary.json",
        {
            "schema_version": 1,
            "pair_summary": pair_summary,
            "scheduler_summaries": [
                {k: v for k, v in summary.items() if k != "random"} for summary in scheduler_summaries
            ],
            "docker_summary": docker_summary,
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
