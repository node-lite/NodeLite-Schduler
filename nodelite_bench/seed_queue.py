from __future__ import annotations

import argparse
import json
import math
import statistics
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .util import read_json, write_json


REUSE_TRANSITION_CLASSES = {"exact_hit", "compatible_reuse", "dirty_reset"}


@dataclass
class PendingProfile:
    profile_id: str
    pending_tasks: int = 1
    waiting_seconds: float = 0.0
    seed_task_id: str | None = None


def _positive_int(value: Any, field: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if number < 0:
        raise ValueError(f"{field} must not be negative")
    return number


def _non_negative_float(value: Any, field: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a number") from exc
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be a finite non-negative number")
    return number


def _pending_entry(value: Any, profile_id: str | None = None) -> PendingProfile:
    if isinstance(value, str):
        return PendingProfile(value)
    if isinstance(value, (int, float)) and profile_id:
        return PendingProfile(profile_id, _positive_int(value, "pending_tasks"))
    if not isinstance(value, dict):
        raise ValueError("pending profile entries must be strings, numbers, or objects")
    resolved_profile_id = str(value.get("profile_id") or profile_id or "").strip()
    if not resolved_profile_id:
        raise ValueError("pending profile entry is missing profile_id")
    pending_tasks = _positive_int(value.get("pending_tasks", value.get("pending_count", 1)), "pending_tasks")
    waiting_seconds = _non_negative_float(value.get("waiting_seconds", 0), "waiting_seconds")
    seed_task_id = value.get("seed_task_id") or value.get("task_id")
    return PendingProfile(
        profile_id=resolved_profile_id,
        pending_tasks=pending_tasks,
        waiting_seconds=waiting_seconds,
        seed_task_id=str(seed_task_id) if seed_task_id is not None else None,
    )


def _merge_pending(entries: list[PendingProfile]) -> dict[str, PendingProfile]:
    merged: dict[str, PendingProfile] = {}
    for entry in entries:
        if entry.pending_tasks == 0:
            continue
        existing = merged.get(entry.profile_id)
        if existing is None:
            merged[entry.profile_id] = entry
            continue
        existing.pending_tasks += entry.pending_tasks
        existing.waiting_seconds = max(existing.waiting_seconds, entry.waiting_seconds)
        existing.seed_task_id = existing.seed_task_id or entry.seed_task_id
    return merged


def load_pending(path: Path) -> dict[str, PendingProfile]:
    if path.suffix.lower() != ".json":
        entries = [PendingProfile(line.strip()) for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.lstrip().startswith("#")]
        return _merge_pending(entries)

    value = read_json(path)
    if value is None:
        raise ValueError(f"cannot read pending state: {path}")
    if isinstance(value, dict) and ("profiles" in value or "pending" in value):
        value = value.get("profiles", value.get("pending"))
    entries: list[PendingProfile] = []
    if isinstance(value, list):
        entries = [_pending_entry(item) for item in value]
    elif isinstance(value, dict):
        entries = [_pending_entry(item, str(profile_id)) for profile_id, item in value.items()]
    else:
        raise ValueError("pending JSON must contain a list or profile-id mapping")
    return _merge_pending(entries)


def _median_window(value: Any) -> float | None:
    if not isinstance(value, list):
        value = [value]
    values = [float(item) for item in value if isinstance(item, (int, float)) and not isinstance(item, bool) and math.isfinite(float(item))]
    return float(statistics.median(values)) if values else None


def _warm_cost(matrix: dict[str, Any], resource_kind: str, object_id: str) -> tuple[float | None, dict[str, Any] | None]:
    entry = matrix.get(resource_kind, {}).get(object_id, {}).get(object_id)
    if not isinstance(entry, dict) or entry.get("transition_class") not in REUSE_TRANSITION_CLASSES:
        return None, None
    value = entry.get("median_ms", entry.get("direct_ms"))
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
        return None, None
    return float(value), entry


def _rounded(value: float) -> float:
    return round(value, 6)


def build_seed_queue(
    objects: list[dict[str, Any]],
    direct_ms_data: dict[str, Any],
    matrix: dict[str, Any],
    pending: dict[str, PendingProfile],
    age_weight: float,
) -> dict[str, Any]:
    if age_weight < 0 or not math.isfinite(age_weight):
        raise ValueError("age_weight must be a finite non-negative number")

    profile_objects: dict[str, set[str]] = defaultdict(set)
    objects_by_id: dict[str, dict[str, Any]] = {}
    for item in objects:
        object_id = str(item.get("object_id") or "")
        if not object_id:
            continue
        objects_by_id[object_id] = item
        for profile_id in item.get("profile_ids") or []:
            profile_objects[str(profile_id)].add(object_id)

    direct_windows = direct_ms_data.get("direct_ms") if isinstance(direct_ms_data.get("direct_ms"), dict) else {}
    pending_demand_by_object: dict[str, int] = defaultdict(int)
    for profile_id, state in pending.items():
        for object_id in profile_objects.get(profile_id, set()):
            pending_demand_by_object[object_id] += state.pending_tasks

    resources: dict[str, dict[str, Any]] = {}
    for object_id, demand in pending_demand_by_object.items():
        item = objects_by_id.get(object_id, {})
        cold_ms = _median_window(direct_windows.get(object_id))
        if cold_ms is None:
            continue
        resource_kind = str(item.get("resource_kind") or "unknown")
        warm_ms, warm_entry = _warm_cost(matrix, resource_kind, object_id)
        reuse_gain_ms = max(cold_ms - warm_ms, 0.0) if warm_ms is not None else None
        resources[object_id] = {
            "object_id": object_id,
            "resource_kind": resource_kind,
            "scope": item.get("scope"),
            "cold_ms": _rounded(cold_ms),
            "warm_ms": _rounded(warm_ms) if warm_ms is not None else None,
            "reuse_gain_ms": _rounded(reuse_gain_ms) if reuse_gain_ms is not None else None,
            "pending_demand": demand,
            "warm_benchmark_id": warm_entry.get("benchmark_id") if warm_entry else None,
            "warm_transition_class": warm_entry.get("transition_class") if warm_entry else None,
        }

    queue: list[dict[str, Any]] = []
    for profile_id, state in pending.items():
        required_object_ids = profile_objects.get(profile_id, set())
        measured = [resources[object_id] for object_id in required_object_ids if object_id in resources]
        valuable_resources = []
        reachable_profiles: set[str] = set()
        seed_value = 0.0
        for resource in measured:
            reuse_gain_ms = resource["reuse_gain_ms"]
            remaining_demand = max(int(resource["pending_demand"]) - 1, 0)
            if reuse_gain_ms is None or reuse_gain_ms <= 0 or remaining_demand == 0:
                continue
            contribution = reuse_gain_ms * remaining_demand
            seed_value += contribution
            valuable_resources.append(
                {
                    **resource,
                    "remaining_demand": remaining_demand,
                    "contribution": _rounded(contribution),
                }
            )
            for candidate_profile_id, candidate_state in pending.items():
                if resource["object_id"] in profile_objects.get(candidate_profile_id, set()) and candidate_state.pending_tasks > 0:
                    reachable_profiles.add(candidate_profile_id)

        reachable_pending_tasks = sum(pending[candidate].pending_tasks for candidate in reachable_profiles)
        if profile_id in reachable_profiles:
            reachable_pending_tasks -= 1
            if state.pending_tasks == 1:
                reachable_profiles.remove(profile_id)
        known_cold_start_ms = sum(float(resource["cold_ms"]) for resource in measured)
        age_bonus = age_weight * state.waiting_seconds
        priority_score = seed_value + age_bonus
        valuable_resources.sort(key=lambda item: (-float(item["contribution"]), item["object_id"]))
        queue.append(
            {
                "profile_id": profile_id,
                "seed_task_id": state.seed_task_id,
                "pending_tasks": state.pending_tasks,
                "waiting_seconds": _rounded(state.waiting_seconds),
                "priority_score": _rounded(priority_score),
                "seed_value": _rounded(seed_value),
                "age_bonus": _rounded(age_bonus),
                "reachable_profile_count": len(reachable_profiles),
                "reachable_pending_tasks": reachable_pending_tasks,
                "known_cold_start_ms": _rounded(known_cold_start_ms),
                "known_cold_object_count": len(measured),
                "required_object_count": len(required_object_ids),
                "valuable_resources": valuable_resources,
            }
        )

    queue.sort(
        key=lambda item: (
            -float(item["priority_score"]),
            -int(item["reachable_pending_tasks"]),
            float(item["known_cold_start_ms"]),
            -float(item["waiting_seconds"]),
            item["profile_id"],
        )
    )
    for rank, item in enumerate(queue, start=1):
        item["rank"] = rank

    unknown_profiles = sorted(set(pending) - set(profile_objects))
    scoreable_resources = [resource for resource in resources.values() if resource["reuse_gain_ms"] is not None]
    return {
        "schema_version": 1,
        "queue_kind": "seed_priority_queue",
        "definition": "fallback queue used when the warm candidate index cannot produce a useful next task",
        "formula": "priority_score = sum(max(cold_ms - warm_ms, 0) * remaining_demand) + age_weight * waiting_seconds",
        "tie_breakers": ["reachable_pending_tasks_desc", "known_cold_start_ms_asc", "waiting_seconds_desc", "profile_id_asc"],
        "parameters": {"age_weight": age_weight},
        "summary": {
            "queue_length": len(queue),
            "pending_task_count": sum(item.pending_tasks for item in pending.values()),
            "measured_resource_count": len(resources),
            "scoreable_resource_count": len(scoreable_resources),
            "unknown_profile_count": len(unknown_profiles),
        },
        "unknown_profiles": unknown_profiles,
        "queue": queue,
    }


def build_parser() -> argparse.ArgumentParser:
    repo = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="生成 NodeLite Seed Priority Queue")
    parser.add_argument("--objects", type=Path, default=repo / "out" / "costdb" / "objects.json")
    parser.add_argument("--direct-ms", type=Path, default=repo / "out" / "costdb" / "direct_ms.json")
    parser.add_argument("--matrix", type=Path, default=repo / "out" / "costdb" / "object_cost_matrix.json")
    parser.add_argument("--pending", type=Path, default=repo.parent / "CTDP" / "swe_smith_64_project_ids.txt")
    parser.add_argument("--output", type=Path, default=repo / "out" / "scheduler" / "seed_priority_queue.json")
    parser.add_argument("--age-weight", type=float, default=0.01, help="每等待一秒增加的 priority 分数")
    parser.add_argument("--top", type=int, default=0, help="仅保留前 N 项；0 表示全部保留")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.top < 0:
        parser.error("--top must not be negative")
    objects = read_json(args.objects)
    direct_ms_data = read_json(args.direct_ms)
    matrix = read_json(args.matrix)
    if not isinstance(objects, list):
        parser.error(f"invalid objects file: {args.objects}")
    if not isinstance(direct_ms_data, dict):
        parser.error(f"invalid direct_ms file: {args.direct_ms}")
    if not isinstance(matrix, dict):
        parser.error(f"invalid matrix file: {args.matrix}")
    try:
        pending = load_pending(args.pending)
        result = build_seed_queue(objects, direct_ms_data, matrix, pending, args.age_weight)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.top:
        result["queue"] = result["queue"][: args.top]
        result["summary"]["output_queue_length"] = len(result["queue"])
    write_json(args.output, result)
    top = [
        {
            key: item[key]
            for key in ("rank", "profile_id", "seed_task_id", "priority_score", "reachable_pending_tasks", "known_cold_start_ms")
        }
        for item in result["queue"][:3]
    ]
    print(json.dumps({"output": str(args.output), **result["summary"], "top": top}, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
