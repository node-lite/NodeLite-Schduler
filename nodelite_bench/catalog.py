from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path


CATALOG_PATTERN = re.compile(r"^\| `(?P<id>[A-Z]+-\d{3})` \|(?P<body>.*)\|$")

GROUP_BY_PREFIX = {
    "CTL": "control",
    "PRE": "prep",
    "SRC": "source",
    "ART": "artifact",
    "CAS": "artifact",
    "REG": "artifact",
    "RUN": "runtime",
    "PM": "pm",
    "PMC": "pm",
    "DEP": "dependency",
    "INS": "dependency",
    "BLD": "build",
    "TST": "test",
    "BRW": "browser",
    "GUI": "browser",
    "DB": "database",
    "DBS": "database",
    "NAT": "native",
    "NTC": "native",
    "SYS": "system",
    "FS": "filesystem",
    "NET": "network",
    "SRV": "server",
    "TSK": "task",
    "FAIL": "failure",
    "CON": "contention",
}

COST_BY_PREFIX = {
    "CTL": "CONTROL",
    "PRE": "PREP",
    "SRC": "TRANSITION",
    "ART": "PREP",
    "CAS": "PREP",
    "REG": "PREP",
    "RUN": "TRANSITION",
    "PM": "TRANSITION",
    "PMC": "TRANSITION",
    "DEP": "TRANSITION",
    "INS": "TRANSITION",
    "BLD": "TRANSITION",
    "TST": "TRANSITION",
    "BRW": "TRANSITION",
    "GUI": "TRANSITION",
    "DB": "TRANSITION",
    "DBS": "TRANSITION",
    "NAT": "TRANSITION",
    "NTC": "PREP",
    "SYS": "PREP",
    "FS": "TRANSITION",
    "NET": "TRANSITION",
    "SRV": "TRANSITION",
    "TSK": "TRANSITION",
    "FAIL": "DIAGNOSTIC",
    "CON": "DIAGNOSTIC",
}


@dataclass(frozen=True)
class BenchmarkSpec:
    benchmark_id: str
    prefix: str
    group: str
    priority: str
    cost_class: str
    description: str
    document_row: list[str]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _cost_class(prefix: str, columns: list[str]) -> str:
    for column in columns:
        for cost_class in ("PREP", "TRANSITION", "EXECUTION", "CLEANUP", "CONTROL", "DIAGNOSTIC"):
            if column.strip() == cost_class:
                return cost_class
    return COST_BY_PREFIX[prefix]


def load_catalog(document: Path) -> list[BenchmarkSpec]:
    catalog: list[BenchmarkSpec] = []
    for line in document.read_text(encoding="utf-8").splitlines():
        match = CATALOG_PATTERN.match(line)
        if not match:
            continue
        benchmark_id = match.group("id")
        prefix = benchmark_id.split("-", 1)[0]
        columns = [part.strip() for part in match.group("body").split("|")]
        priority = columns[0] if columns else ""
        description = " | ".join(columns[1:])
        catalog.append(
            BenchmarkSpec(
                benchmark_id=benchmark_id,
                prefix=prefix,
                group=GROUP_BY_PREFIX[prefix],
                priority=priority,
                cost_class=_cost_class(prefix, columns),
                description=description,
                document_row=columns,
            )
        )
    ids = [item.benchmark_id for item in catalog]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise ValueError(f"duplicate benchmark IDs: {', '.join(duplicates)}")
    if not catalog:
        raise ValueError(f"no benchmark IDs found in {document}")
    return catalog


def catalog_by_id(catalog: list[BenchmarkSpec]) -> dict[str, BenchmarkSpec]:
    return {item.benchmark_id: item for item in catalog}
