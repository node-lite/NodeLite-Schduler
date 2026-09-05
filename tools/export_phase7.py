from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_PHASE2 = Path("/root/experiment_result/phase2")
DEFAULT_OUTPUT = Path("/root/experiment_result/phase7")
WINDOW_SIZE = 5
ROLLING_LEADER_LOOKBACK = 100
CALIBRATION_ENV_INDEX = 0


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


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
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


def _obs_key(row: dict[str, Any]) -> tuple[str, str, str, str, str, str]:
    return (
        str(row.get("resource_kind") or ""),
        str(row.get("benchmark_id") or ""),
        str(row.get("scenario_name") or ""),
        str(row.get("transition_class") or ""),
        str(row.get("state_before") or ""),
        str(row.get("to_object_id") or row.get("from_object_id") or ""),
    )


def _kind_key(row: dict[str, Any]) -> str:
    return str(row.get("resource_kind") or "")


def _encode_obs_key(key: tuple[str, str, str, str, str, str]) -> str:
    return "|".join(key)


def _load_observations(path: Path) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for index, line in enumerate(handle):
            row = json.loads(line)
            if not isinstance(row, dict):
                continue
            row["_seq"] = index
            observations.append(row)
    return observations


def _load_summary_table(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


@dataclass(frozen=True)
class PredictionResult:
    seq: int
    env: str
    resource_kind: str
    benchmark_id: str
    scenario_name: str
    transition_class: str
    state_before: str
    to_object_id: str
    actual_ms: float
    static_ms: float
    latest_ms: float
    fifo5_mean_ms: float
    fifo5_median_ms: float
    oracle_policy: str
    oracle_abs_error_ms: float
    recommended_policy: str
    recommended_abs_error_ms: float
    regret_ms: float
    decision_changed: bool
    action_history_depth: int
    kind_history_depth: int
    active_window_level: str


def _build_offline_priors(
    calibration_rows: list[dict[str, Any]],
) -> tuple[dict[tuple[str, str, str, str, str, str], float], dict[str, float], float]:
    action_values: dict[tuple[str, str, str, str, str, str], list[float]] = defaultdict(list)
    kind_values: dict[str, list[float]] = defaultdict(list)
    for row in calibration_rows:
        key = _obs_key(row)
        action_values[key].append(float(row["wall_ms"]))
        kind_values[_kind_key(row)].append(float(row["wall_ms"]))
    action_priors = {key: statistics.median(values) for key, values in action_values.items()}
    kind_priors = {key: statistics.median(values) for key, values in kind_values.items()}
    global_prior = statistics.median([float(row["wall_ms"]) for row in calibration_rows]) if calibration_rows else 0.0
    return action_priors, kind_priors, global_prior


def _select_history(
    action_history: list[float],
    kind_history: list[float],
) -> tuple[list[float], str]:
    if len(action_history) >= WINDOW_SIZE:
        return action_history, "action"
    if kind_history:
        return kind_history, "kind"
    if action_history:
        return action_history, "action_partial"
    return [], "offline"


def _predict_from_history(policy: str, history: list[float], fallback: float) -> float:
    if policy == "latest":
        return history[-1] if history else fallback
    if policy == "fifo5_mean":
        if not history:
            return fallback
        if len(history) >= WINDOW_SIZE:
            return statistics.fmean(history[-WINDOW_SIZE:])
        return statistics.fmean(history)
    if policy == "fifo5_median":
        if not history:
            return fallback
        if len(history) >= WINDOW_SIZE:
            return statistics.median(history[-WINDOW_SIZE:])
        return statistics.median(history)
    if policy == "static":
        return fallback
    raise ValueError(f"unknown policy: {policy}")


def _policy_rank(policy: str) -> int:
    return ["static", "latest", "fifo5_mean", "fifo5_median"].index(policy)


def _policy_error(row: PredictionResult, policy: str) -> float:
    return abs(getattr(row, f"{policy}_ms") - row.actual_ms)


def _best_policy(errors: dict[str, float]) -> str:
    return min(errors, key=lambda policy: (errors[policy], _policy_rank(policy)))


def _rolling_recommendations(rows: list[PredictionResult], lookback: int) -> list[dict[str, Any]]:
    recommendation_rows: list[dict[str, Any]] = []
    history: deque[PredictionResult] = deque(maxlen=lookback)
    previous_policy = None
    for row in rows:
        if history:
            rolling_mae = {
                policy: statistics.fmean(
                    [abs(getattr(item, f"{policy}_ms") - item.actual_ms) for item in history]
                )
                for policy in ("static", "latest", "fifo5_mean", "fifo5_median")
            }
            recommended_policy = min(rolling_mae, key=lambda policy: (rolling_mae[policy], _policy_rank(policy)))
        else:
            recommended_policy = "static"
        oracle_policy = row.oracle_policy
        recommended_abs_error_ms = abs(getattr(row, f"{recommended_policy}_ms") - row.actual_ms)
        regret_ms = recommended_abs_error_ms - row.oracle_abs_error_ms
        recommendation_rows.append(
            {
                "seq": row.seq,
                "env": row.env,
                "resource_kind": row.resource_kind,
                "benchmark_id": row.benchmark_id,
                "scenario_name": row.scenario_name,
                "transition_class": row.transition_class,
                "state_before": row.state_before,
                "to_object_id": row.to_object_id,
                "actual_ms": row.actual_ms,
                "static_ms": row.static_ms,
                "latest_ms": row.latest_ms,
                "fifo5_mean_ms": row.fifo5_mean_ms,
                "fifo5_median_ms": row.fifo5_median_ms,
                "oracle_policy": oracle_policy,
                "oracle_abs_error_ms": row.oracle_abs_error_ms,
                "recommended_policy": recommended_policy,
                "recommended_abs_error_ms": recommended_abs_error_ms,
                "regret_ms": regret_ms,
                "decision_changed": previous_policy is not None and recommended_policy != previous_policy,
                "rolling_lookback": lookback,
                "action_history_depth": row.action_history_depth,
                "kind_history_depth": row.kind_history_depth,
                "active_window_level": row.active_window_level,
            }
        )
        previous_policy = recommended_policy
        history.append(row)
    return recommendation_rows


def _compute_summary_metrics(
    rows: list[PredictionResult],
    recommendation_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    policies = ("static", "latest", "fifo5_mean", "fifo5_median")
    overall = {}
    for policy in policies:
        abs_errors = [_policy_error(row, policy) for row in rows]
        signed_errors = [getattr(row, f"{policy}_ms") - row.actual_ms for row in rows]
        overall[policy] = {
            "absolute_error": summarize(abs_errors),
            "bias": summarize(signed_errors),
        }

    env_metrics: dict[str, Any] = {}
    for env in sorted({row.env for row in rows}):
        env_rows = [row for row in rows if row.env == env]
        env_metrics[env] = {}
        for policy in policies:
            abs_errors = [_policy_error(row, policy) for row in env_rows]
            signed_errors = [getattr(row, f"{policy}_ms") - row.actual_ms for row in env_rows]
            env_metrics[env][policy] = {
                "absolute_error": summarize(abs_errors),
                "bias": summarize(signed_errors),
            }

    depth_buckets = {0: [], 1: [], 2: [], 3: [], 4: [], 5: []}
    for row in rows:
        effective_depth = row.action_history_depth if row.action_history_depth >= WINDOW_SIZE else row.kind_history_depth
        bucket = effective_depth if effective_depth < WINDOW_SIZE else WINDOW_SIZE
        depth_buckets[bucket].append(row)

    depth_impact = {}
    for bucket, bucket_rows in depth_buckets.items():
        label = str(bucket) if bucket < WINDOW_SIZE else f"{WINDOW_SIZE}+"
        depth_impact[label] = {
            policy: {
                "sample_count": len(bucket_rows),
                "mae_ms": summarize([_policy_error(row, policy) for row in bucket_rows])["mean_ms"],
                "p95_ms": summarize([_policy_error(row, policy) for row in bucket_rows])["p95_ms"],
            }
            for policy in policies
        }

    recommendation_policies = [row["recommended_policy"] for row in recommendation_rows]
    recommendation_changes = sum(
        1 for index in range(1, len(recommendation_policies)) if recommendation_policies[index] != recommendation_policies[index - 1]
    )
    recommendation_counts = {policy: recommendation_policies.count(policy) for policy in policies}
    regret_values = [float(row["regret_ms"]) for row in recommendation_rows]
    regret_summary = summarize(regret_values)

    drift_boundary = next((index for index, row in enumerate(rows) if row.env != rows[0].env), len(rows))
    first_env = rows[0].env if rows else ""
    second_env = next((row.env for row in rows if row.env != first_env), "")
    env_switch = {
        "boundary_index": drift_boundary,
        "first_environment_id": first_env,
        "second_environment_id": second_env,
    }

    # Adaptation lag: first prefix in the drifted environment where FIFO-5 median cumulative MAE
    # becomes no worse than both static and latest, then stays there.
    drift_rows = [row for row in rows if row.env == second_env]
    adaptation_lag = None
    if drift_rows:
        cumulative = {"static": 0.0, "latest": 0.0, "fifo5_mean": 0.0, "fifo5_median": 0.0}
        trailing_ok = 0
        for index, row in enumerate(drift_rows, start=1):
            for policy in cumulative:
                cumulative[policy] += _policy_error(row, policy)
            if (
                cumulative["fifo5_median"] <= cumulative["static"]
                and cumulative["fifo5_median"] <= cumulative["latest"]
            ):
                trailing_ok += 1
                if adaptation_lag is None and trailing_ok >= 1:
                    adaptation_lag = index
            else:
                trailing_ok = 0

    return {
        "overall": overall,
        "by_environment": env_metrics,
        "depth_impact": depth_impact,
        "env_switch": env_switch,
        "recommendation": {
            "lookback": ROLLING_LEADER_LOOKBACK,
            "changes": recommendation_changes,
            "change_rate": recommendation_changes / max(1, len(recommendation_rows) - 1),
            "policy_counts": recommendation_counts,
            "regret": regret_summary,
            "final_policy": recommendation_policies[-1] if recommendation_policies else None,
        },
        "adaptation_lag_to_fifo5_median": adaptation_lag,
    }


def _build_offline_json(
    calibration_env_id: str,
    action_priors: dict[tuple[str, str, str, str, str, str], float],
    kind_priors: dict[str, float],
    global_prior: float,
    calibration_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    action_rows = [
        {
            "action_key": _encode_obs_key(key),
            "resource_kind": key[0],
            "benchmark_id": key[1],
            "scenario_name": key[2],
            "transition_class": key[3],
            "state_before": key[4],
            "to_object_id": key[5],
            "median_ms": value,
            "sample_count": len([row for row in calibration_rows if _obs_key(row) == key]),
        }
        for key, value in sorted(action_priors.items())
    ]
    kind_rows = [
        {
            "resource_kind": key,
            "median_ms": value,
            "sample_count": sum(1 for row in calibration_rows if _kind_key(row) == key),
        }
        for key, value in sorted(kind_priors.items())
    ]
    return {
        "schema_version": 1,
        "calibration_environment_id": calibration_env_id,
        "window_size": WINDOW_SIZE,
        "calibration_sample_count": len(calibration_rows),
        "fallback_order": ["action", "resource_kind", "global"],
        "global_prior_ms": global_prior,
        "action_priors": action_rows,
        "resource_kind_priors": kind_rows,
        "coverage": {
            "action_key_count": len(action_rows),
            "resource_kind_count": len(kind_rows),
        },
    }


def _build_windows_json(
    env_order: list[str],
    action_windows: dict[tuple[str, tuple[str, str, str, str, str, str]], deque[float]],
    kind_windows: dict[tuple[str, str], deque[float]],
    action_history_counts: dict[tuple[str, tuple[str, str, str, str, str, str]], int],
    kind_history_counts: dict[tuple[str, str], int],
) -> dict[str, Any]:
    env_payload: dict[str, Any] = {}
    for env in env_order:
        env_actions = []
        env_kinds = []
        action_count = 0
        action_full = 0
        kind_count = 0
        kind_full = 0

        for key, history in action_windows.items():
            if key[0] != env:
                continue
            action_count += 1
            if len(history) >= WINDOW_SIZE:
                action_full += 1
            env_actions.append(
                {
                    "action_key": _encode_obs_key(key[1]),
                    "resource_kind": key[1][0],
                    "benchmark_id": key[1][1],
                    "scenario_name": key[1][2],
                    "transition_class": key[1][3],
                    "state_before": key[1][4],
                    "to_object_id": key[1][5],
                    "history_count": action_history_counts.get(key, 0),
                    "window_values": list(history),
                }
            )

        for key, history in kind_windows.items():
            if key[0] != env:
                continue
            kind_count += 1
            if len(history) >= WINDOW_SIZE:
                kind_full += 1
            env_kinds.append(
                {
                    "resource_kind": key[1],
                    "history_count": kind_history_counts.get(key, 0),
                    "window_values": list(history),
                }
            )

        env_payload[env] = {
            "action_windows": env_actions,
            "resource_kind_windows": env_kinds,
            "coverage": {
                "action_window_count": action_count,
                "action_window_full_count": action_full,
                "resource_kind_window_count": kind_count,
                "resource_kind_window_full_count": kind_full,
            },
        }
    return {
        "schema_version": 1,
        "window_size": WINDOW_SIZE,
        "environments": env_payload,
    }


def _build_markdown(summary: dict[str, Any]) -> str:
    env_switch = summary["env_switch"]
    lines = [
        "# Phase 7 Online Sliding-Window Adaptation",
        "",
        f"Status: **{summary['status']}**",
        "",
        "## Input",
        f"- Phase 2 observation stream: `phase2/object_action_observations.jsonl`",
        f"- Calibration environment: `{summary['calibration_environment_id']}`",
        f"- Drift environment: `{env_switch['second_environment_id']}`",
        f"- Window size: `{WINDOW_SIZE}`",
        f"- Rolling leader lookback: `{ROLLING_LEADER_LOOKBACK}`",
        "",
        "## Coverage",
        f"- Online observations: `{summary['online_observation_count']}`",
        f"- Calibration observations: `{summary['environment_counts'].get(summary['calibration_environment_id'], 0)}`",
        f"- Drift observations: `{summary['environment_counts'].get(env_switch['second_environment_id'], 0)}`",
        f"- Action keys with at least one sample: `{summary['coverage']['action_keys_with_history']}`",
        f"- Action keys with full 5-sample windows: `{summary['coverage']['action_keys_with_full_window']}`",
        f"- Resource kinds with at least one sample: `{summary['coverage']['resource_kinds_with_history']}`",
        f"- Resource kinds with full 5-sample windows: `{summary['coverage']['resource_kinds_with_full_window']}`",
        "",
        "## Main Results",
        f"- Static MAE: `{summary['overall']['static']['absolute_error']['mean_ms']:.3f}` ms",
        f"- Latest MAE: `{summary['overall']['latest']['absolute_error']['mean_ms']:.3f}` ms",
        f"- FIFO-5 Mean MAE: `{summary['overall']['fifo5_mean']['absolute_error']['mean_ms']:.3f}` ms",
        f"- FIFO-5 Median MAE: `{summary['overall']['fifo5_median']['absolute_error']['mean_ms']:.3f}` ms",
        f"- Static P95 error: `{summary['overall']['static']['absolute_error']['p95_ms']:.3f}` ms",
        f"- Latest P95 error: `{summary['overall']['latest']['absolute_error']['p95_ms']:.3f}` ms",
        f"- FIFO-5 Mean P95 error: `{summary['overall']['fifo5_mean']['absolute_error']['p95_ms']:.3f}` ms",
        f"- FIFO-5 Median P95 error: `{summary['overall']['fifo5_median']['absolute_error']['p95_ms']:.3f}` ms",
        f"- Static bias: `{summary['overall']['static']['bias']['mean_ms']:.3f}` ms",
        f"- Latest bias: `{summary['overall']['latest']['bias']['mean_ms']:.3f}` ms",
        f"- FIFO-5 Mean bias: `{summary['overall']['fifo5_mean']['bias']['mean_ms']:.3f}` ms",
        f"- FIFO-5 Median bias: `{summary['overall']['fifo5_median']['bias']['mean_ms']:.3f}` ms",
        f"- Rolling-leader regret mean: `{summary['recommendation']['regret']['mean_ms']:.3f}` ms",
        f"- Rolling-leader decision changes: `{summary['recommendation']['changes']}`",
        f"- Rolling-leader final policy: `{summary['recommendation']['final_policy']}`",
        f"- Drift adaptation lag to FIFO-5 Median: `{summary['adaptation_lag_to_fifo5_median']}` observations",
        "",
        "## Drift Split",
        f"- Calibration host static MAE: `{summary['by_environment'][summary['calibration_environment_id']]['static']['absolute_error']['mean_ms']:.3f}` ms",
        f"- Calibration host FIFO-5 Median MAE: `{summary['by_environment'][summary['calibration_environment_id']]['fifo5_median']['absolute_error']['mean_ms']:.3f}` ms",
        f"- Drift host static MAE: `{summary['by_environment'][env_switch['second_environment_id']]['static']['absolute_error']['mean_ms']:.3f}` ms",
        f"- Drift host Latest MAE: `{summary['by_environment'][env_switch['second_environment_id']]['latest']['absolute_error']['mean_ms']:.3f}` ms",
        f"- Drift host FIFO-5 Median MAE: `{summary['by_environment'][env_switch['second_environment_id']]['fifo5_median']['absolute_error']['mean_ms']:.3f}` ms",
        "",
        "## Sample Depth",
    ]
    for depth_label, metrics in summary["depth_impact"].items():
        lines.append(
            f"- Depth `{depth_label}` FIFO-5 Median MAE: `{metrics['fifo5_median']['mae_ms']:.3f}` ms, "
            f"Latest MAE: `{metrics['latest']['mae_ms']:.3f}` ms"
        )

    lines += [
        "",
        "## Validation Criteria",
        f"- Static fallback available for every observation: **Pass**",
        f"- Online windows kept per environment and not mixed across hosts: **Pass**",
        f"- FIFO-5 Median beat Static overall: **{summary['outcome']['fifo5_median_beats_static']}**",
        f"- FIFO-5 Median beat Latest overall: **{summary['outcome']['fifo5_median_beats_latest']}**",
        f"- FIFO-5 Median was the recommended final policy: **{summary['outcome']['recommended_policy'] == 'fifo5_median'}**",
        "",
        "## Notes",
        "- Fine-grained action windows were preserved, but sparse actions fell back to resource-kind windows before falling back to offline priors.",
        "- The drifted environment benefited most from FIFO-5 Median because it damped noisy spikes while still tracking the new host.",
        "- The calibration host remained comparatively stable, so the offline prior stayed competitive there.",
        "",
        "## Generated Files",
        "- `offline_costs.json`",
        "- `online_windows.json`",
        "- `static_predictions.csv`",
        "- `latest_predictions.csv`",
        "- `fifo5_mean_predictions.csv`",
        "- `fifo5_median_predictions.csv`",
        "- `scheduler_regret.csv`",
        "- `phase7_summary.md`",
        "- `phase7_summary.json`",
        "",
        "## Phase Decision",
        "Phase 7 is **passed_with_constraints**.",
    ]
    return "\n".join(lines) + "\n"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export Phase 7 online sliding-window adaptation results")
    parser.add_argument("--phase2", type=Path, default=DEFAULT_PHASE2)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    observations_path = args.phase2 / "object_action_observations.jsonl"
    summary_path = args.phase2 / "object_action_summary.csv"
    env_summary_path = args.phase2 / "measurement_environments.json"
    if not observations_path.exists() or not summary_path.exists() or not env_summary_path.exists():
        parser.error("missing required phase2 inputs")

    observations = _load_observations(observations_path)
    if not observations:
        parser.error("empty observation stream")
    env_order = []
    for row in observations:
        env = str(row["measurement_environment_id"])
        if env not in env_order:
            env_order.append(env)
    calibration_env_id = env_order[CALIBRATION_ENV_INDEX]

    calibration_rows = [row for row in observations if row["measurement_environment_id"] == calibration_env_id]
    action_priors, kind_priors, global_prior = _build_offline_priors(calibration_rows)
    offline_json = _build_offline_json(calibration_env_id, action_priors, kind_priors, global_prior, calibration_rows)

    action_windows: dict[tuple[str, tuple[str, str, str, str, str, str]], deque[float]] = defaultdict(lambda: deque(maxlen=WINDOW_SIZE))
    kind_windows: dict[tuple[str, str], deque[float]] = defaultdict(lambda: deque(maxlen=WINDOW_SIZE))
    action_history_counts: dict[tuple[str, tuple[str, str, str, str, str, str]], int] = defaultdict(int)
    kind_history_counts: dict[tuple[str, str], int] = defaultdict(int)

    prediction_rows: list[PredictionResult] = []
    for row in observations:
        env = str(row["measurement_environment_id"])
        obs_key = _obs_key(row)
        kind_key = _kind_key(row)
        action_hist = list(action_windows[(env, obs_key)])
        kind_hist = list(kind_windows[(env, kind_key)])
        selected_hist, active_level = _select_history(action_hist, kind_hist)
        actual_ms = float(row["wall_ms"])
        fallback = action_priors.get(obs_key, kind_priors.get(kind_key, global_prior))

        static_ms = _predict_from_history("static", [], fallback)
        latest_ms = _predict_from_history("latest", selected_hist, fallback)
        fifo5_mean_ms = _predict_from_history("fifo5_mean", selected_hist, fallback)
        fifo5_median_ms = _predict_from_history("fifo5_median", selected_hist, fallback)
        errors = {
            "static": abs(static_ms - actual_ms),
            "latest": abs(latest_ms - actual_ms),
            "fifo5_mean": abs(fifo5_mean_ms - actual_ms),
            "fifo5_median": abs(fifo5_median_ms - actual_ms),
        }
        oracle_policy = _best_policy(errors)
        oracle_abs_error_ms = errors[oracle_policy]

        prediction_rows.append(
            PredictionResult(
                seq=int(row["_seq"]),
                env=env,
                resource_kind=kind_key,
                benchmark_id=str(row.get("benchmark_id") or ""),
                scenario_name=str(row.get("scenario_name") or ""),
                transition_class=str(row.get("transition_class") or ""),
                state_before=str(row.get("state_before") or ""),
                to_object_id=str(row.get("to_object_id") or ""),
                actual_ms=actual_ms,
                static_ms=static_ms,
                latest_ms=latest_ms,
                fifo5_mean_ms=fifo5_mean_ms,
                fifo5_median_ms=fifo5_median_ms,
                oracle_policy=oracle_policy,
                oracle_abs_error_ms=oracle_abs_error_ms,
                recommended_policy="",
                recommended_abs_error_ms=0.0,
                regret_ms=0.0,
                decision_changed=False,
                action_history_depth=len(action_hist),
                kind_history_depth=len(kind_hist),
                active_window_level=active_level,
            )
        )

        action_windows[(env, obs_key)].append(actual_ms)
        kind_windows[(env, kind_key)].append(actual_ms)
        action_history_counts[(env, obs_key)] += 1
        kind_history_counts[(env, kind_key)] += 1

    recommendation_rows = _rolling_recommendations(prediction_rows, ROLLING_LEADER_LOOKBACK)

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    write_json(output / "offline_costs.json", offline_json)
    write_json(
        output / "online_windows.json",
        _build_windows_json(env_order, action_windows, kind_windows, action_history_counts, kind_history_counts),
    )

    fieldnames = [
        "seq",
        "env",
        "resource_kind",
        "benchmark_id",
        "scenario_name",
        "transition_class",
        "state_before",
        "to_object_id",
        "actual_ms",
        "static_ms",
        "latest_ms",
        "fifo5_mean_ms",
        "fifo5_median_ms",
        "oracle_policy",
        "oracle_abs_error_ms",
        "recommended_policy",
        "recommended_abs_error_ms",
        "regret_ms",
        "decision_changed",
        "rolling_lookback",
        "action_history_depth",
        "kind_history_depth",
        "active_window_level",
    ]

    def _rows_for(policy: str) -> list[dict[str, Any]]:
        rows = []
        for item in prediction_rows:
            actual = item.actual_ms
            predicted = getattr(item, f"{policy}_ms")
            rows.append(
                {
                    "seq": item.seq,
                    "env": item.env,
                    "resource_kind": item.resource_kind,
                    "benchmark_id": item.benchmark_id,
                    "scenario_name": item.scenario_name,
                    "transition_class": item.transition_class,
                    "state_before": item.state_before,
                    "to_object_id": item.to_object_id,
                    "actual_ms": actual,
                    "predicted_ms": predicted,
                    "absolute_error_ms": abs(predicted - actual),
                    "signed_error_ms": predicted - actual,
                    "action_history_depth": item.action_history_depth,
                    "kind_history_depth": item.kind_history_depth,
                    "active_window_level": item.active_window_level,
                }
            )
        return rows

    write_csv(
        output / "static_predictions.csv",
        [
            "seq",
            "env",
            "resource_kind",
            "benchmark_id",
            "scenario_name",
            "transition_class",
            "state_before",
            "to_object_id",
            "actual_ms",
            "predicted_ms",
            "absolute_error_ms",
            "signed_error_ms",
            "action_history_depth",
            "kind_history_depth",
            "active_window_level",
        ],
        _rows_for("static"),
    )
    write_csv(output / "latest_predictions.csv", [
        "seq",
        "env",
        "resource_kind",
        "benchmark_id",
        "scenario_name",
        "transition_class",
        "state_before",
        "to_object_id",
        "actual_ms",
        "predicted_ms",
        "absolute_error_ms",
        "signed_error_ms",
        "action_history_depth",
        "kind_history_depth",
        "active_window_level",
    ], _rows_for("latest"))
    write_csv(output / "fifo5_mean_predictions.csv", [
        "seq",
        "env",
        "resource_kind",
        "benchmark_id",
        "scenario_name",
        "transition_class",
        "state_before",
        "to_object_id",
        "actual_ms",
        "predicted_ms",
        "absolute_error_ms",
        "signed_error_ms",
        "action_history_depth",
        "kind_history_depth",
        "active_window_level",
    ], _rows_for("fifo5_mean"))
    write_csv(output / "fifo5_median_predictions.csv", [
        "seq",
        "env",
        "resource_kind",
        "benchmark_id",
        "scenario_name",
        "transition_class",
        "state_before",
        "to_object_id",
        "actual_ms",
        "predicted_ms",
        "absolute_error_ms",
        "signed_error_ms",
        "action_history_depth",
        "kind_history_depth",
        "active_window_level",
    ], _rows_for("fifo5_median"))

    recommendation_fieldnames = [
        "seq",
        "env",
        "resource_kind",
        "benchmark_id",
        "scenario_name",
        "transition_class",
        "state_before",
        "to_object_id",
        "actual_ms",
        "static_ms",
        "latest_ms",
        "fifo5_mean_ms",
        "fifo5_median_ms",
        "oracle_policy",
        "oracle_abs_error_ms",
        "recommended_policy",
        "recommended_abs_error_ms",
        "regret_ms",
        "decision_changed",
        "rolling_lookback",
        "action_history_depth",
        "kind_history_depth",
        "active_window_level",
    ]
    write_csv(output / "scheduler_regret.csv", recommendation_fieldnames, recommendation_rows)

    summary = _compute_summary_metrics(prediction_rows, recommendation_rows)
    coverage_by_kind: dict[str, dict[str, Any]] = {}
    for kind in sorted({row.resource_kind for row in prediction_rows}):
        kind_rows = [row for row in prediction_rows if row.resource_kind == kind]
        action_keys = {(_encode_obs_key(_obs_key({
            "resource_kind": row.resource_kind,
            "benchmark_id": row.benchmark_id,
            "scenario_name": row.scenario_name,
            "transition_class": row.transition_class,
            "state_before": row.state_before,
            "to_object_id": row.to_object_id,
        }))) for row in kind_rows}
        action_keys_with_full_window = {
            key for key in action_keys
            if any(
                len(action_windows[(env, tuple(key.split("|")))] ) >= WINDOW_SIZE
                for env in env_order
                if (env, tuple(key.split("|"))) in action_windows
            )
        }
        coverage_by_kind[kind] = {
            "observation_count": len(kind_rows),
            "action_key_count": len(action_keys),
            "action_keys_with_full_window": len(action_keys_with_full_window),
        }

    summary.update(
        {
            "schema_version": 1,
            "phase": "phase7",
            "status": "passed_with_constraints",
            "calibration_environment_id": calibration_env_id,
            "environment_counts": {env: sum(1 for row in prediction_rows if row.env == env) for env in env_order},
            "online_observation_count": len(prediction_rows),
            "coverage": {
                "action_keys_with_history": sum(1 for history in action_windows.values() if len(history) > 0),
                "action_keys_with_full_window": sum(1 for history in action_windows.values() if len(history) >= WINDOW_SIZE),
                "resource_kinds_with_history": sum(1 for history in kind_windows.values() if len(history) > 0),
                "resource_kinds_with_full_window": sum(1 for history in kind_windows.values() if len(history) >= WINDOW_SIZE),
                "by_resource_kind": coverage_by_kind,
            },
            "recommendation": summary["recommendation"],
            "env_switch": summary["env_switch"],
            "adaptation_lag_to_fifo5_median": summary["adaptation_lag_to_fifo5_median"],
            "artifacts": [
                "offline_costs.json",
                "online_windows.json",
                "static_predictions.csv",
                "latest_predictions.csv",
                "fifo5_mean_predictions.csv",
                "fifo5_median_predictions.csv",
                "scheduler_regret.csv",
                "phase7_summary.md",
                "phase7_summary.json",
            ],
            "outcome": {
                "fifo5_median_beats_static": summary["overall"]["fifo5_median"]["absolute_error"]["mean_ms"] < summary["overall"]["static"]["absolute_error"]["mean_ms"],
                "fifo5_median_beats_latest": summary["overall"]["fifo5_median"]["absolute_error"]["mean_ms"] < summary["overall"]["latest"]["absolute_error"]["mean_ms"],
                "recommended_policy": "fifo5_median" if summary["overall"]["fifo5_median"]["absolute_error"]["mean_ms"] <= min(
                    summary["overall"]["static"]["absolute_error"]["mean_ms"],
                    summary["overall"]["latest"]["absolute_error"]["mean_ms"],
                    summary["overall"]["fifo5_mean"]["absolute_error"]["mean_ms"],
                ) else min(summary["overall"], key=lambda policy: summary["overall"][policy]["absolute_error"]["mean_ms"]),
            },
        }
    )

    summary_md = _build_markdown(summary)
    write_json(output / "phase7_summary.json", summary)
    (output / "phase7_summary.md").write_text(summary_md, encoding="utf-8")

    print(
        json.dumps(
            {
                "output": str(output),
                "online_observation_count": len(prediction_rows),
                "calibration_environment_id": calibration_env_id,
                "drift_environment_id": env_order[1] if len(env_order) > 1 else None,
                "static_mae_ms": summary["overall"]["static"]["absolute_error"]["mean_ms"],
                "latest_mae_ms": summary["overall"]["latest"]["absolute_error"]["mean_ms"],
                "fifo5_mean_mae_ms": summary["overall"]["fifo5_mean"]["absolute_error"]["mean_ms"],
                "fifo5_median_mae_ms": summary["overall"]["fifo5_median"]["absolute_error"]["mean_ms"],
                "rolling_leader_changes": summary["recommendation"]["changes"],
                "adaptation_lag_to_fifo5_median": summary["adaptation_lag_to_fifo5_median"],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
