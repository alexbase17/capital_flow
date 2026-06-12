"""Constituent exposure checks for ETF taxonomy audit."""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, timedelta
from typing import Any

from src.capital_flow.fetcher import (
    index_basic_rows,
    index_classify_rows,
    index_member_rows,
    index_weight_rows,
    yyyymmdd,
)
from src.capital_flow.taxonomy import TaxonomyRecord, classify_etf_detail, is_target_equity_etf, normalize_benchmark
from src.tushare_client import TushareClient


SW2021_SRC = "SW2021"
IndexCandidate = dict[str, str]
IndexLookup = dict[str, list[IndexCandidate]]
BenchmarkImpact = dict[str, Any]


def a_share_sw_exposure_audit(
    client: TushareClient,
    records: dict[str, TaxonomyRecord],
    *,
    end_date: str | None = None,
    lookback_days: int = 45,
    max_indexes: int = 30,
    sample_limit: int = 20,
    benchmark_impacts: dict[str, BenchmarkImpact] | None = None,
) -> dict[str, Any]:
    end_date = end_date or yyyymmdd(date.today())
    start_date = yyyymmdd(parse_date(end_date) - timedelta(days=lookback_days))
    stock_industry = sw2021_l1_stock_industry_map(client)
    index_lookup = a_share_index_code_lookup(client)

    candidates = [
        record
        for record in records.values()
        if record.market == "A股" and record.section == "a_industry" and record.asset_class == "equity"
    ]
    benchmark_impacts = benchmark_impacts or {}
    candidates.sort(key=lambda record: candidate_sort_key(record, benchmark_impacts))
    exposures: list[dict[str, Any]] = []
    resolved: list[tuple[TaxonomyRecord, str]] = []
    missing_index_code: list[dict[str, str]] = []
    no_weight: list[dict[str, str]] = []

    for record in candidates:
        index_code = resolve_index_code(record, index_lookup)
        impact = benchmark_impacts.get(record.benchmark, {})
        if not index_code:
            append_limited(
                missing_index_code,
                sample_limit,
                benchmark=record.benchmark,
                label=record.label,
                scale_yi=round(to_float(impact.get("scale_yi")), 2),
                etf_count=int(to_float(impact.get("etf_count"))),
            )
            continue
        resolved.append((record, index_code))

    query_limit = max(0, max_indexes)
    for record, index_code in resolved[:query_limit]:
        weight_rows = index_weight_rows(client, index_code, start_date=start_date, end_date=end_date)
        exposure = sw2021_exposure_from_weight_rows(weight_rows, stock_industry)
        impact = benchmark_impacts.get(record.benchmark, {})
        if exposure is None:
            append_limited(
                no_weight,
                sample_limit,
                benchmark=record.benchmark,
                label=record.label,
                index_code=index_code,
                scale_yi=round(to_float(impact.get("scale_yi")), 2),
                etf_count=int(to_float(impact.get("etf_count"))),
            )
            continue
        exposures.append(
            {
                "benchmark": record.benchmark,
                "label": record.label,
                "taxonomy_type": record.taxonomy_type,
                "parent_bucket": record.parent_bucket,
                "index_code": index_code,
                "scale_yi": round(to_float(impact.get("scale_yi")), 2),
                "etf_count": int(to_float(impact.get("etf_count"))),
                **exposure,
            }
        )

    return {
        "system": SW2021_SRC,
        "start_date": start_date,
        "end_date": end_date,
        "candidate_count": len(candidates),
        "resolved_index_code_count": len(resolved),
        "queried_index_count": min(len(resolved), query_limit),
        "checked_count": len(exposures),
        "missing_index_code_count": len(candidates) - len(resolved),
        "no_weight_count": len(no_weight),
        "not_checked_due_limit_count": max(0, len(resolved) - query_limit),
        "sw2021_stock_map_count": len(stock_industry),
        "summary": exposure_summary(exposures),
        "exposures": exposures[:sample_limit],
        "missing_index_code_samples": missing_index_code,
        "no_weight_samples": no_weight,
        "label_consistency": label_consistency_audit(exposures, sample_limit=sample_limit),
    }


def a_share_benchmark_impacts(
    funds: dict[str, dict[str, Any]],
    latest_prices: dict[str, float],
    latest_shares: dict[str, float],
    *,
    sample_limit: int = 5,
) -> dict[str, BenchmarkImpact]:
    impacts: dict[str, BenchmarkImpact] = {}
    for code, fund in sorted(funds.items()):
        name = str(fund.get("name") or "")
        benchmark = str(fund.get("benchmark") or "")
        if "ETF" not in name.upper() or not is_target_equity_etf(name, benchmark):
            continue
        result = classify_etf_detail(name, benchmark=benchmark, invest_type=str(fund.get("invest_type") or ""))
        if result is None or result.section != "a_industry":
            continue
        price = to_float(latest_prices.get(code))
        share = to_float(latest_shares.get(code))
        if price <= 0 or share <= 0:
            continue
        scale_yi = share * price / 10000
        impact = impacts.setdefault(
            result.normalized_benchmark,
            {
                "benchmark": result.normalized_benchmark,
                "label": result.label,
                "source": result.source,
                "taxonomy_type": result.taxonomy_type,
                "parent_bucket": result.parent_bucket,
                "scale_yi": 0.0,
                "etf_count": 0,
                "top_etfs": [],
            },
        )
        impact["scale_yi"] = to_float(impact.get("scale_yi")) + scale_yi
        impact["etf_count"] = int(to_float(impact.get("etf_count"))) + 1
        top_etfs = list(impact.get("top_etfs") or [])
        top_etfs.append({"code": code, "name": name, "scale_yi": round(scale_yi, 2)})
        impact["top_etfs"] = sorted(top_etfs, key=lambda item: to_float(item.get("scale_yi")), reverse=True)[
            :sample_limit
        ]
    for impact in impacts.values():
        impact["scale_yi"] = round(to_float(impact.get("scale_yi")), 2)
    return impacts


def candidate_sort_key(record: TaxonomyRecord, benchmark_impacts: dict[str, BenchmarkImpact]) -> tuple[float, str, str]:
    impact = benchmark_impacts.get(record.benchmark, {})
    return (-to_float(impact.get("scale_yi")), record.label, record.benchmark)


def label_consistency_audit(exposures: list[dict[str, Any]], *, sample_limit: int = 20) -> dict[str, Any]:
    by_label: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for exposure in exposures:
        label = str(exposure.get("label") or "")
        if label:
            by_label[label].append(exposure)

    flagged: list[dict[str, Any]] = []
    consistent_count = 0
    single_index_count = 0
    for label, label_exposures in sorted(by_label.items()):
        if len(label_exposures) < 2:
            single_index_count += 1
            continue
        top_industries = {
            str(exposure.get("top_industry") or "")
            for exposure in label_exposures
            if exposure.get("top_industry")
        }
        unknown_weight = max((to_float(exposure.get("unknown_weight")) for exposure in label_exposures), default=0.0)
        min_top_weight = min((to_float(exposure.get("top_industry_weight")) for exposure in label_exposures), default=0.0)
        if len(top_industries) == 1 and unknown_weight <= 20:
            consistent_count += 1
            continue
        append_limited(
            flagged,
            sample_limit,
            label=label,
            index_count=len(label_exposures),
            scale_yi=round(sum(to_float(exposure.get("scale_yi")) for exposure in label_exposures), 2),
            top_industries=",".join(sorted(top_industries)),
            min_top_industry_weight=round(min_top_weight, 2),
            max_unknown_weight=round(unknown_weight, 2),
            benchmarks=";".join(str(exposure.get("benchmark") or "") for exposure in label_exposures[:5]),
        )
    return {
        "label_count": len(by_label),
        "single_index_label_count": single_index_count,
        "consistent_multi_index_label_count": consistent_count,
        "flagged_label_count": len(flagged),
        "flagged_samples": flagged,
    }


def sw2021_l1_stock_industry_map(client: TushareClient) -> dict[str, str]:
    classify_rows = index_classify_rows(client, SW2021_SRC)
    l1_rows = [row for row in classify_rows if row.get("level") == "L1"]
    stock_industry: dict[str, str] = {}
    for row in l1_rows:
        industry_name = str(row.get("industry_name") or "")
        index_code = str(row.get("index_code") or "")
        if not industry_name or not index_code:
            continue
        for member in index_member_rows(client, index_code):
            con_code = str(member.get("con_code") or "")
            if con_code and is_current_member(member):
                stock_industry[con_code] = industry_name
    return stock_industry


def is_current_member(member: dict[str, Any]) -> bool:
    return str(member.get("is_new") or "").upper() == "Y" or not member.get("out_date")


def a_share_index_code_lookup(client: TushareClient) -> IndexLookup:
    rows: list[dict[str, Any]] = []
    for market in ("CSI", "SSE", "SZSE"):
        rows.extend(index_basic_rows(client, market))
    lookup: IndexLookup = defaultdict(list)
    canonical_candidates: defaultdict[str, list[IndexCandidate]] = defaultdict(list)
    for row in rows:
        name = str(row.get("name") or "").strip()
        code = str(row.get("ts_code") or "").strip()
        if not name or not code:
            continue
        candidate = {
            "code": code,
            "name": name,
            "market": str(row.get("market") or "").strip(),
            "publisher": str(row.get("publisher") or "").strip(),
            "category": str(row.get("category") or "").strip(),
        }
        for alias in index_name_aliases(name, include_canonical=False):
            append_unique_candidate(lookup[alias], candidate)
        if is_plain_index_basic_name(name):
            canonical = canonical_index_name(name)
            if canonical:
                append_unique_candidate(canonical_candidates[f"canonical:{canonical}"], candidate)
    for canonical_key, candidates in canonical_candidates.items():
        lookup[canonical_key].extend(candidates)
    return lookup


def index_name_aliases(name: str, *, include_canonical: bool = True) -> set[str]:
    text = normalize_benchmark(name)
    aliases = {text}
    if not text.endswith("指数"):
        aliases.add(f"{text}指数")
    if text.endswith("指数"):
        aliases.add(text[:-2])
    canonical = canonical_index_name(text)
    if include_canonical and canonical:
        aliases.add(canonical)
    return {alias for alias in aliases if alias}


def is_plain_index_basic_name(name: str) -> bool:
    return not any(token in name for token in ("全收益", "净收益", "HKD", "USD", "CNY", "退市", "人民币"))


def canonical_index_name(name: str) -> str:
    text = normalize_benchmark(name)
    for prefix in ("中证", "国证", "上证", "深证", "创业板", "恒生A股", "恒生港股通", "恒生"):
        if text.startswith(prefix):
            text = text[len(prefix) :]
    for token in ("主题", "产业", "行业", "综合", "全指", "指数"):
        text = text.replace(token, "")
    return text.strip()


def resolve_index_code(record: TaxonomyRecord, index_lookup: IndexLookup | dict[str, Any]) -> str:
    if record.index_code:
        return record.index_code
    provider_hint = index_provider_hint(record.benchmark)
    for alias in index_name_aliases(record.benchmark, include_canonical=False):
        code = unique_compatible_index_code(index_lookup.get(alias), provider_hint)
        if code:
            return code
    canonical = canonical_index_name(record.benchmark)
    if canonical:
        return unique_compatible_index_code(index_lookup.get(f"canonical:{canonical}"), provider_hint)
    return ""


def unique_compatible_index_code(candidates: Any, provider_hint: str) -> str:
    if not candidates:
        return ""
    if isinstance(candidates, str):
        return candidates
    compatible = [
        candidate
        for candidate in candidates
        if index_candidate_matches_provider(candidate, provider_hint)
    ]
    codes = {str(candidate.get("code") or "") for candidate in compatible if candidate.get("code")}
    return next(iter(codes)) if len(codes) == 1 else ""


def index_candidate_matches_provider(candidate: IndexCandidate, provider_hint: str) -> bool:
    if not provider_hint:
        return True
    market = str(candidate.get("market") or "").upper()
    name = str(candidate.get("name") or "")
    publisher = str(candidate.get("publisher") or "")
    if provider_hint == "CSI":
        return market == "CSI" or name.startswith("中证") or "中证" in publisher
    if provider_hint == "SSE":
        return market == "SSE" or name.startswith(("上证", "科创")) or "上海证券交易所" in publisher
    if provider_hint == "SZSE":
        return market == "SZSE" or name.startswith(("国证", "深证", "创业板", "中小企业")) or "深圳证券交易所" in publisher
    return True


def index_provider_hint(name: str) -> str:
    text = normalize_benchmark(name)
    if text.startswith("中证"):
        return "CSI"
    if text.startswith(("上证", "科创")):
        return "SSE"
    if text.startswith(("国证", "深证", "创业板", "中小企业")):
        return "SZSE"
    return ""


def append_unique_candidate(target: list[IndexCandidate], candidate: IndexCandidate) -> None:
    if not any(item.get("code") == candidate.get("code") for item in target):
        target.append(candidate)


def sw2021_exposure_from_weight_rows(
    rows: list[dict[str, Any]],
    stock_industry: dict[str, str],
) -> dict[str, Any] | None:
    latest_rows = latest_weight_rows(rows)
    if not latest_rows:
        return None
    industry_weights: defaultdict[str, float] = defaultdict(float)
    unknown_weight = 0.0
    total_weight = 0.0
    for row in latest_rows:
        weight = to_float(row.get("weight"))
        if weight <= 0:
            continue
        total_weight += weight
        industry = stock_industry.get(str(row.get("con_code") or ""))
        if industry:
            industry_weights[industry] += weight
        else:
            unknown_weight += weight
    top_industries = [
        {"industry": industry, "weight": round(weight, 2)}
        for industry, weight in sorted(industry_weights.items(), key=lambda item: item[1], reverse=True)[:5]
    ]
    return {
        "weight_date": str(latest_rows[0].get("trade_date") or ""),
        "constituent_count": len(latest_rows),
        "total_weight": round(total_weight, 2),
        "unknown_weight": round(unknown_weight, 2),
        "top_industries": top_industries,
        "top_industry": top_industries[0]["industry"] if top_industries else "",
        "top_industry_weight": top_industries[0]["weight"] if top_industries else 0.0,
        "top3_weight": round(sum(item["weight"] for item in top_industries[:3]), 2),
    }


def latest_weight_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    dates = [str(row.get("trade_date") or "") for row in rows if row.get("trade_date")]
    if not dates:
        return []
    latest_date = max(dates)
    return [row for row in rows if str(row.get("trade_date") or "") == latest_date]


def exposure_summary(exposures: list[dict[str, Any]]) -> dict[str, Any]:
    top_industries = Counter(str(row.get("top_industry") or "") for row in exposures if row.get("top_industry"))
    concentrated = sum(1 for row in exposures if to_float(row.get("top_industry_weight")) >= 60)
    return {
        "checked_count": len(exposures),
        "concentrated_count": concentrated,
        "top_industry_distribution": dict(sorted(top_industries.items())),
    }


def append_limited(target: list[dict[str, Any]], limit: int, **sample: Any) -> None:
    if len(target) < limit:
        target.append({key: value if value is not None else "" for key, value in sample.items()})


def parse_date(value: str) -> date:
    text = str(value)
    return date(int(text[:4]), int(text[4:6]), int(text[6:]))


def to_float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
