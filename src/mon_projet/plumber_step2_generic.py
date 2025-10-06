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
PDF_PATH = Path("src/mon_projet/assets/pdfs/2_ESL_48931.pdf")
CONFIG_PATH = Path("src/mon_projet/assets/json/config_fournisseurs.json")
PAGES = "1"  # "all" / "1" / "1-2" ...
DEBUG = True


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


def main():
    # 1) Lire PDF
    read = _read_pdf_lines(PDF_PATH, PAGES)
    if DEBUG:
        prev = "\n".join(read["lines"])
        print("---- TEXTE PDF (début) ----")
        print(prev[:1200])
        print("---- FIN EXTRAIT ----")

    # 2) Charger config & détecter fournisseur
    cfg = _load_config(CONFIG_PATH)
    supplier, profile = _detect_supplier(read["lines"], cfg)

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

    block_cfg = profile.get("block") or {}
    start_re = block_cfg.get("start_line_regex")
    stop_re = block_cfg.get("stop_line_regex")
    if not start_re:
        out["items"] = []
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    # 3) Isoler le bloc items (toutes les lignes après l'entête)
    block_lines = _extract_block_lines(read["lines"], start_re, stop_re)

    # 4) Préparer la regex d'item
    line_re = profile.get("item_regex") or profile.get("line_regex")

    items: list[dict[str, Any]] = []
    consumed_for_debug: list[str] = []  # ← défini **avant** l'usage, toutes branches

    if line_re:
        pat = re.compile(line_re)

        # 5) Consommer les lignes jusqu'au premier non-match (fin implicite du tableau)
        for ln in block_lines:
            nln = _norm_line(ln)
            m = pat.match(nln)
            if not m:
                # On s'arrête dès qu'on tombe sur "Page 1 of 1" ou autre non-match
                break
            consumed_for_debug.append(ln)
            item = m.groupdict()
            # post-traitements
            post = profile.get("post") or {}
            for k in post.get("int_fields", []):
                if k in item:
                    item[k] = _to_int_safe(item[k])
            items.append(item)
    else:
        if DEBUG:
            print("[DEBUG] Pas de line_regex/item_regex dans le profil; 0 item.")

    if DEBUG:
        print(f"[DEBUG] Lignes items consommées: {len(consumed_for_debug)}")
        for ln in consumed_for_debug:
            print("[ITEM]  ", ln)

    out["line_count"] = len(items)
    out["items"] = items

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
