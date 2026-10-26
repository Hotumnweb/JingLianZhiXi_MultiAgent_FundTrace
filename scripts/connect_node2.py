# -*- coding: utf-8 -*-
"""连接第二台电脑的 AI 服务（Ollama），并自动写入第一台 `.env`。

前置：第二台已按交接提示词完成 Ollama 局域网监听与防火墙配置。

用法（项目根目录下）：
    conda activate fraud_agent
    cd /d E:\JingLianZhiXi_MultiAgent_FundTrace
    python scripts/connect_node2.py --ip 192.168.0.200

如果第二台有多个模型，可显式指定：
    python scripts/connect_node2.py --ip 192.168.0.200 --model qwen3-4b-fraud:latest

脚本会：
1. 检查 TCP 11434 是否可达；
2. 读取 /api/tags，选择/确认模型；
3. 发起一次最小推理，验证连通和速度；
4. 写入 .env（OLLAMA_BASE_URL / OLLAMA_MODEL / NODE2_TARGET_IP / ENABLE_REPORT_AGENT）；
5. 打印后续测试命令。
"""

from __future__ import annotations

import argparse
import os
import socket
import sys
import time
from pathlib import Path

import requests

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = PROJECT_ROOT / ".env"
DEFAULT_IP = os.getenv("NODE2_TARGET_IP", "192.168.0.200")


def tcp_reachable(host: str, port: int, timeout: float = 3.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def fetch_models(base_url: str) -> list[str]:
    response = requests.get(f"{base_url}/api/tags", timeout=5)
    response.raise_for_status()
    return [item.get("name", "") for item in response.json().get("models", [])]


def pick_model(models: list[str], requested: str | None) -> str:
    if requested:
        if requested in models:
            return requested
        # 允许不带 tag 的简写，例如 qwen3:4b 匹配 qwen3:4b-instruct
        base = requested.split(":")[0]
        candidates = [name for name in models if name.startswith(base)]
        if candidates:
            return candidates[0]
        raise ValueError(f"第二台没有找到模型 {requested}；实际模型：{models}")

    if len(models) == 1:
        return models[0]

    preferred = [name for name in models if "qwen3" in name.lower()]
    if len(preferred) == 1:
        return preferred[0]
    if preferred:
        raise ValueError(
            "第二台有多个 Qwen3 模型，请用 --model 指定实际使用的模型；"
            f"可选：{preferred}"
        )
    raise ValueError(f"无法自动选择模型，请用 --model 指定；第二台模型：{models}")


def smoke_test(base_url: str, model: str) -> dict:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "只回复四个字：连接正常"}],
        "stream": False,
        "options": {"num_predict": 20, "temperature": 0},
    }
    started = time.perf_counter()
    response = requests.post(f"{base_url}/api/chat", json=payload, timeout=600)
    response.raise_for_status()
    elapsed = time.perf_counter() - started
    data = response.json()
    content = ((data.get("message") or {}).get("content") or "").strip()
    eval_count = int(data.get("eval_count") or 0)
    eval_seconds = float(data.get("eval_duration") or 0) / 1e9
    return {
        "content": content,
        "elapsed": round(elapsed, 2),
        "eval_count": eval_count,
        "tokens_per_second": round(eval_count / eval_seconds, 2) if eval_seconds else 0.0,
    }


def update_env(ip: str, model: str) -> None:
    base_url = f"http://{ip}:11434"
    updates = {
        "OLLAMA_BASE_URL": base_url,
        "OLLAMA_MODEL": model,
        "NODE2_TARGET_IP": ip,
        "ENABLE_REPORT_AGENT": "1",
    }

    if ENV_PATH.exists():
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines()
    else:
        lines = []

    written: set[str] = set()
    new_lines = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
        if key in updates:
            new_lines.append(f"{key}={updates[key]}")
            written.add(key)
        else:
            new_lines.append(line)

    missing = [key for key in updates if key not in written]
    if missing:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# ---------- Node2 接入（scripts/connect_node2.py 自动写入） ----------")
        for key in missing:
            new_lines.append(f"{key}={updates[key]}")

    ENV_PATH.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="连接第二台电脑的 Ollama AI 服务")
    parser.add_argument("--ip", default=DEFAULT_IP, help=f"第二台 IP，默认 {DEFAULT_IP}")
    parser.add_argument("--port", type=int, default=11434, help="Ollama 端口，默认 11434")
    parser.add_argument("--model", default=None, help="第二台实际模型名（可选，自动识别）")
    parser.add_argument("--no-write", action="store_true", help="只测试，不修改 .env")
    args = parser.parse_args()

    ip = args.ip.strip()
    base_url = f"http://{ip}:{args.port}"
    print(f"[1/4] 检查第二台 Ollama：{base_url}")

    if not tcp_reachable(ip, args.port):
        print("  [FAIL] 无法连接第二台 11434 端口。")
        print("  请确认：")
        print("    1) 第二台已按 docs/node2_setup_prompt.md 设置 OLLAMA_HOST=0.0.0.0:11434 并重启 Ollama；")
        print("    2) 第二台防火墙已放行 11434；")
        print("    3) 两台电脑仍在同一热点下，且第二台 IP 未变化。")
        return 1
    print("  [OK] TCP 11434 可达")

    print("[2/4] 读取模型列表……")
    try:
        models = fetch_models(base_url)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] 读取 /api/tags 失败：{type(exc).__name__}: {exc}")
        return 1
    print(f"  第二台模型：{models}")
    if not models:
        print("  [FAIL] 第二台没有可用模型，请先 ollama pull / 导入模型")
        return 1

    try:
        model = pick_model(models, args.model)
    except ValueError as exc:
        print(f"  [FAIL] {exc}")
        return 2
    print(f"  使用模型：{model}")

    print("[3/4] 最小推理测试（远端 GPU 应很快）……")
    try:
        result = smoke_test(base_url, model)
    except Exception as exc:  # noqa: BLE001
        print(f"  [FAIL] 推理失败：{type(exc).__name__}: {exc}")
        return 1
    print(f"  回复：{result['content']}")
    print(
        f"  耗时 {result['elapsed']} 秒 | 生成 {result['eval_count']} tokens | "
        f"{result['tokens_per_second']} tok/s"
    )
    if not result["content"]:
        print("  [WARN] 回复为空，请检查模型是否正常")
        return 1

    print("[4/4] 写入第一台 .env……")
    if args.no_write:
        print("  --no-write：跳过写入")
        print(f"  建议配置：OLLAMA_BASE_URL={base_url} ; OLLAMA_MODEL={model}")
        return 0
    update_env(ip, model)
    print(f"  [OK] .env 已更新：OLLAMA_BASE_URL={base_url}，OLLAMA_MODEL={model}")

    print("")
    print("完成。下一步：")
    print("  1) 重启 Streamlit（或刷新页面），节点卡 Node2 应变为在线；")
    print("  2) 在“元智能体调度”提交任务，报告将调用第二台 GPU 节点生成；")
    print("  3) 复验命令：python scripts/check_llm.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
