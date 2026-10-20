# -*- coding: utf-8 -*-
"""报告落盘工具：把研判报告和证据 JSON 保存到 reports/ 目录。

作用：
1. 每次运行生成一个案件编号（时间戳），报告与证据成对保存，便于归档和答辩展示；
2. Streamlit 前端可以直接读取文件并提供下载；
3. 大模型不可用时，用规则模板生成兜底报告，保证整条链路不中断。
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_DIR = PROJECT_ROOT / "reports"


def make_case_id() -> str:
    """生成案件编号，例如 20261020_153012。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _ensure_dir() -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)


def save_evidence(case_id: str, evidence: dict, meta: dict) -> Path:
    """保存结构化证据 JSON（供复核、复现和前端下载）。"""
    _ensure_dir()
    path = REPORT_DIR / f"{case_id}_evidence.json"
    payload = {"case_id": case_id, "meta": meta, "evidence": evidence}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_report(
    case_id: str,
    conclusion: str,
    meta: dict,
    llm_metrics: dict | None = None,
    fallback: bool = False,
) -> Path:
    """保存 Markdown 研判报告（大模型生成或规则模板兜底）。"""
    _ensure_dir()
    path = REPORT_DIR / f"{case_id}_report.md"

    lines = [
        "# 涉案资金穿透研判报告",
        "",
        f"> 案件编号：{case_id}",
        f"> 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
    ]
    for key, value in meta.items():
        lines.append(f"> {key}：{value}")
    if fallback:
        lines.append("> 说明：大模型调用失败，本报告由规则模板自动生成。")
    if llm_metrics:
        lines.append(
            f"> 模型：{llm_metrics.get('model', '-')}；"
            f"生成耗时：{llm_metrics.get('elapsed', '-')} 秒；"
            f"生成速度：{llm_metrics.get('tokens_per_second', '-')} tok/s"
        )
    lines.extend(["", "---", "", conclusion.strip(), ""])

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def build_fallback_report(
    evidence: dict,
    meta: dict,
    suspects: list[str],
    error: str,
) -> str:
    """大模型不可用时的规则模板报告（确定性输出，不依赖网络/算力）。"""
    gather = evidence.get("gather", []) or []
    cycles = evidence.get("cycles", []) or []
    fast_io = evidence.get("fast_io", []) or []
    cycle_accounts = {
        account for item in cycles for account in item.get("accounts", [])
    }

    lines = [
        "## 一、资金网络特征分析",
        "",
        f"本批流水共 **{meta.get('交易笔数', 0)} 条交易**。图规则识别结果如下：",
        "",
        f"- **多层归集（强证据）**：{len(gather)} 个账户在 24 小时内接收 ≥4 个不同上游账户汇入，金额离散度低，符合“水房归集”特征。",
        f"- **环形转账（强证据）**：识别到 {len(cycles)} 条闭环资金链，覆盖 {len(cycle_accounts)} 个账户，资金沿环状路径回流，符合“制造流水、混淆资金去向”特征。",
        f"- **快进快出（辅助证据）**：{len(fast_io)} 个账户在收款后 48 小时内转出 ≥95% 金额，符合“卡农”过渡账户特征。",
        "",
        f"去重后共有 **{len(suspects)} 个可疑账户**，其中强证据账户 {meta.get('强证据账户', 0)} 个，辅助证据账户 {meta.get('辅助证据账户', 0)} 个。",
        "",
        "## 二、高风险账户画像",
        "",
    ]

    if gather:
        lines.extend(["### 2.1 归集账户（水房特征）", ""])
        for item in gather[:10]:
            lines.append(
                f"- `{item['account']}`：上游 {item['upstream_count']} 个，"
                f"汇入约 {item['inflow']} USD，金额离散系数 {item['amount_cv']}"
            )
        lines.append("")

    if cycles:
        lines.extend(["### 2.2 环形转账链", ""])
        for item in cycles[:8]:
            chain = " → ".join(item["accounts"] + [item["accounts"][0]])
            lines.append(
                f"- {chain}（{item['length']} 跳，涉案金额约 {item['amount']} USD，"
                f"跨度约 {item['span_hours']} 小时）"
            )
        lines.append("")

    if fast_io:
        lines.extend(["### 2.3 快进快出账户（辅助证据）", ""])
        for item in fast_io[:10]:
            lines.append(
                f"- `{item['account']}`：命中 {item['hit_count']} 次，"
                f"转出约 {item['outflow']} USD"
            )
        lines.append("")

    lines.extend(
        [
            "## 三、侦查建议",
            "",
            "1. 优先核查归集账户与环形转账链上的账户，调取开户资料、实名信息与设备信息；",
            "2. 对强证据账户对应的交易做资金流向还原，核实上下游账户之间的关联关系；",
            "3. 将快进快出账户作为辅助线索，结合开户时间、交易活跃度和地域信息综合判断；",
            "4. 对已确认的涉案账户依法采取止付、冻结等措施，并同步固定电子证据。",
            "",
            "## 四、方法与局限",
            "",
            "- 本报告的账户、金额、时间均来自图数据库结构化查询结果，未由模型二次生成；",
            "- 图规则基于交易结构识别，存在正常账户被误报的可能，需要人工复核；",
            f"- 说明：大模型调用失败（{error[:200]}），本报告由规则模板自动生成。",
            "",
        ]
    )
    return "\n".join(lines)
