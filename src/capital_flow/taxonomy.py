"""ETF taxonomy rules for market-wide capital-flow analysis."""

from __future__ import annotations

import re


BROAD_BENCHMARK_LABELS: dict[str, str] = {
    "中证A500指数": "中证A500",
    "沪深300指数": "沪深300",
    "中证500指数": "中证500",
    "中证1000指数": "中证1000",
    "中证2000指数": "中证2000",
    "上证50指数": "上证50",
    "上证科创板50成份指数": "科创50",
    "上证科创板100指数": "科创100",
    "中证科创创业50指数": "科创创业50",
    "创业板50指数": "创业板50",
    "创业板指数": "创业板",
    "深证100指数": "深证100",
    "中证100指数": "中证100",
    "上证180指数": "上证180",
    "中证A50指数": "A50",
    "恒生指数": "恒生指数",
    "恒指港股通指数": "恒指港股通",
    "恒生港股通50指数": "港股通50",
    "中证港股通50指数": "港股通50",
    "恒生中国企业指数": "H股指数",
    "恒生中国企业指数(H股指数)": "H股指数",
    "上证综合指数": "上证指数",
    "上证科创板200指数": "科创200",
}

BROAD_INDEX_CODES: dict[str, str] = {
    "中证A500": "000510.SH",
    "沪深300": "000300.SH",
    "中证500": "000905.SH",
    "中证1000": "000852.SH",
    "中证2000": "932000.CSI",
    "上证50": "000016.SH",
    "科创50": "000688.SH",
    "科创100": "000698.SH",
    "科创创业50": "931643.CSI",
    "创业板50": "399673.SZ",
    "创业板": "399006.SZ",
    "深证100": "399330.SZ",
    "中证100": "000903.SH",
    "上证180": "000010.SH",
    "A50": "930050.CSI",
    "恒生指数": "HSI",
    "恒指港股通": "HSICNH",
    "港股通50": "931573.CSI",
    "H股指数": "HSCEI",
    "上证指数": "000001.SH",
    "科创200": "000699.SH",
}

STRATEGY_BENCHMARK_LABELS: dict[str, str] = {
    "中证红利低波动指数": "红利低波",
    "标普中国A股大盘红利低波50指数": "红利低波",
    "标普港股通低波红利指数": "港股红利低波",
    "中证红利指数": "红利",
    "上证红利指数": "红利",
    "标普中国A股红利100指数": "红利",
    "中证港股通高股息投资指数": "港股红利",
    "恒生港股通中国央企红利指数": "港股红利",
    "中证全指红利质量指数": "红利质量",
    "国证自由现金流指数": "现金流",
    "国证大盘价值指数": "价值",
    "中证科技优势成长50策略指数": "成长",
}

STRATEGY_INDEX_PATTERNS: list[tuple[str, str]] = [
    ("红利低波", "红利低波"),
    ("低波红利", "红利低波"),
    ("红利质量", "红利质量"),
    ("红利", "红利"),
    ("高股息", "红利"),
    ("现金流", "现金流"),
    ("价值", "价值"),
    ("质量", "质量"),
    ("成长", "成长"),
]

INDUSTRY_BENCHMARK_LABELS: dict[str, str] = {
    "中证人工智能主题指数": "人工智能",
    "中证人工智能产业指数": "人工智能",
    "中证云计算与大数据主题指数": "云计算",
    "中证创新药产业指数": "创新药",
    "中证生物医药指数": "生物医药",
    "国证生物医药指数": "生物医药",
    "中证医疗指数": "医疗",
    "中证医疗服务指数": "医疗",
    "中证全指医疗保健设备与服务指数": "医疗",
    "中证医药卫生指数": "医药",
    "中证全指医药卫生指数": "医药",
    "沪深300医药卫生指数": "医药",
    "国证医药卫生行业指数": "医药",
    "中证半导体产业指数": "半导体",
    "国证芯片指数": "芯片",
    "中证芯片产业指数": "芯片",
    "中证全指信息技术指数": "信息技术",
    "沪深300信息技术指数": "信息技术",
    "中证软件服务指数": "软件服务",
    "中证全指软件指数": "软件服务",
    "中证全指软件开发指数": "软件服务",
    "国证软件与信息技术服务指数": "软件服务",
    "国证工业软件主题指数": "软件服务",
    "中证计算机主题指数": "计算机",
    "中证全指计算机指数": "计算机",
    "中证全指通信设备指数": "通信",
    "中证通信服务指数": "通信",
    "中证通信设备主题指数": "通信",
    "中证5G通信主题指数": "通信",
    "国证通信指数": "通信",
    "国证商用卫星通信产业指数": "卫星通信",
    "中证科技传媒通信150指数": "TMT",
    "中证机器人指数": "机器人",
    "中证新能源指数": "新能源",
    "中证新能源汽车指数": "新能源车",
    "国证新能源车指数": "新能源车",
    "中证智能汽车主题指数": "智能汽车",
    "中证全指汽车指数": "汽车",
    "中证电池主题指数": "电池",
    "中证光伏产业指数": "光伏",
    "中证光伏龙头30指数": "光伏",
    "中证电网设备主题指数": "电网设备",
    "恒生A股电网设备指数": "电网设备",
    "中证全指证券公司指数": "证券",
    "中证证券公司指数": "证券",
    "中证证券公司30指数": "证券",
    "国证证券龙头指数": "证券",
    "上证证券行业指数": "证券",
    "中证800证券保险指数": "证券保险",
    "沪深300非银行金融指数": "非银金融",
    "中证全指非银行金融指数": "非银金融",
    "中证港股通非银行金融综合指数": "港股非银金融",
    "中证银行指数": "银行",
    "中证全指银行指数": "银行",
    "中证保险主题指数": "保险",
    "中证全指房地产指数": "房地产",
    "中证主要消费指数": "消费",
    "中证消费指数": "消费",
    "中证全指可选消费指数": "消费",
    "中证白酒指数": "酒",
    "中证酒指数": "酒",
    "中证食品饮料指数": "食品饮料",
    "中证全指家用电器指数": "家电",
    "中证传媒指数": "传媒",
    "中证动漫游戏指数": "游戏",
    "中证国防指数": "军工",
    "中证军工指数": "军工",
    "中证有色金属指数": "有色金属",
    "中证稀土产业指数": "稀土",
    "中证钢铁指数": "钢铁",
    "中证煤炭指数": "煤炭",
    "中证细分化工产业主题指数": "化工",
    "中证全指电力公用事业指数": "电力",
    "中证全指公用事业指数": "公用事业",
    "中证绿色电力指数": "绿色电力",
    "国证绿色电力指数": "绿色电力",
    "中证能源指数": "能源",
    "国证石油天然气指数": "石油天然气",
    "中证农业主题指数": "农业",
    "中证全指农牧渔指数": "农牧渔",
    "国证粮食产业指数": "粮食",
    "中证畜牧养殖指数": "畜牧养殖",
    "中证机械指数": "机械",
    "中证电子指数": "电子",
    "中证旅游主题指数": "旅游",
    "中证物流指数": "物流",
    "中证基建指数": "基建",
    "中证全指建筑材料指数": "建材",
    "中证智选船舶产业指数": "船舶",
    "中证通用航空主题指数": "通用航空",
    "恒生科技指数": "恒生科技",
    "中证港股通互联网指数": "港股互联网",
    "中证港股通科技指数": "港股科技",
    "国证港股通科技指数": "港股科技",
    "恒生港股通科技主题指数": "港股科技",
    "恒生港股通中国科技指数": "港股科技",
    "中证港股通医药卫生综合指数": "港股医药",
    "中证港股通消费主题指数": "港股消费",
    "中证港股通信息技术综合指数": "港股信息技术",
    "恒生生物科技指数": "港股生物科技",
    "中证港股通中国100指数": "港股宽基",
}

INDUSTRY_INDEX_PATTERNS: list[tuple[str, str]] = [
    ("非银行金融", "非银金融"),
    ("非银", "非银金融"),
    ("人工智能", "人工智能"),
    ("云计算", "云计算"),
    ("互联网", "互联网"),
    ("创新药", "创新药"),
    ("生物医药", "生物医药"),
    ("医疗", "医疗"),
    ("医药", "医药"),
    ("半导体", "半导体"),
    ("芯片", "芯片"),
    ("信息技术", "信息技术"),
    ("软件", "软件"),
    ("计算机", "计算机"),
    ("通信", "通信"),
    ("机器人", "机器人"),
    ("新能源车", "新能源车"),
    ("智能汽车", "智能汽车"),
    ("汽车", "汽车"),
    ("电池", "电池"),
    ("光伏", "光伏"),
    ("新能源", "新能源"),
    ("证券", "证券"),
    ("券商", "证券"),
    ("银行", "银行"),
    ("保险", "保险"),
    ("地产", "房地产"),
    ("房地产", "房地产"),
    ("消费", "消费"),
    ("酒", "酒"),
    ("食品", "食品"),
    ("家电", "家电"),
    ("传媒", "传媒"),
    ("游戏", "游戏"),
    ("军工", "军工"),
    ("有色", "有色金属"),
    ("稀土", "稀土"),
    ("钢铁", "钢铁"),
    ("煤炭", "煤炭"),
    ("化工", "化工"),
    ("电力", "电力"),
    ("能源", "能源"),
    ("农业", "农业"),
    ("畜牧", "畜牧养殖"),
    ("养殖", "畜牧养殖"),
    ("机械", "机械"),
    ("电子", "电子"),
    ("旅游", "旅游"),
    ("物流", "物流"),
    ("基建", "基建"),
    ("建材", "建材"),
    ("电网设备", "电网设备"),
    ("船舶", "船舶"),
    ("通用航空", "通用航空"),
    ("绿色电力", "绿色电力"),
]

HK_MARKERS = ("港股", "港股通", "恒生", "H股", "香港", "中概")
NON_EQUITY_ETF_MARKERS = (
    "货币",
    "现金",
    "债券",
    "债ETF",
    "债指数",
    "国债",
    "政金债",
    "地方债",
    "公司债",
    "短融",
    "信用债",
    "城投债",
    "科创债",
    "科技创新公司债",
    "基准做市公司债",
    "可转债",
    "转债",
    "短债",
    "活期",
    "存款",
    "通知存款",
    "利率",
)
NON_TARGET_ETF_MARKERS = NON_EQUITY_ETF_MARKERS + (
    "黄金",
    "商品",
    "纳斯达克",
    "纳指",
    "标普",
    "德国",
    "法国",
    "日经",
    "东证",
    "亚太",
    "沙特",
    "美国",
    "日本",
    "REIT",
    "REITS",
)


def classify_etf_group(name: str, benchmark: str = "", invest_type: str = "") -> tuple[str, str] | None:
    clean = name.replace("Ｎ", "N")
    normalized_benchmark = normalize_benchmark(benchmark)
    is_hk = _is_hk_exposure(clean, normalized_benchmark)
    benchmark_label = broad_label_from_benchmark(benchmark, invest_type)
    if benchmark_label:
        return "broad", benchmark_label
    if is_non_equity_etf(clean, normalized_benchmark):
        return None
    strategy_label = _strategy_label_from_benchmark(normalized_benchmark)
    if strategy_label:
        return "strategy", hk_label(strategy_label) if is_hk else strategy_label
    industry_label = _industry_label_from_benchmark(normalized_benchmark)
    if industry_label:
        return ("hk_industry" if is_hk else "a_industry"), hk_label(industry_label) if is_hk else industry_label
    return None


def broad_label_from_benchmark(benchmark: str, invest_type: str) -> str | None:
    if invest_type and invest_type != "被动指数型":
        return None
    normalized = normalize_benchmark(benchmark)
    return BROAD_BENCHMARK_LABELS.get(normalized)


def normalize_benchmark(benchmark: str) -> str:
    text = str(benchmark or "").strip()
    text = text.replace("价格指数", "指数")
    for token in (
        "人民币计价的",
        "经人民币汇率调整的",
        "经汇率调整后的",
        "经估值汇率调整后的",
    ):
        text = text.replace(token, "")
    if "恒生科技" not in text and "恒生指数" in text:
        return "恒生指数"
    if "恒指港股通指数" in text:
        return "恒指港股通指数"
    if "恒生港股通50指数" in text:
        return "恒生港股通50指数"
    if "中证港股通50指数" in text:
        return "中证港股通50指数"
    if "恒生科技指数" in text:
        return "恒生科技指数"
    if "恒生港股通中国科技指数" in text:
        return "恒生港股通中国科技指数"
    if "国证港股通科技指数" in text:
        return "国证港股通科技指数"
    if "恒生中国企业指数" in text or "H股指数" in text:
        return "恒生中国企业指数"
    text = re.sub(r"[（(].*?[）)]", "", text)
    for token in ("收益率", "同期", "*100%"):
        text = text.replace(token, "")
    return text.strip()


def _industry_label_from_benchmark(normalized_benchmark: str) -> str | None:
    if not normalized_benchmark:
        return None
    label = INDUSTRY_BENCHMARK_LABELS.get(normalized_benchmark)
    if label:
        return label
    for pattern, pattern_label in INDUSTRY_INDEX_PATTERNS:
        if pattern in normalized_benchmark:
            return pattern_label
    return None


def _strategy_label_from_benchmark(normalized_benchmark: str) -> str | None:
    if not normalized_benchmark:
        return None
    label = STRATEGY_BENCHMARK_LABELS.get(normalized_benchmark)
    if label:
        return label
    for pattern, pattern_label in STRATEGY_INDEX_PATTERNS:
        if pattern in normalized_benchmark:
            return pattern_label
    return None


def is_non_equity_etf(clean_name: str, normalized_benchmark: str) -> bool:
    return any(marker in clean_name or marker in normalized_benchmark for marker in NON_EQUITY_ETF_MARKERS)


def is_target_equity_etf(clean_name: str, benchmark: str) -> bool:
    normalized_benchmark = normalize_benchmark(benchmark)
    return not any(marker in clean_name or marker in normalized_benchmark for marker in NON_TARGET_ETF_MARKERS)


def hk_label(label: str) -> str:
    return label if label.startswith(("港股", "恒生")) else f"港股{label}"


def _is_hk_exposure(clean_name: str, normalized_benchmark: str) -> bool:
    text = f"{clean_name}{normalized_benchmark}"
    if "恒生A股" in text:
        return False
    return any(marker in text for marker in HK_MARKERS)


def index_code_for_group(section: str, index_name: str) -> str:
    if section != "broad":
        return ""
    return BROAD_INDEX_CODES.get(index_name, "")
