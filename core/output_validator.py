"""
core/output_validator.py
========================
Validateur déterministe d'intégrité et de conformité des documents générés (CV / Lettre).
Comprend le module d'auto-réparation (repair) ciblé via LLM.
"""

from __future__ import annotations

import re
from typing import Callable

from core.lexicons import FORBIDDEN_PHRASES, TECH_CANONICAL
from core.helpers import (
    _norm,
    _profile_corpus,
    _profile_strong_evidence_corpus,
    _build_profile_truth_corpus,
)


class OutputValidator:
    """Valide les documents générés et applique des règles strictes de non-hallucination."""

    def __init__(self, profile: dict):
        self.profile = profile

    def validate(self, output: str, analysis: dict, doc_type: str) -> list[str]:
        issues = []
        low = _norm(output)
        seniority = analysis.get("seniority", {})
        dominant_role = analysis.get("role", {}).get("dominant", "")
        corpus = _profile_corpus(self.profile)

        # Clichés et formules faibles
        for phrase in FORBIDDEN_PHRASES:
            if _norm(phrase) in low:
                issues.append(f"Formule interdite: '{phrase}'")

        if doc_type == "cv":
            cv_voice_patterns = [
                "elle construit", "elle a", "elle est", "la candidate",
                "son profil", "sa capacite", "ses competences", "a permis", "a donne", "a rendu",
                "disponible immediatement",
                "eleve ingenieur", "recherche d'un stage", "stage de fin d'etudes", "pfe",
                "j'ai livre", "j'ai travaille", "j'ai notamment", "j'ai contribue", "j'ai eu l'occasion",
            ]
            if any(pattern in low for pattern in cv_voice_patterns) or re.search(r"\belle\b", low):
                issues.append("Voix incorrecte dans le CV : supprimer la troisième personne, retirer la disponibilité et réécrire en style CV direct/professionnel.")
        if doc_type == "letter":
            letter_banned = ["j'ai permis", "j'ai livre", "j'ai construit", "j'ai donne", "j'ai rendu"]
            if any(pattern in low for pattern in letter_banned):
                issues.append("Lettre trop mécanique: remplacer 'j'ai permis/livré/construit/donné/rendu' par 'j'ai travaillé sur', 'j'ai notamment développé', 'j'ai contribué à'.")

        # JSON brut accidentel
        if '{"' in output or '"company"' in output:
            issues.append("JSON brut détecté dans le document")

        # Compétences non attestées dans le profil
        if doc_type == "cv":
            comp_match = re.search(r"competences techniques(.*?)(?:\n##|\Z)", low, re.DOTALL)
            if comp_match:
                comp_section = comp_match.group(1)
                strong_corpus = _profile_strong_evidence_corpus(self.profile)
                tech_vocab = set(TECH_CANONICAL.keys()) | set(v.lower() for v in TECH_CANONICAL.values())
                tech_vocab |= {"soap", "rest", "rest api", "web services"}
                for tech in tech_vocab:
                    tech_n = _norm(tech)
                    if len(tech_n) < 3:
                        continue
                    pattern = r"(?<![a-z0-9+.#])" + re.escape(tech_n) + r"(?![a-z0-9+.#])"
                    if re.search(pattern, comp_section) and not re.search(pattern, strong_corpus):
                        issues.append(
                            f"Compétence '{tech}' présente en COMPÉTENCES TECHNIQUES mais illustrée par "
                            "aucune bullet réelle d'expérience/projet: retirer ou justifier avant envoi."
                        )

        # QA : ne pas transformer une expérience de validation en QA automation confirmée sans preuve
        if dominant_role == "qa_testing":
            head = low[:800]
            if "qa automation" in head or "test automation engineer" in head or "ingenieure qa automation" in head:
                issues.append("Titre QA trop senior/automation: utiliser un titre Software orienté QA, API Testing & Data Quality, sans surévaluer l'expérience.")
            for tool in ["selenium", "junit", "testng", "cypress"]:
                if tool in low and tool not in corpus:
                    issues.append(f"Compétence QA non attestée dans profil.json: {tool}")

        # Anti-générique : le CV doit contenir des expériences du profil
        selected_companies = [e.get("company", "") for e in analysis.get("exp_scores", [])[:3]]
        selected_company_aliases = [_norm(company) for company in selected_companies if company]
        if doc_type == "cv" and selected_company_aliases and not any(c in low for c in selected_company_aliases if c):
            issues.append("Document trop générique: aucune expérience sélectionnée n'est citée")

        job_ctx = analysis.get("job_context") or {}
        target_company = job_ctx.get("company_name", "") or analysis.get("application_context", {}).get("company_name", "")
        if doc_type == "letter" and target_company:
            target_norm = _norm(target_company)
            occ = low.count(target_norm) if target_norm else 0
            if occ < 1:
                issues.append(f"Lettre trop générique: l'entreprise cible ({target_company}) doit être citée.")

        if "maroc" in low and "morocco" in low:
            issues.append("Doublon Maroc/Morocco")

        if seniority.get("has_mismatch"):
            senior_words = ["expérimenté", "senior", "confirmé", "référent technique", "lead architect"]
            profile_start = low[:600]
            for w in senior_words:
                if w in profile_start:
                    issues.append(f"Mot senior interdit dans le profil: '{w}'")

        # Vérification dynamique des stages prioritaires depuis profil.json
        if doc_type == "cv":
            truth_corpus = _build_profile_truth_corpus(self.profile)
            for comp_info in truth_corpus.get("companies", []):
                if comp_info.get("always_feature"):
                    aliases = comp_info.get("aliases", [])
                    if aliases and not any(alias in low for alias in aliases):
                        issues.append(f"Stage manquant dans le CV: {aliases[0]}")

        suspicious_metric_patterns = [
            r"en 5 ans de stages", r"5 ans de stages"
        ]
        for pat in suspicious_metric_patterns:
            if re.search(pat, low):
                issues.append(f"Métrique ou durée suspecte non attestée: {pat}")

        return issues

    def repair(self, doc: str, doc_type: str, issues: list[str], analysis: dict, llm_fn: Callable) -> str:
        if not issues:
            return doc
        issue_list = "\n".join(f"- {i}" for i in issues)
        cv_voice_repair = ""
        if doc_type.lower() == "cv":
            cv_voice_repair = """
- Réécrire toute phrase à la troisième personne en style CV direct.
- Remplacer les bullets commençant par "A permis / A donné / A rendu" par des verbes d'action concrets : "Conçu", "Développé", "Mis en place", "Implémenté", "Automatisé", "Intégré", "Structuré", "Optimisé".
- Garder un profil court, direct, professionnel, sans pronom.
- Retirer toute mention de disponibilité dans le PROFIL.
- Supprimer "PFE", "stage de fin d'études" et "recherche d'un stage" du CV final.
"""
        letter_voice_repair = ""
        if doc_type.lower() in ("lettre", "letter"):
            letter_voice_repair = """
- Remplacer "j'ai permis", "j'ai livré", "j'ai construit", "j'ai donné", "j'ai rendu" par des formulations naturelles.
- Garder un ton direct et professionnel.
"""
        prompt = f"""Corrige ce document de candidature UNIQUEMENT pour les problèmes listés ci-dessous.
Ne modifie rien d'autre. Ne réécris pas entièrement.

PROBLÈMES À CORRIGER :
{issue_list}

DOCUMENT ({doc_type}) :
{doc}

Règles :
- Supprimer les formules interdites listées
- Ne pas inventer de faits, métriques ou durées
{cv_voice_repair}
{letter_voice_repair}
- Conserver le format Markdown/HTML
- INTERDIT d'ajouter un stage, une mission, une durée ou une compétence absente du profil

Réponds UNIQUEMENT avec le document corrigé.
"""
        return llm_fn(prompt, max_tokens=3000, temperature=0.1)
