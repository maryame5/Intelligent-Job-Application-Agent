"""
core/cv_tailor.py
=================
Moteur d'orchestration CVTailor :
- Chargement dynamique du profil depuis profil.json
- Analyse déterministe de l'offre
- Sélection intelligente des expériences et projets
- Génération avec validation et retry LLM
- Rapport de scoring et checklist ATS
"""

from __future__ import annotations

import io
import json
import os
import sys
from datetime import date
from typing import Any

from google import genai
from openai import OpenAI

from core.helpers import normalize_tech_names, _strip_stray_emojis
from core.offer_analyzer import OfferAnalyzer, build_application_context
from core.context_builder import (
    ContextBuilder,
    build_gap_analysis_report,
    build_ats_formatting_checklist,
)
from core.prompt_builder import build_cv_prompt, build_cover_letter_prompt
from core.output_validator import OutputValidator

from matching.offer_scoring import (
        score_personalization,
        score_factuality,
        score_rh_readability,
        compute_final_score,
    )


from integrations.llm_clients import get_chat_llm


if sys.stdout and sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
if sys.stderr and sys.stderr.encoding and sys.stderr.encoding.lower() != "utf-8":
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def _load_candidate_profile(profile_path: str | None = None) -> dict:
    """Charge profil.json (source de vérité unique). Aucun fallback statique."""
    try:
        from profile.adapter import build_candidate_master_profile
        
        if profile_path is None:
            # Recherche racine ou répertoire courant
            cur_dir = os.path.dirname(os.path.abspath(__file__))
            root_dir = os.path.dirname(cur_dir)
            p1 = os.path.join(root_dir, "profil.json")
            p2 = os.path.join(cur_dir, "profil.json")
            p3 = os.path.join(os.getcwd(), "profil.json")
            for candidate in [p1, p2, p3]:
                if os.path.exists(candidate):
                    profile_path = candidate
                    break

        if not profile_path or not os.path.exists(profile_path):
            raise RuntimeError(
                f"Impossible de charger profil.json : fichier introuvable."
            )

        profile = build_candidate_master_profile(profile_path)
        print(f"✅ [CVTailor] Profil chargé depuis {profile_path}")
        return profile
    except FileNotFoundError:
        raise RuntimeError("Impossible de charger profil.json : fichier introuvable")
    except Exception as e:
        raise RuntimeError(f"Impossible de charger profil.json : {e}") from e


class CVTailor:
    """Moteur principal de génération et d'alignement de candidatures."""

    def __init__(self, model_name: str | None = None, profile: dict | None = None):
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        self.llm_provider = os.getenv("LLM_PROVIDER", "auto").lower().strip()
        self.profile = profile or _load_candidate_profile()
        self.analyzer = OfferAnalyzer(self.profile)
        self.semantic = self.analyzer.semantic
        
        try:
            self.azure_llm = get_chat_llm(temperature=0.25)
        except Exception:
            self.azure_llm = None
        self.gemini_client = None
        self.nvidia_client = None
        self.ctx_builder = ContextBuilder(self.profile)
        self.validator = OutputValidator(self.profile)

    def _call_azure(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.25) -> str:
        if self.azure_llm is None:
            raise RuntimeError("Azure LLM non configuré")
        try:
            bound = self.azure_llm.bind(max_tokens=max_tokens, temperature=temperature)
            return bound.invoke(prompt)
        except Exception:
            return self.azure_llm.invoke(prompt)

    def _call_gemini(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.25) -> str:
        if self.gemini_client is None:
            self.gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        from google.genai import types as genai_types
        config = genai_types.GenerateContentConfig(
            max_output_tokens=max_tokens,
            temperature=temperature,
        )
        response = self.gemini_client.models.generate_content(
            model=self.model_name, contents=prompt, config=config
        )
        return response.text or ""

    def _call_nvidia(self, prompt: str, max_tokens: int, temperature: float) -> str:
        if self.nvidia_client is None:
            self.nvidia_client = OpenAI(
                api_key=os.getenv("NVIDIA_API_KEY"),
                base_url="https://integrate.api.nvidia.com/v1",
            )
        response = self.nvidia_client.chat.completions.create(
            model=os.getenv("NVIDIA_MODEL", "meta/llama-3.3-70b-instruct"),
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Tu es un recruteur technique senior. Tu écris uniquement avec les faits fournis. "
                        "Tu ne dois jamais inventer de stage, date, entreprise, métrique ou technologie. "
                        "Si une exigence de l'offre n'est pas prouvée, tu la présentes comme un intérêt ou une compétence transférable."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""

    def _call_llm(self, prompt: str, max_tokens: int = 4000, temperature: float = 0.25) -> str:
        guard = (
            "\n\nRAPPEL CRITIQUE DE GROUNDING: utilise uniquement les faits fournis dans le profil. "
            "N'invente jamais une mission, une date, une entreprise, un diplôme, une métrique ou une technologie.\n"
        )
        grounded_prompt = guard + prompt

        if self.llm_provider == "azure":
            try:
                return self._call_azure(grounded_prompt, max_tokens)
            except Exception as e:
                return f"Erreur LLM Azure: {e}"

        if self.llm_provider == "nvidia":
            try:
                return self._call_nvidia(grounded_prompt, max_tokens, temperature)
            except Exception as e:
                return f"Erreur LLM NVIDIA: {e}"

        if self.llm_provider == "gemini":
            try:
                return self._call_gemini(grounded_prompt)
            except Exception as e:
                return f"Erreur LLM Gemini: {e}"

        # Mode auto fallback
        try:
            return self._call_azure(grounded_prompt, max_tokens)
        except Exception as e_azure:
            try:
                return self._call_gemini(grounded_prompt)
            except Exception as e_gemini:
                try:
                    return self._call_nvidia(grounded_prompt, max_tokens, temperature)
                except Exception as e_nvidia:
                    return f"Erreur LLM. Azure: {e_azure} | Gemini: {e_gemini} | NVIDIA: {e_nvidia}"

    def generate(
        self,
        job_title: str,
        job_description: str,
        company_name: str,
        current_date: str | None = None,
        verbose: bool = True,
        application_context: dict | None = None,
    ) -> dict:
        if current_date is None:
            current_date = date.today().strftime("%d/%m/%Y")

        if verbose:
            print("━━━ [v6] Étape 1 — Analyse déterministe de l'offre...")
        llm_score = (application_context or {}).get("match_score")
        analysis = self.analyzer.run_full_analysis(
            job_title, job_description, company_name,
            external_match_score=llm_score,
        )
        analysis["job_context"] = {"job_title": job_title, "company_name": company_name}
        analysis["application_context"] = application_context or build_application_context(analysis)

        if verbose:
            role = analysis["role"]
            match = analysis["match"]
            det_s = match.get('deterministic_score', match['global_score'])
            llm_s = match.get('llm_score')
            hybrid_s = match['global_score']
            if llm_s is not None:
                print(f"   📊 Score déterministe: {det_s} | Score LLM: {llm_s} | Score hybride: {hybrid_s}")
            else:
                print(f"   📊 Score déterministe: {det_s} (pas de score LLM externe)")
            print(f"   Rôle dominant : {role['dominant']} (confiance {int(role['confidence']*100)}%)")
            print(f"   Persona recruteur : {analysis['persona']}")
            print(f"   {match['decision']}")
            print(f"   {match['rationale']}")
            app_ctx = analysis.get("application_context", {})
            print(f"   Priorité candidature : {app_ctx.get('priority')} — {app_ctx.get('status')} ({app_ctx.get('apply_mode')})")
            if analysis["seniority"]["has_mismatch"]:
                print(f"   ⚠️  Mismatch séniorité — titre recommandé : {analysis['seniority']['recommended_title']}")

        selected_exps = self.ctx_builder.get_selected_experiences(analysis["selected_exp_ids"])
        selected_projs = self.ctx_builder.get_selected_projects(analysis["selected_proj_ids"])

        if verbose:
            print(f"   Expériences sélectionnées : {[e['company'] for e in selected_exps]}")
            print(f"   Projets sélectionnés : {[p['name'][:30] for p in selected_projs]}")

        if verbose:
            print("━━━ [v6] Étape 2 — Génération CV (validation + retry)...")

        cv_prompt = build_cv_prompt(
            job_title, job_description, company_name,
            analysis, analysis["persona"],
            selected_exps, selected_projs, self.ctx_builder,
            self.profile
        )

        cv = ""
        warnings_cv: list[str] = []
        for attempt in range(3):
            cv = self._call_llm(cv_prompt, max_tokens=5000, temperature=0.22)
            cv = normalize_tech_names(cv)
            cv = _strip_stray_emojis(cv)

            warnings_cv = self.validator.validate(cv, analysis, doc_type="cv")
            if not warnings_cv:
                break
            if attempt < 2:
                if verbose:
                    print(f"   ⚠️  CV warnings (attempt {attempt+1}/3): {warnings_cv}")
                cv = self.validator.repair(cv, "CV", warnings_cv, analysis, self._call_llm)
                cv = normalize_tech_names(cv)
                cv = _strip_stray_emojis(cv)
            else:
                if verbose:
                    print(f"   ❌ CV invalid après retries. Warnings: {warnings_cv}")

        if verbose:
            print("━━━ [v6] Étape 3 — Génération Lettre (validation + retry)...")

        letter_prompt = build_cover_letter_prompt(
            job_title, job_description, company_name,
            analysis, analysis["persona"],
            selected_exps, selected_projs, current_date,
            self.profile
        )

        lettre = ""
        warnings_lettre: list[str] = []
        for attempt in range(3):
            lettre = self._call_llm(letter_prompt, max_tokens=2500, temperature=0.28)
            lettre = normalize_tech_names(lettre)
            lettre = _strip_stray_emojis(lettre)

            warnings_lettre = self.validator.validate(lettre, analysis, doc_type="letter")
            if not warnings_lettre:
                break
            if attempt < 2:
                if verbose:
                    print(f"   ⚠️  Lettre warnings (attempt {attempt+1}/3): {warnings_lettre}")
                lettre = self.validator.repair(lettre, "Lettre", warnings_lettre, analysis, self._call_llm)
                lettre = normalize_tech_names(lettre)
                lettre = _strip_stray_emojis(lettre)
            else:
                if verbose:
                    print(f"   ❌ Lettre invalid après retries. Warnings: {warnings_lettre}")

        if verbose:
            if not warnings_cv and not warnings_lettre:
                print("   ✅ Documents validés — aucun warning restant.")
            else:
                print(f"   ⚠️  Warnings résiduels — CV: {warnings_cv} | Lettre: {warnings_lettre}")

        if verbose:
            print("━━━ [v6] Étape 4 — Gap analysis, checklist ATS & scoring final...")

        gap_analysis = build_gap_analysis_report(self.profile, analysis)
        ats_checklist = build_ats_formatting_checklist(cv, lettre)

        offer_for_scoring = {"company_name": company_name}
        personalization = score_personalization(cv, lettre, analysis, offer_for_scoring)
        factuality = score_factuality(cv, lettre, warnings_cv, warnings_lettre)
        readability = score_rh_readability(cv, lettre, analysis)
        final_scoring = compute_final_score(personalization, factuality, readability)

        weighted_gaps = [
            ("Facticité / preuves (35% du score)", 0.35, factuality["factuality_score"]),
            ("Personnalisation à l'offre (45% du score)", 0.45, personalization["personalization_score"]),
            ("Lisibilité RH / structure (20% du score)", 0.20, readability["rh_readability_score"]),
        ]
        weighted_gaps.sort(key=lambda x: x[1] * (100 - x[2]), reverse=True)
        priority_fixes = [f"{label} — actuellement {score}/100" for label, _w, score in weighted_gaps]

        if verbose:
            print(f"   📊 Score final ATS/RH : {final_scoring['final_score']}/100 "
                  f"(factualité={factuality['factuality_score']}, "
                  f"personnalisation={personalization['personalization_score']}, "
                  f"lisibilité={readability['rh_readability_score']})")
            if ats_checklist["n_issues"]:
                print(f"   ⚠️  {ats_checklist['n_issues']} point(s) de mise en forme ATS à corriger.")

        return {
            "analysis": analysis,
            "cv": cv,
            "lettre": lettre,
            "warnings": {"cv": warnings_cv, "lettre": warnings_lettre},
            "match_score": analysis["match"]["global_score"],
            "decision": analysis["match"]["decision"],
            "persona_used": analysis["persona"],
            "dominant_role": analysis["role"]["dominant"],
            "positioning": analysis.get("positioning", {}),
            "application_context": analysis.get("application_context", {}),
            "application_strategy": analysis.get("application_context", {}).get("apply_mode", "direct_application"),
            "application_priority": analysis.get("application_context", {}).get("priority", "B"),
            "gap_analysis": gap_analysis,
            "ats_checklist": ats_checklist,
            "scoring": {
                "personalization": personalization,
                "factuality": factuality,
                "readability": readability,
                "final": final_scoring,
                "priority_fixes": priority_fixes,
            },
        }


def build_full_report_markdown(result: dict, job_title: str, company_name: str) -> str:
    """Assemble un rapport Markdown complet pour une offre."""
    scoring = result.get("scoring", {})
    final = scoring.get("final", {})
    gap = result.get("gap_analysis", {})
    checklist = result.get("ats_checklist", {})

    lines = [
        f"# Rapport de candidature — {job_title} @ {company_name}",
        "",
        f"## Score final : {final.get('final_score', 0)}/100",
        f"- Factualité : {final.get('score_factuality', 0)}/100 (poids 35%)",
        f"- Personnalisation à l'offre : {final.get('score_personalization', 0)}/100 (poids 45%)",
        f"- Lisibilité RH : {final.get('score_rh_readability', 0)}/100 (poids 20%)",
        "",
        "### Correctifs prioritaires (par impact décroissant sur le score final)",
    ]
    for i, fix in enumerate(scoring.get("priority_fixes", []), start=1):
        lines.append(f"{i}. {fix}")

    lines += [
        "",
        "## Gap analysis — offre vs profil",
        gap.get("summary_text", ""),
        "",
        "## Checklist formatage ATS",
    ]
    for c in checklist.get("checks", []):
        mark = "✅" if c["status"] == "OK" else f"❌ [{c['impact']}]"
        lines.append(f"- {mark} {c['check']} — {c['fix']}")

    return "\n".join(lines)


def generate_application(
    job_title: str,
    job_description: str,
    company_name: str,
    verbose: bool = True,
) -> dict:
    tailor = CVTailor()
    return tailor.generate(
        job_title=job_title,
        job_description=job_description,
        company_name=company_name,
        verbose=verbose,
    )
