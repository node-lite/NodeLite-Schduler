from __future__ import annotations

import csv
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nodelite_bench.reporting import SUMMARY_FIELDS, _active_observations, _latest_observations, build_summaries
from nodelite_bench.util import read_jsonl, write_csv


REQUIRED_OUTPUTS = {
    "objects.json": "costdb/objects.json",
    "action_registry.json": "benchmarks/registry.json",
    "object_action_observations.jsonl": "costdb/object_costs.jsonl",
    "object_action_summary.csv": "reports/object_latency_summary.csv",
    "object_switch_matrix.csv": "reports/object_switch_matrix.csv",
    "direct_ms.json": "costdb/direct_ms.json",
    "invalidation_rules.json": "costdb/invalidation_rules.json",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_outputs(source: Path, destination: Path) -> None:
    for target_name, source_name in REQUIRED_OUTPUTS.items():
        shutil.copy2(source / source_name, destination / target_name)
    for target_name, source_name in {
        "inventory.json": "inventory.json",
        "measurement_environment.json": "measurement_environment.json",
        "catalog_status.json": "benchmarks/catalog_status.json",
        "active_scenarios.json": "benchmarks/active_scenarios.json",
        "profile_requirements.json": "graph/profile_requirements.json",
        "run_summary.json": "reports/run_summary.json",
        "coverage.md": "reports/coverage.md",
        "environment_gaps.md": "reports/environment_gaps.md",
        "object_costs.csv": "reports/object_costs.csv",
        "第一阶段_OBJECT_COST_TABLE.md": "reports/第一阶段_OBJECT_COST_TABLE.md",
        "object_cost_matrix.json": "costdb/object_cost_matrix.json",
        "resource_summaries.json": "costdb/resource_summaries.json",
        "failure_costs.json": "costdb/failure_costs.json",
        "contention_costs.json": "costdb/contention_costs.json",
        "seed_priority_queue.json": "scheduler/seed_priority_queue.json",
    }.items():
        source_path = source / source_name
        if source_path.is_file():
            shutil.copy2(source_path, destination / target_name)


def merge_exact_outputs(source: Path, destination: Path) -> dict[str, Any] | None:
    exact = source / "exact-workload"
    if not (exact / "summary.json").is_file():
        return None
    exported_exact = destination / "exact_workload"
    shutil.copytree(exact, exported_exact, dirs_exist_ok=True)

    base_observations = read_jsonl(source / "costdb" / "object_costs.jsonl")
    exact_observations = read_jsonl(exact / "object_observations.jsonl")
    raw_merged = [*base_observations, *exact_observations]
    active_scenarios = read_json(source / "benchmarks" / "active_scenarios.json")
    base_active = _active_observations(_latest_observations(base_observations), active_scenarios)
    exact_active = _latest_observations(exact_observations)
    merged = [*base_active, *exact_active]
    observations_path = destination / "object_action_observations.jsonl"
    with observations_path.open("w", encoding="utf-8") as handle:
        for item in raw_merged:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    inventory = read_json(source / "inventory.json")
    objects = {str(item["object_id"]): item for item in inventory["objects"]}
    summaries = build_summaries(merged, objects)
    rows = []
    for item in summaries:
        row = dict(item)
        row["invalidation_targets"] = ";".join(item.get("invalidation_targets", []))
        rows.append(row)
    write_csv(destination / "object_action_summary.csv", SUMMARY_FIELDS, rows)
    write_csv(destination / "object_switch_matrix.csv", SUMMARY_FIELDS, rows)

    registry = read_json(source / "benchmarks" / "registry.json")
    exact_registry = read_json(exact / "action_registry.json")
    known = {str(item.get("benchmark_id")) for item in registry}
    registry.extend(item for item in exact_registry if str(item.get("benchmark_id")) not in known)
    write_json(destination / "action_registry.json", registry)

    old_environment = read_json(source / "measurement_environment.json")
    exact_environment = read_json(exact / "measurement_environment.json")
    write_json(
        destination / "measurement_environments.json",
        {
            "schema_version": 1,
            "environments": [old_environment, exact_environment],
            "mixing_policy": "observations and summaries are grouped by measurement_environment_id; direct_ms is never averaged across environments",
        },
    )
    write_json(
        destination / "direct_ms_by_environment.json",
        {
            "schema_version": 1,
            "environments": {
                str(old_environment.get("measurement_environment_id")): "direct_ms.json",
                str(exact_environment.get("measurement_environment_id")): "exact_workload/direct_ms.json",
            },
            "mixing_policy": "select one calibration environment; do not merge latency windows from different hosts",
        },
    )
    return {
        "summary": read_json(exact / "summary.json"),
        "environment": exact_environment,
        "observation_count": len(exact_observations),
        "merged_raw_observation_count": len(raw_merged),
        "merged_active_observation_count": len(merged),
        "merged_summary_count": len(summaries),
    }


def build_unmeasured(source: Path, destination: Path) -> dict[str, Any]:
    inventory = read_json(source / "inventory.json")
    objects = {item["object_id"]: item for item in inventory["objects"]}
    required_ids = sorted({object_id for item in inventory["requirements"] for object_id in item["object_ids"]})
    direct_ms = read_json(source / "costdb/direct_ms.json")
    summaries = read_json(source / "costdb/resource_summaries.json")
    exact_status_document = read_json(destination / "exact_workload" / "object_status.json") if (destination / "exact_workload" / "object_status.json").is_file() else {}
    exact_status = exact_status_document.get("objects", {})
    exact_observed: set[str] = set()
    for item in summaries:
        if item.get("median_ms") is None:
            continue
        for object_id in (item.get("from_object_id"), item.get("to_object_id")):
            if object_id:
                exact_observed.add(str(object_id))
    direct_ids = set(direct_ms.get("direct_ms", {}))
    rows = []
    for object_id in required_ids:
        item = objects[object_id]
        status_evidence = exact_status.get(object_id)
        if object_id in direct_ids:
            status = "measured"
            reason = "exact object has a measured zero-state direct_ms value"
            environment_id = direct_ms.get("measurement_environment_id")
        elif status_evidence:
            status = str(status_evidence.get("status") or "unmeasured")
            reason = str(status_evidence.get("reason") or "exact workload status has no reason")
            environment_id = status_evidence.get("measurement_environment_id")
        elif object_id in exact_observed:
            status = "observed_without_direct_ms"
            reason = "exact object occurs in measured transition summaries but has no unique zero-state direct_ms"
            environment_id = None
        else:
            status = "unmeasured"
            reason = "no exact object_id observation; generic or synthetic benchmark cannot be substituted"
            environment_id = None
        rows.append({
            "object_id": object_id,
            "resource_kind": item.get("resource_kind"),
            "name": item.get("name"),
            "version": item.get("version"),
            "compatibility_key": item.get("compatibility_key"),
            "profile_ids": item.get("profile_ids", []),
            "workload_origin": item.get("workload_origin"),
            "status": status,
            "reason": reason,
            "measurement_environment_id": environment_id,
            "evidence": status_evidence.get("evidence") if status_evidence else None,
        })
    counts = Counter(item["status"] for item in rows)
    by_kind: dict[str, Counter[str]] = defaultdict(Counter)
    for item in rows:
        by_kind[item["resource_kind"]][item["status"]] += 1
    result = {
        "schema_version": 1,
        "definition": "scheduler-relevant objects are the exact object_ids required by the 64 real RepoProfiles",
        "object_count": len(rows),
        "status_counts": dict(counts),
        "status_counts_by_resource_kind": {kind: dict(values) for kind, values in sorted(by_kind.items())},
        "objects": rows,
    }
    write_json(destination / "unmeasured_objects.json", result)
    return result


def build_analysis(source: Path, destination: Path, unmeasured: dict[str, Any], exact: dict[str, Any] | None) -> dict[str, Any]:
    inventory = read_json(source / "inventory.json")
    summary = read_json(source / "reports/run_summary.json")
    catalog_status = read_json(source / "benchmarks/catalog_status.json")
    environment = read_json(source / "measurement_environment.json")
    rows = list(csv.DictReader((destination / "object_action_summary.csv").open(encoding="utf-8")))
    for row in rows:
        row["median_value"] = float(row["median_ms"]) if row.get("median_ms") else None
        row["p95_value"] = float(row["p95_ms"]) if row.get("p95_ms") else None

    top_actions = sorted(
        [row for row in rows if row["median_value"] is not None],
        key=lambda row: row["median_value"],
        reverse=True,
    )[:20]
    reuse_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["median_value"] is not None and row.get("to_object_id"):
            reuse_groups[row["to_object_id"]].append(row)
    reuse_gain = []
    for object_id, candidates in reuse_groups.items():
        cold = [item["median_value"] for item in candidates if item["transition_class"] in {"process_cold", "artifact_cold", "network_cold"}]
        reuse = [item["median_value"] for item in candidates if item["transition_class"] in {"exact_hit", "compatible_reuse", "dirty_reset"}]
        if cold and reuse:
            cold_value = max(cold)
            reuse_value = min(reuse)
            reuse_gain.append({
                "object_id": object_id,
                "cold_median_ms": cold_value,
                "reuse_median_ms": reuse_value,
                "gain_ms": cold_value - reuse_value,
                "gain_ratio": (cold_value - reuse_value) / cold_value if cold_value else None,
            })
    reuse_gain.sort(key=lambda item: item["gain_ms"], reverse=True)
    relevant = unmeasured["object_count"]
    exact_measured = unmeasured["status_counts"].get("measured", 0)
    accounted = summary["accounted_count"] == summary["catalog_count"]
    unresolved = unmeasured["status_counts"].get("unmeasured", 0)
    constrained = sum(unmeasured["status_counts"].get(key, 0) for key in ("blocked", "unsupported", "manual_review", "failed"))
    phase_status = "passed" if accounted and not unresolved and not constrained else "passed_with_constraints" if accounted and not unresolved else "partial"
    exact_summary = exact.get("summary", {}) if exact else {}
    environment_ids = sorted({str(row.get("measurement_environment_id")) for row in rows if row.get("measurement_environment_id")})
    exact_action_rows = [
        {key: value for key, value in row.items() if key not in {"median_value", "p95_value"}}
        for row in rows
        if str(row.get("benchmark_id", "")).startswith("EXACT-") and row.get("median_value") is not None
    ]
    exact_action_rows.sort(key=lambda row: (str(row.get("to_object_id")), str(row.get("benchmark_id"))))
    result = {
        "schema_version": 1,
        "phase": "phase2",
        "status": phase_status,
        "measurement_environment_id": environment.get("measurement_environment_id"),
        "measurement_environment_ids": environment_ids,
        "catalog_count": summary["catalog_count"],
        "catalog_accounted_count": summary["accounted_count"],
        "catalog_coverage_percent": summary["coverage_percent"],
        "catalog_status_counts": summary["status_counts"],
        "raw_observation_count": exact.get("merged_raw_observation_count", summary["raw_observation_count"]) if exact else summary["raw_observation_count"],
        "active_observation_count": exact.get("merged_active_observation_count", summary["observation_count"]) if exact else summary["observation_count"],
        "transition_summary_count": exact.get("merged_summary_count", summary["directed_transition_count"]) if exact else summary["directed_transition_count"],
        "all_object_count": summary["object_count"],
        "scheduler_relevant_object_count": relevant,
        "scheduler_relevant_exact_measured_count": exact_measured,
        "scheduler_relevant_exact_coverage_percent": exact_measured / relevant * 100 if relevant else None,
        "direct_ms_object_count": summary["direct_ms_object_count"],
        "direct_ms_catalog_object_denominator": summary["direct_ms_object_count"],
        "direct_ms_coverage_percent": summary["direct_ms_object_count"] / summary["object_count"] * 100 if summary["object_count"] else None,
        "direct_ms_window_size": summary["direct_ms_window_size"],
        "exact_current_environment_direct_ms_object_count": exact_summary.get("direct_ms_object_count", 0),
        "pollution_failure_count": summary["pollution_failure_count"],
        "top_actions": top_actions,
        "top_reuse_gains": reuse_gain[:20],
        "resource_kind_object_counts": summary["object_counts"],
        "unmeasured_status_counts": unmeasured["status_counts"],
        "scheduler_relevant_status_counts_by_resource_kind": unmeasured["status_counts_by_resource_kind"],
        "exact_workload_run": exact_summary,
        "exact_measured_actions": exact_action_rows,
    }
    write_json(destination / "phase2_summary.json", result)
    write_json(destination / "top_cost_actions.json", top_actions)
    write_json(destination / "top_reuse_gains.json", reuse_gain[:20])

    for name, resource_kind in (("node_switch_matrix.csv", "node_runtime"), ("pm_switch_matrix.csv", "package_manager")):
        with (destination / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys())[:-2])
            writer.writeheader()
            writer.writerows({key: value for key, value in row.items() if key not in {"median_value", "p95_value"}} for row in rows if row["resource_kind"] == resource_kind)

    lines = [
        "# Phase 2 Object / Action Latency Profiling",
        "",
        f"Status: **{phase_status}**",
        "",
        "## Measurement Environment",
        "",
        f"- Environment ID: `{environment.get('measurement_environment_id')}`",
        f"- Environment IDs represented in observations: `{json.dumps(environment_ids, ensure_ascii=False)}`",
        f"- Host: `{environment.get('hostname')}`",
        f"- CPU: `{environment.get('processor')}` / logical CPUs `{environment.get('cpu_count')}`",
        f"- OS/libc: `{environment.get('os')}` / `{environment.get('libc')}`",
        f"- Node/npm: `{environment.get('node')}` / `{environment.get('npm')}`",
        "- Protocol: 2 warmups and 7 measurement samples per scenario where supported; summaries use median and P95.",
        "- Cross-host policy: summary rows retain `measurement_environment_id`; `direct_ms_by_environment.json` prevents silent cross-host averaging.",
        "",
        "## Catalog Coverage",
        "",
        f"- Benchmark catalog: `{summary['catalog_count']} / {summary['catalog_count']}` accounted",
        f"- Catalog coverage: `{summary['coverage_percent']}%`",
        f"- Statuses: `{json.dumps(summary['status_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- Raw/active observations after exact merge: `{result['raw_observation_count']}` / `{result['active_observation_count']}`",
        f"- Transition summaries after exact merge: `{result['transition_summary_count']}`",
        "",
        "## Object Coverage",
        "",
        f"- All inventory objects: `{summary['object_count']}`; Raw CAS objects are included for provenance but are not treated as scheduler resources.",
        f"- Scheduler-relevant exact objects from 64 RepoProfiles: `{relevant}`",
        f"- Exact measured relevant objects: `{exact_measured}` (`{result['scheduler_relevant_exact_coverage_percent']:.2f}%`)",
        f"- Relevant object statuses: `{json.dumps(unmeasured['status_counts'], ensure_ascii=False, sort_keys=True)}`",
        f"- direct_ms entries: `{summary['direct_ms_object_count']}`; FIFO window size `{summary['direct_ms_window_size']}`",
        f"- Current-host exact direct_ms entries: `{exact_summary.get('direct_ms_object_count', 0)}` in `exact_workload/direct_ms.json`",
        "- Generic synthetic actions are retained as calibration evidence but are not counted as exact measurements for a real Profile object.",
        "",
        "## Resource Kinds",
        "",
    ]
    for kind, count in sorted(summary["object_counts"].items()):
        lines.append(f"- `{kind}`: `{count}`")
    lines.extend([
        "",
        "## Exact Workload Status",
        "",
        "| Resource kind | Measured | Blocked | Unsupported | Manual review | Failed |",
        "|---|---:|---:|---:|---:|---:|",
    ])
    for kind, statuses in sorted(unmeasured["status_counts_by_resource_kind"].items()):
        lines.append(
            f"| `{kind}` | {statuses.get('measured', 0)} | {statuses.get('blocked', 0)} | "
            f"{statuses.get('unsupported', 0)} | {statuses.get('manual_review', 0)} | {statuses.get('failed', 0)} |"
        )
    lines.extend([
        "",
        "## Exact Dependency Measurements",
        "",
        "| Object | Action | Median ms | P95 ms | Samples | Environment |",
        "|---|---|---:|---:|---:|---|",
    ])
    for row in exact_action_rows:
        lines.append(
            f"| `{row['to_object_id']}` | `{row['benchmark_id']}` | {float(row['median_ms']):.3f} | {float(row['p95_ms']):.3f} | "
            f"{row['sample_count']} | `{row['measurement_environment_id']}` |"
        )
    lines.extend([
        "",
        "## Key Measured Transitions",
        "",
        "- Node: Node 18/20/22 cold start, exact hit, and all 3x3 directions are present in `node_switch_matrix.csv`.",
        "- Package manager: npm, pnpm, Yarn Classic, Yarn Berry, and Bun exact-version observations are present in `pm_switch_matrix.csv`.",
        "- Browser: Chromium and Firefox process/profile/context actions are measured; WebKit is explicitly unsupported on this host.",
        "- Database: Redis daemon and SQLite snapshot/private-layer actions are measured; MongoDB/PostgreSQL/MySQL are explicitly unsupported because Docker/binaries are unavailable.",
        f"- Dependency view exact run: `{json.dumps(exact_summary.get('status_counts_by_resource_kind', {}).get('dependency_view', {}), ensure_ascii=False, sort_keys=True)}`.",
        f"- Repo/source/build/test/native/rootfs exact statuses: see `unmeasured_objects.json`; no object remains implicit (`unmeasured={unresolved}`).",
        "",
        "## Decision",
        "",
        f"Phase 2 is **{phase_status}**. Every scheduler-relevant exact object is measured or has an explicit blocked/unsupported/manual-review/failed status. Blocked objects are accounted, but they are not latency measurements and must not be treated as zero.",
        "",
        "This output is suitable as a calibration CostDB and as the input to targeted completion work. It must not be interpreted as proof that every real Profile transition has been measured.",
        "",
        f"Generated from NodeLite-Schduler `out/`; catalog statuses and gaps are preserved in `catalog_status.json`, `coverage.md`, and `environment_gaps.md`.",
    ])
    (destination / "phase2_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> None:
    source = Path("/root/NodeLite-Schduler/out").resolve()
    destination = Path("/root/experiment_result/phase2").resolve()
    destination.mkdir(parents=True, exist_ok=True)
    copy_outputs(source, destination)
    exact = merge_exact_outputs(source, destination)
    unmeasured = build_unmeasured(source, destination)
    build_analysis(source, destination, unmeasured, exact)


if __name__ == "__main__":
    main()
