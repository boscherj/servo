import json
import sys
from pathlib import Path

import pdfplumber

from mon_projet.config import FOURNISSEURS_CONFIG, PDF_PATH

if not Path(FOURNISSEURS_CONFIG).exists():
    sys.exit(f"Fichier config introuvable: {FOURNISSEURS_CONFIG}")
if not Path(PDF_PATH).exists():
    sys.exit(f"PDF introuvable: {PDF_PATH}")


# --- Chargement du JSON multi-fournisseur ---
with open(FOURNISSEURS_CONFIG, encoding="utf-8") as f:
    configs = json.load(f)

# --- Lecture du PDF (toutes pages) ---
# --- Chemin du PDF (toutes pages) ---
pdf_path = PDF_PATH  # ex: data/pdfs/2_ESL_48931.pdf selon .env

all_lines = []
with pdfplumber.open(pdf_path) as pdf:
    for page in pdf.pages:
        text = page.extract_text()
        if text:
            all_lines += text.splitlines()

print(all_lines)


# --- Détection du fournisseur ---
selected_config = None
fournisseur_nom = None
for fournisseur, cfg in configs.items():
    patterns = cfg.get("fournisseur_patterns", [])
    print("Patterns : ", patterns)

    if any(any(pattern in line for line in all_lines) for pattern in patterns):
        selected_config = cfg
        fournisseur_nom = fournisseur
        break

print(fournisseur_nom)
