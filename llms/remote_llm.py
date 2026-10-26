# -*- coding: utf-8 -*-
"""Ollama 推理接入层（本地 CPU 调试 / 第二台 GPU 节点通用）。

为什么直接调 Ollama 原生 API，而不是 LangChain 的 OpenAI 兼容接口：
1. OpenAI 兼容接口无法设置 `num_ctx` / `num_predict`，长 prompt 容易超上下文；
2. 原生 API 会返回 eval_count / eval_duration，可以直接算 tok/s，
   答辩时可以展示“本地 7B 模型 CPU 推理约 XX tok/s、生成报告用时 XX 秒”；
3. 本地和第二台电脑共用一套代码，切换只改 `.env` 的 `OLLAMA_BASE_URL`。

`.env` 配置示例：
    # 本地 CPU 调试
    OLLAMA_BASE_URL=http://127.0.0.1:11434
    OLLAMA_MODEL=qwen2.5:7b-instruct
    # 第二台 GPU 节点
    OLLAMA_BASE_URL=http://192.168.50.2:11434
    OLLAMA_MODEL=qwen2.5:7b-instruct-q4_K_M

写成 `http://.../v1` 也可以，代码会自动去掉 `/v1`。
模型名以 `ollama list` 的输出为准。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

load_dotenv()

DEFAULT_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL = "qwen2.5:7b-instruct"


def _normalize_base_url(raw: str) -> str:
    """容忍 http://ip:11434/ 和 http://ip:11434/v1/ 两种写法。"""
    url = (raw or DEFAULT_BASE_URL).strip().rstrip("/")
    if url.endswith("/v1"):
        url = url[:-3].rstrip("/")
    return url


@dataclass(frozen=True)
class LLMConfig:
    base_url: str
    model: str
    timeout: int
    temperature: float
    max_tokens: int
    num_ctx: int
    keep_alive: str
    think: bool | None = None


def _parse_optional_bool(raw: str) -> bool | None:
    value = (raw or "").strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    return None


def load_llm_config() -> LLMConfig:
    """从 .env / 环境变量读取推理配置。"""
    return LLMConfig(
        base_url=_normalize_base_url(os.getenv("OLLAMA_BASE_URL", DEFAULT_BASE_URL)),
        model=os.getenv("OLLAMA_MODEL", DEFAULT_MODEL).strip(),
        timeout=int(os.getenv("LLM_TIMEOUT", "600")),
        temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
        max_tokens=int(os.getenv("LLM_MAX_TOKENS", "800")),
        num_ctx=int(os.getenv("LLM_NUM_CTX", "4096")),
        keep_alive=os.getenv("LLM_KEEP_ALIVE", "5m"),
        think=_parse_optional_bool(os.getenv("LLM_THINK", "")),
    )


def report_agent_enabled() -> bool:
    """报告节点是否启用。"""
    flag = os.getenv("ENABLE_REPORT_AGENT", "0").strip().lower()
    return flag in {"1", "true", "yes", "on"}


def check_connection(timeout: int = 10) -> dict:
    """检查 Ollama 服务是否可达、目标模型是否存在。"""
    config = load_llm_config()
    result: dict = {
        "ok": False,
        "base_url": config.base_url,
        "model": config.model,
        "available": False,
        "models": [],
        "error": "",
    }
    try:
        response = requests.get(f"{config.base_url}/api/tags", timeout=timeout)
        response.raise_for_status()
        names = [item.get("name", "") for item in response.json().get("models", [])]
        result["models"] = names
        base = config.model.split(":")[0]
        result["available"] = any(
            name == config.model or name.startswith(base + ":") for name in names
        )
        result["ok"] = True
    except Exception as exc:  # noqa: BLE001 - 返回状态给调用方展示，不在这里抛
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


def _result(config: LLMConfig, content: str, elapsed: float, data: dict) -> dict:
    """统一整理推理结果与性能指标。"""
    eval_count = int(data.get("eval_count") or 0)
    eval_seconds = float(data.get("eval_duration") or 0) / 1e9
    return {
        "content": content,
        "model": config.model,
        "base_url": config.base_url,
        "elapsed": round(elapsed, 2),
        "eval_count": eval_count,
        "prompt_eval_count": int(data.get("prompt_eval_count") or 0),
        "tokens_per_second": round(eval_count / eval_seconds, 2) if eval_seconds else 0.0,
    }


def generate(
    prompt: str,
    system_prompt: str | None = None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict:
    """调用 Ollama /api/chat 生成文本，返回内容 + 耗时 + tok/s 指标。

    注意：本地 CPU 推理 7B 模型生成 500 字左右通常需要 1~2 分钟，
    这里默认超时 600 秒，避免现场误判为“模型挂了”。
    """
    config = load_llm_config()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": config.model,
        "messages": messages,
        "stream": False,
        "keep_alive": config.keep_alive,
        "options": {
            "temperature": config.temperature if temperature is None else temperature,
            "num_predict": config.max_tokens if max_tokens is None else max_tokens,
            "num_ctx": config.num_ctx,
        },
    }
    if config.think is not None:
        payload["think"] = config.think

    started = time.perf_counter()
    response = requests.post(
        f"{config.base_url}/api/chat",
        json=payload,
        timeout=config.timeout,
    )
    response.raise_for_status()
    elapsed = time.perf_counter() - started
    data = response.json()

    content = ((data.get("message") or {}).get("content") or "").strip()
    return _result(config, content, elapsed, data)


def generate_stream(
    prompt: str,
    system_prompt: str | None = None,
    on_token=None,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict:
    """流式调用 Ollama /api/chat，逐 token 回调，用于平台实时展示报告生成过程。

    on_token(text) 每收到一段增量文本调用一次；最终返回指标与 generate() 一致。
    """
    config = load_llm_config()

    messages = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": prompt})

    payload = {
        "model": config.model,
        "messages": messages,
        "stream": True,
        "keep_alive": config.keep_alive,
        "options": {
            "temperature": config.temperature if temperature is None else temperature,
            "num_predict": config.max_tokens if max_tokens is None else max_tokens,
            "num_ctx": config.num_ctx,
        },
    }
    if config.think is not None:
        payload["think"] = config.think

    started = time.perf_counter()
    parts: list[str] = []
    final_data: dict = {}

    with requests.post(
        f"{config.base_url}/api/chat",
        json=payload,
        timeout=config.timeout,
        stream=True,
    ) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            try:
                data = json.loads(raw_line)
            except json.JSONDecodeError:
                continue
            token = ((data.get("message") or {}).get("content") or "")
            if token:
                parts.append(token)
                if on_token is not None:
                    try:
                        on_token(token)
                    except Exception:  # noqa: BLE001 - 回调失败不影响生成
                        pass
            if data.get("done"):
                final_data = data

    elapsed = time.perf_counter() - started
    return _result(config, "".join(parts).strip(), elapsed, final_data)

