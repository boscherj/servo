# src/mon_projet/plumber_step2_generic.py
"""
plumber_step2_generic.py — pdfplumber + profils JSON (aucun argument CLI)
- Lit un PDF
- Détecte le fournisseur via config_fournisseurs.json
- Isole le bloc "tableau" par regex start/stop
- Parse chaque ligne avec la regex du profil (groupes nommés)
- Affiche un JSON final (items + métadonnées simples)

Exécution :
  python -m mon_projet.plumber_step2_generic
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pdfplumber

# Chemins/paramètres (modifie ici si besoin)
# PDF_PATH = Path("src/mon_projet/assets/pdfs/2_ESL_48931.pdf")
# PDF_PATH = Path("src/mon_projet/assets/pdfs/3_LINEAR_42939.pdf")
# PDF_PATH = Path("src/mon_projet/assets/pdfs/4_LINDEN_INV2251027.pdf")
PDF_PATH = Path("src/mon_projet/assets/pdfs/6_PROF ELEC_PL#41806_SCHENJKER TLL1700993.pdf")


PAGES = "all"

CONFIG_PATH = Path("src/mon_projet/assets/json/config_fournisseurs.json")
DEBUG = True
DEBUG_1 = True


def _extract_multi_blocks(lines: list[str], header_re: str, item_re: str) -> list[dict]:
    header_pat = re.compile(header_re)
    item_pat = re.compile(item_re)

    # === DEBUG: rappels des regex utilisées
    print(f"[DBG] _extract_multi_blocks: header_re={header_re}")
    print(f"[DBG] _extract_multi_blocks: item_re={item_re}")

    blocks: list[dict] = []
    cur_header: dict[str, str] | None = None
    cur_items: list[dict] = []

    # === DEBUG: collecter où ça matche
    header_indices: list[int] = []
    item_indices: list[int] = []

    def flush():
        nonlocal cur_header, cur_items
        if cur_header is not None and cur_items:
            blocks.append({"header": cur_header, "items": cur_items})
        cur_header, cur_items = None, []

    # NOTE: on passe à enumerate(...) pour savoir sur quelle ligne on matche
    for idx, ln in enumerate(lines):
        s = _norm_line(ln)

        m_h = header_pat.search(s)
        if m_h:
            print(f"[DBG] HEADER hit @ {idx}: {s}")
            header_indices.append(idx)
            # nouveau bloc : vider l’ancien
            flush()
            cur_header = m_h.groupdict()
            continue

        if cur_header is not None:
            m_i = item_pat.match(s)
            if m_i:
                if len(item_indices) < 20:  # éviter le spam
                    print(f"[DBG] ITEM hit @ {idx}: {s}")
                item_indices.append(idx)
                cur_items.append(m_i.groupdict())

    # dernier bloc
    flush()

    # === DEBUG: récap utile
    print("[DBG] headers at lines:", header_indices)
    print("[DBG] first header lines:", [_norm_line(lines[i]) for i in header_indices[:5]])
    print("[DBG] item start lines:", item_indices[:10])
    print("[DBG] first item lines:", [_norm_line(lines[i]) for i in item_indices[:5]])

    return blocks


def _norm_line(s: str) -> str:
    # Remplace NBSP par espace, compacte les espaces, strip
    s = s.replace("\u00a0", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


# --- utils pages ---
def _parse_pages_spec(pages: str | int | None, total_pages: int) -> list[int]:
    if pages is None:
        return list(range(total_pages))
    if isinstance(pages, int):
        return [max(0, min(pages - 1, total_pages - 1))]
    spec = str(pages).strip().lower()
    if spec == "all":
        return list(range(total_pages))
    out: list[int] = []
    for chunk in spec.split(","):
        chunk = chunk.strip()
        if "-" in chunk:
            a, b = chunk.split("-", 1)
            if a.isdigit() and b.isdigit():
                start = max(1, int(a))
                end = max(1, int(b))
                if end < start:
                    start, end = end, start
                out.extend(list(range(start - 1, min(end, total_pages))))
        else:
            if chunk.isdigit():
                p = max(1, int(chunk))
                out.append(min(p - 1, total_pages - 1))
    return sorted(set([i for i in out if 0 <= i < total_pages]))


def _read_pdf_lines(pdf_path: Path, pages: str | int | None = "all") -> dict[str, Any]:
    out: dict[str, Any] = {"page_count": 0, "pages_parsed": [], "lines": []}
    with pdfplumber.open(str(pdf_path)) as pdf:
        out["page_count"] = len(pdf.pages)
        idxs = _parse_pages_spec(pages, len(pdf.pages))
        out["pages_parsed"] = idxs
        for i in idxs:
            page = pdf.pages[i]
            txt = page.extract_text() or ""
            for line in txt.splitlines():
                line = line.strip()
                if line:
                    out["lines"].append(line)
    return out


# --- config & détection fournisseur ---
def _load_config(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _detect_supplier(lines: list[str], config: dict[str, Any]) -> tuple[str, dict[str, Any]]:

    suppliers = config.get("suppliers") or {}
    joined = "\n".join(lines)

    if DEBUG_1:
        print(f"[DBG] suppliers in config = {list((config.get('suppliers') or {}).keys())}")
        print(
            f"[DBG] joined has 'Linear Supply Solutions (Europe) BV'? {'Linear Supply Solutions (Europe) BV' in joined}"
        )

    for name, prof in suppliers.items():
        detect = prof.get("detect") or {}
        tokens = detect.get("must_contain_any") or []
        if tokens and any(tok in joined for tok in tokens):
            return name, prof
    # fallback: premier profil si un seul
    if len(suppliers) == 1:
        name = next(iter(suppliers))
        return name, suppliers[name]
    return "unknown", {}


# --- extraction bloc & parsing lignes ---
def _extract_block_lines(lines: list[str], start_re: str, stop_re: str | None) -> list[str]:
    start_p = re.compile(start_re, flags=re.IGNORECASE)
    stop_p = re.compile(stop_re, flags=re.IGNORECASE) if stop_re else None

    start_idx = None
    for i, ln in enumerate(lines):
        if start_p.search(_norm_line(ln)):  # ← search (plus robuste que match)
            start_idx = i + 1  # commence APRÈS l’entête
            break
    if start_idx is None:
        return []

    end_idx = len(lines)
    if stop_p:
        for j in range(start_idx, len(lines)):
            if stop_p.search(_norm_line(lines[j])):  # ← search
                end_idx = j  # s’arrête AVANT la ligne stop
                break

    block = lines[start_idx:end_idx]

    # Barrière de sécurité: enlève toute ligne qui matche le stop, au cas où
    if stop_p:
        block = [ln for ln in block if not stop_p.search(_norm_line(ln))]

    return block

    block = lines[start_idx:end_idx]

    # Sécurité: même si le stop n'a pas été trouvé plus haut,
    # on retire toute ligne qui matche le stop (ex: "Page 1 of 1")
    if stop_p:
        block = [ln for ln in block if not stop_p.search(_norm_line(ln))]

    return block


def _to_int_safe(v: Any) -> int:
    try:
        s = str(v).strip().replace(" ", "").replace("\u00a0", "").replace(",", ".")
        if s.count(".") > 1:
            s = s.replace(".", "")
        return int(float(s))
    except Exception:
        return 0


def _extract_multi_blocks(lines: list[str], header_regex: str, item_regex: str) -> list[dict]:
    """Découpe le document en blocs à chaque en-tête (header_regex) et collecte
    les lignes item (item_regex) jusqu’au prochain en-tête ou fin de fichier.
    Renvoie: [{"header": {...}, "items": [ {...}, ... ]}, ...]
    """
    header_re = re.compile(header_regex)
    item_re = re.compile(item_regex)

    blocks: list[dict] = []
    current: dict | None = None

    for raw in lines:
        ln = _norm_line(raw)

        # Nouveau header ?
        m_hdr = header_re.search(ln)
        if m_hdr:
            # pousse le bloc courant si existant
            if current:
                blocks.append(current)
            current = {"header": m_hdr.groupdict(), "items": []}
            continue

        # Ligne d'item ?
        if current:
            m_it = item_re.match(ln)
            if m_it:
                current["items"].append(m_it.groupdict())

    if current:
        blocks.append(current)

    return blocks


def _get_nested_value(data: dict, path: str) -> Any:
    """Récupère une valeur dans un dict avec notation pointée (ex: 'header.commande_client')."""
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


def _display_item(index: int, item: dict, field_mapping: dict, standard_labels: dict, header: dict = None):
    """Affiche un item avec les champs standards."""
    print(f"\nItem {index}:")

    for standard_field, source_field in field_mapping.items():
        # Gérer les champs du header (pour Linear)
        if source_field.startswith("header.") and header:
            value = _get_nested_value(header, source_field.replace("header.", ""))
        else:
            value = _get_nested_value(item, source_field)

        # Indicateur visuel si manquant
        display_value = value if value is not None else "❌ MANQUANT"

        # Nom lisible du champ
        field_label = standard_labels.get(standard_field, standard_field)

        print(f"  {field_label:25s}: {display_value}")


def display_extraction_summary(supplier: str, items: list, orders: list, config: dict):
    """Affiche un résumé générique de l'extraction."""

    profile = config["suppliers"].get(supplier, {})
    field_mapping = profile.get("field_mapping", {})
    standard_labels = config.get("standard_fields", {})

    print("\n" + "=" * 80)
    print(f"RÉSUMÉ DE L'EXTRACTION - {supplier}")
    print("=" * 80)
    print("\nChamps essentiels extraits:")
    print("-" * 60)

    # Gérer le cas multi-blocs (Linear)
    if orders:
        for order in orders:
            header = order.get("header", {})
            order_num = _get_nested_value(header, field_mapping.get("order_number", "").replace("header.", ""))
            print(f"\n--- Commande {order_num or 'N/A'} ---")

            for i, item in enumerate(order.get("items", []), 1):
                _display_item(i, item, field_mapping, standard_labels, header)
                if i >= 5:
                    remaining = len(order.get("items", [])) - 5
                    if remaining > 0:
                        print(f"\n  ... et {remaining} autres items")
                    break

    # Cas simple (ESL, Linden)
    else:
        for i, item in enumerate(items, 1):
            _display_item(i, item, field_mapping, standard_labels)
            if i >= 5:
                remaining = len(items) - 5
                if remaining > 0:
                    print(f"\n  ... et {remaining} autres items")
                break

    total = len(items) if not orders else sum(len(o.get("items", [])) for o in orders)
    print("\n" + "=" * 80)
    print(f"TOTAL : {total} items extraits")
    print("=" * 80 + "\n")


def _parse_multiline_items(
    lines: list[str],
    multiline_cfg: dict,
    header_regex: str | None,
) -> tuple[list[dict], list[dict]]:
    """
    Parse les items en mode multi-lignes (pour Linden/Prof-Elec).
    Retourne: (items, orders)
    """

    print("[DBG] 🔵 _parse_multiline_items: DÉBUT")
    print(f"[DBG] lines count = {len(lines)}")
    print(f"[DBG] multiline_cfg = {multiline_cfg}")
    print(f"[DBG] header_regex = {header_regex}")

    start_rx = multiline_cfg.get("start_regex")
    desc_rx = multiline_cfg.get("desc_regex")
    max_follow = multiline_cfg.get("max_follow_lines", 5)
    code_group = multiline_cfg.get("code_group", "item")
    qty_group = multiline_cfg.get("qty_group", "qty")
    desc_group = multiline_cfg.get("desc_group", "desc")

    print("[DBG] ⬇️ _parse_multiline_items: entry")
    print(f"[DBG] cfg.start_rx={start_rx!r}")
    print(f"[DBG] cfg.desc_rx={desc_rx!r}")
    print(f"[DBG] cfg.header_regex={header_regex!r}")
    print(f"[DBG] cfg.groups: code_group={code_group}, qty_group={qty_group}, "
      f"desc_group={desc_group}, max_follow={max_follow}")
    )
    print(f"[DBG] incoming lines count = {len(lines)}")
    if lines:
        print(f"[DBG] sample lines[0:2] = {[lines[0], lines[1] if len(lines)>1 else '' ]}")

    if not start_rx:
        print("[DBG] _parse_multiline_items: start_regex manquant → sortie vide")
        return [], []

    start_pat = re.compile(start_rx)
    desc_pat = re.compile(desc_rx) if desc_rx else None
    header_pat = re.compile(header_regex) if header_regex else None

    # ÉTAPE 1 : Identifier positions items & headers
    print(f"[DBG] nombre total de lignes = {len(lines)}")
    item_positions: list[tuple[int, dict]] = []
    order_positions: list[tuple[int, str | None]] = []

    for i, ln in enumerate(lines):
        norm_ln = _norm_line(ln)
        if i < 5:
            print(f"[DBG] L{i}: {norm_ln}")

        # Détecter un item
        m_start = start_pat.match(norm_ln)
        if m_start:
            gd = m_start.groupdict()
            print(f"[DBG] ITEM start @L{i} → {gd} | ligne='{norm_ln}'")
            item_positions.append((i, gd))

        # Détecter un numéro de commande
        if header_pat:
            m_hdr = header_pat.search(norm_ln)
            if m_hdr:
                hdr_gd = m_hdr.groupdict()
                print(f"[DBG] HEADER @L{i} → {hdr_gd} | ligne='{norm_ln}'")
                # Prendre le premier champ non vide
                order_no = None
                for v in hdr_gd.values():
                    if v:
                        order_no = v
                        break
                order_positions.append((i, order_no))

    # DEBUG récap positions
    print(f"[DBG] total headers trouvés = {len(order_positions)}")
    print(f"[DBG] lignes headers = {[idx for idx, _ in order_positions][:10]}")
    print(f"[DBG] total items trouvés = {len(item_positions)}")
    print(f"[DBG] lignes items = {[idx for idx, _ in item_positions][:10]}")

    # Association item → header le plus proche
    def find_closest_order(item_idx: int) -> str | None:
        print(f"[DBG] find_closest_order(item_idx={item_idx})")

        # 1) Chercher APRÈS l'item (fenêtre 10 lignes)
        for order_idx, order_no in order_positions:
            if item_idx < order_idx <= item_idx + 10:
                print(f"[DBG]  ↪ trouvé APRÈS : header@L{order_idx} → {order_no}")
                return order_no

        # 2) Sinon propager le dernier header AVANT
        for order_idx, order_no in reversed(order_positions):
            if order_idx < item_idx:
                print(f"[DBG]  ↪ trouvé AVANT : header@L{order_idx} → {order_no}")
                return order_no

        print("[DBG]  ↪ aucun header trouvé pour cet item")
        return None

    # ÉTAPE 2 : Parser chaque item + description
    items: list[dict] = []

    for item_idx, item_data in item_positions:
        item_code = item_data.get(code_group)
        qty = item_data.get(qty_group)
        order_no = find_closest_order(item_idx)

        print(f"[DBG] ITEM @L{item_idx}: code={item_code!r}, qty={qty!r}, order={order_no!r}")

        # Chercher la description
        description: str | None = None

        # Si max_follow_lines == 0, la description est déjà dans item_data (cas Prof-Elec)
        if max_follow == 0:
            description = item_data.get(desc_group)
            if description:
                print(f"[DBG]   description inline: '{description}'")
        else:
            # Chercher dans les lignes suivantes (cas Linden)
            for j in range(1, max_follow + 1):
                if item_idx + j >= len(lines):
                    break
                next_ln = _norm_line(lines[item_idx + j])
                print(f"[DBG]   cherche desc L{item_idx}+{j} → '{next_ln}'")

                # Arrêt si nouvelle ligne d'item
                if start_pat.match(next_ln):
                    print("[DBG]   STOP: nouvelle ligne d'item détectée")
                    break

                # Ignorer "Subtotal"
                if next_ln.startswith("Subtotal"):
                    print("[DBG]   STOP: ligne 'Subtotal'")
                    break

                # Détecter description
                if desc_pat:
                    m_desc = desc_pat.match(next_ln)
                    if m_desc and not description:
                        desc_text = m_desc.groupdict().get(desc_group, "").strip()
                        if not desc_text.startswith("Subtotal"):
                            description = desc_text
                            print(f"[DBG]   description trouvée: '{description}'")
                            break

        print(f"[DBG]   → ITEM FINAL: code={item_code}, qty={qty}, order={order_no}, desc={description}")

        items.append(
            {
                "item_code": item_code,
                "qty": qty,
                "description": description,
                "your_order": order_no,
            }
        )

    print(f"[DBG] ✅ total items parsés (multiline) = {len(items)}")
    print(f"[DBG] 🟢 _parse_multiline_items: FIN - {len(items)} items")

    return items, []


def main():
    # 1) Lire PDF
    read = _read_pdf_lines(PDF_PATH, PAGES)
    if DEBUG_1:
        prev = "\n".join(read["lines"])
        print("---- TEXTE PDF (début) ----")
        print(prev[:1200])
        print("---- FIN EXTRAIT ----")

    # 2) Charger config & détecter fournisseur
    cfg = _load_config(CONFIG_PATH)

    if DEBUG_1:
        print(f"[DBG] PDF_PATH = {PDF_PATH.resolve()}")
        print(f"[DBG] CONFIG_PATH = {CONFIG_PATH.resolve()}")
        print(f"[DBG] pages_parsed = {read['pages_parsed']}, page_count = {read['page_count']}")
        print(f"[DBG] first 200 chars of joined text = {(' '.join(read['lines']))[:200]}")

    supplier, profile = _detect_supplier(read["lines"], cfg)

    if DEBUG_1:
        print(f"[DBG] supplier chosen = {supplier}")

    out: dict[str, Any] = {
        "file": str(PDF_PATH),
        "supplier": supplier,
        "profile_loaded": bool(profile),
        "page_count": read["page_count"],
        "pages_parsed": read["pages_parsed"],
    }

    if not profile:
        out["items"] = []
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    # 3) Préparer les variables de configuration
    block_cfg = profile.get("block") or {}
    start_re = block_cfg.get("start_line_regex")
    stop_re = block_cfg.get("stop_line_regex")
    line_re = profile.get("item_regex") or profile.get("line_regex")
    header_re = profile.get("header_regex")
    multi = bool(profile.get("multi_blocks"))

    # DEBUG: état du profil
    multiline_cfg = profile.get("multiline_item")
    if DEBUG_1:
        print(f"[DBG] profile keys = {list(profile.keys())}")
        print(f"[DBG] has multiline_item? {bool(multiline_cfg)}")
        if isinstance(multiline_cfg, dict):
            print(f"[DBG] multiline_item keys = {list(multiline_cfg.keys())}")

    if DEBUG_1:
        print(f"[DBG] start_re={repr(start_re)}")
        print(f"[DBG] multi_blocks={multi}, header_regex={repr(header_re)}, item_regex set? {bool(line_re)}")

    # DEBUG: compter les matches sur les lignes brutes
    if DEBUG_1:
        lines_norm = [_norm_line(x) for x in read["lines"]]
        # Header (commande) : utile pour Linear & Linden (pour valider la présence)
        if header_re:
            _hdr_pat = re.compile(header_re)
            hdr_hits = [i for i, ln in enumerate(lines_norm) if _hdr_pat.search(ln)]
            print(f"[DBG] header_regex hits: {len(hdr_hits)} -> {hdr_hits[:10]}")
            for idx in hdr_hits[:3]:
                print(f"[DBG] header line @ {idx}: {lines_norm[idx]}")
        else:
            print("[DBG] header_regex is None")

        # item_regex (ESL/Linear) — pour Linden il sera None (multi-ligne)
        if line_re:
            _it_pat = re.compile(line_re)
            it_hits = [i for i, ln in enumerate(lines_norm) if _it_pat.match(ln)]
            print(f"[DBG] item_regex hits: {len(it_hits)} -> {it_hits[:10]}")
            for idx in it_hits[:3]:
                print(f"[DBG] item line @ {idx}: {lines_norm[idx]}")
        else:
            print("[DBG] item_regex is None (ok si fournisseur multi-ligne comme Linden)")

    # DEBUG: cas Linden — valider les sous-regex multiline_item si présent
    if DEBUG_1 and isinstance(multiline_cfg, dict):
        start_rx = multiline_cfg.get("start_regex")
        qty_rx = multiline_cfg.get("qty_regex")
        desc_rx = multiline_cfg.get("desc_regex")

        def _count_hits(rx, label):
            if not rx:
                print(f"[DBG] {label} regex is None")
                return
            try:
                pat = re.compile(rx)
            except re.error as e:
                print(f"[DBG] {label} regex INVALID: {e}")
                return
            hits = [i for i, ln in enumerate(lines_norm) if pat.search(ln)]
            print(f"[DBG] {label} hits: {len(hits)} -> {hits[:10]}")
            for idx in hits[:3]:
                print(f"[DBG] {label} line @ {idx}: {lines_norm[idx]}")

        _count_hits(start_rx, "multiline.start_regex")
        _count_hits(qty_rx, "multiline.qty_regex")
        _count_hits(desc_rx, "multiline.desc_regex")

    # 4) Isoler le bloc items UNIQUEMENT si on n'est PAS en multi-blocs
    block_lines = []
    if not multi:
        if not start_re:
            if DEBUG_1:
                print("[DBG] early-exit: start_line_regex manquant en mode non-multi — aucun parsing déclenché.")
                if isinstance(multiline_cfg, dict):
                    print(
                        "[DBG] NOTE: profil contient multiline_item mais le code actuel"
                         "" ne l utilise pas en mode non-multi."
                    )

            out["items"] = []
            print(json.dumps(out, ensure_ascii=False, indent=2))
            return

        block_lines = _extract_block_lines(read["lines"], start_re, stop_re)

    # 5) Parser les items
    items: list[dict[str, Any]] = []
    orders: list[dict[str, Any]] = []

    if multi and header_re and line_re:
        # MODE MULTI-BLOCS (Linear)
        if DEBUG_1:
            print("[DBG] Entering multi-blocks mode (Linear)")

        blocks = _extract_multi_blocks(read["lines"], header_re, line_re)
        orders = []
        for b in blocks:
            # post-traitement int
            for it in b["items"]:
                for k in (profile.get("post") or {}).get("int_fields", []):
                    if k in it:
                        it[k] = _to_int_safe(it[k])
            orders.append({"header": b["header"], "items": b["items"]})
            items.extend(b["items"])
        out["orders"] = orders

    elif multiline_cfg:
        # MODE MULTILINE (Linden)
        if DEBUG_1:
            print(f"[DBG] len(block_lines)={len(block_lines)}")
            print(f"[DBG] len(read['lines'])={len(read['lines'])}")

            print("[DBG] Entering multiline parsing mode (Linden)")

        print("[DBG] >>> about to call _parse_multiline_items")
        print(
            f"[DBG] using_lines_var = {'read[\"lines\"]' if lines is read['lines'] else 'block_lines' if 'block_lines' in locals() and lines is block_lines else 'UNKNOWN'}"
        )
        print(f"[DBG] lines_len = {len(lines)}")
        if len(lines) > 0:
            print(f"[DBG] lines[0] = {lines[0]!r}")
            print(f"[DBG] lines[-1] = {lines[-1]!r}")

        print(f"[DBG] multi={multi}")
        print(f"[DBG] len(block_lines)={len(block_lines)}")
        print(f"[DBG] len(read['lines'])={len(read['lines'])}")
        lines_to_parse = read["lines"] if multi else block_lines
        print(f"[DBG] lines_to_parse chosen: {'read[lines]' if multi else 'block_lines'}")
        print(f"[DBG] len(lines_to_parse)={len(lines_to_parse)}")
        print(f"[DBG] type(lines_to_parse)={type(lines_to_parse)}")
        print("[DBG] >>> about to call _parse_multiline_items")

        try:
            items, orders = _parse_multiline_items(lines_to_parse, multiline_cfg, header_re)
            print(f"[DBG] ✅ _parse_multiline_items returned {len(items)} items")
        except Exception as e:
            print(f"[DBG] ❌ ERROR: {e}")
            import traceback

            traceback.print_exc()
            items, orders = [], []

        # Prof-Elec utilise multi_blocks, donc on parse TOUTES les lignes
        lines_to_parse = read["lines"] if multi else block_lines
        try:
            items, orders = _parse_multiline_items(lines_to_parse, multiline_cfg, header_re)
            print(f"[DBG] _parse_multiline_items returned: {len(items)} items")
        except Exception as e:
            print(f"[DBG] ❌ ERROR in _parse_multiline_items: {e}")
            import traceback

            traceback.print_exc()
            items, orders = [], []

        # Post-traitement float
        for it in items:
            for k in (profile.get("post") or {}).get("float_fields", []):
                if k in it and it[k]:
                    # Convertir format européen (1.234,56 → 1234.56)
                    v = str(it[k]).replace(".", "").replace(",", ".")
                    try:
                        it[k] = float(v)
                    except Exception:
                        it[k] = 0.0

        if DEBUG_1:
            print(f"[DBG] Multiline parsing found {len(items)} items")

    else:
        # MODE BLOC UNIQUE (ESL)
        if DEBUG_1:
            print("[DBG] Entering single-block mode (ESL)")

        if line_re:
            pat = re.compile(line_re)
            for ln in block_lines:
                m = pat.match(ln)
                if not m:
                    continue
                it = m.groupdict()
                for k in (profile.get("post") or {}).get("int_fields", []):
                    if k in it:
                        it[k] = _to_int_safe(it[k])
                items.append(it)

    out["line_count"] = len(items)
    out["items"] = items

    # NOUVEAU : Affichage du résumé avant le JSON
    display_extraction_summary(supplier, items, orders, cfg)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
