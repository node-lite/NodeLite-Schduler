from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .catalog import GROUP_BY_PREFIX, catalog_by_id, load_catalog
from .context import RunContext
from .exact_workload import run_exact_workload
from .inventory import build_inventory
from .reporting import DEFAULT_DIRECT_MS_WINDOW_SIZE, generate_reports
from .runners import run_specs
from .util import environment_record, read_json, write_json


def _defaults() -> tuple[Path, Path, Path, Path]:
    repo = Path(__file__).resolve().parents[1]
    return repo, repo / "NODELITE_COMPLETE_LATENCY_BENCHMARK.md", repo.parent / "CTDP" / "swe_smith_64_project_ids.txt", repo.parent / "CTDP" / "acceptance-out"


def build_parser() -> argparse.ArgumentParser:
    repo, document, profiles, ctdp_out = _defaults()
    parser = argparse.ArgumentParser(description="NodeLite Object Cost Database benchmark harness")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--document", type=Path, default=document)
    parser.add_argument("--profiles", type=Path, default=profiles)
    parser.add_argument("--ctdp-out", type=Path, default=ctdp_out)
    parser.add_argument("--out", type=Path, default=repo / "out")
    parser.add_argument(
        "--direct-ms-window-size",
        type=int,
        default=DEFAULT_DIRECT_MS_WINDOW_SIZE,
        help="maximum values retained per object in the direct_ms FIFO window",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("inventory")
    run = subparsers.add_parser("run")
    run.add_argument("--group", choices=sorted(set(GROUP_BY_PREFIX.values())), required=True)
    run_all = subparsers.add_parser("run-all")
    run_one = subparsers.add_parser("run-one")
    run_one.add_argument("benchmark_id")
    run_transition = subparsers.add_parser("run-transition")
    run_transition.add_argument("benchmark_id")
    run_transition.add_argument("--from", dest="from_object_id")
    run_transition.add_argument("--to", dest="to_object_id")
    exact = subparsers.add_parser("run-exact-workload")
    exact.add_argument("--inventory", type=Path, default=repo / "out" / "inventory.json")
    exact.add_argument("--gaps", type=Path, default=repo.parent / "experiment_result" / "phase2" / "unmeasured_objects.json")
    exact.add_argument("--exact-out", type=Path, default=repo / "out" / "exact-workload")
    report = subparsers.add_parser("report")
    for command_parser in (run, run_all, run_one, run_transition, exact):
        command_parser.add_argument("--samples", type=int, default=7)
        command_parser.add_argument("--warmups", type=int, default=2)
        command_parser.add_argument("--force", action="store_true")
        command_parser.add_argument("--retry-failed", action="store_true")
    return parser


def _ensure_inventory(args: argparse.Namespace) -> dict:
    inventory_path = args.out / "inventory.json"
    if args.command == "inventory" or not inventory_path.is_file():
        return build_inventory(args.profiles.resolve(), args.ctdp_out.resolve(), args.out.resolve())
    return read_json(inventory_path, {})


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.direct_ms_window_size < 1:
        parser.error("--direct-ms-window-size must be positive")
    repo = Path(__file__).resolve().parents[1]
    args.out = args.out.resolve()
    args.out.mkdir(parents=True, exist_ok=True)
    catalog = load_catalog(args.document.resolve())
    catalog_map = catalog_by_id(catalog)
    write_json(args.out / "benchmarks" / "registry.json", [item.to_dict() for item in catalog])
    inventory = _ensure_inventory(args)
    environment = environment_record(repo)
    if args.command == "run-exact-workload":
        result = run_exact_workload(
            inventory_path=args.inventory.resolve(),
            gap_path=args.gaps.resolve(),
            ctdp_out=args.ctdp_out.resolve(),
            output=args.exact_out.resolve(),
            environment=environment,
            samples=args.samples,
            warmups=args.warmups,
            force=args.force,
            retry_failed=args.retry_failed,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "inventory":
        print(json.dumps({"catalog_count": len(catalog), "profile_coverage": f"{inventory['profile_coverage_count']}/{inventory['profile_input_count']}", "object_count": len(inventory["objects"])}, indent=2))
        return 0
    if args.command == "report":
        result = generate_reports(args.out, catalog, environment, args.direct_ms_window_size)
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    if args.command == "run":
        specs = [item for item in catalog if item.group == args.group]
    elif args.command == "run-all":
        specs = catalog
    else:
        spec = catalog_map.get(args.benchmark_id)
        if not spec:
            parser.error(f"unknown benchmark ID: {args.benchmark_id}")
        specs = [spec]
    context = RunContext(repo, args.out, args.ctdp_out.resolve(), args.profiles.resolve(), args.document.resolve(), catalog, environment, args.samples, args.warmups, args.force)
    try:
        totals = run_specs(context, specs, retry_failed=args.retry_failed)
    finally:
        context.close()
    result = generate_reports(args.out, catalog, environment, args.direct_ms_window_size)
    print(json.dumps({"run": totals, "report": result}, indent=2, sort_keys=True))
    return 0 if totals["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
