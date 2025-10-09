# src/mon_projet/plumber_step2_generic.py
"""
plumber_step2_generic.py – pdfplumber + profils JSON
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pdfplumber

# Chemins
# Chemins/paramètres (modifie ici si besoin)
PDF_PATH = Path("src/mon_projet/assets/pdfs/2_ESL_48931.pdf")
# PDF_PATH = Path("src/mon_projet/assets/pdfs/3_LINEAR_42939.pdf")
# PDF_PATH = Path("src/mon_projet/assets/pdfs/4_LINDEN_INV2251027.pdf")
# PDF_PATH = Path("src/mon_projet/assets/pdfs/6_PROF ELEC_PL#41806_SCHENJKER TLL1700993.pdf")
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

    print(f"[DBG] suppliers in config = {list(suppliers.keys())}")

    for name, prof in suppliers.items():
        detect = prof.get("detect", {})
        tokens = detect.get("must_contain_any", [])
        if tokens and any(tok in joined for tok in tokens):
            return name, prof
    return "unknown", {}


def _parse_multiline_items(
    lines: list[str],
    multiline_cfg: dict,
    header_regex: str | None,
) -> tuple[list[dict], list[dict]]:
    """Parse items en mode multi-lignes."""

    print(f"[DBG] 🔵 _parse_multiline_items START: {len(lines)} lines")

    start_rx = multiline_cfg.get("start_regex")
    desc_rx = multiline_cfg.get("desc_regex")
    max_follow = multiline_cfg.get("max_follow_lines", 5)
    code_group = multiline_cfg.get("code_group", "item")
    qty_group = multiline_cfg.get("qty_group", "qty")
    desc_group = multiline_cfg.get("desc_group", "desc")

    if not start_rx:
        print("[DBG] No start_regex, returning empty")
        return [], []

    start_pat = re.compile(start_rx)
    desc_pat = re.compile(desc_rx) if desc_rx else None
    header_pat = re.compile(header_regex) if header_regex else None

    # Trouver items et headers
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

    print(f"[DBG] Found {len(item_positions)} items, {len(order_positions)} headers")

    # Associer items aux headers
    def find_closest_order(item_idx: int) -> str | None:
        # Chercher APRÈS (fenêtre 10 lignes)
        for order_idx, order_no in order_positions:
            if item_idx < order_idx <= item_idx + 10:
                return order_no
        # Sinon AVANT
        for order_idx, order_no in reversed(order_positions):
            if order_idx < item_idx:
                return order_no
        return None

    # Parser items
    items = []
    for item_idx, item_data in item_positions:
        item_code = item_data.get(code_group)
        qty = item_data.get(qty_group)
        order_no = find_closest_order(item_idx)

        # Description
        description = None

        # Vérifier description inline (Prof-Elec format 2)
        description_inline = item_data.get("description_inline")
        if description_inline:
            description = description_inline
        elif max_follow > 0:
            # Chercher dans lignes suivantes
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

    print(f"[DBG] 🟢 _parse_multiline_items END: {len(items)} items")
    return items, []


def main():
    read = _read_pdf_lines(PDF_PATH, PAGES)

    print("---- TEXTE PDF (début) ----")
    print("\n".join(read["lines"][:30]))
    print("---- FIN EXTRAIT ----")

    cfg = _load_config(CONFIG_PATH)

    print(f"[DBG] PDF_PATH = {PDF_PATH.resolve()}")
    print(f"[DBG] CONFIG_PATH = {CONFIG_PATH.resolve()}")
    print(f"[DBG] pages_parsed = {read['pages_parsed']}, page_count = {read['page_count']}")

    supplier, profile = _detect_supplier(read["lines"], cfg)
    print(f"[DBG] supplier chosen = {supplier}")

    if not profile:
        print(json.dumps({"supplier": "unknown", "items": []}, indent=2))
        return

    # Config
    multiline_cfg = profile.get("multiline_item")
    header_re = profile.get("header_regex")
    multi = bool(profile.get("multi_blocks"))

    print(f"[DBG] multi_blocks={multi}")
    print(f"[DBG] has multiline_item? {bool(multiline_cfg)}")

    items = []

    if multiline_cfg and multi:
        print("[DBG] Mode: multiline + multi_blocks (Prof-Elec/Linden)")
        print(f"[DBG] Calling _parse_multiline_items with {len(read['lines'])} lines")

        try:
            items, _ = _parse_multiline_items(read["lines"], multiline_cfg, header_re)
            print(f"[DBG] ✅ Got {len(items)} items")
        except Exception as e:
            print(f"[DBG] ❌ ERROR: {e}")
            import traceback

            traceback.print_exc()

    # Post-traitement
    for it in items:
        for k in profile.get("post", {}).get("float_fields", []):
            if k in it and it[k]:
                v = str(it[k]).replace(".", "").replace(",", ".")
                try:
                    it[k] = float(v)
                except Exception:
                    it[k] = 0.0

    # Affichage
    print(f"\n{'='*80}")
    print(f"RÉSUMÉ - {supplier}")
    print(f"{'='*80}\n")

    for i, item in enumerate(items[:5], 1):
        print(f"Item {i}:")
        print(f"  Commande  : {item.get('your_order', '❌')}")
        print(f"  Code      : {item.get('item_code', '❌')}")
        print(f"  Quantité  : {item.get('qty', '❌')}")
        print(f"  Description: {item.get('description', '❌')}\n")

    if len(items) > 5:
        print(f"... et {len(items) - 5} autres items\n")

    print(f"TOTAL: {len(items)} items\n")
    print(json.dumps({"supplier": supplier, "items": items}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
