"""共享状态定义：贯穿 LangGraph 全流程的 CaseState。

设计原则：
1. 第一版只放最小闭环需要的字段，避免状态臃肿；
2. 每个节点只读取自己需要的字段、只返回增量更新；
3. 后续加“话术判别 / 深度链路标注 / 报告生成”时，在这里加字段即可，
   不需要改动已实现的节点。

注意：`next_step` 是 supervisor 的路由决策，供 main.py 的条件边读取，
必须出现在状态定义里，不能只在节点返回值里临时塞一个键。
"""

from typing import Any, Dict, List, TypedDict


class CaseState(TypedDict):
    instruction: str                        # 侦查员输入的自然语言指令
    flow_file: str                          # 待解析的流水文件路径
    parsed_records: List[Dict[str, Any]]    # 解析后的结构化交易记录
    suspicious_accounts: List[str]          # 图分析得到的可疑账户
    evidence: Dict[str, Any]                # 图分析证据：fast_io / gather / cycles
    conclusion: str                         # 大模型生成的研判结论
    logs: List[str]                         # 执行日志（前端逐行展示）
    next_step: str                          # supervisor 的路由结果：parsing_agent / report_agent / END
