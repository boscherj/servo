"""

---------------------
Ce module sert à détecter le fournisseur d’un bordereau de livraison (BL).
Il s’appuie sur TON fichier JSON : src/mon_projet/assets/json/config_fournisseurs.json

Principe :
- On lit le PDF (par ex. les 2 premières pages)
- On normalise le texte (tout en minuscules, sans accents)
- On cherche les chaînes de caractères propres à chaque fournisseur
  (dans le champ "fournisseur_patterns" du fichier JSON)
- Dès qu’une correspondance est trouvée → on renvoie le fournisseur

Exemple d’utilisation :
python -m mon_projet.detect_fournisseur --pdf src/mon_projet/assets/pdfs/3_LINEAR_42939.pdf
"""

import json
import unicodedata
from pathlib import Path
from typing import Any

import pdfplumber


# ----------------------------------------------------------------------------------------
# 1. Fonction utilitaire : normaliser le texte
# ----------------------------------------------------------------------------------------
def normalize_text(text: str) -> str:
    """
    Convertit le texte en minuscules et enlève les accents.
    Cela permet de comparer des textes même s’ils contiennent des majuscules
    ou des caractères accentués.

    Exemple :
        "Électricité" → "electricite"
    """
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


# ----------------------------------------------------------------------------------------
# 2. Lire les premières pages du PDF
# ----------------------------------------------------------------------------------------
def read_pdf_text(pdf_path: Path, pages_to_read: int = 2) -> str:
    """
    Lit le texte brut des premières pages d’un PDF avec pdfplumber.
    On limite à 2 pages pour aller plus vite (et c’est souvent suffisant).
    """
    text_parts = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages[:pages_to_read]:
            text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts)


# ----------------------------------------------------------------------------------------
# 3. Charger la configuration des fournisseurs
# ----------------------------------------------------------------------------------------
def load_config(config_path: Path) -> dict[str, Any]:
    """
    Charge le fichier JSON contenant les règles de détection et de parsing.
    """
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------------------------------
# 3.5 Vérification des entrées et gestion d’erreurs
# ----------------------------------------------------------------------------------------
def check_inputs(pdf_path: Path, config_path: Path):
    """Vérifie que les chemins existent et sont valides."""
    if not pdf_path.exists():
        raise FileNotFoundError(f"Le fichier PDF {pdf_path} n’existe pas.")
    if not config_path.exists():
        raise FileNotFoundError(f"Le fichier JSON {config_path} n’existe pas.")
    if pdf_path.suffix.lower() != ".pdf":
        raise ValueError(f"Le fichier {pdf_path} n’est pas un PDF valide.")


# ----------------------------------------------------------------------------------------
# 4. Détecter le fournisseur à partir du PDF
# ----------------------------------------------------------------------------------------
def detect_fournisseur(pdf_path: Path, config_path: Path, pages_to_read: int = 2) -> dict[str, Any]:
    """
    Cherche quel fournisseur correspond au PDF donné.
    - On lit le texte du PDF
    - On parcourt chaque fournisseur et ses "fournisseur_patterns"
    - Si une des chaînes est trouvée → on renvoie ce fournisseur

    Retourne un dictionnaire :
    {
        "file": "nom_du_fichier.pdf",
        "supplier": "Nom du fournisseur détecté ou 'unknown'",
        "profile": { ... bloc JSON complet ... }
    }
    """
    # Vérifier les fichiers avant de continuer
    check_inputs(pdf_path, config_path)

    # Charger la config complète
    config_data = load_config(config_path)

    # Lire le texte du PDF et le normaliser
    try:
        raw_text = read_pdf_text(pdf_path, pages_to_read)
    except Exception as e:
        raise RuntimeError(f"Erreur de lecture du PDF {pdf_path}: {e}") from e

    # --- DEBUG : afficher le texte extrait pour vérifier ce que pdfplumber lit ---
    # print("---- TEXTE PDF (début) ----")
    # print(raw_text[:1500])   # on limite à 1500 caractères pour éviter un défilement infini
    # print("---- FIN EXTRAIT ----")

    normalized_text = normalize_text(raw_text)

    # Parcourir chaque fournisseur du JSON
    for supplier_name, supplier_info in config_data.items():
        patterns = supplier_info.get("fournisseur_patterns", [])
        for pattern in patterns:
            if normalize_text(pattern) in normalized_text:
                # Dès qu’un mot-clé est trouvé → on renvoie immédiatement le résultat
                return {"file": str(pdf_path), "supplier": supplier_name, "profile": supplier_info}

    # Si rien n’est trouvé → on renvoie "unknown"
    return {"file": str(pdf_path), "supplier": "unknown", "profile": {}}


# ----------------------------------------------------------------------------------------
# 5. Utilisation en ligne de commande (pour tester facilement)
# ----------------------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="Détecte le fournisseur à partir d’un PDF.")
    parser.add_argument("--pdf", required=True, help="Chemin du fichier PDF à analyser")
    parser.add_argument(
        "--config",
        default="src/mon_projet/assets/json/config_fournisseurs.json",
        help="Chemin du fichier de configuration JSON",
    )
    parser.add_argument("--pages", type=int, default=2, help="Nombre de pages à lire (défaut: 2)")

    args = parser.parse_args()

    result = detect_fournisseur(pdf_path=Path(args.pdf), config_path=Path(args.config), pages_to_read=args.pages)

    print(_json.dumps(result, ensure_ascii=False, indent=2))
