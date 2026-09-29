"""
core/helpers.py
===============
Fonctions utilitaires de normalisation de texte, analyse d'évidences,
garde-fous anti-hallucination et helpers pour le pipeline CVTailor.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from core.lexicons import TECH_CANONICAL, TECH_ALIASES, TITLE_WORD_CORRECTIONS, KNOWN_COMPANY_ACRONYMS


def _norm(text: Any) -> str:
    """Normalise une chaîne : minuscules, suppression d'accents et quotes unifiées."""
    text = "" if text is None else str(text)
    text = (
        text.replace("’", "'")
        .replace("‘", "'")
        .replace("`", "'")
        .replace("´", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text.lower().strip()


def _flatten(value: Any) -> list[str]:
    """Aplatit récursivement les listes et dictionnaires en une liste de chaînes."""
    out: list[str] = []
    if isinstance(value, list):
        for x in value:
            out.extend(_flatten(x))
    elif isinstance(value, dict):
        for v in value.values():
            out.extend(_flatten(v))
    elif isinstance(value, str) and value.strip():
        out.append(value.strip())
    return out


def normalize_tech_names(text: str) -> str:
    """Remplace les variantes de casse par les noms canoniques (ex: postgresql -> PostgreSQL)."""
    for wrong, correct in TECH_CANONICAL.items():
        text = re.sub(
            r"(?<![a-zA-Z])" + re.escape(wrong) + r"(?![a-zA-Z])",
            correct, text, flags=re.IGNORECASE,
        )
    return text


def _display_role_for_career_stage(role: str) -> str:
    cleaned = re.sub(r"\s*\(PFE\)\s*", "", role or "", flags=re.IGNORECASE).strip()
    cleaned = cleaned.replace("AI & Software Engineering Intern", "AI & Software Engineer Intern")
    return cleaned


def _profile_corpus(profile: dict) -> str:
    """Texte source utilisé pour vérifier si une compétence est réellement attestée."""
    raw = profile.get("raw_profile") or profile
    return _norm(json.dumps(raw, ensure_ascii=False))


def _profile_experiences(profile: dict) -> list[dict]:
    return profile.get("experiences") or profile.get("professional_experience", [])


def _profile_projects(profile: dict) -> list[dict]:
    return profile.get("projects") or profile.get("featured_projects", [])


def _get_bullets(item: dict) -> list[dict]:
    """Accepte story_bullets (CARA) et key_achievements/highlights (texte)."""
    story_bullets = item.get("story_bullets")
    if story_bullets:
        return [
            b if isinstance(b, dict) else {"context": "", "action": str(b), "result": "", "tech_proof": ""}
            for b in story_bullets
        ]

    raw = item.get("key_achievements") or item.get("highlights", [])
    if isinstance(raw, dict):
        raw = [entry for entries in raw.values() for entry in (entries if isinstance(entries, list) else [entries])]

    return [
        {"context": "", "action": b, "result": "", "tech_proof": ""}
        for b in raw
        if isinstance(b, str)
    ]


def _profile_strong_evidence_corpus(profile: dict) -> str:
    """
    Corpus RESTREINT : uniquement le texte des expériences et projets réels
    (stack + bullets), à l'exclusion de toute liste plate de compétences déclarées.
    """
    parts = []
    for exp in _profile_experiences(profile):
        parts.extend(_norm(t) for t in _flatten(exp.get("stack", [])))
        for b in _get_bullets(exp):
            parts.append(_norm(f"{b.get('context','')} {b.get('action','')} {b.get('result','')} {b.get('tech_proof','')}"))
    for proj in _profile_projects(profile):
        parts.extend(_norm(t) for t in _flatten(proj.get("stack", [])))
        for b in _get_bullets(proj):
            parts.append(_norm(f"{b.get('context','')} {b.get('action','')} {b.get('result','')} {b.get('tech_proof','')}"))
        parts.append(_norm(str(proj.get("description", ""))))
    return " ".join(parts)


def _build_profile_truth_corpus(profile: dict) -> dict:
    """
    Construit dynamiquement depuis profil.json un corpus de vérité structuré.
    """
    companies_info = []
    valid_dates = set()
    required_exps = []

    for exp in _profile_experiences(profile):
        comp = exp.get("company", "")
        if comp:
            aliases = [_norm(comp)]
            comp_n = _norm(comp)
            if "ministere" in comp_n or "ministère" in comp_n:
                aliases.extend(["micepp", "ministere de l'investissement", "ministère de l'investissement"])
            elif "dxc" in comp_n:
                aliases.extend(["dxc technology", "dxc"])
            elif "lotus" in comp_n:
                aliases.extend(["lotus capital", "capquant"])
            companies_info.append({
                "id": exp.get("id", ""),
                "company": comp,
                "aliases": aliases,
                "always_feature": bool(exp.get("always_feature")),
                "role_signal": exp.get("role_signal", []),
            })
            if exp.get("always_feature"):
                required_exps.append((exp.get("id"), comp, aliases, exp.get("role_signal", [])))

        dur = exp.get("duration", "")
        if dur:
            dur_n = _norm(dur)
            valid_dates.add(dur_n)
            for y in re.findall(r"\b20\d{2}\b", dur):
                valid_dates.add(y)

    for proj in _profile_projects(profile):
        pdate = proj.get("date", "")
        if pdate:
            valid_dates.add(_norm(pdate))
            for y in re.findall(r"\b20\d{2}\b", pdate):
                valid_dates.add(y)

    return {
        "companies": companies_info,
        "valid_dates": valid_dates,
        "required_experiences": required_exps,
    }


def _get_profile_ats_keyword_aliases(profile: dict) -> dict[str, list[str]]:
    """Lit les aliases ATS depuis profil.json et retourne un mapping normalisé."""
    if not isinstance(profile, dict):
        return {}

    opt = profile.get("optimization") or {}
    raw_aliases = opt.get("ats_keyword_aliases") or profile.get("ats_keyword_aliases")
    if not isinstance(raw_aliases, dict):
        return {}

    out: dict[str, list[str]] = {}
    for k, v in raw_aliases.items():
        if not isinstance(v, list):
            continue
        key = _norm(k)
        variants = [_norm(x) for x in v if isinstance(x, str) and x.strip()]
        if variants:
            out[key] = variants
    return out


def _split_keywords_by_evidence(profile: dict, keywords: list[str]) -> dict[str, list[str]]:
    """Classe les keywords de l'offre selon leur présence réelle dans profil.json."""
    corpus = _profile_corpus(profile)
    proven, unproven = [], []

    aliases = {
        "api testing": ["api testing", "rest api testing", "postman", "swagger", "openapi"],
        "integration testing": ["integration testing", "end-to-end", "workflow validation", "api testing"],
        "software testing": ["software testing", "validation", "quality validation", "api testing"],
        "qa": ["qa", "quality", "validation", "data quality", "api testing"],
        "test cases": ["test cases", "scénarios", "scenario", "workflow validation"],
        "defect tracking": ["jira", "bug", "defect", "anomaly"],
    }

    ats_aliases = _get_profile_ats_keyword_aliases(profile)

    for kw in keywords:
        k = _norm(kw)
        if not k:
            continue

        candidates = aliases.get(k, [k])
        if k in ats_aliases:
            candidates = list(dict.fromkeys(candidates + ats_aliases[k]))

        if any(c and _norm(c) in corpus for c in candidates):
            proven.append(kw)
        else:
            unproven.append(kw)

    return {"proven": proven, "unproven": unproven}


def _build_evidence_guard(profile: dict, analysis: dict) -> str:
    """Construit un bloc anti-hallucination injecté dans les prompts."""
    top_kw = analysis.get("required_keywords", [])[:30]
    evidence = _split_keywords_by_evidence(profile, top_kw)
    proven = ", ".join(evidence["proven"][:20]) or "aucun keyword direct détecté"
    unproven = ", ".join(evidence["unproven"][:20]) or "aucun"
    return f"""
━━━ GARDE-FOU FACTUEL — COMPÉTENCES OFFRE VS PROFIL ━━━
Compétences demandées par l'offre ET attestées dans profil.json : {proven}
Compétences demandées par l'offre MAIS NON attestées dans profil.json : {unproven}

RÈGLES STRICTES :
- Les compétences NON attestées ne doivent JAMAIS apparaître comme compétences acquises.
- Tu peux les mentionner uniquement comme contexte de l'offre ou axe d'apprentissage, jamais dans la section COMPÉTENCES.
- Ne pas copier les mots-clés de l'offre dans le CV si profil.json ne les prouve pas.
- Pour chaque bullet, utiliser uniquement les faits fournis dans EXPÉRIENCES/PROJETS.
"""


_EMOJI_PATTERN = re.compile(
    "[\U0001F300-\U0001FAFF\U00002600-\U000027BF\U0001F1E6-\U0001F1FF\u2705\u2709\u260E\uFE0F]"
)


def _strip_stray_emojis(text: str) -> str:
    """Retire tout emoji résiduel pour conformité ATS."""
    cleaned = _EMOJI_PATTERN.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    cleaned = re.sub(r"[ \t]+\|", " |", cleaned)
    return cleaned


def _title_for_display(job_title: str) -> str:
    cleaned = (job_title or "").strip().title()
    return " ".join(TITLE_WORD_CORRECTIONS.get(word, word) for word in cleaned.split())


def _company_for_display(company_name: str) -> str:
    cleaned = (company_name or "").strip()
    if cleaned.upper() in KNOWN_COMPANY_ACRONYMS:
        return cleaned.upper()
    return cleaned.title()


def _profile_evidence_text(profile: dict) -> str:
    evidence = {
        "identity": profile.get("identity", {}),
        "narrative_hooks": profile.get("narrative_hooks", {}),
        "experiences": profile.get("experiences") or profile.get("professional_experience", []),
        "projects": profile.get("projects") or profile.get("featured_projects", []),
        "education": profile.get("education") or profile.get("education_and_certs", {}),
        "languages": profile.get("languages", []),
        "technical_evidence": profile.get("technical_ecosystem", {}),
        "optimization": profile.get("optimization", {}),
    }
    return _norm(json.dumps(evidence, ensure_ascii=False))


def _kw_in_evidence(keyword: str, evidence_text: str) -> bool:
    normalized = _norm(keyword)
    candidates = TECH_ALIASES.get(normalized, [normalized])
    for candidate in candidates:
        candidate_norm = _norm(candidate)
        if candidate_norm and re.search(rf"(?<![a-z0-9]){re.escape(candidate_norm)}(?![a-z0-9])", evidence_text):
            return True
    return False


def build_keyword_grounding(profile: dict, analysis: dict, document_type: str = "cv") -> str:
    """Sépare les mots-clés de l'offre en prouvés / non prouvés."""
    evidence_text = _profile_evidence_text(profile)
    required = list(dict.fromkeys(analysis.get("required_keywords", [])[:30]))

    implied_skills_to_use = {_norm(s) for s in analysis.get("implied_skills_to_use", [])}

    proven, missing = [], []
    for kw in required:
        if _kw_in_evidence(kw, evidence_text) or kw in implied_skills_to_use:
            proven.append(kw)
        else:
            missing.append(kw)

    bridge_sentences = analysis.get("bridge_sentences", [])
    bridge_block = ""
    if bridge_sentences:
        bridge_block = (
            "\nCompétences adjacentes — phrases de transfert autorisées en PROFIL ou lettre UNIQUEMENT :\n"
            + "\n".join(f"  • {s}" for s in bridge_sentences)
            + "\n"
        )

    implied_list = analysis.get("implied_skills_to_use", [])
    implied_block = ""
    if implied_list:
        implied_block = (
            f"\nCompétences IMPLIQUÉES (prouvées par déduction logique, autorisées en COMPÉTENCES TECHNIQUES) :\n"
            f"  {', '.join(implied_list)}\n"
            "  → Ces compétences sont logiquement garanties par les technologies prouvées du profil.\n"
        )

    if document_type == "letter":
        missing_rule = """
- Dans la lettre, les compétences NON prouvées peuvent être mentionnées comme environnement cible, intérêt ou montée en compétence.
- Formulations autorisées : "exposition à", "notions de", "intérêt pour", "capacité à monter en compétence sur".
- Interdit : les présenter comme maîtrise, expérience livrée ou compétence principale.
"""
    else:
        missing_rule = """
- Dans le CV, les compétences NON prouvées ne doivent JAMAIS apparaître dans la section COMPÉTENCES TECHNIQUES.
- Elles peuvent apparaître uniquement dans le PROFIL ou une phrase de positionnement sous forme honnête : "notions de", "exposition à", "montée en compétence sur".
- Interdit : écrire TensorFlow/PyTorch/Deep Learning/Computer Vision comme compétences maîtrisées si aucune preuve profil.json ne les atteste.
"""

    return f"""
━━━ GROUNDING DES COMPÉTENCES — SOURCE DE VÉRITÉ PROFIL.JSON ━━━
Compétences / mots-clés de l'offre réellement prouvés dans le profil : {', '.join(proven) if proven else 'aucun mot-clé direct détecté'}
Compétences demandées mais NON prouvées explicitement : {', '.join(missing) if missing else 'aucun manque critique détecté'}
{implied_block}{bridge_block}
RÈGLES STRICTES :
- Les compétences prouvées (liste ci-dessus + impliquées) doivent être conservées avec leurs noms techniques exacts.
{missing_rule}
- Le document doit vendre les preuves réelles, pas recopier les mots-clés de l'offre.
"""
