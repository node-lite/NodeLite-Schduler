from __future__ import annotations

import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .catalog import BenchmarkSpec
from .util import append_jsonl, read_json, read_jsonl, write_json


@dataclass
class Scenario:
    benchmark_id: str
    resource_kind: str
    from_object_id: str | None
    to_object_id: str
    transition_class: str
    cost_class: str
    state_before: str
    workload_origin: str
    action: Any
    invalidates: list[str] = field(default_factory=list)
    reuse_safe: bool = True
    pollution_check: str = "pass"
    scenario_name: str = "default"

    def identity(self, environment_id: str) -> str:
        return "|".join(
            [
                environment_id,
                self.benchmark_id,
                self.scenario_name,
                self.from_object_id or "cold",
                self.to_object_id,
                self.transition_class,
            ]
        )

    def key(self, sample_index: int, environment_id: str) -> str:
        return f"{self.identity(environment_id)}|{sample_index}"


class RunContext:
    def __init__(
        self,
        repo: Path,
        output: Path,
        ctdp_out: Path,
        profiles: Path,
        document: Path,
        catalog: list[BenchmarkSpec],
        environment: dict[str, Any],
        samples: int,
        warmups: int,
        force: bool,
    ):
        self.repo = repo
        self.output = output
        self.ctdp_out = ctdp_out
        self.profiles = profiles
        self.document = document
        self.catalog = catalog
        self.environment = environment
        self.samples = samples
        self.warmups = warmups
        self.force = force
        self.measurement_run_id = f"run:{uuid.uuid4().hex}"
        self.inventory = read_json(output / "inventory.json", {})
        self.objects = self.inventory.get("objects", [])
        self.object_by_id = {item["object_id"]: item for item in self.objects}
        self.observations_path = output / "costdb" / "object_costs.jsonl"
        raw_observations = read_jsonl(self.observations_path)
        latest_observations = {
            str(item["observation_key"]): item
            for item in raw_observations
            if item.get("observation_key")
        }
        self.observations = list(latest_observations.values())
        self.completed_keys = {str(item.get("observation_key")) for item in self.observations if item.get("success")}
        self.status_path = output / "benchmarks" / "catalog_status.json"
        self.status = read_json(self.status_path, {}) or {}
        self.active_scenarios_path = output / "benchmarks" / "active_scenarios.json"
        self.active_scenarios = read_json(self.active_scenarios_path, {}) or {}
        self.shared: dict[str, Any] = {}

    @property
    def environment_id(self) -> str:
        return str(self.environment["measurement_environment_id"])

    def objects_of_kind(self, resource_kind: str) -> list[dict[str, Any]]:
        return [item for item in self.objects if item.get("resource_kind") == resource_kind]

    def ensure_object(
        self,
        object_id: str,
        resource_kind: str,
        name: str,
        version: str = "v1",
        workload_origin: str = "synthetic",
        dimensions: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        existing = self.object_by_id.get(object_id)
        if existing:
            return existing
        value = {
            "object_id": object_id,
            "resource_kind": resource_kind,
            "name": name,
            "version": version,
            "scope": "node",
            "compatibility_key": f"{resource_kind}|{name}|{version}|{json.dumps(dimensions or {}, sort_keys=True)}",
            "dimensions": dimensions or {},
            "workload_origin": workload_origin,
            "profile_ids": [],
            "source": {"evidence": "benchmark fixture", "available": True},
        }
        self.objects.append(value)
        self.objects.sort(key=lambda item: item["object_id"])
        self.object_by_id[object_id] = value
        self.inventory["objects"] = self.objects
        write_json(self.output / "costdb" / "objects.json", self.objects)
        write_json(self.output / "inventory.json", self.inventory)
        return value

    def update_status(self, benchmark_id: str, status: str, reason: str, **extra: Any) -> None:
        previous = self.status.get(benchmark_id)
        rank = {"measured": 6, "failed": 5, "blocked": 4, "manual_review": 3, "unsupported": 2, "not_applicable": 1}
        if previous and rank.get(previous.get("status"), 0) > rank.get(status, 0):
            return
        self.status[benchmark_id] = {"benchmark_id": benchmark_id, "status": status, "reason": reason, **extra}
        write_json(self.status_path, self.status)

    def update_active_scenarios(self, benchmark_id: str, scenarios: list[Scenario]) -> None:
        self.active_scenarios[benchmark_id] = [scenario.identity(self.environment_id) for scenario in scenarios]
        write_json(self.active_scenarios_path, self.active_scenarios)

    def record(self, scenario: Scenario, sample_index: int, metrics: dict[str, Any]) -> dict[str, Any]:
        key = scenario.key(sample_index, self.environment_id)
        observation = {
            "schema_version": 1,
            "observation_key": key,
            "benchmark_id": scenario.benchmark_id,
            "resource_kind": scenario.resource_kind,
            "from_object_id": scenario.from_object_id,
            "to_object_id": scenario.to_object_id,
            "transition_class": scenario.transition_class,
            "cost_class": scenario.cost_class,
            "state_before": scenario.state_before,
            "sample_index": sample_index,
            "measurement_run_id": self.measurement_run_id,
            "measurement_environment_id": self.environment_id,
            "wall_ms": metrics.get("wall_ms"),
            "ready_ms": metrics.get("ready_ms"),
            "switch_ms": metrics.get("switch_ms", metrics.get("wall_ms") if scenario.transition_class == "incompatible_switch" else 0),
            "reset_ms": metrics.get("reset_ms", 0),
            "cleanup_ms": metrics.get("cleanup_ms", 0),
            "invalidation_ms": metrics.get("invalidation_ms", 0),
            "user_cpu_ms": metrics.get("user_cpu_ms"),
            "system_cpu_ms": metrics.get("system_cpu_ms"),
            "rss_mb": metrics.get("rss_mb"),
            "peak_rss_mb": metrics.get("peak_rss_mb"),
            "read_bytes": metrics.get("read_bytes", 0),
            "write_bytes": metrics.get("write_bytes", 0),
            "network_bytes": metrics.get("network_bytes", 0),
            "files_created": metrics.get("files_created", 0),
            "inodes_created": metrics.get("inodes_created", 0),
            "cache_hit": metrics.get("cache_hit", scenario.transition_class in {"exact_hit", "compatible_reuse"}),
            "success": bool(metrics.get("success")),
            "timed_out": bool(metrics.get("timed_out")),
            "exit_code": metrics.get("exit_code"),
            "reuse_safe": scenario.reuse_safe and bool(metrics.get("reuse_safe", True)),
            "pollution_check": metrics.get("pollution_check", scenario.pollution_check),
            "invalidates": scenario.invalidates,
            "workload_origin": scenario.workload_origin,
            "scenario_name": scenario.scenario_name,
            "error": metrics.get("error"),
            "details": {key: value for key, value in metrics.items() if key not in {"stdout", "stderr"} and key not in {
                "wall_ms", "ready_ms", "switch_ms", "reset_ms", "cleanup_ms", "invalidation_ms", "user_cpu_ms", "system_cpu_ms", "rss_mb", "peak_rss_mb", "read_bytes", "write_bytes", "network_bytes", "files_created", "inodes_created", "cache_hit", "success", "timed_out", "exit_code", "reuse_safe", "pollution_check", "error"
            }},
        }
        append_jsonl(self.observations_path, observation)
        self.observations.append(observation)
        if observation["success"]:
            self.completed_keys.add(key)
        return observation

    def progress(self, message: str) -> None:
        print(message, file=sys.stderr, flush=True)

    def close(self) -> None:
        seen: set[int] = set()
        for key, value in reversed(list(self.shared.items())):
            if id(value) in seen:
                continue
            seen.add(id(value))
            if key == "xvfb" and isinstance(value, tuple):
                try:
                    from .measure import terminate_process

                    terminate_process(value[0])
                except Exception:
                    pass
                continue
            close = getattr(value, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
        for path in self.shared.get("persistent_views", []):
            try:
                import shutil

                shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass
