"""
profile_enrichment.py — Enrichissement semi-supervisé du profil candidat
========================================================================
Deux couches d'automatisation pour résoudre les faux "gaps" de compétences :

  Couche 1 — Graphe d'implication (calcul unique, réutilisé partout)
  ------------------------------------------------------------------
  Si le profil prouve Spring Boot → il maîtrise IoC.
  Si le profil prouve REST API → il sait manipuler JSON.
  Ces implications sont logiques, pas "probables" — on les marque
  comme "prouvées" dans le prompt CV sans mentir.

  Couche 2 — Pont sémantique (par offre, via embeddings existants)
  ---------------------------------------------------------------
  Si MongoDB manque mais Redis est prouvé (similitude ~0.8),
  on génère une phrase de transfert pour PROFIL ou la lettre,
  jamais pour COMPÉTENCES TECHNIQUES.

Usage :
  python profile_enrichment.py --propose [--profile profil.json]
  python profile_enrichment.py --review  [--profile profil.json]
  python profile_enrichment.py --status  [--profile profil.json]

  Depuis le code (cv_tailor.py) :
    from profile_enrichment import resolve_gap_keywords, build_bridge_sentence
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

# ─── Chemins par défaut ───────────────────────────────────────────────────────

_DEFAULT_PROFILE_PATH = Path(__file__).parent / "profil.json"


# ─── Helpers JSON ────────────────────────────────────────────────────────────

def _load_profile(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_profile(profile: dict, path: Path) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)
    print(f"✅  profil.json mis à jour → {path}")


def _get_implied_skills(profile: dict) -> list[dict]:
    """Retourne la liste implied_skills depuis optimization, ou [] si absente."""
    return profile.get("optimization", {}).get("implied_skills", [])


def _set_implied_skills(profile: dict, items: list[dict]) -> None:
    if "optimization" not in profile:
        profile["optimization"] = {}
    profile["optimization"]["implied_skills"] = items


# ─── Extraction du corpus prouvé ─────────────────────────────────────────────

def _collect_proven_stack(profile: dict) -> list[str]:
    """
    Retourne toutes les technologies/compétences **attestées** par au moins
    une expérience ou un projet réel (stack uniquement — pas les listes plates).
    """
    proven: list[str] = []
    for exp in profile.get("professional_experience", []):
        stack = exp.get("stack", [])
        if isinstance(stack, dict):
            for values in stack.values():
                if isinstance(values, list):
                    proven.extend(str(v) for v in values)
        elif isinstance(stack, list):
            proven.extend(str(v) for v in stack)

    for proj in profile.get("featured_projects", []):
        proven.extend(str(v) for v in proj.get("stack", []))

    return list(dict.fromkeys(proven))  # déduplique l'ordre


# ─── Couche 1 : Proposition LLM ─────────────────────────────────────────────

IMPLICATION_PROMPT = """\
Tu analyses un profil technique de développeuse (Junior / Entry-Level).

Voici les compétences PROUVÉES par ses expériences/projets réels :
{proven_stack}

Ta mission : identifier les compétences techniques qu'une connaissance de ces outils
implique QUASI CERTAINEMENT chez tout développeur qui les utilise en conditions réelles.

Règles strictes :
1. Implication logique SEULEMENT — évidente pour tout dev senior.
   Exemples valides :
     Spring Boot → Injection de Dépendances (IoC), Application Context
     REST API / Spring MVC → manipulation JSON, sérialisation/désérialisation
     Java backend → utilisation d'un IDE (IntelliJ IDEA ou Eclipse)
     JUnit / Tests unitaires → notion de couverture de code, mocking
     Docker Compose → réseau Docker, variables d'environnement conteneurisées
     PostgreSQL + ORM → gestion des transactions, mapping objet-relationnel
2. PAS d'implication "probable mais non garantie" (ex: Docker ≠ Kubernetes).
3. PAS de compétences déjà explicitement présentes dans la liste ci-dessus.
4. Confidence = "high" si l'implication est automatique (100%), "medium" si usuelle (>80%).
5. Max 20 implications — ne retenir que les plus impactantes pour un CV.

Retourne UNIQUEMENT du JSON valide, sans balise markdown, sans commentaire :
[
  {{
    "implied_skill": "Injection de Dépendances (IoC)",
    "normalized_key": "ioc",
    "source_evidence": "Spring Boot 3",
    "confidence": "high",
    "justification": "Tout dev Spring Boot gère le container IoC quotidiennement.",
    "status": "pending_review"
  }}
]
"""


def propose_implications(profile: dict, model_name: str = "gemini-2.5-flash") -> list[dict]:
    """
    Appelle le LLM (Gemini) une seule fois sur tout le profil pour proposer
    des implications technologiques. Retourne les candidats avec status='pending_review'.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌  GEMINI_API_KEY non définie — impossible d'appeler le LLM.", file=sys.stderr)
        return []

    proven = _collect_proven_stack(profile)
    if not proven:
        print("⚠️  Aucun stack prouvé trouvé dans profil.json.", file=sys.stderr)
        return []

    proven_text = "\n".join(f"- {p}" for p in proven)
    prompt = IMPLICATION_PROMPT.format(proven_stack=proven_text)

    print(f"🤖  Appel LLM ({model_name}) pour proposer les implications…")
    try:
        from google import genai  # type: ignore
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        raw = (response.text or "").strip()

        # Nettoyage : retirer les balises ```json … ``` si présentes
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw)

        candidates: list[dict] = json.loads(raw)
        if not isinstance(candidates, list):
            raise ValueError("La réponse LLM n'est pas une liste JSON.")

        # S'assurer que chaque item a les champs attendus + status pending
        normalized = []
        for item in candidates:
            if not isinstance(item, dict) or "implied_skill" not in item:
                continue
            item.setdefault("status", "pending_review")
            item.setdefault("normalized_key", _normalize_key(item["implied_skill"]))
            normalized.append(item)

        print(f"✅  {len(normalized)} implications proposées.")
        return normalized

    except json.JSONDecodeError as e:
        print(f"❌  Réponse LLM non parseable : {e}", file=sys.stderr)
        print(f"    Réponse brute :\n{raw[:500]}", file=sys.stderr)
        return []
    except Exception as e:
        print(f"❌  Erreur LLM : {e}", file=sys.stderr)
        return []


def _normalize_key(skill: str) -> str:
    """Normalise un nom de compétence pour le stocker comme clé de recherche."""
    key = skill.lower().strip()
    key = re.sub(r"\(.*?\)", "", key).strip()   # retire les parenthèses
    key = re.sub(r"[^a-z0-9\s/#+.]", " ", key) # garde seulement les chars utiles
    key = re.sub(r"\s+", " ", key).strip()
    return key


# ─── Couche 1 : CLI Review ───────────────────────────────────────────────────

_REVIEW_PROMPT = """\
  implied_skill  : {implied_skill}
  source_evidence: {source_evidence}
  confidence     : {confidence}
  justification  : {justification}

  [a] Approuver  [r] Rejeter  [s] Passer (décider plus tard)  [q] Quitter
>>> """


def review_implications(profile: dict, profile_path: Path) -> None:
    """
    CLI interactive : parcourt les items 'pending_review' et demande
    approve / reject / skip pour chacun. Sauvegarde après chaque décision.
    """
    items = _get_implied_skills(profile)
    pending = [i for i in items if i.get("status") == "pending_review"]

    if not pending:
        print("✅  Aucun item en attente de review.")
        # Afficher un résumé
        approved = [i for i in items if i.get("status") == "approved"]
        rejected = [i for i in items if i.get("status") == "rejected"]
        print(f"   Approuvés: {len(approved)}  |  Rejetés: {len(rejected)}  |  Total: {len(items)}")
        return

    print(f"\n{'─'*60}")
    print(f"  REVIEW DES IMPLICATIONS — {len(pending)} item(s) en attente")
    print(f"{'─'*60}\n")

    for idx, item in enumerate(pending, 1):
        print(f"[{idx}/{len(pending)}]")
        answer = input(_REVIEW_PROMPT.format(**item)).strip().lower()

        if answer == "a":
            item["status"] = "approved"
            print("   ✅ Approuvé")
        elif answer == "r":
            item["status"] = "rejected"
            print("   ❌ Rejeté")
        elif answer == "q":
            print("   ⏹️  Review interrompue — progrès sauvegardé.")
            _save_profile(profile, profile_path)
            return
        else:
            print("   ⏭️  Passé (reste pending)")

        print()

    _save_profile(profile, profile_path)

    approved = sum(1 for i in _get_implied_skills(profile) if i["status"] == "approved")
    still_pending = sum(1 for i in _get_implied_skills(profile) if i["status"] == "pending_review")
    print(f"\n📊  Review terminée — {approved} approuvées, {still_pending} encore en attente.")


# ─── Couche 1 : Status ───────────────────────────────────────────────────────

def print_status(profile: dict) -> None:
    """Affiche l'état actuel du graphe d'implications dans profil.json."""
    items = _get_implied_skills(profile)
    if not items:
        print("ℹ️  Aucune implication dans profil.json — lance --propose pour commencer.")
        return

    groups: dict[str, list[dict]] = {"approved": [], "rejected": [], "pending_review": []}
    for item in items:
        groups.setdefault(item.get("status", "pending_review"), []).append(item)

    print(f"\n{'═'*60}")
    print(f"  GRAPHE D'IMPLICATIONS — {len(items)} entrées")
    print(f"{'═'*60}")

    if groups["approved"]:
        print(f"\n✅  APPROUVÉES ({len(groups['approved'])}) — utilisées automatiquement dans le CV :")
        for item in groups["approved"]:
            print(f"    • {item['implied_skill']!r}  ← {item['source_evidence']}")

    if groups["pending_review"]:
        print(f"\n⏳  EN ATTENTE DE REVIEW ({len(groups['pending_review'])}) :")
        for item in groups["pending_review"]:
            src = item.get("source_evidence", "?")
            print(f"    • {item['implied_skill']!r}  ← {src}  [{item.get('confidence','?')}]")

    if groups["rejected"]:
        print(f"\n❌  REJETÉES ({len(groups['rejected'])}) :")
        for item in groups["rejected"]:
            print(f"    • {item['implied_skill']!r}")

    print()


# ─── Couche 2 : Résolution des gaps (appelé par cv_tailor) ──────────────────

def resolve_gap_keywords(
    missing_keywords: list[str],
    profile: dict,
    semantic,  # SemanticMatcher — évite l'import circulaire
    threshold: float = 0.75,
) -> dict[str, list]:
    """
    Classifie chaque mot-clé manquant en 3 catégories :
      - implied    : couvert par le graphe d'implications approuvées
      - bridgeable : proche sémantiquement d'une compétence prouvée
      - true_gap   : vrai manque, décision manuelle

    Args:
        missing_keywords : liste de termes normalisés (_norm) manquants
        profile          : profil.json chargé
        semantic         : instance SemanticMatcher avec cache profil pré-calculé
        threshold        : seuil cosinus pour le pont sémantique (défaut 0.75)

    Returns:
        {
          "implied":    [str, ...],
          "bridgeable": [{"missing": str, "bridge_from": str, "similarity": float}, ...],
          "true_gap":   [str, ...]
        }
    """
    # Ensemble des compétences impliquées (approuvées uniquement)
    approved_implied = {
        _normalize_key(i["implied_skill"])
        for i in _get_implied_skills(profile)
        if i.get("status") == "approved"
    }
    # Aussi les normalized_key explicites
    approved_implied.update(
        i["normalized_key"]
        for i in _get_implied_skills(profile)
        if i.get("status") == "approved" and "normalized_key" in i
    )

    result: dict[str, list] = {"implied": [], "bridgeable": [], "true_gap": []}

    bridge_candidates: list[str] = []
    for kw in missing_keywords:
        kw_norm = kw.lower().strip()
        # Couche 1 : le graphe d'implications
        if kw_norm in approved_implied:
            result["implied"].append(kw)
        else:
            bridge_candidates.append(kw)

    if not bridge_candidates:
        return result

    # Couche 2 : pont sémantique via embeddings en batch unique
    items_to_embed = [(f"gap:{kw}", kw) for kw in bridge_candidates]
    if hasattr(semantic, "get_or_compute_batch"):
        vectors_map = semantic.get_or_compute_batch(items_to_embed)
    else:
        vectors_map = {f"gap:{kw}": _safe_embed(semantic, f"gap:{kw}", kw) for kw in bridge_candidates}

    for kw in bridge_candidates:
        kw_vec = vectors_map.get(f"gap:{kw}")
        if kw_vec is None:
            result["true_gap"].append(kw)
            continue

        best_match, best_sim = _find_closest_profile_item(semantic, kw_vec)
        if best_sim >= threshold:
            result["bridgeable"].append({
                "missing": kw,
                "bridge_from": best_match,
                "similarity": round(best_sim, 2),
            })
        else:
            result["true_gap"].append(kw)

    return result


def _safe_embed(semantic, key: str, text: str):
    """Calcule l'embedding d'un terme via le SemanticMatcher existant (graceful)."""
    try:
        return semantic._get_or_compute(key, text)
    except Exception:
        return None


def _find_closest_profile_item(semantic, kw_vec: list[float]) -> tuple[str, float]:
    """
    Cherche l'item du cache profil le plus proche du vecteur donné.
    Retourne (item_key, cosine_similarity).
    """
    from semantic_matcher import cosine_similarity  # import local pour éviter la circularité

    best_match, best_sim = "", 0.0
    for cache_key, vec in semantic._cache.items():
        if not cache_key.startswith("profile:"):
            continue
        sim = cosine_similarity(kw_vec, vec)
        if sim > best_sim:
            best_match, best_sim = cache_key, sim
    return best_match, best_sim


# ─── Couche 2 : Phrase-pont (template, zéro LLM) ────────────────────────────

def build_bridge_sentence(bridge: dict, profile: dict) -> str:
    """
    Génère une phrase de transfert de compétence via template.
    Destination : section PROFIL ou lettre de motivation UNIQUEMENT.
    JAMAIS dans COMPÉTENCES TECHNIQUES.

    Args:
        bridge : {"missing": str, "bridge_from": str, "similarity": float}
        profile: profil.json (pour récupérer un libellé lisible de la tech source)
    """
    source_key = bridge["bridge_from"].replace("profile:", "")
    source_label = _lookup_skill_label(source_key, profile)
    missing_label = bridge["missing"].title()
    sim = bridge["similarity"]

    if sim >= 0.87:
        # Très proche — formulation affirmative
        return (
            f"Expérience concrète en {source_label}, technologie très proche de {missing_label} "
            f"— compétences directement transférables."
        )
    else:
        # Proche mais distinct — formulation honnête de transfert
        return (
            f"Expérience en {source_label} (adjacent à {missing_label}) "
            f"— capacité de montée en compétence rapide."
        )


def _lookup_skill_label(item_key: str, profile: dict) -> str:
    """
    Essaie de retrouver le nom lisible d'une expérience/projet par son ID.
    Fallback sur l'ID lui-même nettoyé.
    """
    for exp in profile.get("professional_experience", []):
        if exp.get("id") == item_key:
            return exp.get("company", item_key)
    for proj in profile.get("featured_projects", []):
        if proj.get("id") == item_key:
            return proj.get("name", item_key)
    # Fallback : nettoyer l'ID brut
    return item_key.replace("_", " ").title()


# ─── CLI ─────────────────────────────────────────────────────────────────────

def _run_propose(args) -> None:
    path = Path(args.profile)
    profile = _load_profile(path)

    existing = _get_implied_skills(profile)
    existing_keys = {
        (i.get("normalized_key") or _normalize_key(i["implied_skill"]))
        for i in existing
    }

    print(f"📖  Profil chargé : {path}")
    candidates = propose_implications(profile, model_name=args.model)

    if not candidates:
        print("Aucun candidat retourné — rien à sauvegarder.")
        return

    # Fusionner : ne pas dupliquer les entrées déjà présentes
    added = 0
    for item in candidates:
        key = item.get("normalized_key") or _normalize_key(item["implied_skill"])
        if key not in existing_keys:
            existing.append(item)
            existing_keys.add(key)
            added += 1

    _set_implied_skills(profile, existing)
    _save_profile(profile, path)
    print(f"ℹ️   {added} nouvelles implications ajoutées ({len(candidates) - added} doublons ignorés).")
    print(f"     Lance maintenant : python profile_enrichment.py --review")


def _run_review(args) -> None:
    path = Path(args.profile)
    profile = _load_profile(path)
    review_implications(profile, path)


def _run_status(args) -> None:
    path = Path(args.profile)
    profile = _load_profile(path)
    print_status(profile)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enrichissement semi-supervisé du profil candidat (implied skills + bridge semantique).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemples :
  python profile_enrichment.py --propose             # LLM propose des implications
  python profile_enrichment.py --review              # Review interactive CLI
  python profile_enrichment.py --status              # Affiche l'état du graphe
  python profile_enrichment.py --propose --model gemini-2.5-pro  # Modèle alternatif
        """,
    )
    parser.add_argument(
        "--profile", default=str(_DEFAULT_PROFILE_PATH),
        help="Chemin vers profil.json (défaut: profil.json dans le même dossier)"
    )
    parser.add_argument(
        "--model", default="gemini-2.5-flash",
        help="Modèle Gemini à utiliser pour --propose (défaut: gemini-2.5-flash)"
    )

    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--propose", action="store_true", help="LLM propose les implications (1 appel API)")
    action.add_argument("--review",  action="store_true", help="Review interactive des implications en attente")
    action.add_argument("--status",  action="store_true", help="Affiche l'état du graphe d'implications")

    args = parser.parse_args()

    if args.propose:
        _run_propose(args)
    elif args.review:
        _run_review(args)
    elif args.status:
        _run_status(args)


if __name__ == "__main__":
    main()
