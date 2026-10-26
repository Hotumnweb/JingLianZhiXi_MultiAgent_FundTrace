# -*- coding: utf-8 -*-
"""报告智能体：把 graph_agent 的证据交给大模型生成正式研判报告，并落盘归档。

流程：
1. 从 state 读取 graph_agent 产出的结构化证据（没有则兜底重查）；
2. 生成案件编号，先把证据 JSON 落盘（即使后续 LLM 失败也有证据）；
3. 调用本地/远程 Ollama 生成四段式《涉案资金穿透研判报告》；
4. LLM 不可用时自动降级为规则模板报告，保证链路不中断；
5. 保存 Markdown 报告，返回路径给前端下载。

防幻觉约束：账号、金额、时间只允许引用图查询结果，Prompt 中明确禁止编造。
"""

from llms.remote_llm import generate, generate_stream
from tools.graph_query import (
    find_circular_loops,
    find_fan_in,
    find_fast_in_fast_out,
)
from tools.report_writer import (
    build_fallback_report,
    make_case_id,
    save_evidence,
    save_report,
)

try:  # LangGraph 自定义流式输出（平台展示实时 token）
    from langgraph.config import get_stream_writer
except Exception:  # pragma: no cover
    get_stream_writer = None

SYSTEM_PROMPT = (
    "你是一名资深的公安反诈中心资金研判专家，熟悉电信网络诈骗资金流侦查、"
    "水房归集、卡农过渡账户和环形转账等洗钱手法。"
    "你只能依据用户提供的结构化图查询事实撰写报告，严禁编造账户、金额、时间或案件背景。"
    "不同证据类别（多层归集 / 环形转账 / 快进快出）的账户不得交叉混用。"
    "输出使用简体中文 Markdown，不要输出与研判无关的寒暄和免责声明。"
)


def _build_evidence(fast_io: list[dict], gather: list[dict], cycles: list[dict]) -> str:
    """把三类图规则结果整理成给模型看的事实清单（控制长度，避免超上下文）。"""
    lines = []
    if gather:
        lines.append("【强证据 · 多层归集】24 小时内 ≥4 个上游账户汇入、金额高度接近：")
        for item in gather[:6]:
            lines.append(
                f"- {item['account']}：上游 {item['upstream_count']} 个，"
                f"汇入约 {item['inflow']}，金额离散系数 {item['amount_cv']}"
            )
    if cycles:
        lines.append("【强证据 · 环形转账】时间递增、金额逐跳递减的闭环资金链：")
        for item in cycles[:5]:
            chain = " -> ".join(item["accounts"] + [item["accounts"][0]])
            lines.append(
                f"- {chain}（{item['length']} 跳，涉案金额约 {item['amount']}，"
                f"跨度约 {item['span_hours']} 小时）"
            )
    if fast_io:
        lines.append("【辅助证据 · 快进快出】48 小时内转出 ≥95% 收款金额且交易笔数较少：")
        for item in fast_io[:6]:
            lines.append(
                f"- {item['account']}：命中 {item['hit_count']} 次，转出约 {item['outflow']}"
            )
    return "\n".join(lines) if lines else "本次图查询未命中明显可疑模式。"


def _build_prompt(evidence_text: str, meta: dict) -> str:
    return f"""以下是图数据库对一批银行流水做结构化分析后得到的事实（不是推测），请据此撰写研判报告。

## 一、案件数据
- 本批流水：{meta['交易笔数']} 条交易
- 图谱规模：{meta['图谱规模']}
- 多层归集账户：{meta['归集账户']} 个
- 环形转账链：{meta['环形链条']} 条，覆盖 {meta['环形账户']} 个账户
- 快进快出账户：{meta['快进快出账户']} 个
- 强证据账户：{meta['强证据账户']} 个；辅助证据账户：{meta['辅助证据账户']} 个；可疑账户合计：{meta['可疑账户']} 个
- 规则口径：多层归集 = 24 小时窗口；环形转账 = 时间递增且跨度不超过 7 天；快进快出 = 48 小时窗口

## 二、图规则命中的证据
{evidence_text}

## 三、报告要求
请撰写《涉案资金穿透研判报告》，必须包含以下四个部分（使用 Markdown 二级标题）：
## 一、资金网络特征分析
## 二、高风险账户画像
## 三、侦查建议
## 四、方法与局限

要求：
1. 语言严谨、专业，符合公安机关资金研判报告风格；
2. 所有账户、金额、时间只能引用上面给出的事实，不得编造；
3. 明确区分“强证据”（多层归集、环形转账）与“辅助证据”（快进快出），时间窗口必须符合上述规则口径；
4. 报告要体现“水房归集”“卡农过渡”“环形流转”的洗钱逻辑；
5. **全文控制在 900 字左右，必须完整包含上述四个部分**；
6. 账户清单只列举有代表性的 3~5 个，其余用数量概括，不要逐条罗列全部账户；
7. 数据集金额单位为 **USD**，请用 USD 表述，不要写成人民币“元”；
8. **严格按证据分类引用，禁止跨类别混用**：
   - “多层归集”只能引用【强证据 · 多层归集】里的账户；
   - “环形转账”只能引用【强证据 · 环形转账】里的账户；
   - “快进快出”只能引用【辅助证据 · 快进快出】里的账户；
   - 不得把一个类别的账户写进另一个类别，也不得补充证据里没有的金额、时间或行为；
9. 只输出报告正文，不要重复本提示词。
"""


def report_agent_node(state: dict) -> dict:
    logs = list(state.get("logs", []))
    evidence = state.get("evidence") or {}

    if evidence:
        fast_io = evidence.get("fast_io", []) or []
        gather = evidence.get("gather", []) or []
        cycles = evidence.get("cycles", []) or []
        suspects = list(state.get("suspicious_accounts", []))
        logs.append("[ReportAgent] 复用 GraphAgent 的图分析证据，不重复查询")
    else:
        # 正常情况下 supervisor 会先路由到 graph_agent，这里只是兜底
        logs.append("[ReportAgent] 未发现图分析证据，直接执行图查询")
        fast_io = find_fast_in_fast_out()
        gather = find_fan_in()
        cycles = find_circular_loops()
        strong = {item["account"] for item in gather}
        strong |= {account for item in cycles for account in item["accounts"]}
        suspects = sorted(strong | {item["account"] for item in fast_io})
        evidence = {"fast_io": fast_io, "gather": gather, "cycles": cycles}

    summary = evidence.get("summary") or {}
    meta = {
        "数据源": state.get("flow_file", ""),
        "交易笔数": len(state.get("parsed_records", [])),
        "图谱规模": f"{summary.get('accounts', 0)} 个账户 / {summary.get('transfers', 0)} 条转账",
        "强证据账户": evidence.get("strong_count", 0),
        "辅助证据账户": evidence.get("weak_count", 0),
        "可疑账户": len(suspects),
        "归集账户": len(gather),
        "环形链条": len(cycles),
        "环形账户": len({account for item in cycles for account in item["accounts"]}),
        "快进快出账户": len(fast_io),
        "金额单位": "USD（合成数据）",
    }

    case_id = make_case_id()
    evidence_path = save_evidence(case_id, evidence, meta)
    logs.append(f"[ReportAgent] 证据已落盘：{evidence_path.name}")

    llm_status = "ok"
    llm_metrics: dict | None = None
    writer = None
    if get_stream_writer is not None:
        try:
            writer = get_stream_writer()
        except Exception:  # noqa: BLE001 - 非流式调用场景下拿不到 writer
            writer = None

    try:
        logs.append("[ReportAgent] 正在调用 AI 生成研判报告……")
        prompt = _build_prompt(_build_evidence(fast_io, gather, cycles), meta)

        if writer is not None:
            try:
                writer({"type": "stage", "stage": "report_start"})
            except Exception:  # noqa: BLE001
                pass

            def _on_token(text: str) -> None:
                try:
                    writer({"type": "token", "text": text})
                except Exception:  # noqa: BLE001
                    pass

            llm_metrics = generate_stream(
                prompt, system_prompt=SYSTEM_PROMPT, on_token=_on_token
            )
            try:
                writer({"type": "stage", "stage": "report_done"})
            except Exception:  # noqa: BLE001
                pass
        else:
            llm_metrics = generate(prompt, system_prompt=SYSTEM_PROMPT)

        conclusion = llm_metrics["content"]
        if not conclusion:
            raise ValueError("模型返回内容为空")
        logs.append(
            f"[ReportAgent] 大模型完成：耗时 {llm_metrics['elapsed']} 秒，"
            f"输入 {llm_metrics['prompt_eval_count']} tokens，"
            f"生成 {llm_metrics['eval_count']} tokens，"
            f"速度 {llm_metrics['tokens_per_second']} tok/s"
        )
    except Exception as exc:  # noqa: BLE001 - 大模型失败时降级，保证链路不中断
        llm_status = "fallback"
        conclusion = build_fallback_report(
            evidence, meta, suspects, f"{type(exc).__name__}: {exc}"
        )
        logs.append(f"[ReportAgent][WARN] 大模型调用失败，已生成规则模板报告：{exc}")
        if writer is not None:
            try:
                writer({"type": "stage", "stage": "report_fallback"})
            except Exception:  # noqa: BLE001
                pass

    report_path = save_report(
        case_id,
        conclusion,
        meta,
        llm_metrics=llm_metrics,
        fallback=(llm_status == "fallback"),
    )
    logs.append(f"[ReportAgent] 研判报告已落盘：{report_path.name}")

    return {
        "suspicious_accounts": suspects,
        "conclusion": conclusion,
        "report_path": str(report_path),
        "evidence_path": str(evidence_path),
        "llm_status": llm_status,
        "logs": logs,
    }
