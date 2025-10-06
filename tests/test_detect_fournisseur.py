"""
test_detect_fournisseur.py
--------------------------
Ce script permet de tester automatiquement la détection de fournisseurs
sur un ensemble de fichiers PDF.

👉 Il parcourt un dossier (par défaut src/mon_projet/assets/pdfs/)
👉 Il applique ton module detect_fournisseur.py à chaque fichier
👉 Il affiche un rapport clair et coloré :
    ✅ fournisseur détecté
    ❌ inconnu ou erreur de lecture
"""

import json
import traceback
from pathlib import Path

from mon_projet.detect_fournisseur import detect_fournisseur

# ANSI colors pour l'affichage terminal
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

# Répertoires
PDF_DIR = Path("src/mon_projet/assets/pdfs")
CONFIG_PATH = Path("src/mon_projet/assets/json/config_fournisseurs.json")


def test_all_pdfs():
    pdf_files = sorted(PDF_DIR.glob("*.pdf"))
    if not pdf_files:
        print(f"{RED}Aucun PDF trouvé dans {PDF_DIR}{RESET}")
        return

    print("\n=== Test de détection des fournisseurs ===")
    print(f"Dossier : {PDF_DIR}")
    print(f"Nombre de fichiers : {len(pdf_files)}\n")

    results = []
    for pdf_path in pdf_files:
        try:
            result = detect_fournisseur(pdf_path, CONFIG_PATH)
            supplier = result.get("supplier", "unknown")
            if supplier == "unknown":
                print(f"{YELLOW}❌ {pdf_path.name:<40} → Aucun fournisseur reconnu{RESET}")
            else:
                print(f"{GREEN}✅ {pdf_path.name:<40} → {supplier}{RESET}")
            results.append(result)
        except Exception as e:
            print(f"{RED}💥 ERREUR sur {pdf_path.name}: {e}{RESET}")
            traceback.print_exc()
            results.append({"file": str(pdf_path), "error": str(e)})

    # Résumé final
    ok = sum(1 for r in results if r.get("supplier") not in (None, "unknown"))
    ko = len(results) - ok
    print("\n--- Résumé ---")
    print(f"{GREEN}{ok} fichiers reconnus{RESET}")
    print(f"{YELLOW}{ko} fichiers inconnus ou erreurs{RESET}")

    # Sauvegarde d’un rapport JSON complet
    out_path = Path("tests/results_detect_fournisseur.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\n📄 Rapport enregistré dans {out_path.resolve()}\n")


if __name__ == "__main__":
    test_all_pdfs()
