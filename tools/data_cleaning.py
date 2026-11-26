# -*- coding: utf-8 -*-
"""数据接入与清洗引擎：把真实世界里“混乱 + 很大”的一手流水变成平台可建图的数据。

真实公安数据的典型问题，本模块逐一处理：
- 编码混乱：UTF-8（带/不带 BOM）、GBK/GB18030、Big5、Latin-1 自动识别；
- 分隔符混乱：逗号、分号、Tab、竖线自动识别；
- 列名混乱：中英文别名、大小写、空格、括号、全角字符；
- 字段结构混乱：付款方可能是“银行 + 账号”两列；时间可能是字符串、Unix 时间戳、
  毫秒时间戳或“步长（小时）”；金额可能带 ￥、逗号、负号括号；
- 数据量很大：几百 MB / 几百万行，用分块流式处理，不整表进内存；
- 脏数据：空账号、自转账、重复行、无效时间/金额，按规则剔除并记录原因；
- 标签泄漏：原始数据里的 Is Laundering / isFraud 等标签一律不进入输出流水，
  只允许评测脚本单独读取原始文件。

输出（写入 `data/cleaned/`，原始文件只读，不改不删）：
    <name>_clean.csv        统一中文流水：交易时间,金额,付款账号,收款账号,摘要
    <name>_stats.json       清洗报告：行数、剔除原因、时间范围、金额统计、映射参数
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
CLEANED_DIR = DATA_DIR / "cleaned"

READABLE_EXTENSIONS = (".csv", ".tsv", ".txt", ".xlsx", ".xls")
ENCODING_CANDIDATES = ("utf-8-sig", "utf-8", "gb18030", "gbk", "big5", "latin1")
CHUNK_SIZE = 200_000
OUTPUT_COLUMNS = ["交易时间", "金额", "付款账号", "收款账号", "摘要"]

# 列名别名：真实数据里常见的各种写法
ALIASES: dict[str, list[str]] = {
    "trade_time": [
        "交易时间", "交易日期", "交易日期时间", "发生时间", "记账时间", "时间", "日期",
        "交易时间戳", "trade_time", "time", "timestamp", "datetime", "tradedt",
        "transactiondt", "交易dt", "step", "步长",
    ],
    "amount": [
        "金额", "交易金额", "发生额", "转账金额", "交易额", "金额(元)", "交易金额(元)",
        "amount", "amt", "amount paid", "amount received", "transactionamt",
        "transactionamount", "金额usd", "amount_usd",
    ],
    "from_account": [
        "付款账号", "付款账户", "付方账号", "付款人账号", "出账账号", "转出账号",
        "付款卡号", "付款方", "汇款账号", "from_account", "fromaccount", "sender",
        "sender_account", "nameorig", "payer", "from", "orig", "付方",
    ],
    "to_account": [
        "收款账号", "收款账户", "收方账号", "对方账号", "入账账号", "转入账号",
        "收款卡号", "收款方", "to_account", "toaccount", "receiver",
        "receiver_account", "namedest", "payee", "to", "dest", "收方",
    ],
    "summary": [
        "摘要", "附言", "备注", "交易摘要", "用途", "交易类型", "交易说明", "说明",
        "summary", "memo", "remark", "type", "payment format", "paymentformat",
        "交易渠道",
    ],
}

# 已知数据集的识别特征与推荐映射
_IBM_FROM = ["From Bank", "Account"]
_IBM_TO = ["To Bank", "Account.1"]


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def ensure_cleaned_dir() -> None:
    CLEANED_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# 文件画像
# ---------------------------------------------------------------------------
def resolve_path(relative_or_abs: str) -> Path:
    path = Path(str(relative_or_abs))
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def relative_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(path)


def read_head_text(path: Path, nbytes: int = 200_000) -> tuple[str, str]:
    """读取文件开头并猜测编码，返回 (文本, 编码)。"""
    with path.open("rb") as handle:
        raw = handle.read(nbytes)
    for encoding in ENCODING_CANDIDATES:
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("latin1", errors="replace"), "latin1"


def _detect_delimiter(text: str) -> str:
    lines = [line for line in text.splitlines()[:50] if line.strip()]
    if not lines:
        return ","
    counts = {delimiter: 0 for delimiter in (",", "\t", ";", "|")}
    for line in lines:
        for delimiter in counts:
            counts[delimiter] += line.count(delimiter)
    best = max(counts, key=counts.get)
    return best if counts[best] > 0 else ","


def _count_lines(path: Path) -> int:
    """快速数文件行数（分块读字节，不解析内容）。"""
    total = 0
    last_byte = b""
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(8 * 1024 * 1024)
            if not chunk:
                break
            total += chunk.count(b"\n")
            last_byte = chunk[-1:]
    if last_byte and last_byte != b"\n":
        total += 1
    return total


def _guess_header(text: str, delimiter: str) -> tuple[bool, int]:
    """猜测首行是否为表头，返回 (是否表头, 列数)。"""
    lines = [line for line in text.splitlines()[:5] if line.strip()]
    if not lines:
        return True, 0
    first = lines[0].split(delimiter)
    if len(first) < 2:
        return True, len(first)
    non_numeric = 0
    for value in first:
        text_value = value.strip().strip('"')
        if not text_value:
            continue
        try:
            float(text_value.replace(",", ""))
        except ValueError:
            non_numeric += 1
    return non_numeric >= max(1, len(first) // 2), len(first)


def _normalize_name(name: str) -> str:
    text = str(name).strip().lower()
    text = text.replace("（", "(").replace("）", ")").replace("：", ":")
    text = re.sub(r"[\s_\-/\\()\[\]{}]+", "", text)
    return text


def _alias_index() -> dict[str, str]:
    index: dict[str, str] = {}
    for field_name, aliases in ALIASES.items():
        for alias in aliases:
            index[_normalize_name(alias)] = field_name
    return index


_ALIAS_INDEX = _alias_index()


def _match_field(column: str) -> str | None:
    normalized = _normalize_name(column)
    if not normalized:
        return None
    if normalized in _ALIAS_INDEX:
        return _ALIAS_INDEX[normalized]
    # 子串匹配（处理“交易金额(万元)”这类带后缀的列名）
    for alias, field_name in _ALIAS_INDEX.items():
        if len(alias) >= 3 and (alias in normalized or normalized in alias):
            return field_name
    return None


def _read_preview_frame(path: Path, encoding: str, delimiter: str, has_header: bool,
                        nrows: int = 200) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, nrows=nrows, dtype=str)
    header_arg = 0 if has_header else None
    return pd.read_csv(
        path,
        sep=delimiter,
        encoding=encoding,
        header=header_arg,
        nrows=nrows,
        dtype=str,
        keep_default_na=False,
        on_bad_lines="skip",
    )


def _column_profile(frame: pd.DataFrame) -> list[dict]:
    profiles = []
    for column in frame.columns:
        series = frame[column].astype(str).fillna("").str.strip()
        samples = [value for value in series.head(500).tolist() if value][:5]
        empty = int((series.head(500) == "").sum())
        numeric = 0
        for value in series.head(100):
            try:
                float(value.replace(",", "").strip("()￥$¥ "))
                numeric += 1
            except ValueError:
                continue
        profiles.append(
            {
                "name": str(column),
                "samples": samples,
                "empty_ratio": round(empty / max(1, min(len(series), 500)), 3),
                "numeric_ratio": round(numeric / max(1, min(len(series), 100)), 2),
            }
        )
    return profiles


def _dataset_hint(columns: list[str]) -> tuple[str, str]:
    """根据列名猜数据集类型，返回 (hint_key, 说明)。"""
    normalized = {_normalize_name(column) for column in columns}
    if {"frombank", "account", "tobank", "account.1"} <= normalized and "islaundering" in normalized:
        return "ibm_aml", "IBM AML 银行流水（From Bank/Account 两列组成账号）"
    if {"nameorig", "namedest", "step"} <= normalized:
        return "paysim", "PaySim 移动支付（step 为小时步长）"
    if {"transactionid", "transactionamt"} & normalized:
        return "ieee_fraud", "IEEE-CIS 表格欺诈数据（无收付款双方账户，无法建资金图）"
    if {"txid1", "txid2"} & normalized:
        return "elliptic_edges", "Elliptic 交易图边表（无金额，不适合资金流水建图）"
    # 通用中英文资金流水：按列名别名匹配，匹配到 4 个标准字段即认为是流水
    matched_fields = {
        field_name
        for column in columns
        if (field_name := _match_field(str(column)))
    }
    if len(matched_fields) >= 4:
        return "generic_flow", "通用资金流水（可按下方映射直接清洗）"
    if len(matched_fields) >= 3:
        return "generic_flow_partial", "疑似资金流水（部分字段需手工确认）"
    return "unknown", "未识别数据集，请手动指定字段映射"


def suggest_mapping(columns: list[str]) -> dict:
    """根据列名自动建议字段映射。"""
    hint_key, hint_text = _dataset_hint(columns)

    def pick(*candidates: str) -> list[str]:
        lookup = {_normalize_name(column): str(column) for column in columns}
        result = []
        for candidate in candidates:
            matched = lookup.get(_normalize_name(candidate))
            if matched:
                result.append(matched)
        return result

    if hint_key == "ibm_aml":
        mapping = {
            "time_columns": pick("Timestamp"),
            "time_mode": "datetime",
            "amount_columns": pick("Amount Paid", "Amount Received"),
            "from_columns": pick(*_IBM_FROM),
            "from_separator": ":",
            "to_columns": pick(*_IBM_TO),
            "to_separator": ":",
            "summary_columns": pick("Payment Format"),
            "confidence": "high",
            "note": "IBM AML 格式：账号由银行号 + 账号两列拼接",
        }
    elif hint_key == "paysim":
        mapping = {
            "time_columns": pick("step"),
            "time_mode": "step_hours",
            "amount_columns": pick("amount"),
            "from_columns": pick("nameOrig"),
            "from_separator": "",
            "to_columns": pick("nameDest"),
            "to_separator": "",
            "summary_columns": pick("type"),
            "confidence": "high",
            "note": "PaySim 格式：step 为小时步长，映射到 2017-01-01 起算",
        }
    else:
        found: dict[str, list[str]] = {}
        for column in columns:
            field_name = _match_field(str(column))
            if field_name and field_name not in found:
                found[field_name] = [str(column)]
        mapping = {
            "time_columns": found.get("trade_time", []),
            "time_mode": "auto",
            "amount_columns": found.get("amount", []),
            "from_columns": found.get("from_account", []),
            "from_separator": "",
            "to_columns": found.get("to_account", []),
            "to_separator": "",
            "summary_columns": found.get("summary", []),
            "confidence": "medium" if len(found) >= 3 else "low",
            "note": "按中文/英文列名别名自动匹配，请在界面上核对",
        }

    required = ["time_columns", "amount_columns", "from_columns", "to_columns"]
    missing = [name for name in required if not mapping.get(name)]
    mapping["missing"] = missing
    mapping["hint_key"] = hint_key
    mapping["hint_text"] = hint_text
    if hint_key in {"ieee_fraud", "elliptic_edges"}:
        mapping["warnings"] = [hint_text]
    else:
        mapping["warnings"] = []
    return mapping


def profile_file(
    relative_or_abs: str,
    preview_rows: int = 200,
    encoding: str | None = None,
    delimiter: str | None = None,
    has_header: bool | None = None,
) -> dict:
    """文件画像：编码、分隔符、表头、行数、列画像、字段映射建议。

    encoding / delimiter / has_header 可传入人工修正值（界面“识别参数修正”）。
    """
    path = resolve_path(relative_or_abs)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{relative_or_abs}")
    if path.suffix.lower() not in READABLE_EXTENSIONS:
        raise ValueError(f"暂不支持的文件类型：{path.suffix}")

    started = time.perf_counter()
    size_bytes = path.stat().st_size
    suffix = path.suffix.lower()
    warnings: list[str] = []

    if suffix in {".xlsx", ".xls"}:
        encoding = "excel"
        delimiter = ""
        frame = pd.read_excel(path, nrows=preview_rows, dtype=str)
        has_header = True
        estimated_rows = None
        try:
            from openpyxl import load_workbook

            workbook = load_workbook(path, read_only=True)
            sheet = workbook.active
            estimated_rows = int(sheet.max_row or 0)
            workbook.close()
        except Exception:  # noqa: BLE001
            warnings.append("Excel 行数读取失败，仅按预览行展示")
        columns = [str(column) for column in frame.columns]
        preview = frame.head(10).astype(str).to_dict(orient="records")
    else:
        text, detected_encoding = read_head_text(path)
        encoding = encoding or detected_encoding
        detected_delimiter = "\t" if suffix == ".tsv" else _detect_delimiter(text)
        delimiter = delimiter or detected_delimiter
        detected_header, _ = _guess_header(text, delimiter)
        if has_header is None:
            has_header = detected_header
        estimated_rows = _count_lines(path)
        frame = _read_preview_frame(path, encoding, delimiter, has_header, preview_rows)
        frame.columns = [str(column) for column in frame.columns]
        columns = [str(column) for column in frame.columns]
        preview = frame.head(10).astype(str).to_dict(orient="records")
        if has_header is False:
            warnings.append("当前按“无表头”处理，列名为 0/1/2…，可在识别参数里修正")
        if estimated_rows and estimated_rows < 2:
            warnings.append("文件行数过少，请确认是否选择了正确的文件")

    column_profiles = _column_profile(frame)
    mapping = suggest_mapping(columns)
    warnings.extend(mapping.get("warnings") or [])

    return {
        "path": relative_path(path),
        "abs_path": str(path),
        "name": path.name,
        "suffix": suffix,
        "size_bytes": size_bytes,
        "size_mb": round(size_bytes / 1024 / 1024, 2),
        "encoding": encoding,
        "delimiter": delimiter,
        "delimiter_label": {"\t": "Tab", ",": "逗号", ";": "分号", "|": "竖线", "": "—"}.get(
            delimiter, delimiter
        ),
        "has_header": has_header,
        "estimated_rows": estimated_rows,
        "column_count": len(columns),
        "columns": columns,
        "column_profiles": column_profiles,
        "preview": preview,
        "dataset_hint": mapping.get("hint_key", "unknown"),
        "dataset_hint_text": mapping.get("hint_text", ""),
        "suggested_mapping": mapping,
        "warnings": warnings,
        "elapsed_s": round(time.perf_counter() - started, 2),
    }


# ---------------------------------------------------------------------------
# 清洗
# ---------------------------------------------------------------------------
@dataclass
class CleanOptions:
    time_mode: str = "auto"  # auto / datetime / epoch_s / epoch_ms / step_hours
    time_base: str = "2017-01-01T00:00:00"
    drop_self_transfer: bool = True
    drop_duplicates: bool = True
    row_limit: int = 100_000  # 0 表示全部
    sample_mode: str = "head"  # head=前 N 行；uniform=均匀抽样（跨全时段）
    time_start: str = ""
    time_end: str = ""
    output_name: str = ""

    def to_dict(self) -> dict:
        return {
            "time_mode": self.time_mode,
            "time_base": self.time_base,
            "drop_self_transfer": self.drop_self_transfer,
            "drop_duplicates": self.drop_duplicates,
            "row_limit": self.row_limit,
            "sample_mode": self.sample_mode,
            "time_start": self.time_start,
            "time_end": self.time_end,
            "output_name": self.output_name,
        }


def _parse_amounts(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    negative = text.str.match(r"^\(.*\)$").fillna(False)
    cleaned = text.str.replace(r"[^\d.\-]", "", regex=True)
    values = pd.to_numeric(cleaned, errors="coerce")
    return values.where(~negative, -values.abs())


def _to_datetime_lenient(text: pd.Series) -> pd.Series:
    """兼容多种日期写法：2025/01/02 13:05、2025-01-02 13:05:00、2025年1月2日 等。"""
    for kwargs in (
        {"format": "mixed"},
        {},
    ):
        try:
            parsed = pd.to_datetime(text, errors="coerce", **kwargs)
        except (TypeError, ValueError):
            continue
        if parsed.notna().mean() >= 0.5:
            return parsed
    # 斜杠/中文日期替换后再试一次
    normalized = (
        text.str.replace("/", "-", regex=False)
        .str.replace("年", "-", regex=False)
        .str.replace("月", "-", regex=False)
        .str.replace("日", " ", regex=False)
        .str.strip()
    )
    try:
        return pd.to_datetime(normalized, errors="coerce", format="mixed")
    except (TypeError, ValueError):
        return pd.to_datetime(normalized, errors="coerce")


def _parse_times(series: pd.Series, mode: str, base: str) -> pd.Series:
    text = series.astype(str).str.strip()
    if mode == "epoch_s":
        return pd.to_datetime(pd.to_numeric(text, errors="coerce"), unit="s", errors="coerce")
    if mode == "epoch_ms":
        return pd.to_datetime(pd.to_numeric(text, errors="coerce"), unit="ms", errors="coerce")
    if mode == "step_hours":
        base_time = pd.Timestamp(base)
        return base_time + pd.to_timedelta(pd.to_numeric(text, errors="coerce"), unit="h")
    if mode == "datetime":
        return _to_datetime_lenient(text)

    # auto：先按字符串日期，失败再按数值猜测
    parsed = _to_datetime_lenient(text)
    if parsed.notna().mean() >= 0.5:
        return parsed
    numeric = pd.to_numeric(text, errors="coerce")
    if numeric.notna().mean() >= 0.5:
        median = float(numeric.dropna().median()) if numeric.notna().any() else 0.0
        if median > 1e12:
            return pd.to_datetime(numeric, unit="ms", errors="coerce")
        if median > 1e8:
            return pd.to_datetime(numeric, unit="s", errors="coerce")
        base_time = pd.Timestamp(base)
        return base_time + pd.to_timedelta(numeric, unit="h")
    return parsed


def _join_columns(frame: pd.DataFrame, columns: list[str], separator: str) -> pd.Series:
    if not columns:
        return pd.Series([""] * len(frame), index=frame.index)
    parts = [frame[column].astype(str).str.strip() for column in columns if column in frame.columns]
    if not parts:
        return pd.Series([""] * len(frame), index=frame.index)
    if len(parts) == 1:
        return parts[0]
    result = parts[0]
    for part in parts[1:]:
        result = result.str.cat(part, sep=separator)
    return result


def _require_columns(frame: pd.DataFrame, columns: list[str]) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise ValueError(f"映射的列在文件中不存在：{missing}")


def _clean_frame(
    frame: pd.DataFrame,
    mapping: dict,
    options: CleanOptions,
    counters: dict,
) -> pd.DataFrame:
    """对一块数据执行映射 + 解析 + 过滤，返回统一流水。"""
    time_columns = mapping.get("time_columns") or []
    amount_columns = mapping.get("amount_columns") or []
    from_columns = mapping.get("from_columns") or []
    to_columns = mapping.get("to_columns") or []
    summary_columns = mapping.get("summary_columns") or []
    if not time_columns:
        raise ValueError("未指定时间列")
    if not amount_columns:
        raise ValueError("未指定金额列")
    if not from_columns or not to_columns:
        raise ValueError("未指定付款账号列 / 收款账号列")

    _require_columns(frame, time_columns + amount_columns + from_columns + to_columns)

    counters["read_rows"] += len(frame)
    trade_time = _parse_times(frame[time_columns[0]], options.time_mode, options.time_base)
    amount = _parse_amounts(frame[amount_columns[0]])
    from_account = _join_columns(frame, from_columns, mapping.get("from_separator") or "")
    to_account = _join_columns(frame, to_columns, mapping.get("to_separator") or "")
    if summary_columns:
        summary = _join_columns(frame, summary_columns[:1], "")
    else:
        summary = pd.Series(["转账"] * len(frame), index=frame.index)

    valid = pd.Series([True] * len(frame), index=frame.index)
    bad_time = trade_time.isna()
    bad_amount = amount.isna()
    bad_account = (
        from_account.str.strip().isin(["", "nan", "none", "null", "NaN"])
        | to_account.str.strip().isin(["", "nan", "none", "null", "NaN"])
    )
    counters["dropped_time"] += int(bad_time.sum())
    counters["dropped_amount"] += int(bad_amount.sum())
    counters["dropped_account"] += int(bad_account.sum())
    valid &= ~bad_time & ~bad_amount & ~bad_account
    if options.drop_self_transfer:
        self_transfer = from_account.str.strip() == to_account.str.strip()
        counters["dropped_self_transfer"] += int((self_transfer & valid).sum())
        valid &= ~self_transfer

    if options.time_start or options.time_end:
        try:
            start = pd.Timestamp(options.time_start) if options.time_start else None
            end = pd.Timestamp(options.time_end) if options.time_end else None
        except ValueError as exc:
            raise ValueError(f"时间过滤条件格式不对：{exc}") from exc
        in_range = pd.Series([True] * len(frame), index=frame.index)
        if start is not None:
            in_range &= trade_time >= start
        if end is not None:
            in_range &= trade_time <= end
        counters["dropped_time_range"] += int((~in_range & valid).sum())
        valid &= in_range

    cleaned = pd.DataFrame(
        {
            "交易时间": trade_time[valid].dt.strftime("%Y-%m-%dT%H:%M:%S"),
            "金额": amount[valid].round(2),
            "付款账号": from_account[valid].str.strip(),
            "收款账号": to_account[valid].str.strip(),
            "摘要": summary[valid].astype(str).str.strip().replace("", "转账"),
        }
    )
    if options.drop_duplicates and not cleaned.empty:
        before = len(cleaned)
        cleaned = cleaned.drop_duplicates(subset=OUTPUT_COLUMNS, keep="first")
        counters["dropped_duplicates"] += before - len(cleaned)
    counters["valid_rows"] += len(cleaned)
    return cleaned.reset_index(drop=True)


def _frame_reader(path: Path, profile: dict):
    """按文件类型返回分块迭代器（每块是 DataFrame，列名统一）。"""
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(path, dtype=str)
        yield 0, frame
        return
    header_arg = 0 if profile.get("has_header", True) else None
    reader = pd.read_csv(
        path,
        sep=profile.get("delimiter") or ",",
        encoding=profile.get("encoding") or "utf-8",
        header=header_arg,
        dtype=str,
        keep_default_na=False,
        chunksize=CHUNK_SIZE,
        on_bad_lines="skip",
    )
    if header_arg is None:
        columns = profile.get("columns") or []
        for index, chunk in enumerate(reader):
            if len(columns) == chunk.shape[1]:
                chunk.columns = columns
            yield index, chunk
    else:
        for index, chunk in enumerate(reader):
            yield index, chunk


def _stats_payload(
    path: Path,
    profile: dict,
    mapping: dict,
    options: CleanOptions,
    counters: dict,
    output_path: Path,
    started: float,
    preview: list[dict],
    time_min: str,
    time_max: str,
    amount_sum: float,
    amount_min: float,
    amount_max: float,
    accounts: set[str],
) -> dict:
    return {
        "source": relative_path(path),
        "source_name": path.name,
        "source_size_mb": profile.get("size_mb"),
        "generated_at": _now(),
        "elapsed_s": round(time.perf_counter() - started, 1),
        "encoding": profile.get("encoding"),
        "delimiter": profile.get("delimiter"),
        "has_header": profile.get("has_header"),
        "dataset_hint": profile.get("dataset_hint"),
        "mapping": mapping,
        "options": options.to_dict(),
        "counters": counters,
        "output": relative_path(output_path),
        "time_min": time_min,
        "time_max": time_max,
        "amount_sum": round(amount_sum, 2),
        "amount_min": round(amount_min, 2) if amount_min != float("inf") else None,
        "amount_max": round(amount_max, 2) if amount_max != float("-inf") else None,
        "unique_accounts": len(accounts),
        "preview": preview,
        "note": "标签字段（Is Laundering / isFraud 等）未进入输出；原始文件只读，输出独立保存",
    }


def clean_file(
    relative_or_abs: str,
    profile: dict,
    mapping: dict,
    options: CleanOptions,
    progress_callback: Callable[[float, str], None] | None = None,
) -> dict:
    """流式清洗一个大文件，写出统一流水 + 清洗报告，返回 stats。"""
    path = resolve_path(relative_or_abs)
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{relative_or_abs}")
    ensure_cleaned_dir()
    started = time.perf_counter()

    base_name = options.output_name.strip() or f"{path.stem}_clean"
    safe_name = re.sub(r"[^\w\u4e00-\u9fff\-]+", "_", base_name).strip("_") or "cleaned"
    output_path = CLEANED_DIR / f"{safe_name}.csv"
    stats_path = CLEANED_DIR / f"{safe_name}_stats.json"

    counters = {
        "read_rows": 0,
        "valid_rows": 0,
        "written_rows": 0,
        "dropped_time": 0,
        "dropped_amount": 0,
        "dropped_account": 0,
        "dropped_self_transfer": 0,
        "dropped_duplicates": 0,
        "dropped_time_range": 0,
        "limited": 0,
        "sampled_by_stride": 0,
        "chunks": 0,
    }
    accounts: set[str] = set()
    preview: list[dict] = []
    time_min = None
    time_max = None
    amount_sum = 0.0
    amount_min = float("inf")
    amount_max = float("-inf")
    written = 0
    header_written = False
    limit = int(options.row_limit or 0)
    stride = 1
    if limit and options.sample_mode == "uniform":
        estimated = int(profile.get("estimated_rows") or 0)
        stride = max(1, estimated // max(1, limit))

    with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
        for chunk_index, frame in _frame_reader(path, profile):
            counters["chunks"] += 1
            cleaned = _clean_frame(frame, mapping, options, counters)
            if cleaned.empty:
                continue
            if stride > 1:
                before = len(cleaned)
                cleaned = cleaned.iloc[::stride].reset_index(drop=True)
                counters["sampled_by_stride"] = counters.get("sampled_by_stride", 0) + (before - len(cleaned))
            if limit and written + len(cleaned) > limit:
                take = max(0, limit - written)
                counters["limited"] += len(cleaned) - take
                cleaned = cleaned.iloc[:take]
            if cleaned.empty:
                if limit and written >= limit:
                    break
                continue

            times = pd.to_datetime(cleaned["交易时间"], errors="coerce")
            chunk_time_min = times.min()
            chunk_time_max = times.max()
            if pd.notna(chunk_time_min) and (time_min is None or chunk_time_min < time_min):
                time_min = chunk_time_min
            if pd.notna(chunk_time_max) and (time_max is None or chunk_time_max > time_max):
                time_max = chunk_time_max
            amount_series = cleaned["金额"].astype(float)
            amount_sum += float(amount_series.sum())
            amount_min = min(amount_min, float(amount_series.min()))
            amount_max = max(amount_max, float(amount_series.max()))
            accounts.update(cleaned["付款账号"].astype(str).tolist())
            accounts.update(cleaned["收款账号"].astype(str).tolist())
            if not preview:
                preview = cleaned.head(10).astype(str).to_dict(orient="records")

            cleaned.to_csv(handle, index=False, header=not header_written, lineterminator="\n")
            header_written = True
            written += len(cleaned)
            counters["written_rows"] = written

            if progress_callback is not None:
                if limit:
                    fraction = min(0.99, written / max(1, limit))
                else:
                    total = profile.get("estimated_rows") or 0
                    fraction = min(0.99, counters["read_rows"] / total) if total else 0.5
                progress_callback(fraction, f"已读取 {counters['read_rows']:,} 行 / 已写出 {written:,} 行")
            if limit and written >= limit:
                break

    stats = _stats_payload(
        path,
        profile,
        mapping,
        options,
        counters,
        output_path,
        started,
        preview,
        time_min.strftime("%Y-%m-%dT%H:%M:%S") if time_min is not None else "",
        time_max.strftime("%Y-%m-%dT%H:%M:%S") if time_max is not None else "",
        amount_sum,
        amount_min,
        amount_max,
        accounts,
    )
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")
    stats["stats_file"] = relative_path(stats_path)
    return stats


def preview_clean(
    relative_or_abs: str,
    profile: dict,
    mapping: dict,
    options: CleanOptions,
    limit: int = 200,
) -> dict:
    """只清洗前若干行，用于映射校验（不写文件）。"""
    path = resolve_path(relative_or_abs)
    suffix = path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        frame = pd.read_excel(path, nrows=limit, dtype=str)
    else:
        header_arg = 0 if profile.get("has_header", True) else None
        frame = pd.read_csv(
            path,
            sep=profile.get("delimiter") or ",",
            encoding=profile.get("encoding") or "utf-8",
            header=header_arg,
            nrows=limit,
            dtype=str,
            keep_default_na=False,
            on_bad_lines="skip",
        )
        if header_arg is None:
            columns = profile.get("columns") or []
            if len(columns) == frame.shape[1]:
                frame.columns = columns
    counters = {
        "read_rows": 0,
        "valid_rows": 0,
        "dropped_time": 0,
        "dropped_amount": 0,
        "dropped_account": 0,
        "dropped_self_transfer": 0,
        "dropped_duplicates": 0,
        "dropped_time_range": 0,
    }
    cleaned = _clean_frame(frame, mapping, options, counters)
    return {
        "preview": cleaned.head(50).astype(str).to_dict(orient="records"),
        "counters": counters,
        "columns": OUTPUT_COLUMNS,
    }


# ---------------------------------------------------------------------------
# 已清洗数据集索引 / pandas 分析
# ---------------------------------------------------------------------------
def cleaned_datasets() -> list[dict]:
    """列出 data/cleaned 下已清洗数据集（读 stats 报告）。"""
    if not CLEANED_DIR.exists():
        return []
    items = []
    for stats_path in sorted(CLEANED_DIR.glob("*_stats.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            stats = json.loads(stats_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        csv_path = CLEANED_DIR / f"{stats_path.stem[:-6]}.csv" if stats_path.stem.endswith("_stats") else None
        if csv_path is None or not csv_path.exists():
            output = stats.get("output")
            csv_path = resolve_path(output) if output else None
        items.append(
            {
                "name": stats_path.stem.replace("_stats", ""),
                "stats_path": str(stats_path),
                "csv_path": relative_path(csv_path) if csv_path and csv_path.exists() else "",
                "source": stats.get("source", ""),
                "generated_at": stats.get("generated_at", ""),
                "rows": (stats.get("counters") or {}).get("written_rows", 0),
                "unique_accounts": stats.get("unique_accounts", 0),
                "time_min": stats.get("time_min", ""),
                "time_max": stats.get("time_max", ""),
                "stats": stats,
            }
        )
    return items


def analyze_frame(frame: pd.DataFrame) -> dict:
    """pandas 快速画像：缺失、金额分布、时间趋势、Top 账户。"""
    if frame.empty:
        return {"empty": True}
    amount = pd.to_numeric(frame.get("金额"), errors="coerce")
    times = pd.to_datetime(frame.get("交易时间"), errors="coerce")
    accounts_out = frame.get("付款账号", pd.Series(dtype=str)).astype(str).value_counts().head(10)
    accounts_in = frame.get("收款账号", pd.Series(dtype=str)).astype(str).value_counts().head(10)
    by_day = (
        times.dt.strftime("%Y-%m-%d").value_counts().sort_index().head(60)
        if times.notna().any()
        else pd.Series(dtype=int)
    )
    summary = frame.get("摘要", pd.Series(dtype=str)).astype(str).value_counts().head(10)
    return {
        "empty": False,
        "rows": len(frame),
        "amount": {
            "min": round(float(amount.min()), 2) if amount.notna().any() else None,
            "max": round(float(amount.max()), 2) if amount.notna().any() else None,
            "mean": round(float(amount.mean()), 2) if amount.notna().any() else None,
            "sum": round(float(amount.sum()), 2) if amount.notna().any() else None,
        },
        "missing": {str(column): int(frame[column].isna().sum()) for column in frame.columns},
        "top_payers": {str(key): int(value) for key, value in accounts_out.items()},
        "top_payees": {str(key): int(value) for key, value in accounts_in.items()},
        "by_day": {str(key): int(value) for key, value in by_day.items()},
        "by_summary": {str(key): int(value) for key, value in summary.items()},
    }


def run_pandas_expression(frame: pd.DataFrame, expression: str):
    """受限 pandas 表达式执行（只给 df / pd，禁用内置函数），用于平台分析台。"""
    text = (expression or "").strip()
    if not text:
        raise ValueError("表达式为空")
    if len(text) > 500:
        raise ValueError("表达式过长（≤500 字符）")
    forbidden = ["import", "__", "open(", "exec(", "eval(", "os.", "sys.", "subprocess", "rmtree"]
    lowered = text.lower()
    for word in forbidden:
        if word in lowered:
            raise ValueError(f"表达式包含不允许的内容：{word}")
    allowed = {"df": frame, "pd": pd}
    try:
        result = eval(text, {"__builtins__": {}}, allowed)  # noqa: S307 - 本地演示沙箱
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"表达式执行失败：{type(exc).__name__}: {exc}") from exc
    return result
