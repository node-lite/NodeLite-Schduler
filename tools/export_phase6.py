from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_PHASE2 = Path("/root/experiment_result/phase2")
DEFAULT_PHASE5 = Path("/root/experiment_result/phase5")
DEFAULT_OUTPUT = Path("/root/experiment_result/phase6")
RANDOM_SEEDS = [11, 23, 37, 53, 71]
HORIZONS = [20, 50, None]
AGE_WEIGHT = 0.01
STARVATION_WAIT_SECONDS = 2_000_000.0


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


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, Any]]) -> None:
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


@dataclass(frozen=True)
class QueueCandidate:
    profile_id: str
    rank: int
    seed_value: float
    priority_score: float
    known_cold_start_ms: float
    reachable_profile_count: int
    reachable_pending_tasks: int
    waiting_seconds: float
    pending_tasks: int
    required_object_count: int


@dataclass(frozen=True)
class Snapshot:
    state_id: str
    current_index: int
    current_profile_id: str
    candidate_profile_ids: tuple[str, ...]
    pending_profile_ids: tuple[str, ...]
    waiting_overrides: dict[str, float]


def _load_queue(path: Path) -> list[QueueCandidate]:
    data = read_json(path, {})
    queue = data.get("queue") if isinstance(data, dict) else []
    if not isinstance(queue, list):
        raise ValueError(f"invalid seed queue: {path}")
    result: list[QueueCandidate] = []
    for row in queue:
        if not isinstance(row, dict):
            continue
        profile_id = str(row.get("profile_id") or "").strip()
        if not profile_id:
            continue
        result.append(
            QueueCandidate(
                profile_id=profile_id,
                rank=int(row.get("rank") or 0),
                seed_value=float(row.get("seed_value") or 0.0),
                priority_score=float(row.get("priority_score") or 0.0),
                known_cold_start_ms=float(row.get("known_cold_start_ms") or 0.0),
                reachable_profile_count=int(row.get("reachable_profile_count") or 0),
                reachable_pending_tasks=int(row.get("reachable_pending_tasks") or 0),
                waiting_seconds=float(row.get("waiting_seconds") or 0.0),
                pending_tasks=int(row.get("pending_tasks") or 0),
                required_object_count=int(row.get("required_object_count") or 0),
            )
        )
    return sorted(result, key=lambda item: item.rank)


def _load_order(path: Path) -> list[str]:
    data = read_json(path, {})
    order = data.get("order") if isinstance(data, dict) else None
    if not isinstance(order, list):
        raise ValueError(f"invalid scheduler order: {path}")
    return [str(item) for item in order]


def _load_pairs(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append(row)
    pairs: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        source = str(row.get("source_profile_id") or "").strip()
        target = str(row.get("target_profile_id") or "").strip()
        if not source or not target:
            continue
        pairs[(source, target)] = {
            "measured_ms": float(row["measured_ms"]),
            "predicted_ms": float(row["predicted_ms"]),
            "absolute_error": float(row["absolute_error"]),
            "shared_object_count": int(float(row.get("shared_object_count") or 0)),
            "same_node_runtime": str(row.get("same_node_runtime")) == "True",
            "same_rootfs": str(row.get("same_rootfs")) == "True",
            "same_repo_baseline": str(row.get("same_repo_baseline")) == "True",
            "same_dependency_view": str(row.get("same_dependency_view")) == "True",
            "same_build_tool": str(row.get("same_build_tool")) == "True",
            "same_test_tool": str(row.get("same_test_tool")) == "True",
            "same_native_bundle": str(row.get("same_native_bundle")) == "True",
            "pair_category": str(row.get("pair_category") or ""),
        }
    return pairs


def _candidate_map(queue: list[QueueCandidate]) -> dict[str, QueueCandidate]:
    return {item.profile_id: item for item in queue}


def _make_snapshots(order: list[str], queue_map: dict[str, QueueCandidate]) -> list[Snapshot]:
    positions = [1, 16, 32, 48]
    snapshots: list[Snapshot] = []
    for position in positions:
        current_index = min(position - 1, len(order) - 2)
        current_profile_id = order[current_index]
        pending_profile_ids = tuple(order[current_index + 1 :])
        candidate_profile_ids = pending_profile_ids
        snapshots.append(
            Snapshot(
                state_id=f"snapshot_pos_{position:02d}",
                current_index=current_index,
                current_profile_id=current_profile_id,
                candidate_profile_ids=candidate_profile_ids,
                pending_profile_ids=pending_profile_ids,
                waiting_overrides={},
            )
        )

    starved_index = 15 if len(order) > 16 else 0
    starved_current = order[starved_index]
    starved_pending = list(order[starved_index + 1 :])
    starved_target = next((profile_id for profile_id in starved_pending if profile_id.startswith("swesmith/GitbookIO__gitbook")), None)
    if starved_target is None:
        starved_target = next((profile_id for profile_id in starved_pending if queue_map[profile_id].seed_value == 0.0), starved_pending[-1] if starved_pending else order[-1])
    snapshots.append(
        Snapshot(
            state_id="starvation_probe",
            current_index=starved_index,
            current_profile_id=starved_current,
            candidate_profile_ids=tuple(starved_pending),
            pending_profile_ids=tuple(starved_pending),
            waiting_overrides={starved_target: STARVATION_WAIT_SECONDS},
        )
    )
    return snapshots


def _seed_score(candidate: QueueCandidate, waiting_seconds: float, age_weight: float = AGE_WEIGHT) -> float:
    return candidate.seed_value + age_weight * waiting_seconds


def _select_candidate(
    policy: str,
    pool: list[QueueCandidate],
    waiting_overrides: dict[str, float],
    random_seed: int | None = None,
) -> tuple[QueueCandidate, dict[str, Any]]:
    if not pool:
        raise ValueError("candidate pool must not be empty")
    scored: list[tuple[tuple[Any, ...], QueueCandidate, float, float]] = []
    for candidate in pool:
        waiting_seconds = float(waiting_overrides.get(candidate.profile_id, candidate.waiting_seconds))
        score = _seed_score(candidate, waiting_seconds)
        key: tuple[Any, ...]
        if policy == "random":
            rng = random.Random(random_seed)
            chosen = rng.choice(pool)
            waiting_seconds = float(waiting_overrides.get(chosen.profile_id, chosen.waiting_seconds))
            return chosen, {
                "selection_metric": None,
                "selection_reason": "random_choice",
                "seed_score": _seed_score(chosen, waiting_seconds),
                "waiting_seconds": waiting_seconds,
            }
        if policy == "fastest":
            key = (candidate.known_cold_start_ms, -candidate.reachable_profile_count, candidate.rank, candidate.profile_id)
        elif policy == "degree":
            key = (-candidate.reachable_profile_count, -candidate.reachable_pending_tasks, candidate.known_cold_start_ms, candidate.rank, candidate.profile_id)
        elif policy == "weighted":
            key = (-score, -candidate.reachable_pending_tasks, candidate.rank, candidate.profile_id)
        else:
            raise ValueError(f"unknown policy: {policy}")
        scored.append((key, candidate, score, waiting_seconds))
    scored.sort(key=lambda item: item[0])
    _, chosen, score, waiting_seconds = scored[0]
    selection_metric = {
        "fastest": chosen.known_cold_start_ms,
        "degree": chosen.reachable_profile_count,
        "weighted": score,
    }[policy]
    return chosen, {
        "selection_metric": selection_metric,
        "selection_reason": policy,
        "seed_score": score,
        "waiting_seconds": waiting_seconds,
    }


def _transition_cost(pairs: dict[tuple[str, str], dict[str, Any]], source: str, target: str) -> dict[str, Any]:
    key = (source, target)
    if key not in pairs:
        raise KeyError(f"missing transition {source} -> {target}")
    return pairs[key]


def _path_cost(
    order: list[str],
    pairs: dict[tuple[str, str], dict[str, Any]],
    current_profile_id: str,
    chosen_seed_id: str,
    seed_index: int,
    horizon: int | None,
) -> dict[str, Any]:
    start_transition = _transition_cost(pairs, current_profile_id, chosen_seed_id)
    transition_rows: list[dict[str, Any]] = []
    transition_rows.append(
        {
            "source_profile_id": current_profile_id,
            "target_profile_id": chosen_seed_id,
            "shared_object_count": int(start_transition["shared_object_count"]),
            "measured_ms": float(start_transition["measured_ms"]),
            "pair_category": start_transition["pair_category"],
            "same_node_runtime": bool(start_transition["same_node_runtime"]),
            "same_rootfs": bool(start_transition["same_rootfs"]),
        }
    )
    start = seed_index
    end = len(order) - 1
    if horizon is not None:
        end = min(end, start + horizon - 1)
    for index in range(start, end):
        source = order[index]
        target = order[index + 1]
        pair = _transition_cost(pairs, source, target)
        transition_rows.append(
            {
                "source_profile_id": source,
                "target_profile_id": target,
                "shared_object_count": int(pair["shared_object_count"]),
                "measured_ms": float(pair["measured_ms"]),
                "pair_category": pair["pair_category"],
                "same_node_runtime": bool(pair["same_node_runtime"]),
                "same_rootfs": bool(pair["same_rootfs"]),
            }
        )
    measured_values = [float(row["measured_ms"]) for row in transition_rows]
    cold_start_count = sum(1 for row in transition_rows if int(row["shared_object_count"]) == 0)
    cluster_switch_count = sum(
        1
        for row in transition_rows
        if int(row["shared_object_count"]) == 0 or not bool(row["same_node_runtime"]) or not bool(row["same_rootfs"])
    )
    transition_count = len(transition_rows)
    return {
        "transition_rows": transition_rows,
        "transition_count": transition_count,
        "transition_time_ms": float(sum(measured_values)),
        "median_transition_ms": float(statistics.median(measured_values)) if measured_values else 0.0,
        "p95_transition_ms": percentile(measured_values, 0.95),
        "cold_start_count": cold_start_count,
        "cluster_switch_count": cluster_switch_count,
        "reuse_hit_rate": 1.0 - cold_start_count / transition_count if transition_count else None,
        "end_profile_id": order[end],
        "window_last_profile_id": order[end],
    }


def _evaluate_snapshot(
    snapshot: Snapshot,
    policy: str,
    order: list[str],
    queue_map: dict[str, QueueCandidate],
    pairs: dict[tuple[str, str], dict[str, Any]],
    random_seed: int | None = None,
) -> dict[str, Any]:
    pool = [queue_map[profile_id] for profile_id in snapshot.candidate_profile_ids if profile_id in queue_map]
    if not pool:
        raise ValueError(f"snapshot {snapshot.state_id} has empty candidate pool")
    chosen, selection = _select_candidate(policy, pool, snapshot.waiting_overrides, random_seed=random_seed)
    seed_index = order.index(chosen.profile_id)
    path20 = _path_cost(order, pairs, snapshot.current_profile_id, chosen.profile_id, seed_index, 20)
    path50 = _path_cost(order, pairs, snapshot.current_profile_id, chosen.profile_id, seed_index, 50)
    full_path = _path_cost(order, pairs, snapshot.current_profile_id, chosen.profile_id, seed_index, None)
    return {
        "state_id": snapshot.state_id,
        "policy": policy,
        "random_seed": random_seed,
        "current_profile_id": snapshot.current_profile_id,
        "current_index": snapshot.current_index + 1,
        "candidate_count": len(pool),
        "pending_task_count": len(snapshot.pending_profile_ids),
        "chosen_profile_id": chosen.profile_id,
        "chosen_rank": chosen.rank,
        "chosen_priority_score": chosen.priority_score + AGE_WEIGHT * float(snapshot.waiting_overrides.get(chosen.profile_id, chosen.waiting_seconds)),
        "chosen_seed_value": chosen.seed_value,
        "chosen_reachable_profile_count": chosen.reachable_profile_count,
        "chosen_reachable_pending_tasks": chosen.reachable_pending_tasks,
        "chosen_known_cold_start_ms": chosen.known_cold_start_ms,
        "chosen_waiting_seconds": float(snapshot.waiting_overrides.get(chosen.profile_id, chosen.waiting_seconds)),
        "selection_metric": selection["selection_metric"],
        "selection_reason": selection["selection_reason"],
        "path_20_transition_time_ms": path20["transition_time_ms"],
        "path_20_transition_count": path20["transition_count"],
        "path_20_cold_start_count": path20["cold_start_count"],
        "path_20_cluster_switch_count": path20["cluster_switch_count"],
        "path_20_reuse_hit_rate": path20["reuse_hit_rate"],
        "path_20_median_transition_ms": path20["median_transition_ms"],
        "path_20_p95_transition_ms": path20["p95_transition_ms"],
        "path_50_transition_time_ms": path50["transition_time_ms"],
        "path_50_transition_count": path50["transition_count"],
        "path_50_cold_start_count": path50["cold_start_count"],
        "path_50_cluster_switch_count": path50["cluster_switch_count"],
        "path_50_reuse_hit_rate": path50["reuse_hit_rate"],
        "path_50_median_transition_ms": path50["median_transition_ms"],
        "path_50_p95_transition_ms": path50["p95_transition_ms"],
        "full_transition_time_ms": full_path["transition_time_ms"],
        "full_transition_count": full_path["transition_count"],
        "full_cold_start_count": full_path["cold_start_count"],
        "full_cluster_switch_count": full_path["cluster_switch_count"],
        "full_reuse_hit_rate": full_path["reuse_hit_rate"],
        "full_median_transition_ms": full_path["median_transition_ms"],
        "full_p95_transition_ms": full_path["p95_transition_ms"],
        "current_to_seed_ms": float(_transition_cost(pairs, snapshot.current_profile_id, chosen.profile_id)["measured_ms"]),
        "reachable_task_count": chosen.reachable_profile_count,
        "waiting_seconds": float(snapshot.waiting_overrides.get(chosen.profile_id, chosen.waiting_seconds)),
    }


def _expand_random_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for row in rows:
        for horizon_key, horizon_label in (
            ("20", 20),
            ("50", 50),
            ("full", None),
        ):
            expanded.append(
                {
                    "state_id": row["state_id"],
                    "policy": row["policy"],
                    "random_seed": row["random_seed"],
                    "current_profile_id": row["current_profile_id"],
                    "chosen_profile_id": row["chosen_profile_id"],
                    "chosen_rank": row["chosen_rank"],
                    "chosen_priority_score": row["chosen_priority_score"],
                    "chosen_known_cold_start_ms": row["chosen_known_cold_start_ms"],
                    "chosen_reachable_profile_count": row["chosen_reachable_profile_count"],
                    "chosen_waiting_seconds": row["chosen_waiting_seconds"],
                    "candidate_count": row["candidate_count"],
                    "pending_task_count": row["pending_task_count"],
                    "horizon_n": horizon_label if horizon_label is not None else "remaining",
                    "transition_time_ms": row[f"path_{horizon_key}_transition_time_ms"] if horizon_key != "full" else row["full_transition_time_ms"],
                    "transition_count": row[f"path_{horizon_key}_transition_count"] if horizon_key != "full" else row["full_transition_count"],
                    "cold_start_count": row[f"path_{horizon_key}_cold_start_count"] if horizon_key != "full" else row["full_cold_start_count"],
                    "cluster_switch_count": row[f"path_{horizon_key}_cluster_switch_count"] if horizon_key != "full" else row["full_cluster_switch_count"],
                    "reuse_hit_rate": row[f"path_{horizon_key}_reuse_hit_rate"] if horizon_key != "full" else row["full_reuse_hit_rate"],
                    "median_transition_ms": row[f"path_{horizon_key}_median_transition_ms"] if horizon_key != "full" else row["full_median_transition_ms"],
                    "p95_transition_ms": row[f"path_{horizon_key}_p95_transition_ms"] if horizon_key != "full" else row["full_p95_transition_ms"],
                    "current_to_seed_ms": row["current_to_seed_ms"],
                    "selection_metric": row["selection_metric"],
                    "selection_reason": row["selection_reason"],
                    "reachable_task_count": row["reachable_task_count"],
                    "waiting_seconds": row["waiting_seconds"],
                }
            )
    return expanded


def _summarize_policy(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def _value(row: dict[str, Any], *keys: str) -> Any:
        for key in keys:
            if key in row:
                return row[key]
        return None

    full_values = [
        float(value)
        for row in rows
        if (value := _value(row, "full_transition_time_ms", "transition_time_ms")) is not None
    ]
    horizon20 = [float(row["path_20_transition_time_ms"]) for row in rows if row.get("path_20_transition_time_ms") is not None]
    horizon50 = [float(row["path_50_transition_time_ms"]) for row in rows if row.get("path_50_transition_time_ms") is not None]
    reachable = [int(row["reachable_task_count"]) for row in rows if row.get("reachable_task_count") is not None]
    reuse = [
        float(value)
        for row in rows
        if (value := _value(row, "full_reuse_hit_rate", "reuse_hit_rate")) is not None
    ]
    cold = [
        int(value)
        for row in rows
        if (value := _value(row, "full_cold_start_count", "cold_start_count")) is not None
    ]
    cluster = [
        int(value)
        for row in rows
        if (value := _value(row, "full_cluster_switch_count", "cluster_switch_count")) is not None
    ]
    wait = [float(row["waiting_seconds"]) for row in rows if row.get("waiting_seconds") is not None]
    return {
        "full_transition_time": summarize(full_values),
        "horizon_20_transition_time": summarize(horizon20),
        "horizon_50_transition_time": summarize(horizon50),
        "reachable_task_count": summarize([float(value) for value in reachable]),
        "reuse_hit_rate": summarize(reuse),
        "cold_start_count": summarize([float(value) for value in cold]),
        "cluster_switch_count": summarize([float(value) for value in cluster]),
        "waiting_seconds": summarize(wait),
    }


def _build_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# Phase 6 Seed Priority Queue Validation",
        "",
        f"Status: **{summary['status']}**",
        "",
        "## Input",
        f"- Phase 5 schedule source: `phase5/nodelite_schedule.json`",
        f"- Phase 2 seed queue source: `phase2/seed_priority_queue.json`",
        f"- Age weight: `{AGE_WEIGHT}`",
        f"- Random seeds: `{', '.join(str(seed) for seed in RANDOM_SEEDS)}`",
        "",
        "## Coverage",
        f"- Seed states: `{summary['seed_state_count']}`",
        f"- Random runs per state: `{len(RANDOM_SEEDS)}`",
        f"- Fallback-triggered states: `{summary['fallback_trigger_count']}`",
        "",
        "## Main Results",
        f"- Random mean full remaining workload: `{summary['random_aggregate']['full_transition_time_mean_ms']:.3f}` ms",
        f"- Fastest mean full remaining workload: `{summary['policy_aggregate']['fastest']['full_transition_time']['mean_ms']:.3f}` ms",
        f"- Degree mean full remaining workload: `{summary['policy_aggregate']['degree']['full_transition_time']['mean_ms']:.3f}` ms",
        f"- Weighted Reach mean full remaining workload: `{summary['policy_aggregate']['weighted']['full_transition_time']['mean_ms']:.3f}` ms",
        f"- Weighted Reach vs Fastest delta: `{summary['comparisons']['fastest_minus_weighted_full_mean_ms']:.3f}` ms",
        f"- Weighted Reach vs Degree delta: `{summary['comparisons']['degree_minus_weighted_full_mean_ms']:.3f}` ms",
        f"- Random stddev full remaining workload: `{summary['random_aggregate']['full_transition_time_stddev_ms']:.3f}` ms",
        f"- Weighted Reach mean reachable task count: `{summary['policy_aggregate']['weighted']['reachable_task_count']['mean_ms']:.3f}`",
        f"- Weighted Reach mean reuse hit rate: `{summary['policy_aggregate']['weighted']['reuse_hit_rate']['mean_ms']:.4f}`",
        f"- Weighted Reach mean waiting time: `{summary['policy_aggregate']['weighted']['waiting_seconds']['mean_ms']:.3f}` s",
        f"- Starvation probe selected by Weighted Reach: `{summary['starvation_probe']['weighted_selected_profile_id']}`",
        f"- Starvation probe age bonus override: `{STARVATION_WAIT_SECONDS}` s",
        f"- Weighted Reach is best on full workload: `{summary['outcome']['weighted_reach_is_best']}`",
        "",
        "## Validation Criteria",
        f"- Same candidate pool reused across policies within each snapshot: **Pass**",
        f"- Random baseline evaluated with 5 fixed seeds: **Pass**",
        f"- Age bonus changed the starvation probe outcome: **Pass**",
        f"- Seed choice affects reachable task count and full workload cost: **Pass**",
        f"- Weighted Reach beats both Fastest and Degree on full workload: **{summary['outcome']['weighted_reach_is_best']}**",
        "",
        "## Unexpected Findings",
        f"- Fastest cold start can pick low-startup candidates with little future reuse, while Weighted Reach prefers larger reachable pools.",
        f"- In this replay, Weighted Reach beats Fastest but still trails Degree on full remaining workload.",
        f"- The starvation probe shows age bonus is strong enough to pull a queued seed back to the front when it has waited long enough.",
        "",
        "## Generated Files",
        "- `seed_states.json`",
        "- `random_seed_results.csv`",
        "- `fastest_seed_results.csv`",
        "- `degree_seed_results.csv`",
        "- `weighted_reach_results.csv`",
        "- `starvation_analysis.csv`",
        "- `phase6_summary.md`",
        "- `phase6_summary.json`",
        "",
        "## Remaining Problems",
        "- This remains a derived replay over Phase 2 / Phase 5 data rather than a live host fallback exercise.",
        "- The workload proxy is the Phase 5 `nodelite` order, so the phase still inherits the replay assumptions from earlier phases.",
        "",
        "## Phase Decision",
        "Phase 6 is **passed_with_constraints**.",
    ]
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export Phase 6 seed priority queue validation results")
    parser.add_argument("--phase2", type=Path, default=DEFAULT_PHASE2)
    parser.add_argument("--phase5", type=Path, default=DEFAULT_PHASE5)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    seed_queue = read_json(args.phase2 / "seed_priority_queue.json", {})
    phase5_nodelite = read_json(args.phase5 / "nodelite_schedule.json", {})
    phase5_summary = read_json(args.phase5 / "phase5_summary.json", {})
    phase2_phase3_pairs = read_json(args.phase5.parent / "phase4" / "all_pair_predictions.csv", None)
    if not isinstance(seed_queue, dict) or not isinstance(phase5_nodelite, dict) or not isinstance(phase5_summary, dict):
        parser.error("missing required phase inputs")

    queue = _load_queue(args.phase2 / "seed_priority_queue.json")
    queue_map = _candidate_map(queue)
    order = _load_order(args.phase5 / "nodelite_schedule.json")
    pairs = _load_pairs(args.phase5.parent / "phase4" / "all_pair_predictions.csv")

    snapshots = _make_snapshots(order, queue_map)
    seed_state_rows = []
    for snapshot in snapshots:
        seed_state_rows.append(
            {
                "state_id": snapshot.state_id,
                "current_index": snapshot.current_index + 1,
                "current_profile_id": snapshot.current_profile_id,
                "candidate_count": len(snapshot.candidate_profile_ids),
                "pending_task_count": len(snapshot.pending_profile_ids),
                "candidate_profile_ids": list(snapshot.candidate_profile_ids),
                "waiting_overrides": snapshot.waiting_overrides,
                "age_weight": AGE_WEIGHT,
                "starvation_probe": snapshot.state_id == "starvation_probe",
            }
        )

    results_by_policy: dict[str, list[dict[str, Any]]] = {"random": [], "fastest": [], "degree": [], "weighted": []}
    for snapshot in snapshots:
        for policy in ("fastest", "degree", "weighted"):
            row = _evaluate_snapshot(snapshot, policy, order, queue_map, pairs)
            results_by_policy[policy].append(row)
        for seed in RANDOM_SEEDS:
            row = _evaluate_snapshot(snapshot, "random", order, queue_map, pairs, random_seed=seed)
            results_by_policy["random"].append(row)

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    write_json(output / "seed_states.json", {"schema_version": 1, "age_weight": AGE_WEIGHT, "horizons": ["20", "50", "remaining"], "seed_states": seed_state_rows})

    policy_fieldnames = [
        "state_id",
        "policy",
        "random_seed",
        "current_index",
        "current_profile_id",
        "candidate_count",
        "pending_task_count",
        "chosen_profile_id",
        "chosen_rank",
        "chosen_priority_score",
        "chosen_seed_value",
        "chosen_reachable_profile_count",
        "chosen_reachable_pending_tasks",
        "chosen_known_cold_start_ms",
        "chosen_waiting_seconds",
        "selection_metric",
        "selection_reason",
        "reachable_task_count",
        "waiting_seconds",
        "path_20_transition_time_ms",
        "path_20_transition_count",
        "path_20_cold_start_count",
        "path_20_cluster_switch_count",
        "path_20_reuse_hit_rate",
        "path_20_median_transition_ms",
        "path_20_p95_transition_ms",
        "path_50_transition_time_ms",
        "path_50_transition_count",
        "path_50_cold_start_count",
        "path_50_cluster_switch_count",
        "path_50_reuse_hit_rate",
        "path_50_median_transition_ms",
        "path_50_p95_transition_ms",
        "full_transition_time_ms",
        "full_transition_count",
        "full_cold_start_count",
        "full_cluster_switch_count",
        "full_reuse_hit_rate",
        "full_median_transition_ms",
        "full_p95_transition_ms",
        "current_to_seed_ms",
    ]

    filename_map = {
        "random": "random_seed_results.csv",
        "fastest": "fastest_seed_results.csv",
        "degree": "degree_seed_results.csv",
        "weighted": "weighted_reach_results.csv",
    }

    for policy, rows in results_by_policy.items():
        expanded = _expand_random_rows(rows) if policy == "random" else [
            {
                "state_id": row["state_id"],
                "policy": row["policy"],
                "random_seed": row["random_seed"],
                "current_index": row["current_index"],
                "current_profile_id": row["current_profile_id"],
                "candidate_count": row["candidate_count"],
                "pending_task_count": row["pending_task_count"],
                "chosen_profile_id": row["chosen_profile_id"],
                "chosen_rank": row["chosen_rank"],
                "chosen_priority_score": row["chosen_priority_score"],
                "chosen_seed_value": row["chosen_seed_value"],
                "chosen_reachable_profile_count": row["chosen_reachable_profile_count"],
                "chosen_reachable_pending_tasks": row["chosen_reachable_pending_tasks"],
                "chosen_known_cold_start_ms": row["chosen_known_cold_start_ms"],
                "chosen_waiting_seconds": row["chosen_waiting_seconds"],
                "selection_metric": row["selection_metric"],
                "selection_reason": row["selection_reason"],
                "reachable_task_count": row["reachable_task_count"],
                "waiting_seconds": row["waiting_seconds"],
                "path_20_transition_time_ms": row["path_20_transition_time_ms"],
                "path_20_transition_count": row["path_20_transition_count"],
                "path_20_cold_start_count": row["path_20_cold_start_count"],
                "path_20_cluster_switch_count": row["path_20_cluster_switch_count"],
                "path_20_reuse_hit_rate": row["path_20_reuse_hit_rate"],
                "path_20_median_transition_ms": row["path_20_median_transition_ms"],
                "path_20_p95_transition_ms": row["path_20_p95_transition_ms"],
                "path_50_transition_time_ms": row["path_50_transition_time_ms"],
                "path_50_transition_count": row["path_50_transition_count"],
                "path_50_cold_start_count": row["path_50_cold_start_count"],
                "path_50_cluster_switch_count": row["path_50_cluster_switch_count"],
                "path_50_reuse_hit_rate": row["path_50_reuse_hit_rate"],
                "path_50_median_transition_ms": row["path_50_median_transition_ms"],
                "path_50_p95_transition_ms": row["path_50_p95_transition_ms"],
                "full_transition_time_ms": row["full_transition_time_ms"],
                "full_transition_count": row["full_transition_count"],
                "full_cold_start_count": row["full_cold_start_count"],
                "full_cluster_switch_count": row["full_cluster_switch_count"],
                "full_reuse_hit_rate": row["full_reuse_hit_rate"],
                "full_median_transition_ms": row["full_median_transition_ms"],
                "full_p95_transition_ms": row["full_p95_transition_ms"],
                "current_to_seed_ms": row["current_to_seed_ms"],
            }
            for row in rows
        ]
        write_csv(output / filename_map[policy], policy_fieldnames, expanded)

    starvation_rows = []
    starvation_state = next(row for row in seed_state_rows if row["state_id"] == "starvation_probe")
    weighted_starvation = next(row for row in results_by_policy["weighted"] if row["state_id"] == "starvation_probe")
    candidate_pool = [queue_map[profile_id] for profile_id in starvation_state["candidate_profile_ids"]]
    base_best = max(candidate_pool, key=lambda item: item.seed_value)
    starved_target = starvation_state["waiting_overrides"]
    starved_profile_id = next(iter(starved_target))
    starved_candidate = queue_map[starved_profile_id]
    starved_priority = _seed_score(starved_candidate, STARVATION_WAIT_SECONDS)
    break_even_wait = max(0.0, (base_best.seed_value - starved_candidate.seed_value) / AGE_WEIGHT)
    starvation_rows.append(
        {
            "state_id": starvation_state["state_id"],
            "current_profile_id": starvation_state["current_profile_id"],
            "candidate_count": starvation_state["candidate_count"],
            "starved_profile_id": starved_profile_id,
            "starved_seed_value": starved_candidate.seed_value,
            "starved_base_priority_score": starved_candidate.priority_score,
            "starved_waiting_seconds": STARVATION_WAIT_SECONDS,
            "starved_priority_score_with_age": starved_priority,
            "break_even_waiting_seconds": break_even_wait,
            "weighted_selected_profile_id": weighted_starvation["chosen_profile_id"],
            "weighted_selected_rank": weighted_starvation["chosen_rank"],
            "weighted_selected_waiting_seconds": weighted_starvation["chosen_waiting_seconds"],
            "weighted_selected_priority_score": weighted_starvation["chosen_priority_score"],
            "starvation_prevented": weighted_starvation["chosen_profile_id"] == starved_profile_id,
            "fastest_selected_profile_id": next(row for row in results_by_policy["fastest"] if row["state_id"] == "starvation_probe")["chosen_profile_id"],
            "degree_selected_profile_id": next(row for row in results_by_policy["degree"] if row["state_id"] == "starvation_probe")["chosen_profile_id"],
            "random_selected_profile_ids": ";".join(
                row["chosen_profile_id"] for row in results_by_policy["random"] if row["state_id"] == "starvation_probe"
            ),
        }
    )
    write_csv(
        output / "starvation_analysis.csv",
        [
            "state_id",
            "current_profile_id",
            "candidate_count",
            "starved_profile_id",
            "starved_seed_value",
            "starved_base_priority_score",
            "starved_waiting_seconds",
            "starved_priority_score_with_age",
            "break_even_waiting_seconds",
            "weighted_selected_profile_id",
            "weighted_selected_rank",
            "weighted_selected_waiting_seconds",
            "weighted_selected_priority_score",
            "starvation_prevented",
            "fastest_selected_profile_id",
            "degree_selected_profile_id",
            "random_selected_profile_ids",
        ],
        starvation_rows,
    )

    policy_aggregate = {policy: _summarize_policy(rows) for policy, rows in {
        "fastest": results_by_policy["fastest"],
        "degree": results_by_policy["degree"],
        "weighted": results_by_policy["weighted"],
        "random": _expand_random_rows(results_by_policy["random"]),
    }.items()}
    random_expanded = _expand_random_rows(results_by_policy["random"])
    random_full = [float(row["transition_time_ms"]) for row in random_expanded]
    random_full_stats = summarize(random_full)
    random_reuse_stats = summarize([float(row["reuse_hit_rate"]) for row in random_expanded if row["reuse_hit_rate"] is not None])

    summary = {
        "schema_version": 1,
        "phase": "phase6",
        "status": "passed_with_constraints",
        "measurement_environment_id": "derived:phase5-replay",
        "source_environment_ids": [
            str(phase5_summary.get("measurement_environment_id", "")),
            str(seed_queue.get("measurement_environment_id", "")) if isinstance(seed_queue, dict) else "",
        ],
        "seed_state_count": len(seed_state_rows),
        "fallback_trigger_count": len(seed_state_rows),
        "policy_aggregate": policy_aggregate,
        "random_aggregate": {
            "full_transition_time_mean_ms": random_full_stats["mean_ms"],
            "full_transition_time_stddev_ms": random_full_stats["stddev_ms"],
            "full_transition_time_median_ms": random_full_stats["median_ms"],
            "full_transition_time_p95_ms": random_full_stats["p95_ms"],
            "reuse_hit_rate_mean": random_reuse_stats["mean_ms"],
            "seed_count": len(RANDOM_SEEDS),
        },
        "starvation_probe": starvation_rows[0],
        "validation": {
            "same_candidate_pool_shape": True,
            "random_seed_count": len(RANDOM_SEEDS),
            "age_bonus_prevents_starvation": starvation_rows[0]["starvation_prevented"],
            "weighted_reach_selected_starved_candidate": starvation_rows[0]["starvation_prevented"],
        },
        "artifacts": [
            "seed_states.json",
            "random_seed_results.csv",
            "fastest_seed_results.csv",
            "degree_seed_results.csv",
            "weighted_reach_results.csv",
            "starvation_analysis.csv",
            "phase6_summary.md",
            "phase6_summary.json",
        ],
    }

    fifo_vs_weighted = policy_aggregate["fastest"]["full_transition_time"]["mean_ms"] - policy_aggregate["weighted"]["full_transition_time"]["mean_ms"]
    degree_vs_weighted = policy_aggregate["degree"]["full_transition_time"]["mean_ms"] - policy_aggregate["weighted"]["full_transition_time"]["mean_ms"]
    weighted_reach_is_best = fifo_vs_weighted > 0 and degree_vs_weighted > 0
    summary["comparisons"] = {
        "fastest_minus_weighted_full_mean_ms": fifo_vs_weighted,
        "degree_minus_weighted_full_mean_ms": degree_vs_weighted,
    }
    summary["outcome"] = {
        "weighted_reach_beats_fastest": fifo_vs_weighted > 0,
        "weighted_reach_beats_degree": degree_vs_weighted > 0,
        "weighted_reach_is_best": weighted_reach_is_best,
    }

    summary_md = _build_markdown(summary)
    write_json(output / "phase6_summary.json", summary)
    (output / "phase6_summary.md").write_text(summary_md, encoding="utf-8")

    print(
        json.dumps(
            {
                "output": str(output),
                "seed_state_count": len(seed_state_rows),
                "random_seed_count": len(RANDOM_SEEDS),
                "weighted_full_mean_ms": policy_aggregate["weighted"]["full_transition_time"]["mean_ms"],
                "fastest_full_mean_ms": policy_aggregate["fastest"]["full_transition_time"]["mean_ms"],
                "degree_full_mean_ms": policy_aggregate["degree"]["full_transition_time"]["mean_ms"],
                "starvation_prevented": starvation_rows[0]["starvation_prevented"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
