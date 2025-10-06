# src/mon_projet/plumber_step1.py
"""
plumber_step1.py — pdfplumber only, sans arguments CLI
- Lit un PDF cible
- Détecte le fournisseur via le JSON de config
- Affiche les lignes de texte extraites
- Imprime aussi un JSON récap à la fin

Exécution (aucun argument) :
  python -m mon_projet.plumber_step1
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pdfplumber

# Détecteur existant (utilise ton JSON de configuration)
from mon_projet.detect_fournisseur import detect_fournisseur

# ------------ PARAMÈTRES À MODIFIER ICI SI BESOIN ------------
PDF_PATH = Path("src/mon_projet/assets/pdfs/2_ESL_48931.pdf")
CONFIG_PATH = Path("src/mon_projet/assets/json/config_fournisseurs.json")
PAGES = "1"  # "all", "1", "1-3", "1,3" ...
DEBUG_PREVIEW = True
# -------------------------------------------------------------


def _parse_pages_spec(pages: str | int | None, total_pages: int) -> list[int]:
    """Convertit '1', '1-3', '1,3', 'all' en liste d'index 0-based pour pdfplumber."""
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


def read_pdf_lines(pdf_path: Path, pages: str | int | None = "all") -> dict[str, Any]:
    """Ouvre le PDF avec pdfplumber et renvoie page_count, pages_parsed, lines."""
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


def main():
    # 1) Détecter le fournisseur via le JSON de config
    detect = detect_fournisseur(PDF_PATH, CONFIG_PATH)
    supplier = detect.get("supplier", "unknown")
    profile = detect.get("profile") or {}

    # 2) Lire le PDF (pdfplumber) et récupérer les lignes
    read = read_pdf_lines(PDF_PATH, PAGES)

    # 3) Aperçu debug
    if DEBUG_PREVIEW:
        preview_text = "\n".join(read["lines"])
        print("---- TEXTE PDF (début) ----")
        print(preview_text[:1200])
        print("---- FIN EXTRAIT ----")

    # 4) Sortie JSON simple
    out = {
        "file": str(PDF_PATH),
        "supplier": supplier,
        "profile_loaded": bool(profile),
        "page_count": read["page_count"],
        "pages_parsed": read["pages_parsed"],
        "line_count": len(read["lines"]),
        "lines": read["lines"],
    }
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
