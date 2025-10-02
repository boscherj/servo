"""Gestion centralisée des chemins et fichiers du projet (PDF, JSON, etc.)."""

# src/mon_projet/config.py
import os
from pathlib import Path

from dotenv import load_dotenv

# Charge .env s'il existe (sinon ne fait rien)
load_dotenv()

# Racine du repo: .../servo
ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = ROOT / "src"
PKG_DIR = SRC_DIR / "mon_projet"
ASSETS_DIR = PKG_DIR / "assets"

# Défauts alignés sur TON arbo actuelle
DEFAULT_PDF_DIR = ASSETS_DIR / "pdfs"
DEFAULT_JSON_DIR = ASSETS_DIR / "json"
DEFAULT_PDF_FILE = "2_ESL_48931.pdf"
DEFAULT_FOURNISSEURS = DEFAULT_JSON_DIR / "config_fournisseurs.json"


def _resolve(p: str | Path) -> Path:
    """Convertit en chemin absolu (relatif à la racine du repo si nécessaire)."""
    p = Path(p)
    return p if p.is_absolute() else (ROOT / p).resolve()


# Dossiers (overridables par variables d'env)
PDF_DIR = _resolve(os.getenv("PDF_DIR", str(DEFAULT_PDF_DIR)))
JSON_DIR = _resolve(os.getenv("JSON_DIR", str(DEFAULT_JSON_DIR)))

# Fichiers (overridables par variables d'env)
PDF_FILE = os.getenv("PDF_FILE", DEFAULT_PDF_FILE)
FOURNISSEURS_CONFIG = _resolve(os.getenv("FOURNISSEURS_CONFIG", str(DEFAULT_FOURNISSEURS)))

# Chemin complet du PDF courant
PDF_PATH = _resolve(PDF_DIR / PDF_FILE)
