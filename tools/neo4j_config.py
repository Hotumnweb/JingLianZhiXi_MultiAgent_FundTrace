# -*- coding: utf-8 -*-
"""Neo4j 图数据工具连接配置（IP + 端口写法）。

图数据工具统一用“IP（或主机名）+ 端口”两个变量描述 Neo4j 位置，
不再要求把地址写进 `bolt://...` 这种 URI 字符串：

    # .env（本机回环地址示例）
    NEO4J_HOST=127.0.0.1
    NEO4J_PORT=7687
    NEO4J_USER=neo4j
    NEO4J_PASSWORD=fraud2026

    # 部署到第三台工具节点时只改前两行，例如：
    # NEO4J_HOST=10.20.30.30
    # NEO4J_PORT=7687

可选变量：
    NEO4J_SCHEME=bolt            # 默认 bolt；TLS 用 bolt+s / neo4j+s
    NEO4J_DATABASE=neo4j         # 指定数据库；不填用服务端默认库
    NEO4J_CONNECTION_TIMEOUT=5   # 建立连接超时（秒），默认 5
    NEO4J_IP=127.0.0.1           # NEO4J_HOST 的别名，两个变量名都认

兼容旧写法：只写 `NEO4J_URI=bolt://localhost:7687` 时自动解析出 host / port；
若同时配置，显式 NEO4J_HOST / NEO4J_IP / NEO4J_PORT 优先于 URI。

`NEO4J_HOST` 也允许直接写 `127.0.0.1:7687`（未单独配置 NEO4J_PORT 时生效），
IPv6 地址写成 `::1` 或 `[::1]:7687` 都可以。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

load_dotenv()

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 7687
DEFAULT_SCHEME = "bolt"
DEFAULT_USER = "neo4j"
DEFAULT_CONNECTION_TIMEOUT = 5.0

# 视为“本机”的地址：平台据此显示“本机调试”，不影响连接逻辑
LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


@dataclass(frozen=True)
class Neo4jConfig:
    """Neo4j 连接参数：host + port 是主配置，uri 由它们拼出来。"""

    host: str
    port: int
    scheme: str = DEFAULT_SCHEME
    user: str = DEFAULT_USER
    password: str = ""
    database: str = ""
    connection_timeout: float = DEFAULT_CONNECTION_TIMEOUT

    @property
    def uri(self) -> str:
        """驱动实际使用的 URI，例如 bolt://127.0.0.1:7687。"""
        host = self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"{self.scheme}://{host}:{self.port}"

    @property
    def endpoint(self) -> str:
        """展示用地址：127.0.0.1:7687。"""
        return f"{self.host}:{self.port}"

    @property
    def is_local(self) -> bool:
        """是否本机回环地址。"""
        host = self.host.strip().lower()
        return host in LOOPBACK_HOSTS or host.startswith("127.")


def _clean(value) -> str:
    return str(value or "").strip()


def _parse_uri(raw: str) -> tuple[str, str, int | None, str]:
    """从旧写法 URI 中解析 (scheme, host, port, database)。"""
    text = _clean(raw)
    if not text:
        return "", "", None, ""
    if "://" not in text:
        text = f"{DEFAULT_SCHEME}://{text}"
    try:
        parsed = urlparse(text)
    except ValueError:
        return "", "", None, ""
    host = parsed.hostname or ""
    try:
        port = parsed.port
    except ValueError:  # 端口不是合法数字
        port = None
    database = (parsed.path or "").strip("/")
    return parsed.scheme or DEFAULT_SCHEME, host, port, database


def _split_host_port(raw: str) -> tuple[str, int | None]:
    """允许 NEO4J_HOST 直接写 127.0.0.1:7687 或 [::1]:7687。"""
    text = _clean(raw)
    if not text:
        return "", None
    if text.startswith("["):
        end = text.find("]")
        if end > 0:
            host = text[1:end]
            rest = text[end + 1 :]
            if rest.startswith(":") and rest[1:].isdigit():
                return host, int(rest[1:])
            return host, None
    if text.count(":") == 1:
        host, _, port_text = text.partition(":")
        if port_text.isdigit():
            return host, int(port_text)
    return text, None


def _parse_port(raw) -> int | None:
    text = _clean(raw)
    if not text:
        return None
    try:
        port = int(text)
    except ValueError:
        return None
    return port if 0 < port < 65536 else None


def _parse_timeout(raw) -> float | None:
    text = _clean(raw)
    if not text:
        return None
    try:
        timeout = float(text)
    except ValueError:
        return None
    return timeout if timeout > 0 else None


def _normalize_scheme(raw: str) -> str:
    text = _clean(raw).lower()
    if text.endswith("://"):
        text = text[:-3]
    return text or DEFAULT_SCHEME


def load_neo4j_config() -> Neo4jConfig:
    """读取 Neo4j 连接配置。

    每次调用都重新读取环境变量，便于脚本临时覆盖（--host/--port）
    以及单元测试；`.env` 在模块导入时由 python-dotenv 载入。
    """
    uri_scheme, uri_host, uri_port, uri_database = _parse_uri(os.getenv("NEO4J_URI", ""))

    host, host_port = _split_host_port(
        _clean(os.getenv("NEO4J_HOST")) or _clean(os.getenv("NEO4J_IP"))
    )
    if not host:
        host = uri_host or DEFAULT_HOST

    port = _parse_port(os.getenv("NEO4J_PORT")) or host_port or uri_port or DEFAULT_PORT
    scheme = _normalize_scheme(os.getenv("NEO4J_SCHEME") or uri_scheme)
    database = _clean(os.getenv("NEO4J_DATABASE")) or uri_database

    return Neo4jConfig(
        host=host,
        port=port,
        scheme=scheme,
        user=_clean(os.getenv("NEO4J_USER")) or DEFAULT_USER,
        password=os.getenv("NEO4J_PASSWORD", ""),
        database=database,
        connection_timeout=_parse_timeout(os.getenv("NEO4J_CONNECTION_TIMEOUT"))
        or DEFAULT_CONNECTION_TIMEOUT,
    )


def neo4j_endpoint() -> str:
    """平台展示用的 IP:端口。"""
    return load_neo4j_config().endpoint


def neo4j_is_local() -> bool:
    """当前 Neo4j 是否配置为本机回环地址。"""
    return load_neo4j_config().is_local


def connection_info() -> dict:
    """连接配置摘要，供平台页面/自检脚本展示。"""
    config = load_neo4j_config()
    return {
        "host": config.host,
        "port": config.port,
        "endpoint": config.endpoint,
        "uri": config.uri,
        "scheme": config.scheme,
        "user": config.user,
        "database": config.database,
        "local": config.is_local,
        "timeout": config.connection_timeout,
    }
