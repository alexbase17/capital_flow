"""Prompt construction for capital-flow AI summaries."""

from __future__ import annotations

import json
from typing import Any


def deepseek_summary_request_payload(summary_input: dict[str, Any], *, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "temperature": 0.2,
        "max_tokens": 1200,
        "thinking": {"type": "disabled"},
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system_prompt()},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": task_prompt(),
                        "schema": response_schema(),
                        "json_example": response_example(),
                        "data": summary_input,
                    },
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
            },
        ],
    }


def system_prompt() -> str:
    return (
        "你是市场资金流向看板的分析助手。只能基于用户提供的结构化数据总结，"
        "不要编造外部信息，不给买卖建议，不预测收益。必须输出简体中文 JSON，"
        "不要输出 markdown 或代码块。"
    )


def task_prompt() -> str:
    return (
        "任务目标：从用户提供的资金流向数据中，筛选当前最值得关注、"
        "最能辅助后续观察决策的3-5个信号。不要平均覆盖所有板块，不要机械复述排行榜，"
        "要优先找出异常、共振、背离、冲突和风格切换。"
        "优先筛选维度如下；不要求每条关注点全部满足，满足一项且有辅助决策价值即可，"
        "多个维度同时满足时优先级更高："
        "1. 金额、净申购占比、涨跌幅、成交均值占比中任一指标显著异常，"
        "或多指标组合后形成异常的流入、流出、交易热度或价格信号；"
        "2. 1日、5日、20日、60日多窗口同向强化；"
        "3. 短线与中长期趋势冲突；"
        "4. 一级净申购、价格、成交均值占比之间的同窗口共振或背离；"
        "5. 宽基、A股行业、港股行业、策略因子之间的风格切换或分化；"
        "6. 资金行为和价格表现明显不一致、需要后续验证的点。"
        "每条关注点应尽量包含：发生了什么关键数据现象；可能代表什么资金行为；"
        "后续最应该观察什么变化。如果多个信号属于同一条资金主线，优先合并表达，"
        "不要拆成多条重复关注点。若没有足够强的信号，请明确说信号偏弱。"
        "硬约束：只能基于 data 提供的数据，不编造外部信息，不给买卖建议，不预测收益，"
        "若 data.quality.payload_cache_status 为 stale，只能说明基于上次成功缓存数据，"
        "不得表述为本次已成功刷新后的最新结果。"
        "不要写确定性结论。必须严格遵守 data.metric_notes 的字段口径：只有同一窗口的数据"
        "才能表述为同期、背离或共振，例如 flow_60d_yi 只能和 change_60d_pct、"
        "turnover_60d_avg_pct 做同期比较；不得用最新1日涨跌幅解释20日或60日资金。"
        "跨窗口只能表述为短线与中期/长期趋势对照。输出时使用表格一致术语："
        "一级市场用净申购/净赎回和净申购占比，二级市场用成交均值占比，"
        "不使用流入强度、成交热度、换手率等容易和表格口径不一致的说法。"
        "金额单位为亿元，按表格展示习惯保留有效精度：绝对值100亿元及以上不保留小数，"
        "10到100亿元保留1位小数，10亿元以下最多保留2位小数。"
        "请按辅助决策价值从高到低排序，最多输出5个关注点；如有需要谨慎解读的点，"
        "合并进对应关注点 detail，不要单独堆在末尾。"
    )


def response_schema() -> dict[str, Any]:
    return {
        "headline": "一句话概括最核心资金特征，尽量短",
        "focus_items": [
            {
                "title": "关注点标题",
                "detail": "用一到三句话说明为什么重要、可能代表什么资金行为、下一步观察什么",
            }
        ],
        "risks": [],
        "data_quality": "可选：仅供后端保留，不会在前端展示",
    }


def response_example() -> dict[str, Any]:
    return {
        "headline": "宽基短线回流，行业分化",
        "focus_items": [
            {
                "title": "沪深300回流",
                "detail": "近5日净申购转强，但近20日仍为净赎回，说明短线资金修复尚未完全扭转中期流出。后续重点观察回流能否延续，并和成交均值占比、价格表现形成共振。",
            }
        ],
        "risks": [],
        "data_quality": "",
    }
