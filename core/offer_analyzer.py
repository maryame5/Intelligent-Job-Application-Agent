"""
core/offer_analyzer.py
======================
Moteur d'analyse déterministe de l'offre d'emploi :
- Détection du rôle dominant et du profil cible
- Détection de la persona recruteur
- Détection d'écart de séniorité
- Pondération et scoring des expériences / projets avec bonus sémantiques
- Stratégie et positionnement de candidature
"""

from __future__ import annotations

import re
from typing import Any

from core.lexicons import (
    ROLE_DETECTION_SIGNALS,
    COMPANY_PERSONA_SIGNALS,
    SENIOR_JOB_PATTERNS,
    JUNIOR_PROFILE_MARKERS,
    CAREER_STAGE,
    PRIMARY_PROFESSIONAL_IDENTITY,
    SECONDARY_PROFESSIONAL_IDENTITIES,
)
from core.helpers import (
    _norm,
    _flatten,
    _profile_experiences,
    _profile_projects,
    _display_role_for_career_stage,
)

from matching.semantic_matcher import SemanticMatcher



def build_application_context(analysis: dict, external_match_score: int | None = None) -> dict:
    """
    Classe toute offre en A/B/C/D sans jamais la rejeter automatiquement.
    """
    score = int(analysis.get("match", {}).get("global_score", 0) or 0)
    score = max(0, min(100, score))
    seniority_mismatch = bool(analysis.get("seniority", {}).get("has_mismatch", False))

    if score >= 75 and not seniority_mismatch:
        return {
            "priority": "A",
            "status": "Strong Match",
            "apply_mode": "direct_application",
            "risk_level": "low",
            "cv_positioning": "CV très ciblé sur les preuves directes du profil.",
            "letter_positioning": "Lettre directe, orientée valeur immédiate.",
            "time_budget_minutes": 25,
            "auto_apply_recommended": True,
        }
    if score >= 55 and not seniority_mismatch:
        return {
            "priority": "B",
            "status": "Medium Match",
            "apply_mode": "adapted_application",
            "risk_level": "medium",
            "cv_positioning": "CV adapté, en séparant preuves directes et compétences transférables.",
            "letter_positioning": "Lettre ciblée sur les expériences les plus proches du poste.",
            "time_budget_minutes": 18,
            "auto_apply_recommended": True,
        }
    if seniority_mismatch or score >= 35:
        return {
            "priority": "C",
            "status": "Opportunistic Match",
            "apply_mode": "honest_opportunistic",
            "risk_level": "high",
            "cv_positioning": "CV opportuniste mais honnête : profil junior solide, preuves transférables, aucune promesse senior.",
            "letter_positioning": "Lettre confiante qui reconnaît implicitement la trajectoire junior sans s'excuser.",
            "time_budget_minutes": 10,
            "auto_apply_recommended": False,
        }
    return {
        "priority": "D",
        "status": "Low Match",
        "apply_mode": "light_apply",
        "risk_level": "very_high",
        "cv_positioning": "Candidature légère : CV générique amélioré, pas de sur-personnalisation ni d'invention.",
        "letter_positioning": "Lettre courte, factuelle, orientée motivation et capacité d'apprentissage.",
        "time_budget_minutes": 5,
        "auto_apply_recommended": False,
    }


ROLE_POSITIONING_PLAYBOOK = {
    "software_engineer": {
        "label": "Software Engineering",
        "angle": "ingénieure software orientée développement applicatif, APIs robustes, architecture backend/frontend et intégration",
        "profile_focus": "Développement logiciel, APIs REST, microservices, bases de données relationnelles, sécurité et tests.",
        "proof_focus": "Mettre en valeur les expériences et projets orientés développement, architecture logicielle et APIs.",
        "avoid": "ne pas encombrer le CV avec des outils sans rapport avec l'offre si elle ne demande que du software.",
    },
    "frontend_fullstack_ai_product": {
        "label": "Full-Stack Product / Web",
        "angle": "ingénieure full-stack orientée application web produit, UX, APIs et intégration de fonctionnalités intelligentes",
        "profile_focus": "React, TypeScript, frontend moderne, backend API, gestion d'état et dashboards applicatifs.",
        "proof_focus": "Mettre en avant les réalisations UI/UX, les intégrations frontend-backend et les dashboards.",
        "avoid": "ne pas transformer l'offre en poste ML pur si elle concerne le développement produit web.",
    },
    "ai_engineer": {
        "label": "AI / Machine Learning Engineering",
        "angle": "ingénieure IA & Software capable de concevoir et intégrer des modèles, pipelines et agents intelligents",
        "profile_focus": "ML, pipelines d'entraînement/inférence, LLM/agents, validation et intégration d'IA dans les systèmes.",
        "proof_focus": "Mettre en valeur les projets et expériences démontrant du Machine Learning, des agents IA et du tracking de modèles.",
        "avoid": "ne pas prétendre maîtriser des frameworks absents de profil.json.",
    },
    "data_engineer": {
        "label": "Data Engineering",
        "angle": "ingénieure Data & Software orientée pipelines de données, modélisation, qualité et valorisation analytique",
        "profile_focus": "Pipelines de données, SQL, modélisation, stockage, qualité de données et automatisation.",
        "proof_focus": "Mettre en valeur les pipelines d'ingestion/transformation, les architectures de stockage et l'analyse de données.",
        "avoid": "ne pas négliger la robustesse logicielle et l'automatisation des flux.",
    },
    "qa_testing": {
        "label": "QA / Software Testing",
        "angle": "ingénieure software orientée qualité logicielle, validation d'APIs, debugging et tests fonctionnels",
        "profile_focus": "Tests d'APIs, validation de données, scénarios end-to-end, conformité et documentation.",
        "proof_focus": "Mettre en valeur la validation des flux, les scénarios de test et le contrôle qualité.",
        "avoid": "ne pas revendiquer d'outils d'automatisation non pratiqués.",
    },
    "cloud_devops": {
        "label": "Cloud / DevOps",
        "angle": "ingénieure software orientée conteneurisation, déploiement, observabilité et services distribués",
        "profile_focus": "Docker, conteneurisation, architectures distribuées, configuration et déploiement.",
        "proof_focus": "Mettre en valeur les architectures conteneurisées, les microservices et les configurations d'environnements.",
        "avoid": "ne pas prétendre maîtriser des infrastructures cloud non attestées.",
    },
    "consulting": {
        "label": "IT / Technology Consulting",
        "angle": "ingénieure IT capable de cadrer un besoin métier, structurer une solution technique et communiquer avec les équipes",
        "profile_focus": "Analyse fonctionnelle, formalisation de besoin, documentation technique, relation métier et dashboards.",
        "proof_focus": "Mettre en valeur la compréhension des use-cases métier, l'architecture et la clarté de restitution.",
        "avoid": "ne pas surcharger de jargon purement théorique.",
    },
    "general": {
        "label": "Software Engineering",
        "angle": "ingénieure software polyvalente, solide sur le développement applicatif, la gestion des données et l'intégration",
        "profile_focus": "Socle software engineering, APIs, bases de données, structuration et bonnes pratiques de code.",
        "proof_focus": "Mettre en avant les compétences centrales et la capacité d'adaptation.",
        "avoid": "ne pas forcer de spécialisation artificielle si l'offre est généraliste.",
    },
}


def _infer_positioning_title(dominant_role: str, job_title: str, job_description: str) -> str:
    text = _norm(f"{job_title} {job_description}")
    if dominant_role == "frontend_fullstack_ai_product":
        if "next" in text:
            return "Ingénieure Full-Stack React/TypeScript orientée applications AI-first"
        return "Ingénieure Full-Stack & Software"
    if dominant_role == "ai_engineer":
        return "Ingénieure IA & Software"
    if dominant_role == "data_engineer":
        return "Ingénieure Data & Software"
    if dominant_role == "qa_testing":
        return "Ingénieure Software orientée QA, API Testing & Data Quality"
    if dominant_role == "consulting":
        return "Ingénieure IT & Technology Consulting"
    if dominant_role == "cloud_devops":
        return "Ingénieure Software orientée Cloud & DevOps"

    has_java = "java" in text or "spring" in text or "j2ee" in text
    has_angular = "angular" in text
    has_react = "react" in text or "next" in text
    has_python = "python" in text or "fastapi" in text
    if has_java and has_angular:
        return "Ingénieure Full-Stack Java/Angular"
    if has_java and has_react:
        return "Ingénieure Full-Stack Java/React"
    if has_react:
        return "Ingénieure Full-Stack React/TypeScript"
    if has_java:
        return "Ingénieure Software Backend Java & Spring Boot"
    if has_python:
        return "Ingénieure Software Backend Python"
    return "Ingénieure Software Full-Stack"


def detect_profile_mode(dominant_role: str, job_title: str, job_description: str) -> str:
    text = _norm(f"{job_title} {job_description}")
    if dominant_role == "ai_engineer":
        return "AI_ENGINEER"
    if dominant_role == "data_engineer":
        return "DATA_ENGINEER"
    if dominant_role == "qa_testing":
        return "QA_ENGINEER"
    if dominant_role == "cloud_devops":
        return "CLOUD_DEVOPS_ENGINEER"
    if dominant_role == "consulting":
        return "CONSULTING_ENGINEER"
    if any(k in text for k in ["full stack", "full-stack", "frontend", "angular", "react", "next"]):
        return "FULLSTACK_ENGINEER"
    if any(k in text for k in ["backend", "back-end", "java", "j2ee", "spring boot", "api rest", "rest api"]):
        return "BACKEND_ENGINEER"
    return "SOFTWARE_ENGINEER"


def _positioning_title_for_mode(profile_mode: str, dominant_role: str, job_title: str, job_description: str) -> str:
    text = _norm(f"{job_title} {job_description}")
    if profile_mode == "AI_ENGINEER":
        return "Ingénieure IA & Software"
    if profile_mode == "DATA_ENGINEER":
        return "Ingénieure Data & Software"
    if profile_mode == "FULLSTACK_ENGINEER":
        if "java" in text and "angular" in text:
            return "Ingénieure Full-Stack & Software"
        return "Ingénieure Logiciel & Software"
    if profile_mode == "BACKEND_ENGINEER":
        return "Ingénieure Backend & Software"
    if profile_mode == "QA_ENGINEER":
        return "Ingénieure Software orientée QA, API Testing & Data Quality"
    if profile_mode == "CLOUD_DEVOPS_ENGINEER":
        return "Ingénieure Software orientée Cloud & DevOps"
    if profile_mode == "CONSULTING_ENGINEER":
        return "Ingénieure IT & Technology Consulting"
    return _infer_positioning_title(dominant_role, job_title, job_description)


def _experience_positioning_bias(exp: dict, profile_mode: str, jd_norm: str) -> int:
    signals = exp.get("role_signal", [])
    bias = 0
    mode_lower = profile_mode.lower()

    for sig in signals:
        if sig.lower() in mode_lower or mode_lower in sig.lower():
            bias += 25
            break

    stack_raw = exp.get("stack", [])
    stack_flat = _flatten(list(stack_raw.values()) if isinstance(stack_raw, dict) else stack_raw)
    for tech in stack_flat:
        tech_norm = _norm(str(tech))
        if len(tech_norm) >= 3 and tech_norm in jd_norm:
            bias += 4

    return min(bias, 50)


def _project_positioning_bias(proj: dict, profile_mode: str, jd_norm: str) -> int:
    signals = proj.get("role_signal", [])
    bias = 0
    mode_lower = profile_mode.lower()

    for sig in signals:
        if sig.lower() in mode_lower or mode_lower in sig.lower():
            bias += 25
            break

    stack = proj.get("stack", [])
    for tech in _flatten(stack):
        tech_norm = _norm(str(tech))
        if len(tech_norm) >= 3 and tech_norm in jd_norm:
            bias += 5

    return min(bias, 50)


def build_offer_positioning(analysis: dict, job_title: str, job_description: str) -> dict:
    """Produit la boussole de candidature utilisée par le CV et la lettre."""
    role = analysis.get("role", {})
    dominant = role.get("dominant", "software_engineer")
    profile_mode = detect_profile_mode(dominant, job_title, job_description)
    playbook = ROLE_POSITIONING_PLAYBOOK.get(dominant, ROLE_POSITIONING_PLAYBOOK["software_engineer"])
    seniority = analysis.get("seniority", {})
    title = seniority.get("recommended_title") or _positioning_title_for_mode(
        profile_mode, dominant, job_title, job_description
    )

    exp_scores = analysis.get("exp_scores", [])
    proj_scores = analysis.get("proj_scores", [])
    primary_exp = exp_scores[0] if exp_scores else {}
    secondary_exp = exp_scores[1] if len(exp_scores) > 1 else {}
    primary_project = proj_scores[0] if proj_scores else {}

    return {
        "target_title": title,
        "career_stage": CAREER_STAGE,
        "profile_mode": profile_mode,
        "primary_identity": PRIMARY_PROFESSIONAL_IDENTITY,
        "secondary_identities": SECONDARY_PROFESSIONAL_IDENTITIES,
        "role_label": playbook["label"],
        "angle": playbook["angle"],
        "profile_focus": playbook["profile_focus"],
        "proof_focus": playbook["proof_focus"],
        "avoid": playbook["avoid"],
        "primary_experience": primary_exp.get("company", ""),
        "secondary_experience": secondary_exp.get("company", ""),
        "primary_project": primary_project.get("name", ""),
        "keywords_to_lead_with": analysis.get("required_keywords", [])[:10],
    }


def format_offer_positioning(positioning: dict) -> str:
    keywords = ", ".join(positioning.get("keywords_to_lead_with", [])) or "aucun keyword prioritaire détecté"
    return f"""
━━━ POSITIONNEMENT OFFRE — BOUSSOLE OBLIGATOIRE ━━━
Titre cible : {positioning.get('target_title', '')}
Career stage : {positioning.get('career_stage', '')}
Profile mode : {positioning.get('profile_mode', '')}
Identité principale : {positioning.get('primary_identity', '')}
Identités secondaires : {', '.join(positioning.get('secondary_identities', []))}
Famille de rôle : {positioning.get('role_label', '')}
Angle à défendre : {positioning.get('angle', '')}
Profil CV : {positioning.get('profile_focus', '')}
Preuves à privilégier : {positioning.get('proof_focus', '')}
Expérience principale selon scoring : {positioning.get('primary_experience', '')}
Expérience secondaire selon scoring : {positioning.get('secondary_experience', '')}
Projet principal selon scoring : {positioning.get('primary_project', '')}
Keywords à faire apparaître tôt si prouvés : {keywords}
À éviter : {positioning.get('avoid', '')}

RÈGLE : tout le document doit servir ce positionnement. Si une preuve est impressionnante mais moins alignée avec l'offre, elle devient secondaire.
"""


def _extract_jd_candidate_terms(job_description: str, job_title: str) -> set[str]:
    """Extrait les mots-clés ATS depuis le texte brut de l'offre."""
    text = f"{job_title}\n{job_description}"
    candidates: set[str] = set()

    candidates.update(re.findall(r"\b[A-Z]{2,6}\b", text))
    candidates.update(re.findall(r"\b\w*[A-Z]\w*[A-Z]\w*\b", text))
    candidates.update(re.findall(r"\b[A-Za-z]+(?:[.\-/#+][A-Za-z0-9]+)+\b", text))
    candidates.update(re.findall(r"bac\s*\+\s*\d", text, re.IGNORECASE))

    trigger = (
        r"\b(?:ma\u00eetrise de|ma\u00eetrise d'|connaissance de|connaissance d'|"
        r"exp\u00e9rience (?:en|avec|de)|comp\u00e9tences? (?:en|requises?)|"
        r"familiar(?:ity)? with|proficiency in|experience (?:in|with))"
        r"\s*[:\-]?\s*([^.;\n]{3,60})"
    )
    for m in re.findall(trigger, text, re.IGNORECASE):
        m = m.rsplit(" ", 1)[0] if len(m) >= 60 else m
        for piece in re.split(r",| et | and |/", m):
            piece = piece.strip(" .")
            if 2 <= len(piece) <= 40:
                candidates.add(piece)

    return {_norm(c) for c in candidates if len(_norm(c)) >= 2}


class OfferAnalyzer:
    """
    Analyse déterministe de l'offre :
    - Détecte le rôle dominant (AI / Data / Software / QA / etc.)
    - Détecte la persona recruteur (startup / tech global / RH Maroc)
    - Calcule les scores d'alignement par expérience et projet
    - Produit un audit structuré pour le prompt LLM
    """

    def __init__(self, profile: dict):
        self.profile = profile
        self.semantic = SemanticMatcher()

    def detect_dominant_role(self, job_title: str, job_description: str) -> dict:
        text = _norm(f"{job_title} {job_description}")
        scores = {}
        for role, signals in ROLE_DETECTION_SIGNALS.items():
            score = sum(6 for kw in signals["strong"] if kw in text)
            score += sum(2 for kw in signals["medium"] if kw in text)
            for kw in signals["strong"]:
                if kw in _norm(job_title):
                    score += 4
            scores[role] = score

        if all(v == 0 for v in scores.values()):
            dominant = "general"
        else:
            dominant = max(scores, key=scores.get)

        total = sum(scores.values()) or 1
        confidence = (scores[dominant] / total) if dominant in scores and scores[dominant] > 0 else 0.0

        sorted_roles = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        secondary = sorted_roles[1][0] if len(sorted_roles) > 1 and sorted_roles[1][1] > 0 else None

        return {
            "dominant": dominant,
            "secondary": secondary,
            "scores": scores,
            "confidence": round(confidence, 2),
            "is_hybrid": confidence < 0.55 and secondary is not None,
        }

    def detect_company_persona(self, job_title: str, job_description: str, company_name: str) -> str:
        text = _norm(f"{job_title} {job_description} {company_name}")
        persona_scores = {}
        for ptype, config in COMPANY_PERSONA_SIGNALS.items():
            persona_scores[ptype] = sum(1 for kw in config["keywords"] if kw in text)

        best = max(persona_scores, key=persona_scores.get)
        if persona_scores[best] == 0:
            if any(kw in text for kw in ["maroc", "morocc", "casa", "rabat"]):
                return "rh_senior_maroc"
            return "senior_ta_tech"
        return COMPANY_PERSONA_SIGNALS[best]["persona"]

    def detect_seniority_mismatch(self, job_title: str, job_description: str) -> dict:
        text = _norm(f"{job_title} {job_description}")
        profile_text = _norm(str(self.profile))

        senior_required = any(p in text for p in SENIOR_JOB_PATTERNS)
        junior_candidate = any(p in profile_text for p in JUNIOR_PROFILE_MARKERS)

        if senior_required and junior_candidate:
            role_info = self.detect_dominant_role(job_title, job_description)
            recommended = self._infer_honest_title(role_info["dominant"], job_title, job_description)
            return {
                "has_mismatch": True,
                "recommended_title": recommended,
                "strategy": "opportunity_framing",
            }
        return {
            "has_mismatch": False,
            "recommended_title": None,
            "strategy": "direct_match",
        }

    def _infer_honest_title(self, dominant_role: str, job_title: str, job_description: str) -> str:
        return _infer_positioning_title(dominant_role, job_title, job_description)

    def _extract_keyword_weights(self, job_title: str, job_description: str) -> dict[str, int]:
        title_norm = _norm(job_title)
        jd_norm = _norm(job_description)

        all_techs = set()
        for signals in ROLE_DETECTION_SIGNALS.values():
            all_techs.update(signals["strong"])
            all_techs.update(signals["medium"])

        for exp in _profile_experiences(self.profile):
            all_techs.update(_norm(t) for t in _flatten(exp.get("stack", [])))
        for proj in _profile_projects(self.profile):
            all_techs.update(_norm(t) for t in _flatten(proj.get("stack", [])))

        weights = {}
        for tech in sorted(all_techs, key=len, reverse=True):
            if len(tech) < 2:
                continue
            pattern = r"(?<![a-z0-9+.#])" + re.escape(tech) + r"(?![a-z0-9+.#])"
            count_jd = len(re.findall(pattern, jd_norm))
            count_title = len(re.findall(pattern, title_norm))
            if count_jd > 0 or count_title > 0:
                weights[tech] = count_jd + (10 * count_title)
        return weights

    def extract_required_keywords(self, job_title: str, job_description: str) -> list[str]:
        weights = self._extract_keyword_weights(job_title, job_description)
        jd_terms = _extract_jd_candidate_terms(job_description, job_title)
        for t in jd_terms:
            weights.setdefault(t, 1)
        sorted_kws = sorted(weights.items(), key=lambda x: x[1], reverse=True)
        return [kw[0] for kw in sorted_kws[:35]]

    def score_experiences(self, keyword_weights: dict[str, int], role_dominant: str, job_description: str) -> list[dict]:
        results = []
        jd_norm = _norm(job_description)
        required_keywords = set(keyword_weights.keys())
        profile_mode = detect_profile_mode(role_dominant, job_description.split("\n")[0][:80], job_description)

        for exp in _profile_experiences(self.profile):
            stack_raw = exp.get("stack", {})
            if isinstance(stack_raw, dict):
                stack_flat = _flatten(list(stack_raw.values()))
            else:
                stack_flat = _flatten(stack_raw)
            stack_norm = {_norm(t) for t in stack_flat}
            exp_text = _norm(str(exp))

            direct_hits = stack_norm & required_keywords
            score = sum(keyword_weights[kw] * 10 for kw in direct_hits)

            text_hits = {kw for kw in required_keywords if kw in exp_text and kw not in direct_hits}
            score += sum(keyword_weights[kw] * 4 for kw in text_hits)

            if role_dominant in exp.get("role_signal", []):
                score += 30

            TEST_SIGNALS = {"junit", "mockito", "tdd", "tests unitaires", "test unitaire",
                            "tests d'integration", "test d'integration", "jmockit", "selenium",
                            "testng", "quality", "qualite", "qualité"}
            jd_mentions_tests = TEST_SIGNALS & set(jd_norm.split()) or any(s in jd_norm for s in TEST_SIGNALS)
            exp_proves_tests = bool(TEST_SIGNALS & stack_norm) or any(s in exp_text for s in TEST_SIGNALS)
            if jd_mentions_tests and exp_proves_tests:
                score += 20

            semantic_sim = self.semantic.score_item(self._offer_embedding, exp.get("id", ""))
            score += int(20 * semantic_sim)
            score += _experience_positioning_bias(exp, profile_mode, jd_norm)

            results.append({
                "id": exp["id"],
                "company": exp.get("company", ""),
                "role": _display_role_for_career_stage(exp.get("role", exp.get("title", ""))),
                "score": min(score, 100),
                "raw_score": score,
                "semantic_similarity": round(semantic_sim, 3),
                "profile_mode_bias": _experience_positioning_bias(exp, profile_mode, jd_norm),
                "direct_hits": sorted(direct_hits),
                "text_hits": sorted(text_hits)[:5],
            })

        results.sort(key=lambda x: (x["raw_score"], x["profile_mode_bias"]), reverse=True)
        return results

    def score_projects(self, keyword_weights: dict[str, int], role_dominant: str, job_description: str = "") -> list[dict]:
        results = []
        jd_norm = _norm(job_description)
        required_keywords = set(keyword_weights.keys())
        profile_mode = detect_profile_mode(role_dominant, "", job_description)

        for proj in _profile_projects(self.profile):
            stack_norm = {_norm(t) for t in _flatten(proj.get("stack", []))}
            proj_text = _norm(str(proj))

            direct_hits = stack_norm & required_keywords
            score = sum(keyword_weights[kw] * 12 for kw in direct_hits)

            text_hits = {kw for kw in required_keywords if kw in proj_text and kw not in direct_hits}
            score += sum(keyword_weights[kw] * 4 for kw in text_hits)

            if role_dominant in proj.get("role_signal", []):
                score += 25

            proj_category = _norm(proj.get("category", ""))
            for kw in required_keywords:
                if len(kw) > 3 and kw in proj_category:
                    score += 10

            TEST_SIGNALS = {"junit", "mockito", "tdd", "tests unitaires", "test unitaire",
                            "tests d'integration", "test d'integration", "jmockit", "selenium",
                            "testng", "quality", "qualite", "qualité"}
            jd_mentions_tests = TEST_SIGNALS & set(jd_norm.split()) or any(s in jd_norm for s in TEST_SIGNALS)
            proj_proves_tests = bool(TEST_SIGNALS & stack_norm) or any(s in proj_text for s in TEST_SIGNALS)
            if jd_mentions_tests and proj_proves_tests:
                score += 20

            semantic_sim = self.semantic.score_item(self._offer_embedding, proj.get("id", ""))
            score += int(20 * semantic_sim)

            score = int(score * 0.9)
            project_bias = _project_positioning_bias(proj, profile_mode, jd_norm)
            score += project_bias

            results.append({
                "id": proj["id"],
                "name": proj["name"],
                "score": min(score, 100),
                "raw_score": score,
                "semantic_similarity": round(semantic_sim, 3),
                "profile_mode_bias": project_bias,
                "direct_hits": sorted(direct_hits),
                "text_hits": sorted(text_hits)[:3],
            })

        results.sort(key=lambda x: (x["raw_score"], x["profile_mode_bias"]), reverse=True)
        return results

    def compute_match_score(self, exp_scores: list, proj_scores: list, required_keywords: list) -> dict:
        best_exp = exp_scores[0]["score"] if exp_scores else 0
        top3_avg = sum(x["score"] for x in exp_scores[:3]) / max(len(exp_scores[:3]), 1)

        all_hits: set = set()
        for e in exp_scores:
            all_hits.update(e["direct_hits"])
            all_hits.update(e["text_hits"])
        for p in proj_scores:
            all_hits.update(p["direct_hits"])
            all_hits.update(p.get("text_hits", []))
        keyword_coverage = len(all_hits & set(required_keywords)) / max(len(required_keywords), 1)

        global_score = int(0.45 * best_exp + 0.30 * top3_avg + 0.25 * keyword_coverage * 100)

        if global_score >= 70:
            decision = "✅ CANDIDATER"
            rationale = "Alignement fort — le profil couvre les exigences clés de l'offre."
        elif global_score >= 50:
            decision = "⚡ CANDIDATER (adapter le pitch)"
            rationale = "Alignement partiel — mettre en avant les expériences transférables et l'apprentissage rapide."
        elif global_score >= 35:
            decision = "⚠️ RISQUÉ — Candidature opportuniste"
            rationale = "Écart notable — positionner comme profil junior ambitieux avec preuves concrètes. Risque de refus élevé."
        else:
            decision = "❌ DÉCONSEILLÉ"
            rationale = "Trop peu d'alignement direct — investir ce temps ailleurs."

        return {
            "global_score": global_score,
            "decision": decision,
            "rationale": rationale,
            "keyword_coverage_pct": round(keyword_coverage * 100),
        }

    def run_full_analysis(self, job_title: str, job_description: str, company_name: str, external_match_score: int | None = None) -> dict:
        role_info = self.detect_dominant_role(job_title, job_description)
        persona = self.detect_company_persona(job_title, job_description, company_name)
        seniority = self.detect_seniority_mismatch(job_title, job_description)

        offer_text = f"{job_title} {job_description}"
        self.semantic.precompute_profile(
            _profile_experiences(self.profile),
            _profile_projects(self.profile),
        )
        self._offer_embedding = self.semantic.get_offer_embedding(offer_text)

        kw_weights = self._extract_keyword_weights(job_title, job_description)
        for t in _extract_jd_candidate_terms(job_description, job_title):
            kw_weights.setdefault(t, 1)
        required_kw = sorted(kw_weights.keys(), key=lambda x: kw_weights[x], reverse=True)

        exp_scores = self.score_experiences(kw_weights, role_info["dominant"], job_description)
        proj_scores_raw = self.score_projects(kw_weights, role_info["dominant"], job_description)

        covered_by_exps = set()
        for e in exp_scores[:2]:
            covered_by_exps.update(e.get("direct_hits", []))

        proj_scores = []
        for p in proj_scores_raw:
            p_hits = set(p.get("direct_hits", []))
            new_gaps = p_hits - covered_by_exps
            complementarity_bonus = sum(20 for kw in new_gaps if kw_weights.get(kw, 0) >= 2)
            p["raw_score"] = p.get("raw_score", p["score"]) + complementarity_bonus
            p["score"] = min(100, p["raw_score"])
            p["is_complementary"] = complementarity_bonus > 0
            proj_scores.append(p)

        proj_scores.sort(key=lambda x: (x.get("raw_score", x["score"]), x.get("profile_mode_bias", 0)), reverse=True)

        match = self.compute_match_score(exp_scores, proj_scores, required_kw)

        deterministic_score = int(match["global_score"])
        match["deterministic_score"] = deterministic_score
        match["llm_score"] = external_match_score
        if external_match_score is not None:
            hybrid = round(0.5 * deterministic_score + 0.5 * int(external_match_score))
            match["global_score"] = max(0, min(100, hybrid))

        selected_exp_ids = [
            e["id"] for e in exp_scores
            if e["score"] >= 20 and "perception" not in _norm(e.get("company", ""))
        ][:3]

        core_ids_with_score = []
        for e in exp_scores:
            exp_id = e["id"]
            exp_raw = next((x for x in _profile_experiences(self.profile) if x.get("id") == exp_id), {})
            if exp_raw.get("always_feature") or role_info["dominant"] in exp_raw.get("role_signal", []):
                core_ids_with_score.append((exp_id, e["score"]))

        core_ids_with_score.sort(key=lambda x: x[1], reverse=True)
        for eid, _score in core_ids_with_score:
            if eid not in selected_exp_ids:
                selected_exp_ids.append(eid)
        selected_exp_ids = selected_exp_ids[:3]

        project_limit = 3 if role_info["dominant"] in {
            "ai_engineer", "data_engineer", "software_java", "software_engineer",
            "software_fullstack", "frontend_fullstack_ai_product",
        } else 2
        selected_proj_ids = [p["id"] for p in proj_scores[:project_limit] if p["score"] > 3]

        all_proven_hits: set[str] = set()
        for e in exp_scores:
            all_proven_hits.update(e.get("direct_hits", []))
        for p in proj_scores:
            all_proven_hits.update(p.get("direct_hits", []))

        true_missing = [kw for kw in required_kw if kw not in all_proven_hits]

        try:
            from profile.enrichment import resolve_gap_keywords, build_bridge_sentence
            resolved = resolve_gap_keywords(true_missing, self.profile, self.semantic)
            implied_skills_to_use = resolved["implied"]
            bridge_sentences = [
                build_bridge_sentence(b, self.profile) for b in resolved["bridgeable"]
            ]
            true_gap = resolved["true_gap"]
        except Exception:
            implied_skills_to_use, bridge_sentences, true_gap = [], [], list(true_missing)

        analysis = {
            "role": role_info,
            "persona": persona,
            "seniority": seniority,
            "required_keywords": required_kw,
            "exp_scores": exp_scores,
            "proj_scores": proj_scores,
            "match": match,
            "selected_exp_ids": selected_exp_ids,
            "selected_proj_ids": selected_proj_ids,
            "implied_skills_to_use": implied_skills_to_use,
            "bridge_sentences": bridge_sentences,
            "true_gap": true_gap,
        }
        analysis["positioning"] = build_offer_positioning(analysis, job_title, job_description)
        return analysis
