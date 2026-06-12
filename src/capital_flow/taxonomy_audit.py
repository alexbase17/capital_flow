"""Audit helpers for ETF taxonomy coverage and confidence."""

from __future__ import annotations

from collections import Counter
from typing import Any

from src.capital_flow.taxonomy import (
    classify_etf_detail,
    is_target_equity_etf,
    normalize_benchmark,
)


def audit_fund_taxonomy(funds: dict[str, dict[str, Any]], *, sample_limit: int = 40) -> dict[str, Any]:
    counters: Counter[str] = Counter()
    by_section: Counter[str] = Counter()
    by_source: Counter[str] = Counter()
    by_confidence: Counter[str] = Counter()
    by_taxonomy_type: Counter[str] = Counter()
    by_parent_bucket: Counter[str] = Counter()
    unclassified: list[dict[str, str]] = []
    pattern_classified: list[dict[str, str]] = []

    for code, fund in sorted(funds.items()):
        name = str(fund.get("name") or "")
        if "ETF" not in name.upper():
            continue
        benchmark = str(fund.get("benchmark") or "")
        invest_type = str(fund.get("invest_type") or "")
        normalized_benchmark = normalize_benchmark(benchmark)
        counters["total_etf"] += 1

        if not is_target_equity_etf(name, benchmark):
            counters["excluded_non_target"] += 1
            continue

        counters["target_equity_etf"] += 1
        result = classify_etf_detail(name, benchmark=benchmark, invest_type=invest_type)
        if result is None:
            counters["unclassified_target_equity"] += 1
            append_sample(
                unclassified,
                sample_limit,
                code=code,
                name=name,
                benchmark=normalized_benchmark,
                invest_type=invest_type,
            )
            continue

        counters["classified_target_equity"] += 1
        by_section[result.section] += 1
        by_source[result.source] += 1
        by_confidence[result.confidence] += 1
        if result.taxonomy_type:
            by_taxonomy_type[result.taxonomy_type] += 1
        if result.parent_bucket:
            by_parent_bucket[result.parent_bucket] += 1
        if result.source == "benchmark_pattern":
            append_sample(
                pattern_classified,
                sample_limit,
                code=code,
                name=name,
                benchmark=result.normalized_benchmark,
                invest_type=invest_type,
                section=result.section,
                label=result.label,
            )

    coverage_pct = 0.0
    if counters["target_equity_etf"]:
        coverage_pct = round(counters["classified_target_equity"] / counters["target_equity_etf"] * 100, 2)

    return {
        "summary": {
            **dict(counters),
            "coverage_pct": coverage_pct,
        },
        "by_section": dict(sorted(by_section.items())),
        "by_source": dict(sorted(by_source.items())),
        "by_confidence": dict(sorted(by_confidence.items())),
        "by_taxonomy_type": dict(sorted(by_taxonomy_type.items())),
        "by_parent_bucket": dict(sorted(by_parent_bucket.items())),
        "unclassified_samples": unclassified,
        "pattern_classified_samples": pattern_classified,
    }


def append_sample(target: list[dict[str, str]], limit: int, **sample: str) -> None:
    if len(target) < limit:
        target.append({key: str(value or "") for key, value in sample.items()})
