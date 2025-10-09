# src/mon_projet/plumber_step3_generic.py
"""
plumber_step2_generic.py – pdfplumber + profils JSON
Supporte : ESL, Linear, Linden, Prof-Elec
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pdfplumber

# Chemins
# PDF_PATH = Path("src/mon_projet/assets/pdfs/2_ESL_48931.pdf")
# PDF_PATH = Path("src/mon_projet/assets/pdfs/3_LINEAR_42939.pdf")
# PDF_PATH = Path("src/mon_projet/assets/pdfs/4_LINDEN_INV2251027.pdf")
PDF_PATH = Path("src/mon_projet/assets/pdfs/6_PROF ELEC_PL#41806_SCHENJKER TLL1700993.pdf")

CONFIG_PATH = Path("src/mon_projet/assets/json/config_fournisseurs.json")
PAGES = "all"
DEBUG = True


def _norm_line(s: str) -> str:
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _parse_pages_spec(pages: str | int | None, total_pages: int) -> list[int]:
    if pages is None or str(pages).lower() == "all":
        return list(range(total_pages))
    if isinstance(pages, int):
        return [max(0, min(pages - 1, total_pages - 1))]
    return list(range(total_pages))


def _read_pdf_lines(pdf_path: Path, pages: str | int | None = "all") -> dict[str, Any]:
    out = {"page_count": 0, "pages_parsed": [], "lines": []}
    with pdfplumber.open(str(pdf_path)) as pdf:
        out["page_count"] = len(pdf.pages)
        idxs = _parse_pages_spec(pages, len(pdf.pages))
        out["pages_parsed"] = idxs
        for i in idxs:
            txt = pdf.pages[i].extract_text() or ""
            for line in txt.splitlines():
                line = line.strip()
                if line:
                    out["lines"].append(line)
    return out


def _load_config(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _detect_supplier(lines: list[str], config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    suppliers = config.get("suppliers", {})
    joined = "\n".join(lines)

    if DEBUG:
        print(f"[DBG] suppliers in config = {list(suppliers.keys())}")

    for name, prof in suppliers.items():
        detect = prof.get("detect", {})
        tokens = detect.get("must_contain_any", [])
        if tokens and any(tok in joined for tok in tokens):
            return name, prof
    return "unknown", {}


def _to_int_safe(v: Any) -> int:
    try:
        s = str(v).strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
        if s.count(".") > 1:
            s = s.replace(".", "")
        return int(float(s))
    except Exception:
        return 0


def _extract_block_lines(lines: list[str], start_re: str, stop_re: str | None) -> list[str]:
    start_p = re.compile(start_re, flags=re.IGNORECASE)
    stop_p = re.compile(stop_re, flags=re.IGNORECASE) if stop_re else None

    start_idx = None
    for i, ln in enumerate(lines):
        if start_p.search(_norm_line(ln)):
            start_idx = i + 1
            break
    if start_idx is None:
        return []

    end_idx = len(lines)
    if stop_p:
        for j in range(start_idx, len(lines)):
            if stop_p.search(_norm_line(lines[j])):
                end_idx = j
                break

    block = lines[start_idx:end_idx]
    if stop_p:
        block = [ln for ln in block if not stop_p.search(_norm_line(ln))]

    return block


def _extract_multi_blocks(lines: list[str], header_regex: str, item_regex: str) -> list[dict]:
    """Pour Linear : blocs avec header + items sur une ligne."""
    header_re = re.compile(header_regex)
    item_re = re.compile(item_regex)

    blocks = []
    current = None

    for raw in lines:
        ln = _norm_line(raw)

        m_hdr = header_re.search(ln)
        if m_hdr:
            if current:
                blocks.append(current)
            current = {"header": m_hdr.groupdict(), "items": []}
            continue

        if current:
            m_it = item_re.match(ln)
            if m_it:
                current["items"].append(m_it.groupdict())

    if current:
        blocks.append(current)

    return blocks


def _parse_multiline_items(
    lines: list[str],
    multiline_cfg: dict,
    header_regex: str | None,
) -> tuple[list[dict], list[dict]]:
    """Pour Linden/Prof-Elec : items multi-lignes."""

    if DEBUG:
        print(f"[DBG] 🔵 _parse_multiline_items START: {len(lines)} lines")

    start_rx = multiline_cfg.get("start_regex")
    desc_rx = multiline_cfg.get("desc_regex")
    max_follow = multiline_cfg.get("max_follow_lines", 5)
    code_group = multiline_cfg.get("code_group", "item")
    qty_group = multiline_cfg.get("qty_group", "qty")
    desc_group = multiline_cfg.get("desc_group", "desc")

    if not start_rx:
        if DEBUG:
            print("[DBG] No start_regex, returning empty")
        return [], []

    start_pat = re.compile(start_rx)
    desc_pat = re.compile(desc_rx) if desc_rx else None
    header_pat = re.compile(header_regex) if header_regex else None

    item_positions = []
    order_positions = []

    for i, ln in enumerate(lines):
        norm_ln = _norm_line(ln)

        m_start = start_pat.match(norm_ln)
        if m_start:
            item_positions.append((i, m_start.groupdict()))

        if header_pat:
            m_hdr = header_pat.search(norm_ln)
            if m_hdr:
                order_no = next((v for v in m_hdr.groupdict().values() if v), None)
                order_positions.append((i, order_no))

    if DEBUG:
        print(f"[DBG] Found {len(item_positions)} items, {len(order_positions)} headers")

    def find_closest_order(item_idx: int) -> str | None:
        for order_idx, order_no in order_positions:
            if item_idx < order_idx <= item_idx + 10:
                return order_no
        for order_idx, order_no in reversed(order_positions):
            if order_idx < item_idx:
                return order_no
        return None

    items = []
    for item_idx, item_data in item_positions:
        item_code = item_data.get(code_group)
        qty = item_data.get(qty_group)
        order_no = find_closest_order(item_idx)

        description = None

        description_inline = item_data.get("description_inline")
        if description_inline:
            description = description_inline
        elif max_follow > 0:
            for j in range(1, max_follow + 1):
                if item_idx + j >= len(lines):
                    break
                next_ln = _norm_line(lines[item_idx + j])

                if start_pat.match(next_ln):
                    break
                if next_ln.startswith("Subtotal"):
                    break

                if desc_pat:
                    m_desc = desc_pat.match(next_ln)
                    if m_desc and not description:
                        desc_text = m_desc.groupdict().get(desc_group, "").strip()
                        if not desc_text.startswith("Subtotal"):
                            description = desc_text
                            break

        items.append(
            {
                "item_code": item_code,
                "qty": qty,
                "description": description,
                "your_order": order_no,
            }
        )

    if DEBUG:
        print(f"[DBG] 🟢 _parse_multiline_items END: {len(items)} items")
    return items, []


def _get_nested_value(data: dict, path: str) -> Any:
    if not path:
        return None
    keys = path.split(".")
    value = data
    for key in keys:
        if isinstance(value, dict):
            value = value.get(key)
        else:
            return None
    return value


def display_extraction_summary(supplier: str, items: list, orders: list, config: dict):
    profile = config["suppliers"].get(supplier, {})
    field_mapping = profile.get("field_mapping", {})
    standard_labels = config.get("standard_fields", {})

    print(f"\n{'='*80}")
    print(f"RÉSUMÉ - {supplier}")
    print(f"{'='*80}\n")

    if orders:
        for order in orders[:3]:
            header = order.get("header", {})
            order_num = _get_nested_value(header, field_mapping.get("order_number", "").replace("header.", ""))
            print(f"--- Commande {order_num or 'N/A'} ---\n")

            for i, item in enumerate(order.get("items", [])[:3], 1):
                print(f"Item {i}:")
                for std_field, src_field in field_mapping.items():
                    if src_field.startswith("header."):
                        value = _get_nested_value(header, src_field.replace("header.", ""))
                    else:
                        value = _get_nested_value(item, src_field)
                    label = standard_labels.get(std_field, std_field)
                    print(f"  {label:20s}: {value if value else '❌'}")
                print()
    else:
        for i, item in enumerate(items[:5], 1):
            print(f"Item {i}:")
            for std_field, src_field in field_mapping.items():
                value = _get_nested_value(item, src_field)
                label = standard_labels.get(std_field, std_field)
                print(f"  {label:20s}: {value if value else '❌'}")
            print()

    total = len(items) if not orders else sum(len(o.get("items", [])) for o in orders)
    if total > 5:
        print(f"... et {total - 5} autres items\n")
    print(f"TOTAL: {total} items\n")


def main():
    read = _read_pdf_lines(PDF_PATH, PAGES)

    print("---- TEXTE PDF (début) ----")
    print("\n".join(read["lines"][:30]))
    print("---- FIN EXTRAIT ----")

    cfg = _load_config(CONFIG_PATH)

    if DEBUG:
        print(f"[DBG] PDF_PATH = {PDF_PATH.resolve()}")
        print(f"[DBG] CONFIG_PATH = {CONFIG_PATH.resolve()}")

    supplier, profile = _detect_supplier(read["lines"], cfg)
    if DEBUG:
        print(f"[DBG] supplier chosen = {supplier}")

    if not profile:
        print(json.dumps({"supplier": "unknown", "items": []}, indent=2))
        return

    block_cfg = profile.get("block", {})
    start_re = block_cfg.get("start_line_regex")
    stop_re = block_cfg.get("stop_line_regex")
    line_re = profile.get("item_regex")
    header_re = profile.get("header_regex")
    multi = bool(profile.get("multi_blocks"))
    multiline_cfg = profile.get("multiline_item")

    items = []
    orders = []

    # MODE 1: Multi-blocs avec items sur une ligne (Linear)
    if multi and header_re and line_re:
        if DEBUG:
            print("[DBG] Mode: Linear (multi_blocks + item_regex)")
        blocks = _extract_multi_blocks(read["lines"], header_re, line_re)
        for b in blocks:
            for it in b["items"]:
                for k in profile.get("post", {}).get("int_fields", []):
                    if k in it:
                        it[k] = _to_int_safe(it[k])
            orders.append({"header": b["header"], "items": b["items"]})
            items.extend(b["items"])

    # MODE 2: Multiline (Linden/Prof-Elec)
    elif multiline_cfg:
        if DEBUG:
            print("[DBG] Mode: Linden/Prof-Elec (multiline)")
        lines_to_parse = read["lines"] if multi else []
        if not multi and start_re:
            lines_to_parse = _extract_block_lines(read["lines"], start_re, stop_re)

        if lines_to_parse:
            items, _ = _parse_multiline_items(lines_to_parse, multiline_cfg, header_re)

            for it in items:
                for k in profile.get("post", {}).get("float_fields", []):
                    if k in it and it[k]:
                        v = str(it[k]).replace(".", "").replace(",", ".")
                        try:
                            it[k] = float(v)
                        except Exception:
                            it[k] = 0.0

    # MODE 3: Bloc unique avec items sur une ligne (ESL)
    else:
        if DEBUG:
            print("[DBG] Mode: ESL (single block)")
        if start_re and line_re:
            block_lines = _extract_block_lines(read["lines"], start_re, stop_re)
            pat = re.compile(line_re)
            for ln in block_lines:
                m = pat.match(_norm_line(ln))
                if m:
                    it = m.groupdict()
                    for k in profile.get("post", {}).get("int_fields", []):
                        if k in it:
                            it[k] = _to_int_safe(it[k])
                    items.append(it)

    display_extraction_summary(supplier, items, orders, cfg)

    out = json.dumps(
        {"supplier": supplier, "items": items, "orders": orders if orders else None},
        ensure_ascii=False,
        indent=2,
    )
    print(out)


if __name__ == "__main__":
    main()
