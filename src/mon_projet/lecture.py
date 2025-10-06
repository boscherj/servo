import json
import re
import sys
from pathlib import Path

import pandas as pd
import pdfplumber

# Le fichier config.py gère les chemins
from mon_projet.config import FOURNISSEURS_CONFIG, PDF_PATH

# Le fichier config_fournisseurs.json est le fichier qui contient les patterns et regex
# par fournisseur
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

# --- Détection du fournisseur ---
selected_config = None
fournisseur_nom = None
for fournisseur, cfg in configs.items():
    patterns = cfg.get("fournisseur_patterns", [])
    if any(any(pattern in line for line in all_lines) for pattern in patterns):
        selected_config = cfg
        fournisseur_nom = fournisseur
        break

if not selected_config:
    raise ValueError("Aucun fournisseur reconnu dans ce BL.")

# --- Extraction de la date ---
date_livraison = None
for line in all_lines:
    if selected_config["date_pattern"] in line:
        match = re.search(selected_config["date_regex"], line)
        if match:
            date_livraison = match.group(1).strip()
            break

# --- Extraction du tableau articles ---
tableau_articles = []
tableau_started = False
entete = selected_config["tableau_entete"]
ligne_regex = selected_config["ligne_regex"]
fields = selected_config["fields"]
code_article_regex = selected_config.get("code_article_regex")

for i, line in enumerate(all_lines):
    if entete in line:
        tableau_started = True
        continue

    if tableau_started:
        if not line.strip():
            continue
        match = re.match(ligne_regex, line)
        if not match:
            continue

        data = match.groups()

        # --- Quantité (gère virgule, point, espace) ---
        quantite = None
        if "quantite" in fields:
            qty_str = (
                data[fields["quantite"] - 1].replace(".", "").replace(",", ".").replace(" ", "")
            )
            try:
                quantite = float(qty_str)
            except ValueError:
                quantite = None

        # --- Code Article & Description (par défaut) ---
        code_article = data[fields["code_article"] - 1] if "code_article" in fields else None
        description = data[fields["description"] - 1] if "description" in fields else None

        # --- Description lookahead universel (jusqu'à N lignes après, configurable) ---
        description_fallback = selected_config.get("description_fallback_lines", 0)
        if (not description or description == "") and description_fallback > 0:
            for k in range(1, description_fallback + 1):
                if (i + k) < len(all_lines):
                    next_line = all_lines[i + k].strip()
                    if next_line and not next_line.startswith(
                        (
                            "Manufacturer:",
                            "Customs Tariff",
                            "Your order no.",
                            "Linden order",
                            "Subtotal",
                            "INVOICE",
                            "page",
                            "Pos.",
                        )
                    ):
                        description = next_line
                        break

        # --- Purchase Order lookahead universel (jusqu'à 10 lignes après) ---
        purchase_order = None
        po_pattern = selected_config.get("purchase_order_pattern")
        po_regex = selected_config.get("purchase_order_regex")
        if po_pattern and po_regex:
            for j in range(1, 11):  # Jusqu'à 10 lignes après !
                if (i + j) < len(all_lines):
                    po_line = all_lines[i + j]
                    if po_pattern in po_line:
                        m_po = re.search(po_regex, po_line)
                        if m_po:
                            purchase_order = m_po.group(1)
                        break
        # Cas direct si mapping dans fields
        elif "purchase_order" in fields and isinstance(fields["purchase_order"], int):
            purchase_order = data[fields["purchase_order"] - 1]

        # --- Code article via regex dédiée (ex : JS Electrical) ---
        if code_article_regex and description:
            m_code = re.search(code_article_regex, description)
            if m_code:
                code_article = m_code.group(1)

        article = {
            "Fournisseur": fournisseur_nom,
            "Date": date_livraison,
            "Purchase Order": purchase_order,
            "Code Article": code_article,
            "Description": description,
            "Quantité": quantite,
        }
        tableau_articles.append(article)

# --- Affichage du tableau ---
df = pd.DataFrame(tableau_articles)
print(df)
# (Optionnel) df.to_excel("articles_extraits.xlsx", index=False)
# (Optionnel) df.to_csv("articles_extraits.csv", index=False)
