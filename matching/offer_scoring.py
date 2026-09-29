from __future__ import annotations

import re
from typing import Any


def _norm(s: Any) -> str:
    s = "" if s is None else str(s)
    s = s.lower()
    replacements = {
        "’": "'",
        "‘": "'",
        "`": "'",
        "´": "'",
        "é": "e",
        "è": "e",
        "ê": "e",
        "à": "a",
        "â": "a",
        "ô": "o",
        "î": "i",
        "ï": "i",
        "ç": "c",
    }
    for a, b in replacements.items():
        s = s.replace(a, b)
    return s


def _contains_any(norm_text: str, phrases: list[str]) -> bool:
    return any(p and _norm(p) in norm_text for p in phrases)


def score_personalization(cv: str, letter: str, analysis: dict[str, Any], offer: dict[str, Any]) -> dict[str, Any]:
    """Heuristiques simples mais utiles pour évaluer la personnalisation."""
    cvn = _norm(cv)
    letn = _norm(letter)

    positioning = analysis.get("positioning", {}) or {}
    app_ctx = analysis.get("application_context", {}) or {}
    match = analysis.get("match", {}) or {}

    expected_primary_company = (positioning.get("primary_experience") or "").strip()
    expected_primary_project = (positioning.get("primary_project") or "").strip()

    target_company = (analysis.get("job_context", {}) or {}).get("company_name", "") or offer.get("company_name", "")

    # 1) Entreprise cible dans la lettre (ou fallback CV)
    target_company_norm = _norm(target_company)
    company_short_candidates = []
    if target_company_norm:
        # Ex: "alten maroc" -> "alten"
        company_short_candidates = list({
            target_company_norm,
            target_company_norm.replace(" maroc", ""),
            target_company_norm.replace(" sarl", ""),
            target_company_norm.replace(" sa", ""),
        })
        company_short_candidates = [c for c in company_short_candidates if c and c.strip()]

    target_company_present = False
    if company_short_candidates:
        target_company_present = any(c in letn for c in company_short_candidates) or any(c in cvn for c in company_short_candidates)

    # 2) Titre cible dans le CV (si fourni)
    target_title = (positioning.get("target_title") or "").strip()
    target_title_in_cv = bool(target_title) and _norm(target_title) in cvn

    # 3) Preuve principale dans le CV
    primary_company_in_cv = bool(expected_primary_company) and _norm(expected_primary_company) in cvn

    # 4) Preuve projet principale dans la section projets (approche simple)
    primary_project_in_cv = bool(expected_primary_project) and _norm(expected_primary_project) in cvn

    # 5) Présence de 2+ entreprises (indique non-template)
    companies = [
        (e.get("company") or "") for e in (analysis.get("exp_scores") or [])[:5] if isinstance(e, dict)
    ]
    distinct = {c.strip().lower() for c in companies if c.strip()}
    distinct_companies_in_cv = sum(1 for c in distinct if c and c in cvn)

    # Score
    score = 0
    score += 35 if target_company_present else 0
    score += 15 if target_title_in_cv else 0
    score += 25 if primary_company_in_cv else 0
    score += 10 if primary_project_in_cv else 0
    score += 15 if distinct_companies_in_cv >= 2 else 0

    max_score = 100

    return {
        "personalization_score": int(score),
        "target_company_present": target_company_present,
        "target_title_in_cv": target_title_in_cv,
        "primary_company_in_cv": primary_company_in_cv,
        "primary_project_in_cv": primary_project_in_cv,
        "distinct_companies_in_cv": distinct_companies_in_cv,
        "match_global_score": match.get("global_score", ""),
        "priority": app_ctx.get("priority", ""),
    }


def score_factuality(cv: str, letter: str, validator_issues_cv: list[str], validator_issues_letter: list[str]) -> dict[str, Any]:
    cvn = _norm(cv)
    letn = _norm(letter)

    issues = (validator_issues_cv or []) + (validator_issues_letter or [])
    # 0 issues => 100
    if not issues:
        return {"factuality_score": 100, "issue_count": 0}

    # Heuristique: plus il y a d'issues critiques (hallucination/tech non attestée), plus on pénalise.
    critical = 0
    for i in issues:
        li = _norm(i)
        if any(k in li for k in ["m&eacute;trique", "metrique", "fait invente", "non attest", "non prouve", "stage", "trop senior", "entreprise cible"]):
            critical += 1

    issue_count = len(issues)
    score = max(0, 100 - 8 * issue_count - 12 * critical)

    return {
        "factuality_score": int(score),
        "issue_count": issue_count,
        "critical_issue_count": critical,
        "issues_sample": issues[:10],
    }


def score_rh_readability(cv: str, letter: str, analysis: dict[str, Any]) -> dict[str, Any]:
    cvn = _norm(cv)
    letn = _norm(letter)

    # CV: présence de sections
    has_profile = "## profil" in cvn
    has_formation = "## formation" in cvn
    has_experiences = "## experiences professionnelles" in cvn
    has_skills = "## competences techniques" in cvn
    has_projets = "## projets" in cvn

    # Pondération (max 100) : projets important pour profils juniors.
    cv_struct_score = 0
    cv_struct_score += 15 if has_profile else 0
    cv_struct_score += 15 if has_formation else 0
    cv_struct_score += 15 if has_experiences else 0
    cv_struct_score += 15 if has_skills else 0
    cv_struct_score += 20 if has_projets else 0

    # Lettre: doit contenir "objet" et "cordialement" (ou signature)
    has_objet = "objet" in letn
    has_bye = "cordialement" in letn

    letter_score = 0
    letter_score += 20 if has_objet else 0
    letter_score += 20 if has_bye else 0

    total = cv_struct_score + letter_score
    # Bonus si la lettre est assez longue (au moins ~150 mots)
    words = re.findall(r"\w+", letn)
    if len(words) >= 180:
        total += 10

    # Bonus si pas de marqueurs interdits évidents
    forbidden_like = ["dans l'espoir", "n'hesitez pas", "je vous remercie", "grand interet"]
    if not any(_norm(x) in letn for x in forbidden_like):
        total += 10

    total = min(100, total)

    return {
        "rh_readability_score": int(total),
        "cv_struct_score": cv_struct_score,
        "letter_score": letter_score,
        "letter_word_count": len(words),
        "has_profile": has_profile,
        "has_formation": has_formation,
        "has_experiences": has_experiences,
        "has_skills": has_skills,
        "has_objet": has_objet,
        "has_bye": has_bye,
    }


def compute_final_score(personalization: dict[str, Any], factuality: dict[str, Any], readability: dict[str, Any]) -> dict[str, Any]:
    # pondération
    # - factuality est prioritaire
    # - personalization est second
    # - readability en troisième
    p = int(personalization.get("personalization_score", 0))
    f = int(factuality.get("factuality_score", 0))
    r = int(readability.get("rh_readability_score", 0))

    # Pondération : réduire l'impact des warnings de forme, renforcer l'alignement perso et la lisibilité.
    final = int(0.35 * f + 0.45 * p + 0.20 * r)

    return {
        "final_score": final,
        "score_factuality": f,
        "score_personalization": p,
        "score_rh_readability": r,
    }

