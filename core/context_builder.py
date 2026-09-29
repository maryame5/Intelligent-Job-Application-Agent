"""
core/context_builder.py
=======================
Prépare le contexte filtré et formaté pour les prompts LLM,
ainsi que les rapports déterministes d'audit et de formatage ATS.
"""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from core.helpers import (
    _norm,
    _flatten,
    _get_bullets,
    _profile_experiences,
    _profile_projects,
    _profile_strong_evidence_corpus,
    _split_keywords_by_evidence,
    _display_role_for_career_stage,
    _EMOJI_PATTERN,
)
from core.offer_analyzer import build_application_context


def build_gap_analysis_report(profile: dict, analysis: dict) -> dict:
    """Rapport offre vs profil."""
    required = analysis.get("required_keywords", [])
    evidence = _split_keywords_by_evidence(profile, required)
    proven, missing = evidence["proven"], evidence["unproven"]

    strong_corpus = _profile_strong_evidence_corpus(profile)
    weakly_proven = [kw for kw in proven if _norm(kw) not in strong_corpus]
    solidly_proven = [kw for kw in proven if kw not in weakly_proven]

    match = analysis.get("match", {})
    seniority = analysis.get("seniority", {})

    lines = [
        f"Couverture keywords : {match.get('keyword_coverage_pct', 0)}% "
        f"({len(proven)}/{len(required)} mots-clés attestés dans le profil)",
        "",
        "✅ Compétences demandées ET illustrées par une expérience/projet concret (à mettre en avant) :",
        "  " + (", ".join(solidly_proven[:25]) or "aucune"),
    ]
    if weakly_proven:
        lines += [
            "",
            "🟡 Compétences demandées, présentes dans profil.json, mais JAMAIS illustrées par une "
            "vraie bullet d'expérience/projet — risque si le recruteur creuse en entretien "
            "(vérifier avant de les laisser dans COMPÉTENCES TECHNIQUES) :",
            "  " + ", ".join(weakly_proven[:25]),
        ]
    lines += [
        "",
        "⚠️ Compétences demandées mais NON prouvées dans profil.json "
        "(ne seront pas ajoutées au CV — à combler par un projet perso, une formation, ou à mentionner à l'oral) :",
        "  " + (", ".join(missing[:25]) or "aucune"),
    ]
    if seniority.get("has_mismatch"):
        lines += [
            "",
            f"⚠️ Écart de séniorité détecté — titre recommandé : {seniority.get('recommended_title')}",
        ]

    return {
        "keywords_proven": proven,
        "keywords_proven_solid": solidly_proven,
        "keywords_proven_weak": weakly_proven,
        "keywords_missing": missing,
        "keyword_coverage_pct": match.get("keyword_coverage_pct", 0),
        "seniority_mismatch": seniority.get("has_mismatch", False),
        "recommended_title": seniority.get("recommended_title"),
        "summary_text": "\n".join(lines),
    }


def build_ats_formatting_checklist(cv_text: str, letter_text: str = "") -> dict:
    """Checklist ATS déterministe."""
    checks = []

    def add(label, ok, fix, impact="medium"):
        checks.append({"check": label, "status": "OK" if ok else "À CORRIGER", "impact": impact, "fix": fix})

    header_block = cv_text[:400]
    has_emoji = bool(_EMOJI_PATTERN.search(header_block))
    add("Pas d'émojis/icônes dans l'en-tête de contact (adresse, email, téléphone, LinkedIn)",
        not has_emoji, "Remplacer les icônes par du texte séparé par '|'.", "high")

    has_tables = bool(re.search(r"^\s*\|.+\|\s*$", cv_text, re.MULTILINE))
    add("Pas de tableaux Markdown (illisibles par la plupart des parseurs ATS)",
        not has_tables, "Remplacer tout tableau par des listes à puces simples.", "high")

    required_sections = ["## Profil", "## Formation", "## Expériences", "## Compétences"]
    missing_sections = [s for s in required_sections if _norm(s) not in _norm(cv_text)]
    add("Titres de sections standards présents (Profil / Formation / Expériences / Compétences)",
        not missing_sections,
        f"Sections manquantes ou mal nommées : {', '.join(missing_sections) or 'aucune'}.", "high")

    weird_bullets = bool(re.search(r"[▪●◆➤➔✓✔]", cv_text))
    add("Puces standards (- ou •), pas de symboles exotiques",
        not weird_bullets, "Remplacer les puces spéciales par '-' ou '•' standard.", "medium")

    has_email = bool(re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", cv_text))
    add("Email visible en texte brut (pas dans une image/icône)", has_email,
        "Ajouter l'email en texte brut dans l'en-tête.", "high")

    has_phone = bool(re.search(r"(\+\d{1,3}|0)[\s.-]?\d[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}[\s.-]?\d{2}", cv_text))
    add("Téléphone visible en texte brut", has_phone,
        "Ajouter le numéro en texte brut dans l'en-tête.", "medium")

    dates_present = len(re.findall(r"\b(19|20)\d{2}\b", cv_text)) >= 2
    add("Dates d'expérience présentes en texte (format année lisible)", dates_present,
        "Vérifier que chaque expérience a des dates au format texte (ex: 2024–2025).", "medium")

    word_count = len(re.findall(r"\w+", cv_text))
    add("Longueur raisonnable (ni trop court ni trop long pour 1 page ATS-friendly)",
        250 <= word_count <= 750,
        f"CV actuel ≈ {word_count} mots — viser 300-650 mots pour tenir sur une page.", "low")

    add("Un seul fichier, format texte natif (pas un scan/image)",
        True, "Déjà garanti par la génération Markdown → PDF du pipeline.", "low")

    n_issues = sum(1 for c in checks if c["status"] != "OK")
    return {"checks": checks, "n_issues": n_issues, "n_total": len(checks)}


def _qa_honesty_instruction(profile: dict, analysis: dict) -> str:
    if analysis.get("role", {}).get("dominant") != "qa_testing":
        return ""
    evidence = _split_keywords_by_evidence(
        profile,
        ["Selenium", "JUnit", "TestNG", "Cypress", "test automation", "CI/CD", "regression testing"],
    )
    missing = ", ".join(evidence["unproven"]) or "aucun"
    return f"""
RÈGLE SPÉCIALE QA — POSITIONNEMENT HONNÊTE :
L'offre est QA/Test Automation, mais le profil prouve surtout API testing, validation, Postman, Swagger/OpenAPI, Data Quality, scénarios end-to-end et debugging.
Titre autorisé : "Ingénieure Software orientée QA, API Testing & Validation".
Titre alternatif : "Junior QA / Software Testing Engineer — API Testing & Data Quality".
Titre interdit : "Ingénieure QA Automation", "QA Automation Engineer", "Test Automation Engineer" sauf si Selenium/JUnit/TestNG/Cypress sont prouvés.
Compétences QA non prouvées à ne pas mettre comme acquises : {missing}.
Dire clairement la valeur : double lecture développeur + qualité, validation d'APIs, documentation de scénarios, analyse de bugs, qualité de données.
Si l'offre demande 3 ans d'expérience, positionner la candidature comme opportuniste/transferable match, jamais comme profil confirmé.
"""


def _select_email_for_context(profile: dict, analysis: dict) -> str:
    identity = profile.get("identity") or {}
    email_institutionnel = identity.get("email", "") or ""
    email_personnel = identity.get("email_personnel", "") or ""

    app_ctx = analysis.get("application_context") or build_application_context(analysis)
    apply_mode = (app_ctx or {}).get("apply_mode", "")

    if apply_mode in {"honest_opportunistic", "light_apply"} and email_personnel:
        return email_personnel
    return email_institutionnel or email_personnel or ""


def _role_family_key_from_dominant(dominant_role: str) -> str:
    mapping = {
        "software_engineer": "software_java",
        "frontend_fullstack_ai_product": "software_fullstack",
        "ai_engineer": "ai_agents",
        "data_engineer": "data_analytics",
        "qa_testing": "qa_testing",
        "cloud_devops": "software_java",
        "consulting": "consulting",
    }
    return mapping.get(dominant_role, "software_java")


def _positioning_by_role_family_text(profile: dict, dominant_role: str) -> str:
    p = profile.get("career_strategy") or {}
    by_family = p.get("positioning_by_role_family") or {}
    key = _role_family_key_from_dominant(dominant_role)
    return by_family.get(key, "")



_FR_TO_EN_MONTHS = {
    "jan": "Jan", "fév": "Feb", "fev": "Feb", "mar": "Mar", "avr": "Apr",
    "mai": "May", "juin": "Jun", "juil": "Jul", "jul": "Jul",
    "aoû": "Aug", "aou": "Aug", "sep": "Sep", "oct": "Oct",
    "nov": "Nov", "déc": "Dec", "dec": "Dec",
    "présent": "Present", "present": "Present",
}


def _normalize_date_for_lang(date_str: str, offer_lang: str) -> str:
    """Translate French abbreviated month names to English when offer_lang=='en'."""
    if offer_lang != "en" or not date_str:
        return date_str
    result = date_str
    for fr, en in _FR_TO_EN_MONTHS.items():
        import re as _re
        result = _re.sub(fr, en, result, flags=_re.IGNORECASE)
    return result


def _detect_offer_language(job_description: str) -> str:
    """Detect the dominant language of a job offer (returns 'en' or 'fr').

    Uses a weighted ratio: if English signals outnumber French signals by at
    least 40 %, or if there are no French signals at all and at least 3 English
    signals, the offer is considered English.
    """
    text = (job_description or "").lower()
    en_signals = [
        # Core structural English JD phrases
        "you will", "we are looking", "we're looking", "you have", "you'll",
        "we offer", "our team", "join us", "requirements", "responsibilities",
        "about the role", "about us", "what you'll do", "what we're looking for",
        "strong experience", "strong background", "proven experience",
        "you are", "you bring", "we expect", "we need",
        # Additional English automation/dev JD phrases
        "what you can expect", "what success looks like",
        "work independently", "take ownership", "strong assets",
        "build and deploy", "build solutions", "practical experience",
        "work location", "full-time remote", "remote position",
        "years of experience", "2+ years", "3+ years",
        "good written", "verbal english", "english communication",
        "python, javascript", "python, typescript",
        "api integrations", "third-party integrations", "webhook",
        "automation platform", "workflow automation", "business process",
        "llm api", "openai", "langchain", "langgraph", "n8n", "make.com", "zapier",
        "strong problem-solving",
    ]
    fr_signals = [
        "vous avez", "vous maîtrisez", "nous recherchons", "poste de",
        "mission :", "profil recherché", "vos missions", "votre profil",
        "rejoignez", "au sein de", "dans le cadre de", "cdi", "cdd",
        "bac+", "bac +", "ingénieur", "ingénieure", "développeur",
        "vos compétences", "votre expérience", "poste ouvert",
    ]
    en_count = sum(1 for s in en_signals if s in text)
    fr_count = sum(1 for s in fr_signals if s in text)

    # No French signals at all → English offer
    if fr_count == 0 and en_count >= 2:
        return "en"
    # English signals dominate by 40 % relative margin
    total = en_count + fr_count
    if total > 0 and (en_count / total) >= 0.65:
        return "en"
    return "fr"


def _build_contact_line(profile: dict, job_description: str, selected_email: str) -> str:
    identity = profile.get("identity", {})
    links = identity.get("links", {})
    github = links.get("github", "")
    portfolio = links.get("portfolio", "")
    linkedin = links.get("linkedin", "")
    phone = identity.get("phone", "")
    location = identity.get("location", "")

    jd_norm = _norm(job_description)
    wants_github = any(k in jd_norm for k in [
        "github", "portfolio", "repos", "repository", "repositories",
        "demos", "demo", "prototypes", "show us", "examples of projects",
        "side projects", "personal projects", "open source",
    ])

    parts = [location, selected_email, phone]
    if linkedin:
        parts.append(linkedin)
    if github and wants_github:
        parts.append(github)
    if portfolio and wants_github:
        parts.append(portfolio)
    return " | ".join(p for p in parts if p)


def _mirror_job_title_keywords(job_title: str, base_title: str) -> str:
    jt_norm = _norm(job_title)
    mirror_terms = {
        "ai-native": "AI-Native",
        "ai native": "AI-Native",
        "agentic": "Agentic AI",
        "junior": "Junior",
        "early career": "Early Career",
        "entry level": "Entry-Level",
        "entry-level": "Entry-Level",
        "ml engineer": "ML Engineer",
        "llm": "LLM",
        "generative ai": "Generative AI",
        "gen ai": "Gen AI",
        "web3": "Web3",
        "blockchain": "Blockchain",
        "defi": "DeFi",
        "fullstack": "Full-Stack",
        "full-stack": "Full-Stack",
    }
    found = []
    for key, label in mirror_terms.items():
        if key in jt_norm and label.lower() not in _norm(base_title):
            found.append(label)
    if found:
        return f"{base_title} — {' | '.join(found[:2])}"
    return base_title


def _format_letter_evidence(selected_experiences: list, selected_projects: list, limit_per_exp: int = 4) -> str:
    lines = []
    for exp in selected_experiences[:3]:
        lines.append(f"### {exp.get('company', '')} — {_display_role_for_career_stage(exp.get('role', exp.get('title', '')))} — {exp.get('duration', exp.get('period', ''))}")
        delivered = exp.get('what_was_delivered', {}).get('for_rh', exp.get('description', ''))
        if delivered:
            lines.append(f"Livré: {delivered}")
        for b in _get_bullets(exp)[:limit_per_exp]:
            fact = " | ".join(x for x in [b.get('action',''), b.get('result',''), b.get('tech_proof','')] if x)
            if fact.strip():
                lines.append(f"- {fact}")
        lines.append("")
    if selected_projects:
        lines.append("### Projets utilisables")
        for proj in selected_projects[:2]:
            lines.append(f"- {proj.get('name','')}: {proj.get('what_was_built') or proj.get('description', '')}")
            for b in _get_bullets(proj)[:2]:
                lines.append(f"  - {b.get('action', '')}")
    return "\n".join(lines).strip()


class ContextBuilder:
    """Prépare le contexte filtré et formaté pour les prompts LLM."""

    def __init__(self, profile: dict):
        self.profile = profile

    def _experiences(self) -> list[dict]:
        return _profile_experiences(self.profile)

    def _projects(self) -> list[dict]:
        return _profile_projects(self.profile)

    def get_selected_experiences(self, selected_ids: list) -> list:
        id_map = {e["id"]: e for e in self._experiences()}
        return [id_map[eid] for eid in selected_ids if eid in id_map]

    def get_selected_projects(self, selected_ids: list) -> list:
        id_map = {p["id"]: p for p in self._projects()}
        return [id_map[pid] for pid in selected_ids if pid in id_map]

    def format_experience_for_prompt(self, exp: dict, dominant_role: str,
                                      required_keywords: set | None = None,
                                      jd_norm: str = "") -> str:
        lines = [
            f"### {exp.get('company', '')} | {_display_role_for_career_stage(exp.get('role', exp.get('title', '')))} | {exp.get('duration', exp.get('period', ''))}",
            f"Problème métier résolu : {exp.get('business_problem', exp.get('context', ''))}",
            f"Ce qui a été livré (pour RH) : {exp.get('what_was_delivered', {}).get('for_rh', exp.get('description', ''))}",
            f"Ce qui a été livré (technique) : {exp.get('what_was_delivered', {}).get('for_tech', '')}",
            "",
            "BULLETS DISPONIBLES — notation de pertinence pour cette offre :",
            "(★★★ = très pertinent pour ce poste | ★★☆ = pertinent | ★☆☆ = contexte uniquement)",
        ]
        required_keywords = required_keywords or set()
        for b in _get_bullets(exp):
            bullet_text = _norm(f"{b.get('context', '')} {b.get('action', '')} {b.get('result', '')} {b.get('tech_proof', '')}")
            kw_hits = sum(1 for kw in required_keywords if kw in bullet_text)
            jd_sim = SequenceMatcher(None, bullet_text[:300], jd_norm[:300]).ratio() if jd_norm else 0
            relevance = kw_hits * 3 + int(jd_sim * 10)
            if relevance >= 6:
                stars = "★★★ PRIORITÉ HAUTE — utiliser en premier"
            elif relevance >= 3:
                stars = "★★☆ PERTINENT — inclure si place"
            else:
                stars = "★☆☆ SECONDAIRE — inclure seulement si besoin de contexte"
            lines.append(f"  [{stars}]")
            lines.append(f"  CONTEXTE: {b.get('context', '')}")
            lines.append(f"  ACTION: {b.get('action', '')}")
            lines.append(f"  RÉSULTAT: {b.get('result', '')}")
            lines.append(f"  PREUVE TECH: {b.get('tech_proof', '')}")
            lines.append("")
        stack = exp.get("stack", [])
        if stack:
            lines.append(f"Stack prouvé : {', '.join(_flatten(stack)[:20])}")
        lines.append("⚠️ RÈGLE BULLETS : utiliser en priorité les ★★★, puis ★★☆. 3-4 bullets maximum par expérience.")
        lines.append("⚠️ RÈGLE RÉDACTION : Intégrer les technologies directement et naturellement dans le texte de l'action. Ne JAMAIS copier-coller de bloc technologique ou de phrase redondante entre parenthèses à la fin de chaque bullet.")
        return "\n".join(lines)


    def format_project_for_prompt(self, proj: dict) -> str:
        context_line = f"Contexte: {proj.get('context', '')}" if proj.get('context') else ""
        result_line = f"Résultat notable: {proj.get('result', '')}" if proj.get('result') else ""
        problem = proj.get("business_problem") or proj.get("description", "")
        built = proj.get("what_was_built") or proj.get("description", "")
        lines = [
            f"### {proj.get('name', '')} ({proj.get('date', proj.get('year', ''))})",
            f"Problème résolu : {problem}",
            f"Ce qui a été construit : {built}",
        ]
        if context_line:
            lines.append(context_line)
        if result_line:
            lines.append(result_line)
        lines += [
            "",
            "BULLETS DISPONIBLES (CONTEXTE → ACTION → RÉSULTAT) :",
            "(Injecter le contexte métier dans le bullet final pour le persona rh_senior_maroc)",
        ]
        for b in _get_bullets(proj):
            ctx = b.get("context", "").strip()
            action = b.get("action", "").strip()
            result = b.get("result", "").strip()
            tech = b.get("tech_proof", "").strip()
            if ctx:
                lines.append(f"  CONTEXTE: {ctx}")
            lines.append(f"  ACTION: {action}")
            if result:
                lines.append(f"  RÉSULTAT: {result}")
            if tech:
                lines.append(f"  PREUVE TECH: {tech}")
            lines.append("")
        stack = proj.get("stack", [])
        if stack:
            lines.append(f"Stack prouvé : {', '.join(_flatten(stack)[:15])}")
        return "\n".join(lines)

    def format_narrative_hooks(self, dominant_role: str) -> str:
        hooks = self.profile.get("narrative_hooks") or {
            "ai_engineer": {
                "hook": "Ingénieure IA & Software avec expérience en plateformes analytiques et pipelines ML.",
                "proof": "Orchestrateur LangGraph 10 nœuds, 3 agents sectoriels, pipeline ML (Scikit-learn/XGBoost/LightGBM + MLflow), moteur prédictif 93% accuracy livré en 48h.",
                "differentiator": "Double lecture ingénierie logicielle et IA appliquée, adaptée à un profil junior.",
            },
            "software_engineer": {
                "hook": "Ingénieure Software avec expériences backend, frontend et data.",
                "proof": "Microservices Java Spring Boot, portail full-stack, plateforme analytique.",
                "differentiator": "Capacité à cadrer un besoin, choisir une architecture adaptée et livrer des composants exploitables.",
            },
            "data_engineer": {
                "hook": "Ingénieure Data & Software avec expérience en pipelines ETL et qualité de données.",
                "proof": "Pipeline ETL bancaire Airflow/DBT, architecture Medallion MinIO/DuckDB, MLflow tracking complet.",
                "differentiator": "Expérience sur la chaîne data : ingestion, transformation, ML et visualisation.",
            },
        }
        role_key = dominant_role if dominant_role in hooks else "software_engineer"
        h = hooks.get(role_key, hooks["software_engineer"])
        return f"""MATÉRIAUX NARRATIVE POUR LE PROFIL (adapter, ne pas copier) :
Hook : {h.get('hook', '')}
Preuve : {h.get('proof', '')}
Différenciateur : {h.get('differentiator', '')}"""

    def format_audit_summary(self, analysis: dict) -> str:
        match = analysis["match"]
        role = analysis["role"]
        lines = [
            f"━━━ AUDIT D'ALIGNEMENT ━━━",
            f"Rôle dominant détecté : {role['dominant']} (confiance : {int(role['confidence']*100)}%)",
            f"Rôle secondaire : {role.get('secondary', 'aucun')}",
            f"Hybride : {'oui' if role['is_hybrid'] else 'non'}",
            f"",
            f"Score global : {match['global_score']}/100",
            f"Décision : {match['decision']}",
            f"Rationale : {match['rationale']}",
            f"Couverture keywords : {match['keyword_coverage_pct']}%",
            f"",
            f"Top keywords requis : {', '.join(analysis['required_keywords'][:12])}",
            f"",
            "Scores expériences :",
        ]
        for e in analysis["exp_scores"]:
            lines.append(f"  {e['company']}: {e['score']}/100 — hits: {', '.join(e['direct_hits'][:5])}")
        lines.append("\nScores projets :")
        for p in analysis["proj_scores"][:3]:
            lines.append(f"  {p['name'][:40]}: {p['score']}/100")
        return "\n".join(lines)
