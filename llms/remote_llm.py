"""远程大模型接入层：只负责“怎么连模型”，不负责业务逻辑。

约定：
1. 大模型跑在第二台电脑（GPU Inference Node）的 Ollama 上；
2. Ollama 提供 OpenAI 兼容接口，所以直接用 langchain-openai 的 ChatOpenAI；
3. 第二台未就绪时，`.env` 里 `ENABLE_REPORT_AGENT=0`，
   supervisor 不会路由到报告节点，本模块不会被真正调用。
"""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

DEFAULT_MODEL = "qwen2.5:7b-instruct-q4_K_M"
DEFAULT_BASE_URL = "http://192.168.50.2:11434/v1/"


def get_remote_llm(temperature: float = 0.0) -> ChatOpenAI:
    """返回指向第二台 Ollama 的 OpenAI 兼容客户端。"""
    return ChatOpenAI(
        model=os.getenv("OLLAMA_MODEL", DEFAULT_MODEL),
        base_url=os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL),
        api_key="ollama",  # Ollama 不校验这个值，但 SDK 要求非空
        temperature=temperature,
        timeout=120,
        max_retries=1,
    )


def report_agent_enabled() -> bool:
    """报告节点是否启用（第二台未就绪时返回 False）。"""
    flag = os.getenv("ENABLE_REPORT_AGENT", "0").strip().lower()
    return flag in {"1", "true", "yes", "on"}
