"""
profile_adapter.py
==================
Convertit profil.json (source de vérité unique) en CANDIDATE_MASTER_PROFILE
utilisé par cv_tailor.py.

Responsabilités :
- Charger profil.json
- Adapter la structure (experiences → story_bullets, role_signal, etc.)
- Enrichir les projets avec les champs attendus par le moteur de scoring
- Produire narrative_hooks à partir du profil réel
"""

from __future__ import annotations
import json
import os
from typing import Any


# ── Mapping : stack de projet → role_signal ──────────────────────────────────
_ROLE_SIGNAL_RULES = {
    "frontend_fullstack_ai_product": [
        "next.js", "nextjs", "react", "typescript", "vite", "tailwind", "shadcn",
        "zustand", "tanstack", "react hook form", "web app", "dashboard", "frontend",
        "fastapi", "postgresql jsonb", "alembic", "sqlalchemy", "github", "api testing"
    ],
    "ai_engineer": [
        "langgraph", "langchain", "llm", "openai", "hugging face", "mlflow",
        "scikit-learn", "xgboost", "lightgbm", "pytorch", "tensorflow",
        "nlp", "spacy", "vader", "stable diffusion", "rag", "mcp",
        "azure openai", "prompt engineering", "insight agent", "sectorcontext"
    ],
    "data_engineer": [
        "airflow", "dbt", "etl", "spark", "databricks", "data warehouse",
        "star schema", "medallion", "duckdb", "looker studio", "power bi",
        "tableau", "bigquery", "snowflake", "data preparation", "data quality",
        "pandas", "minio", "bronze/silver/gold", "ydata profiling"
    ],
    "qa_testing": [
        "qa", "software testing", "api testing", "postman", "swagger", "openapi",
        "end-to-end", "workflow validation", "data quality validation", "bug documentation"
    ],
    "consulting": [
        "business analysis", "requirements", "use case", "kpi mapping", "solution design",
        "digital transformation", "stakeholder", "uml", "bpmn", "functional specification"
    ],
    "software_engineer": [
        "spring boot", "spring cloud", "java", "angular", "react",
        "microservices", "kafka", "rabbitmq", "hibernate", "jpa",
        "django", "flask", "kotlin", "android", "rest api"
    ],
}


def _infer_role_signals(stack: list[str], category: str) -> list[str]:
    """Infère les role_signal depuis le stack et la catégorie du projet."""
    text = " ".join(stack + [category]).lower()
    signals = []
    for role, keywords in _ROLE_SIGNAL_RULES.items():
        if any(kw in text for kw in keywords):
            signals.append(role)
    return signals or ["software_engineer"]


def _highlights_to_bullets(highlights: list[str], default_context: str = "") -> list[dict]:
    """
    Convertit les highlights de profil.json en story_bullets structurés.
    Chaque highlight devient context+action+result inféré.
    """
    bullets: list[dict] = []
    for h in highlights:
        # Découper en context / action / résultat selon les marqueurs naturels
        if " — " in h:
            parts = h.split(" — ", 1)
            action = parts[0].strip()
            result = parts[1].strip()
        elif "→" in h:
            parts = h.split("→", 1)
            action = parts[0].strip()
            result = parts[1].strip()
        else:
            action = h
            result = ""

        import re
        tech_matches = re.findall(r'\(([^)]+)\)', h)
        tech_proof = tech_matches[-1] if tech_matches else ""

        bullets.append({
            "context": default_context or "",  # garantit un context non vide quand possible
            "action": action,
            "result": result,
            "tech_proof": tech_proof,
        })
    return bullets


def _achievements_to_bullets(achievements: list[str | dict] | dict[str, list[str] | list[dict]], default_context: str = "") -> list[dict]:
    """Convertit key_achievements (liste ou dict) en story_bullets.

    Si achievements est un dict de listes par catégorie (DXC),
    on conserve la catégorie dans chaque bullet via `category` (tag).
    """
    bullets: list[dict] = []

    # Cas dict: category -> list
    if isinstance(achievements, dict):
        for category, values in achievements.items():
            if not isinstance(values, list):
                continue
            for a in values:
                # On traite a (string ou dict) une seule fois et on tag toutes les bullets produites
                produced = _achievements_to_bullets([a], default_context=default_context)
                for b in produced:
                    b["category"] = category
                bullets.extend(produced)
        return bullets

    # Cas liste
    for a in achievements:
        if isinstance(a, dict):
            a = dict(a)
            if not a.get("context"):
                a["context"] = default_context
            # category si présent dans l'objet
            bullets.append(a)
            continue

        import re
        tech_matches = re.findall(r'\(([^)]+)\)', a)
        tech_proof = tech_matches[-1] if tech_matches else ""

        context = default_context
        action = a
        result = ""

        if " — " in a:
            parts = a.split(" — ", 1)
            left, right = parts[0].strip(), parts[1].strip()

            action_starts_verbs = (
                "concu", "developpe", "developp", "developpé", "mis en place", "implémente",
                "implemente", "orchestré", "optimisé", "optimise", "intégré",
                "integre", "automatisé", "automatis", "structuré", "structure", "déployé",
                "deployee", "validé", "valide", "construit", "créé", "cree"
            )
            left_norm = left.lower().strip()
            is_action_like = any(left_norm.startswith(v) for v in action_starts_verbs)

            if is_action_like:
                context = default_context
                action = left
                result = right
            else:
                context = left or default_context
                action = left
                result = right

        elif "→" in a:
            parts = a.split("→", 1)
            left, right = parts[0].strip(), parts[1].strip()

            action_starts_verbs = (
                "concu", "developpe", "developp", "developpé", "mis en place", "implémente",
                "implemente", "orchestré", "optimisé", "optimise", "intégré", "integre",
                "automatisé", "automatis", "structuré", "déployé", "deployee", "validé", "valide",
                "construit", "créé", "cree"
            )
            left_norm = left.lower().strip()
            is_action_like = any(left_norm.startswith(v) for v in action_starts_verbs)

            if is_action_like:
                context = default_context
                action = left
                result = right
            else:
                context = left or default_context
                action = left
                result = right

        bullets.append({
            "context": context if context else default_context,
            "action": action,
            "result": result,
            "tech_proof": tech_proof,
        })
    return bullets



def _infer_company_type(company: str) -> str:
    company_lower = company.lower()
    if any(k in company_lower for k in ["dxc", "capgemini", "accenture", "alten", "inetum", "ibm"]):
        return "global_tech_consulting"
    if any(k in company_lower for k in ["capital", "bank", "finance", "trading", "fintech"]):
        return "fintech_trading"
    if any(k in company_lower for k in ["ministère", "gouvernement", "public", "perception"]):
        return "public_sector"
    return "tech_company"


def _build_what_was_delivered(exp: dict) -> dict:
    """Construit for_rh et for_tech depuis les données de profil.json."""
    description = exp.get("description", "")

    # 1) for_rh : doit être RH-friendly et distinct de description (pas redondant)
    whd = exp.get("what_was_delivered") or {}
    if isinstance(whd, dict) and whd.get("for_rh"):
        for_rh = (whd.get("for_rh") or "").strip()
    else:
        role = (exp.get("role") or "").strip()
        company = (exp.get("company") or "").strip()

        base = (description or "").strip()
        if not base:
            achievements = exp.get("key_achievements", [])
            candidate = ""
            if isinstance(achievements, dict):
                flat_ach: list[str] = []
                for v in achievements.values():
                    if isinstance(v, list):
                        flat_ach.extend([x for x in v if isinstance(x, str)])
                candidate = flat_ach[0] if flat_ach else ""
            else:
                candidate = achievements[0] if achievements else ""

            if isinstance(candidate, str):
                if " — " in candidate:
                    base = candidate.split(" — ", 1)[0].strip()
                elif "→" in candidate:
                    base = candidate.split("→", 1)[0].strip()
                else:
                    base = candidate.strip()

        # Rephrase légère: on évite de réutiliser la description telle quelle
        base = base.strip().strip(".")
        if role and company and base:
            for_rh = f"{company} : {base}"
        elif role and base:
            for_rh = f"{role} : {base}"
        else:
            for_rh = base

    # 2) for_tech : stack + architecture highlights
    arch = exp.get("architecture_highlights", [])
    stack = exp.get("stack", [])
    stack_flat = stack if isinstance(stack, list) else list(stack.values()) if isinstance(stack, dict) else []
    if isinstance(stack_flat[0], list) if stack_flat else False:
        from itertools import chain
        stack_flat = list(chain.from_iterable(stack_flat))

    stack_str = ", ".join(
        s if isinstance(s, str) else ""
        for s in stack_flat[:10]
        if isinstance(s, str)
    )
    for_tech = arch[0] if arch else f"Stack : {stack_str}."

    return {"for_rh": for_rh, "for_tech": for_tech}



def _flatten_stack(stack: Any) -> list[str]:
    """Aplatit un stack qui peut être list, dict de listes, ou list de listes."""
    if isinstance(stack, dict):
        result = []
        for v in stack.values():
            result.extend(_flatten_stack(v))
        return result
    if isinstance(stack, list):
        result = []
        for item in stack:
            if isinstance(item, str):
                result.append(item)
            elif isinstance(item, list):
                result.extend(_flatten_stack(item))
        return result
    return []


def build_candidate_master_profile(profil_path: str = "profil.json") -> dict:
    """
    Charge profil.json et retourne un dict compatible CANDIDATE_MASTER_PROFILE.
    Utilisé comme remplacement du dict hardcodé dans cv_tailor.py.
    """
    if not os.path.exists(profil_path):
        raise FileNotFoundError(f"profil.json introuvable : {profil_path}")

    with open(profil_path, "r", encoding="utf-8") as f:
        p = json.load(f)

    identity_raw = p.get("identity", {})
    links_raw = identity_raw.get("links", {})
    availability_raw = identity_raw.get("availability") or {}
    availability_status = availability_raw.get("status", "") if isinstance(availability_raw, dict) else str(availability_raw)
    availability_start = availability_raw.get("start_date", "") if isinstance(availability_raw, dict) else ""
    status_parts = [str(value).strip() for value in (availability_status, availability_start) if str(value).strip()]

    identity = {
        "full_name": identity_raw.get("full_name", ""),
        "location": identity_raw.get("location", ""),
        "email": identity_raw.get("email", ""),
        "email_personal": identity_raw.get("email_personnel", ""),
        "phone": identity_raw.get("phone", ""),
        "links": {
            "linkedin": links_raw.get("linkedin", ""),
            "github": links_raw.get("github", ""),
            "portfolio": links_raw.get("portfolio", ""),
        },
        "availability": {
            "status": availability_status,
            "start_date": availability_start,
        },
        "status": " — ".join(status_parts),
        # P1: professional_title n'est pas global (AI-first) : il doit être repositionné par famille de rôle
        "professional_title": "",
    }

    # ── Experiences ─────────────────────────────────────────────────────────
    experiences = []
    for idx, exp in enumerate(p.get("professional_experience", [])):
        company = exp.get("company", "")
        stack_raw = exp.get("stack", [])
        stack_flat = _flatten_stack(stack_raw)

        achievements = exp.get("key_achievements", [])
        default_context = exp.get("description", "")
        bullets = _achievements_to_bullets(
            achievements if achievements else [exp.get("description", "")],
            default_context=default_context,
        )

        explicit_role_signals = exp.get("role_signal")
        if not explicit_role_signals:
            explicit_role_signals = exp.get("role_signals")

        normalized_explicit_role_signals: list[str] = []
        if isinstance(explicit_role_signals, str):
            s = explicit_role_signals.strip()
            if s:
                normalized_explicit_role_signals = [s]
        elif isinstance(explicit_role_signals, list):
            normalized_explicit_role_signals = [str(x).strip() for x in explicit_role_signals if str(x).strip()]
        else:
            normalized_explicit_role_signals = []

        role_signal = (
            normalized_explicit_role_signals
            if normalized_explicit_role_signals
            else _infer_role_signals(stack_flat, exp.get("role", ""))
        )

        is_always_feature = exp.get("always_feature")
        if is_always_feature is None:
            is_always_feature = (idx < 3)
        else:
            is_always_feature = bool(is_always_feature)

        experiences.append({
            "id": company.lower().replace(" ", "_").replace("(", "").replace(")", "")[:20],
            "company": company,
            "always_feature": is_always_feature,
            "company_type": _infer_company_type(company),
            "role": exp.get("role", ""),
            "duration": exp.get("duration", ""),
            "location": exp.get("location", ""),
            "project_name": exp.get("project_name", ""),
            "business_problem": exp.get("description", ""),
            "what_was_delivered": _build_what_was_delivered(exp),
            "story_bullets": bullets,
            "stack": stack_flat,
            "role_signal": role_signal,
        })


    # ── Projects ─────────────────────────────────────────────────────────────
    projects = []
    for proj in p.get("featured_projects", []):
        stack_flat = _flatten_stack(proj.get("stack", []))
        highlights = proj.get("highlights", [])
        proj_desc = proj.get("description", "") or ""
        bullets_raw = _highlights_to_bullets(highlights, default_context=proj_desc)

        # Construire what_was_built depuis les highlights ou description
        what_was_built = proj.get("description", "")
        if highlights:
            what_was_built = highlights[0]

        role_signal = _infer_role_signals(
            stack_flat + proj.get("relevance_tags", []),
            proj.get("category", "")
        )

        # result et context depuis les highlights
        result = ""
        if len(highlights) >= 2:
            last = highlights[-1]
            if any(m in last.lower() for m in ["place", "hackathon", "précision", "accuracy", "roi", "%" ]):
                result = last

        # bullets_raw est déjà list[dict] avec action/result/tech_proof.
        # On garantit un context non vide pour le storytelling.
        for b in bullets_raw:
            if isinstance(b, dict) and not b.get("context"):
                b["context"] = proj_desc

        projects.append({
            "id": proj.get("name", "").lower().replace(" ", "_").replace("—", "").replace("-", "_")[:25],
            "name": proj.get("name", ""),
            "category": proj.get("category", ""),
            "year": proj.get("date", "2024")[:4] if proj.get("date") else "2024",
            "context": proj_desc,
            "result": result,
            "business_problem": proj_desc,
            "what_was_built": what_was_built,
            "story_bullets": bullets_raw,
            "stack": stack_flat,
            "role_signal": role_signal,
        })

    # ── Education ─────────────────────────────────────────────────────────────
    edu_raw = p.get("education_and_certs", {})
    academic = [
        {
            "institution": a.get("institution", ""),
            "degree": a.get("degree", ""),
            "field": a.get("field", ""),
            "period": a.get("period", ""),
        }
        for a in edu_raw.get("academic", [])
    ]
    certifications = [
        {
            "name": c.get("name", ""),
            "issuer": c.get("issuer", ""),
            "year": c.get("year", ""),
        }
        for c in edu_raw.get("certifications", [])
    ]

    # ── Narrative hooks (générés dynamiquement depuis profil.json) ───────────
    positioning_map = p.get("career_strategy", {}).get("positioning_by_role_family", {})
    summary_short = p.get("career_strategy", {}).get("summary", {}).get("short", "")
    headline = identity.get("headline", identity.get("professional_title", ""))

    narrative_hooks = {
        role: {
            "hook": f"{identity.get('full_name', '')} — {headline}",
            "proof": pos_text,
            "differentiator": summary_short or "Solide capacité d'adaptation et livraison de solutions concrètes et testées."
        }
        for role, pos_text in positioning_map.items()
    }
    # Fallback pour rôles standard
    if "software_engineer" not in narrative_hooks:
        narrative_hooks["software_engineer"] = {
            "hook": f"{identity.get('full_name', '')} — {headline}",
            "proof": positioning_map.get("software_fullstack", summary_short),
            "differentiator": summary_short
        }
    if "ai_engineer" not in narrative_hooks:
        narrative_hooks["ai_engineer"] = {
            "hook": f"{identity.get('full_name', '')} — {headline}",
            "proof": positioning_map.get("ai_agents", summary_short),
            "differentiator": summary_short
        }
    if "data_engineer" not in narrative_hooks:
        narrative_hooks["data_engineer"] = {
            "hook": f"{identity.get('full_name', '')} — {headline}",
            "proof": positioning_map.get("data_analytics", summary_short),
            "differentiator": summary_short
        }

    return {
        "identity": identity,
        "narrative_hooks": narrative_hooks,
        "experiences": experiences,
        "projects": projects,
        "education": {
            "academic": academic,
            "certifications": certifications,
        },
        "languages": p.get("optimization", {}).get("languages_spoken", [
            {"language": "Arabe", "level": "Langue maternelle"},
            {"language": "Français", "level": "Professionnel "},
            {"language": "Anglais", "level": "Professionnel "},
        ]),

        # IMPORTANT: keep the source-of-truth blocks from profil.json.
        # They are used by main_agent.py for search strategy and by the LLM prompts
        # for strict grounding, so the adapter must not throw them away.
        # Garder ces blocs pour le scoring, le scraping et le grounding.
        "career_strategy": p.get("career_strategy", {}),
        "technical_ecosystem": p.get("technical_ecosystem", {}),
        "optimization": p.get("optimization", {}),
        "raw_profile": p,
    }


# ── Point d'entrée pour test rapide ──────────────────────────────────────────
if __name__ == "__main__":
    profile = build_candidate_master_profile("profil.json")
    print(f"✅ Identité : {profile['identity']['full_name']}")
    print(f"✅ {len(profile['experiences'])} expériences chargées :")
    for e in profile['experiences']:
        print(f"   - {e['company']} | role_signal: {e['role_signal']} | {len(e['story_bullets'])} bullets")
    print(f"✅ {len(profile['projects'])} projets chargés :")
    for proj in profile['projects']:
        print(f"   - {proj['name'][:45]} | role_signal: {proj['role_signal']}")
    print(f"✅ {len(profile['education']['academic'])} formations")
    print(f"✅ {len(profile['education']['certifications'])} certifications")
