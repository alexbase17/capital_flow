#!/usr/bin/env python3
"""Validate ETF taxonomy master data and print coverage diagnostics."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.capital_flow.fetcher import fund_basic_map
from src.capital_flow.taxonomy import TAXONOMY_DATA_PATH, VALID_TAXONOMY_SECTIONS, load_taxonomy_records
from src.capital_flow.taxonomy_audit import audit_fund_taxonomy
from src.tushare_client import TushareClient


VALID_ASSET_CLASSES = {"equity", "fixed_income", "commodity", "money_market", "mixed", "other"}
VALID_TAXONOMY_TYPES = {"broad", "industry", "theme", "factor", "excluded", "commodity", "fixed_income", "other"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate ETF taxonomy master data.")
    parser.add_argument("--path", default=str(TAXONOMY_DATA_PATH), help="taxonomy_data.json path")
    parser.add_argument("--audit", action="store_true", help="also run current fund taxonomy coverage audit")
    parser.add_argument("--sample-limit", type=int, default=20, help="sample size when --audit is enabled")
    args = parser.parse_args()

    path = Path(args.path)
    errors, warnings = validate_taxonomy_json(path)
    summary: dict[str, object] = {
        "path": str(path),
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
    }
    if not errors:
        records = load_taxonomy_records(path)
        summary["record_count"] = len(records)
        summary["by_section"] = dict(sorted(Counter(record.section for record in records.values()).items()))
        summary["by_taxonomy_type"] = dict(sorted(Counter(record.taxonomy_type for record in records.values()).items()))
    if args.audit and not errors:
        funds = fund_basic_map(TushareClient.from_env())
        summary["audit"] = audit_fund_taxonomy(funds, sample_limit=args.sample_limit)

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if errors else 0


def validate_taxonomy_json(path: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return [f"failed to read taxonomy json: {exc}"], warnings

    records = payload.get("records")
    if not isinstance(records, list):
        return ["taxonomy records must be a list"], warnings

    benchmarks: Counter[str] = Counter()
    labels_by_section: Counter[tuple[str, str]] = Counter()
    for index, raw in enumerate(records):
        if not isinstance(raw, dict):
            errors.append(f"record[{index}] must be an object")
            continue
        benchmark = str(raw.get("benchmark") or "").strip()
        section = str(raw.get("section") or "").strip()
        label = str(raw.get("label") or "").strip()
        market = str(raw.get("market") or "").strip()
        asset_class = str(raw.get("asset_class") or "").strip()
        taxonomy_type = str(raw.get("taxonomy_type") or "").strip()

        if not benchmark:
            errors.append(f"record[{index}] missing benchmark")
        else:
            benchmarks[benchmark] += 1
        if section not in VALID_TAXONOMY_SECTIONS:
            errors.append(f"record[{index}] invalid section: {section}")
        if section != "excluded" and not label:
            errors.append(f"record[{index}] missing label for non-excluded record")
        if not market:
            errors.append(f"record[{index}] missing market")
        if asset_class not in VALID_ASSET_CLASSES:
            errors.append(f"record[{index}] invalid asset_class: {asset_class}")
        if taxonomy_type not in VALID_TAXONOMY_TYPES:
            errors.append(f"record[{index}] invalid taxonomy_type: {taxonomy_type}")
        if label:
            labels_by_section[(section, label)] += 1

    duplicates = sorted(benchmark for benchmark, count in benchmarks.items() if count > 1)
    errors.extend(f"duplicate benchmark: {benchmark}" for benchmark in duplicates)

    sparse_labels = sorted(
        f"{section}:{label}" for (section, label), count in labels_by_section.items() if count == 1 and section != "excluded"
    )
    if sparse_labels:
        warnings.append(f"single-record labels may be expected but should be reviewed: {', '.join(sparse_labels[:20])}")
    return errors, warnings


if __name__ == "__main__":
    raise SystemExit(main())
