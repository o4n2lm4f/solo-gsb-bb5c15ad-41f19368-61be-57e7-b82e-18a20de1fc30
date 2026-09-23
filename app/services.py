"""业务服务：CSV 解析、标准库装载、匹配调用。"""
from __future__ import annotations

import csv
import io

from . import database
from .matching import StandardRecord, match_address
from .normalize import normalize_address

# CSV 表头别名（英文标准命名 + 常见中文命名）
FIELD_ALIASES: dict[str, set[str]] = {
    "id": {"id", "std_id", "address_id", "编号", "标准编号", "id编号"},
    "address": {"address", "street", "std_address", "standard_address",
                "full_address", "标准地址", "地址", "完整地址", "街道"},
    "city": {"city", "town", "城市", "市"},
    "state": {"state", "province", "region", "州", "省", "省州"},
    "postcode": {"postcode", "zip", "zipcode", "zip_code", "postal_code",
                 "邮编", "邮政编码"},
}


def _resolve_headers(fieldnames: list[str]) -> dict[str, str]:
    """把实际表头映射到 {规范字段: 实际列名}。"""
    alias_to_canonical: dict[str, str] = {}
    for canon, aliases in FIELD_ALIASES.items():
        for a in aliases:
            alias_to_canonical[a.strip().lower()] = canon
    mapping: dict[str, str] = {}
    for name in fieldnames or []:
        key = (name or "").strip().lower()
        canon = alias_to_canonical.get(key)
        if canon and canon not in mapping:
            mapping[canon] = name
    return mapping


def parse_csv(content: bytes, external: bool = False) -> list[dict]:
    """解析地址 CSV。

    标准地址表必须包含地址列和编号列（编号缺失时用行号自动生成）；
    外部地址表只需地址列，source_id 缺失时用行号。
    """
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    header_map = _resolve_headers(reader.fieldnames or [])
    if "address" not in header_map:
        raise ValueError(
            "未找到地址列。表头需包含 address / street / 标准地址 / 地址 之一，"
            f"实际表头：{reader.fieldnames}"
        )

    rows: list[dict] = []
    for line_no, row in enumerate(reader, start=2):
        address = (row.get(header_map["address"]) or "").strip()
        if not address:
            continue
        rid_col = header_map.get("id")
        rid = (row.get(rid_col) or "").strip() if rid_col else ""
        if not rid:
            rid = f"ROW-{line_no}"
        rows.append({
            "id": rid,
            "address": address,
            "city": (row.get(header_map["city"], "") or "").strip() if "city" in header_map else "",
            "state": (row.get(header_map["state"], "") or "").strip() if "state" in header_map else "",
            "postcode": (row.get(header_map["postcode"], "") or "").strip() if "postcode" in header_map else "",
        })
    if not rows:
        raise ValueError("CSV 中没有有效的地址行")
    return rows


def import_standards(rows: list[dict]) -> dict:
    """归一化并写入标准地址表（按 ext_id upsert）。"""
    imported, updated = 0, 0
    existed_before = database.count_standards()
    existing_ids: set[str] = set()
    if existed_before:
        with database.get_conn() as conn:
            existing_ids = {r["ext_id"] for r in
                            conn.execute("SELECT ext_id FROM standard_addresses").fetchall()}
    for row in rows:
        norm = _build_norm(row)
        is_new = row["id"] not in existing_ids
        database.upsert_standard(row["id"], row["address"], row["city"],
                                 row["state"], row["postcode"], norm)
        if is_new:
            imported += 1
        else:
            updated += 1
    return {"imported": imported, "updated": updated, "total": database.count_standards()}


def _build_norm(row: dict):
    """结构化字段拼入归一化文本：地址 + 城市 + 省州 + 邮编。"""
    parts = [row["address"], row.get("city", ""), row.get("state", ""), row.get("postcode", "")]
    return normalize_address(" ".join(p for p in parts if p))


def load_standards() -> list[StandardRecord]:
    """从 SQLite 全量装载标准库到内存（本地数据量下直接线性扫描）。"""
    import json as _json
    from .normalize import NormalizedAddress
    records: list[StandardRecord] = []
    with database.get_conn() as conn:
        for r in conn.execute("SELECT * FROM standard_addresses ORDER BY id"):
            norm = NormalizedAddress(
                raw=r["address"],
                text=r["norm_text"],
                tokens=_json.loads(r["tokens_json"]),
                house_number=r["house_number"],
            )
            records.append(StandardRecord(
                id=r["id"], ext_id=r["ext_id"], raw_text=r["address"],
                city=r["city"], state=r["state"], postcode=r["postcode"], norm=norm,
            ))
    return records


def run_match(raw_text: str, standards: list[StandardRecord] | None = None,
              fields: dict | None = None, persist: bool = True,
              source_id: str = "", **thresholds) -> dict:
    """对单条文本执行匹配，可选持久化。返回 API 响应体。"""
    fields = fields or {}
    norm = normalize_address(" ".join(p for p in
                                      [raw_text, fields.get("city", ""),
                                       fields.get("state", ""),
                                       fields.get("postcode", "")] if p))
    if standards is None:
        standards = load_standards()
    result = match_address(norm, standards, query_fields=fields, **thresholds)

    candidates = [c.to_dict() for c in result["candidates"]]
    best = result["best_candidate"].to_dict() if result["best_candidate"] else None
    body = {
        "input": raw_text,
        "normalized": norm.text,
        "tokens": norm.tokens,
        "house_number": norm.house_number,
        "status": result["status"],
        "reasons": result["reasons"],
        "best_candidate": best,
        "candidates": candidates,
    }
    if persist:
        body["id"] = database.save_result(
            source_id, raw_text, result["status"], result["reasons"],
            candidates, fields, norm.house_number)
    return body
