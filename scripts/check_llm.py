# -*- coding: utf-8 -*-
"""检查 Ollama 服务连通性，并做一次最小推理测试。

用法（项目根目录下）：
    conda activate fraud_agent
    python scripts/check_llm.py

也可以临时指定地址做“第二台节点联调”：
    $env:OLLAMA_BASE_URL = "http://192.168.50.2:11434"
    $env:OLLAMA_MODEL = "qwen2.5:7b-instruct-q4_K_M"
    python scripts/check_llm.py
"""

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from llms.remote_llm import check_connection, generate, load_llm_config  # noqa: E402


def main() -> int:
    config = load_llm_config()
    print(
        f"[1/3] 配置：{config.base_url} | 模型 {config.model} | "
        f"上下文 {config.num_ctx} | 超时 {config.timeout}s"
    )

    info = check_connection()
    if not info["ok"]:
        print(f"[2/3] 服务检查失败：{info['error']}")
        print("      排查：Ollama 是否启动（ollama serve / 托盘程序）")
        return 1
    print(f"[2/3] 服务检查通过，可用模型：{info['models']}")
    if not info["available"]:
        print(f"      [WARN] 未找到目标模型 {config.model}，请检查 .env 或先 ollama pull")
        return 2

    print("[3/3] 最小推理测试（首次加载模型可能需要 10~20 秒）……")
    try:
        result = generate(
            "请只回复四个字：连接正常",
            temperature=0,
            max_tokens=24,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"      推理失败：{type(exc).__name__}: {exc}")
        return 1

    print(f"      回复：{result['content']}")
    print(
        f"      耗时 {result['elapsed']} 秒 | 生成 {result['eval_count']} tokens | "
        f"{result['tokens_per_second']} tok/s"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
