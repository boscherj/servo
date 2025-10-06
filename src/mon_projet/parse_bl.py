"""
parse_bl.py - Étape 2 (Partie A)
--------------------------------
Objectif : choisir le "flavor" Camelot le plus adapté pour un PDF donné,
en se basant sur l'entête de tableau déclaré dans le profil fournisseur.

Ce module NE PARSE PAS encore les lignes produits. On valide d'abord :
- la détection fournisseur,
- la recherche d'un tableau dont le début "ressemble" à l'entête attendu,
- le choix du flavor qui détecte le mieux l'entête.

Utilisation :
    python -m mon_projet.parse_bl --pdf src/mon_projet/assets/pdfs/3_LINEAR_42939.pdf --debug

Sortie : un JSON imprimé sur stdout :
{
  "file": "...",
  "supplier": "Linear Supply Solutions (Europe) BV",
  "chosen_flavor": "network",
  "flavor_results": {
      "network": {"tables_found": 9, "header_match": true, "matched_tables": [1]},
      "hybrid":  {"tables_found": 9, "header_match": true, "matched_tables": [1]},
      "stream":  {"tables_found": 3, "header_match": false, "matched_tables": []},
      "lattice": {"tables_found": 0, "header_match": false, "matched_tables": []}
  }
}

Étape suivante (Partie B) : une fois validé, on extraira les lignes avec la regex.
"""

from __future__ import annotations

import argparse
import json
import re

# ------------------------------
# Petites fonctions utilitaires
# ------------------------------
import string
import sys
import unicodedata

# === Utils extraction (AJOUTER APRÈS LES IMPORTS) ===
from pathlib import Path
from typing import Any

# Dépendances : camelot (pour l'extraction de tableaux)
# pip install camelot-py[cv]
import camelot

# On réutilise ton détecteur existant
from mon_projet.detect_fournisseur import detect_fournisseur, read_pdf_text

# --- Extraction des lignes produits à partir des tables Camelot ---
# Cette fonction parcourt les tables détectées par Camelot et applique
# la regex définie dans le profil ("ligne_regex") pour extraire les champs.
# Elle retourne une liste de dicts homogènes (items).


def extract_items_from_tables(profile, tables, debug: bool = False):
    """
    Parcourt les tables Camelot et applique la regex de ligne.
    Corrige le cas où Camelot découpe une ligne article en plusieurs sous-lignes
    (description wrap) via un buffer de concaténation.
    """
    items = []

    # 1) Préparer la regex de ligne (sinon retour vide)
    ligne_regex = profile.get("ligne_regex")
    if not ligne_regex:
        return items
    pattern = re.compile(ligne_regex)

    # 2) Champs à extraire
    fields_map = profile.get("fields", {})

    # 3) Optionnel : code article dans la description
    code_article_inside_desc_re = None
    if profile.get("code_article_regex"):
        code_article_inside_desc_re = re.compile(profile["code_article_regex"])

    # 4) Petite aide : qu’est-ce qui ressemble à un début de ligne article ESL ?
    #    Exemple: commence par une série de chiffres (Document No), puis des tokens...
    #    On s’en passe : on essaie d’abord la regex, sinon on concatène.
    def clean_text(s: str) -> str:
        # Nettoyage léger + suppression des "nan" (très fréquent dans t.df)
        s = " ".join(str(s).split())
        s = s.replace(" nan ", " ").replace(" NaN ", " ")
        s = s.replace("nan ", " ").replace(" nan", " ")
        return re.sub(r"\s+", " ", s).strip()

    for t in tables:
        buffer = ""  # on accumule ici quand une ligne ne matche pas encore
        for _, row in t.df.iterrows():
            row_text = clean_text(" ".join(str(x).strip() for x in row.tolist()))

            # Si on a un buffer en cours, on concatène la sous-ligne
            candidate = (buffer + " " + row_text).strip() if buffer else row_text

            m = pattern.match(candidate)
            if m:
                # OK, on a reconstitué une ligne complète
                item = {}
                for field_name, grp_index in fields_map.items():
                    try:
                        item[field_name] = m.group(grp_index)
                    except IndexError:
                        item[field_name] = ""

                # Complément éventuel : code article dans la description
                if (
                    "code_article" not in item or not item["code_article"]
                ) and code_article_inside_desc_re:
                    if item.get("description"):
                        m2 = code_article_inside_desc_re.search(item["description"])
                        if m2:
                            item["code_article"] = m2.group(1)

                items.append(item)
                buffer = ""  # on repart de zéro pour la prochaine ligne
                continue

            # Pas encore de match → on peuple/étend le buffer
            if buffer:
                buffer = candidate
            else:
                buffer = row_text

        # Sécurité : si on sort de la table avec un buffer non vide, on tente une dernière fois
        if buffer:
            m = pattern.match(buffer)
            if m:
                item = {}
                for field_name, grp_index in fields_map.items():
                    try:
                        item[field_name] = m.group(grp_index)
                    except IndexError:
                        item[field_name] = ""
                if (
                    "code_article" not in item or not item["code_article"]
                ) and code_article_inside_desc_re:
                    if item.get("description"):
                        m2 = code_article_inside_desc_re.search(item["description"])
                        if m2:
                            item["code_article"] = m2.group(1)
                items.append(item)
            elif debug:
                print(f"[DEBUG] Fin de table, buffer non matché: {buffer[:160]}", file=sys.stderr)

    return items


# (Duplicate advanced extractor removed;
# we keep the simple extract_items_from_tables(profile, tables)
# defined above.)


def extract_metadata_from_text(
    profile: dict[str, Any], pdf_path: Path, pages_opt
) -> dict[str, Any]:
    """
    Lit (un extrait de) texte du PDF et applique les regex du profil pour récupérer :
    - date_document (ex: '23/07/2025')
    - purchase_orders : liste de tous les n° de commandes trouvés (ex: ['CF0-123', 'CF0-456'])

    profile: dict du profil fournisseur (contient date_regex, purchase_order_regex, etc.)
    pdf_path: chemin du PDF
    pages_opt: valeur passée par la CLI (--pages), peut être 'all', '1', '1-3', int, etc.

    Retourne un dict avec des clés optionnelles: {"date_document": "...", "purchase_orders": [...]}
    """

    # 1) On convertit --pages en entier si possible (sinon None = lire tout)
    pages_for_text = None
    if isinstance(pages_opt, str) and pages_opt.isdigit():
        pages_for_text = int(pages_opt)
    elif isinstance(pages_opt, int):
        pages_for_text = pages_opt
    # sinon: 'all' / '1-3' -> on laisse None pour lire tout (on reste simple)

    # 2) On essaie de lire du texte (robuste et silencieux si erreur)
    try:
        raw = read_pdf_text(pdf_path, pages_to_read=pages_for_text)
        if isinstance(raw, str):
            txt = raw
        elif isinstance(raw, list | tuple):
            txt = "\n".join(map(str, raw))
        elif isinstance(raw, dict):
            txt = json.dumps(raw, ensure_ascii=False)
        else:
            txt = str(raw)
    except Exception:
        # En cas d’échec, on retourne un dict vide, on ne bloque pas le pipeline
        return {}

    out_meta: dict[str, Any] = {}

    # 3) Date du document (on prend la 1ère occurrence)
    date_regex = profile.get("date_regex")
    if date_regex:
        m = re.search(date_regex, txt)
        if m:
            out_meta["date_document"] = m.group(1)

    # 4) Un ou plusieurs n° de commande client (on récupère toutes les occurrences)
    po_regex = profile.get("purchase_order_regex")
    if po_regex:
        pos = re.findall(po_regex, txt)
        # On déduplique en conservant l’ordre d’apparition
        if pos:
            seen = set()
            uniq = []
            for p in pos:
                if p not in seen:
                    seen.add(p)
                    uniq.append(p)
            out_meta["purchase_orders"] = uniq

    return out_meta


def _to_int_safe(v: Any) -> int:
    """
    Convertit une valeur texte vers un entier de façon tolérante :
    - supprime espaces, points/virgules de milliers,
    - remplace la virgule décimale par un point,
    - tronque la partie décimale si présente,
    - renvoie 0 en cas d'échec.
    """
    try:
        if v is None:
            return 0
        s = str(v).strip()
        if not s:
            return 0
        # enlever séparateurs de milliers les plus fréquents
        s = s.replace(" ", "").replace("\u00a0", "").replace(",", ".")
        # certains PDF génèrent "2.000" pour 2000 (CMS),
        # on retire les points superflus s'il y en a >1
        # mais on garde la première occurrence (décimale potentielle)
        # pour pouvoir tronquer ensuite
        if s.count(".") > 1:
            # ex: "2.000.000" -> "2000000"
            s = s.replace(".", "")
        # nombre flottant -> on tronque (quantités = entiers dans nos BL)
        f = float(s)
        return int(f)
    except Exception:
        return 0


def normalize_numeric_fields(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Parcourt la liste d'items; pour chaque clé qui 'ressemble' à une quantité
    (nom qui commence par 'qte_' ou est parmi un petit set connu), convertit en int.
    Retourne la liste modifiée (pour chaînage).
    """
    numeric_like = {"quantite", "qty", "quantity"}
    out = []
    for it in items:
        it2 = dict(it)  # copie superficielle
        for k, v in it.items():
            if k.startswith("qte_") or k in numeric_like:
                it2[k] = _to_int_safe(v)
        out.append(it2)
    return out


def normalize_text(s: str) -> str:
    """
    Normalise un texte pour comparer facilement :
    - passe en minuscules,
    - retire les accents,
    - remplace sauts de ligne/tabulations par des espaces,
    - retire la ponctuation (.,:; etc.), y compris symboles spéciaux,
    - compresse les espaces multiples.
    """
    if not isinstance(s, str):
        return ""
    s = s.lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.replace("\n", " ").replace("\r", " ").replace("\t", " ")
    # Retrait de la ponctuation pour des comparaisons plus robustes
    allowed = "".join(ch for ch in s if ch not in string.punctuation)
    # Certains PDF ont des caractères spéciaux (ex: “°”, “’”, etc.)
    #  → on les garde si non ponctuation
    s = allowed
    # Espaces multiples → simple espace
    s = re.sub(r"\s+", " ", s).strip()
    return s


def table_head_as_text(df, max_rows: int = 5) -> str:
    """
    Concatène les 'max_rows' premières lignes du DataFrame Camelot en une chaîne.
    Utile pour tester si l'entête attendue apparaît 'quelque part' au début du tableau.
    """
    lines = []
    for i, row in enumerate(df.values.tolist()):
        if i >= max_rows:
            break
        # On joint les cellules de la ligne en séparant par un espace
        line = " ".join(str(cell) for cell in row if cell is not None)
        lines.append(line)
    return normalize_text(" ".join(lines))


def header_tokens(header: str) -> list[str]:
    """
    Convertit l'entête attendue (string du JSON) en une liste de tokens normalisés.
    Exemple: "Pos Marque Code Description Commandée Livrée ce jour suivre"
    → ["pos", "marque", "code", "description", "commandee", "livree", "ce", "jour", "suivre"]
    """
    norm = normalize_text(header)
    return [tok for tok in norm.split(" ") if tok]


def table_matches_header(df, header: str) -> bool:
    """
    Renvoie True si TOUS les tokens de l'entête apparaissent dans les premières lignes du tableau.
    C'est volontairement "binaire" et simple (comme demandé).
    Si c'est trop strict, on pourra desserrer la condition plus tard.
    """
    if not header:
        return False
    tokens = header_tokens(header)
    head_text = table_head_as_text(df, max_rows=6)  # on regarde un peu plus de lignes
    return all(tok in head_text for tok in tokens)


# ------------------------------
# Sélection du flavor Camelot
# ------------------------------
DEFAULT_TRY_FLAVORS = ["network", "hybrid", "stream", "lattice"]


def _header_tokens_in_text(header: str, text: str) -> bool:
    """Secours : si l'en-tête n'apparaît pas dans les tables Camelot,
    on vérifie que *tous* les tokens de l'entête existent dans le texte brut.
    Utile pour valider le flavor même si l'entête n'est pas capturé comme table."""
    if not header or not text:
        return False
    head = normalize_text(header)
    txt = normalize_text(text)
    return all(tok in txt for tok in head.split())


def choose_best_flavor(
    pdf_path: Path, profile: dict[str, Any], pages: str = "all"
) -> dict[str, Any]:
    """
    Si le profil contient 'fixed_flavor' (ou 'flavor'), on lit UNIQUEMENT avec ce flavor
    et on le choisit, même si l'entête n'apparaît pas dans les tables (cas ESL).
    Sinon, on essaie la liste DEFAULT_TRY_FLAVORS et on choisit le premier flavor
    dont au moins une table contient l'entête.
    """
    header = profile.get("tableau_entete", "")
    fixed = profile.get("fixed_flavor") or profile.get("flavor")

    # --- Cas 1 : flavor fixé dans le profil ---
    if fixed:
        flavor_results: dict[str, Any] = {}
        try:
            tables = camelot.read_pdf(str(pdf_path), flavor=fixed, pages=pages)
        except Exception as e:
            flavor_results[fixed] = {
                "tables_found": 0,
                "header_match": False,
                "matched_tables": [],
                "error": f"{type(e).__name__}: {e}",
            }
            return {"chosen_flavor": fixed, "flavor_results": flavor_results}

        matched_indexes: list[int] = []
        for idx, table in enumerate(tables):
            if table_matches_header(table.df, header):
                matched_indexes.append(idx)

        # Si pas de match dans les tables, on tente une vérification de secours dans le texte brut :
        header_match = bool(matched_indexes)
        if not header_match:
            try:
                # lire peu de texte suffit (première page / pages demandées)
                pages_for_text = None
                if isinstance(pages, str) and pages.isdigit():
                    pages_for_text = int(pages)
                elif isinstance(pages, int):
                    pages_for_text = pages
                raw = read_pdf_text(pdf_path, pages_to_read=pages_for_text)
                txt = (
                    raw
                    if isinstance(raw, str)
                    else "\n".join(map(str, raw)) if isinstance(raw, list | tuple) else str(raw)
                )
            except Exception:
                txt = ""
            header_match = _header_tokens_in_text(header, txt)

        flavor_results[fixed] = {
            "tables_found": len(tables),
            "header_match": header_match,
            "matched_tables": matched_indexes,
        }

        # Très important : on CHOISIT le flavor fixe quoi qu'il arrive.
        return {"chosen_flavor": fixed, "flavor_results": flavor_results}

    # --- Cas 2 : flavor non fixé -> on essaie plusieurs flavors ---
    try_flavors = profile.get("preferred_flavors", DEFAULT_TRY_FLAVORS)
    flavor_results: dict[str, Any] = {}
    chosen = None

    for flavor in try_flavors:
        try:
            tables = camelot.read_pdf(str(pdf_path), flavor=flavor, pages=pages)
        except Exception as e:
            flavor_results[flavor] = {
                "tables_found": 0,
                "header_match": False,
                "matched_tables": [],
                "error": f"{type(e).__name__}: {e}",
            }
            continue

        matched_indexes: list[int] = []
        for idx, table in enumerate(tables):
            if table_matches_header(table.df, header):
                matched_indexes.append(idx)

        flavor_results[flavor] = {
            "tables_found": len(tables),
            "header_match": bool(matched_indexes),
            "matched_tables": matched_indexes,
        }

        if matched_indexes and chosen is None:
            chosen = flavor

    return {"chosen_flavor": chosen, "flavor_results": flavor_results}


# ------------------------------
# CLI principale (Étape A)
# ------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Étape 2A: choisir le flavor Camelot (sans parsing de lignes)."
    )
    parser.add_argument("--pdf", required=True, type=Path, help="Chemin du fichier PDF à analyser")
    parser.add_argument(
        "--config",
        default=Path("src/mon_projet/assets/json/config_fournisseurs.json"),
        type=Path,
        help="Chemin du JSON de configuration fournisseurs",
    )
    parser.add_argument(
        "--pages", default="all", help="Pages Camelot à analyser (ex: '1', '1-2', 'all')"
    )
    parser.add_argument(
        "--debug", action="store_true", help="Affiche un extrait du texte du PDF pour debug"
    )
    args = parser.parse_args()

    # 1) Détecter le fournisseur et récupérer le profil
    detect = detect_fournisseur(args.pdf, args.config)
    supplier = detect.get("supplier", "unknown")
    profile = detect.get("profile") or {}

    out: dict[str, Any] = {
        "file": str(args.pdf),
        "supplier": supplier,
        "profile_loaded": bool(profile),
    }

    # --- REMPLACE le bloc d'aperçu debug par ceci ---
    # --- Aperçu texte (debug) robuste: on passe un int/None à read_pdf_text ----
    if args.debug:
        try:
            # read_pdf_text attend un entier ou None pour pages_to_read
            pages_for_text = None
            if isinstance(args.pages, str) and args.pages.isdigit():
                pages_for_text = int(args.pages)
            elif isinstance(args.pages, int):
                pages_for_text = args.pages
            # sinon, on laisse None (ex: "all" ou "1-2")

            raw = read_pdf_text(args.pdf, pages_to_read=pages_for_text)

            # Normaliser en chaîne sliceable, quoi que renvoie read_pdf_text
            if isinstance(raw, str):
                preview_text = raw
            elif isinstance(raw, list | tuple):
                preview_text = "\n".join(map(str, raw))
            elif isinstance(raw, dict):
                preview_text = json.dumps(raw, ensure_ascii=False)
            else:
                preview_text = str(raw)

            print("---- TEXTE PDF (début) ----")
            print(preview_text[:1200])
            print("---- FIN EXTRAIT ----")
        except Exception as e:
            print(f"[DEBUG] Impossible de lire un extrait texte : {e}", file=sys.stderr)

    # --- FIN REMPLACEMENT ---

    if supplier == "unknown" or not profile:
        out["chosen_flavor"] = None
        out["flavor_results"] = {}
        print(json.dumps(out, ensure_ascii=False, indent=2))
        sys.exit(0)

    # 2) Choisir le flavor
    choice = choose_best_flavor(args.pdf, profile, pages=args.pages)
    out.update(choice)

    # --- Étape 2B : extraction des lignes (une fois le flavor choisi) ---
    chosen = out.get("chosen_flavor")
    if chosen:
        import camelot

        # Relire les tables avec "chosen_flavor"
        # NB: on réutilise args.pages si fourni (ex: "--pages 1")
        read_kwargs = {"flavor": chosen}
        if args.pages:
            read_kwargs["pages"] = args.pages
        # Petite option utile pour éviter des espaces parasites
        read_kwargs["strip_text"] = "\n"

        tables = camelot.read_pdf(args.pdf, **read_kwargs)

        # On ne garde que les tables dont l'indice figure dans matched_tables du flavor choisi.
        matched_idx = out.get("flavor_results", {}).get(chosen, {}).get("matched_tables", [])

        # Fallback : si aucun index d'entête n'a été reconnu, on tente toutes les tables
        if matched_idx:
            selected_tables = [tables[i] for i in matched_idx if 0 <= i < len(tables)]
        else:
            selected_tables = list(tables)
            if args.debug:
                # Petit log utile pour vérifier ce que Camelot a réellement capturé
                print(
                    "[DEBUG] matched_tables vide → fallback sur "
                    f"{len(selected_tables)} table(s) pour l'extraction.",
                    file=sys.stderr,
                )

        # Extraire les items via la regex définie dans le profil
        items = extract_items_from_tables(profile, selected_tables, debug=args.debug)

        # Normaliser les types (quantités -> int) AVANT de poser dans la sortie
        items = normalize_numeric_fields(items)

        # Ajouter dans la sortie JSON
        out["line_count"] = len(items)
        out["items"] = items

        # --- Étape 2C : métadonnées (date + n° de commandes) depuis le texte ---
        meta = extract_metadata_from_text(profile, args.pdf, args.pages)
        # On fusionne proprement les champs trouvés (si absents, rien n’est ajouté)
        out.update(meta)

    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
