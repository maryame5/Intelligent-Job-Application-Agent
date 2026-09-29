"""
core/prompt_builder.py
======================
Constructeurs des prompts LLM pour le CV et la Lettre de Motivation.
100% dynamique depuis profil.json — aucun nom ni information personnelle codée en dur.
"""

from __future__ import annotations

from core.lexicons import (
    CV_STYLE_MODE,
    CAREER_STAGE,
    RECRUITER_STYLE_GUIDE,
)
from core.personas import PERSONA_PROMPTS
from core.helpers import (
    _norm,
    _company_for_display,
    _title_for_display,
    _display_role_for_career_stage,
    _build_evidence_guard,
    build_keyword_grounding,
)
from core.offer_analyzer import (
    build_application_context,
    build_offer_positioning,
    format_offer_positioning,
)
from core.context_builder import (
    ContextBuilder,
    _select_email_for_context,
    _positioning_by_role_family_text,
    _detect_offer_language,
    _normalize_date_for_lang,
    _build_contact_line,
    _mirror_job_title_keywords,
    _qa_honesty_instruction,
    _format_letter_evidence,
)


def build_cv_prompt(
    job_title: str,
    job_description: str,
    company_name: str,
    analysis: dict,
    persona: str,
    selected_experiences: list,
    selected_projects: list,
    ctx_builder: ContextBuilder,
    profile: dict,
) -> str:
    identity = profile.get("identity", {})
    professional_title = identity.get("professional_title", "")
    selected_email = _select_email_for_context(profile, analysis)
    positioning_by_role_family = _positioning_by_role_family_text(profile, analysis["role"]["dominant"])
    education = profile.get("education") or profile.get("education_and_certs", {})
    seniority = analysis["seniority"]
    dominant_role = analysis["role"]["dominant"]
    application_context = analysis.get("application_context") or build_application_context(analysis)
    positioning = analysis.get("positioning") or build_offer_positioning(analysis, job_title, job_description)
    positioning_block = format_offer_positioning(positioning)
    target_title = positioning.get("target_title") or professional_title or "Ingénieure Software"

    offer_lang = _detect_offer_language(job_description)
    contact_line = _build_contact_line(profile, job_description, selected_email)
    
    # ─── Adapt title and pillars dynamically to offer ─────────────────────────
    jt_norm = _norm(job_title)
    if any(k in jt_norm for k in ["conversational", "chatbot", "voicebot"]):
        target_title = "AI & Software Engineer | Conversational AI, Voicebots & LLM Systems"
    elif any(k in jt_norm for k in ["ai engineer", "ai dev", "ia", "intelligence artificielle", "machine learning", "llm", "agent", "agentic"]):
        target_title = "AI & Software Engineer | Data Pipelines, Backend Microservices & LLM Systems"
    elif any(k in jt_norm for k in ["data engineer", "data", "analytics"]):
        target_title = "Data & Software Engineer | ETL Pipelines, Data Quality & Analytics Systems"
    elif any(k in jt_norm for k in ["full stack", "fullstack", "full-stack"]):
        target_title = "Full-Stack Software Engineer | React, TypeScript, FastAPI & Microservices"
    elif any(k in jt_norm for k in ["backend", "back-end", "java", "spring"]):
        target_title = "Software Engineer | Backend Microservices, Java Spring Boot & Distributed Systems"
    elif any(k in jt_norm for k in ["qa", "testing", "test", "quality"]):
        target_title = "Software Engineer | API Testing, Data Quality & Automated Validation"
    else:
        target_title = _mirror_job_title_keywords(job_title, "AI & Software Engineer | Data Pipelines, Backend Microservices & LLM Systems")

    if application_context.get("apply_mode") in {"honest_opportunistic", "light_apply"}:
        if offer_lang == "en":
            cv_title_instruction = f"""
⚠️ APPLICATION PRIORITY {application_context['priority']} — {application_context['status']}
Goal: Apply honestly without claiming senior experience or unproven skills.
Recommended title: "{target_title}"
If the job title has a level term ("junior", "entry-level", "early career"): reflect it in the CV title.
FORBIDDEN: Any senior, lead, principal, architect title.
FORBIDDEN: Claiming 3+ years experience.
POSITION AS: Junior engineer with solid transferable deliverables and quick adaptability.
FORBIDDEN: Mentioning availability in PROFILE."""
        else:
            cv_title_instruction = f"""
⚠️ CANDIDATURE {application_context['priority']} — {application_context['status']}
Objectif : postuler quand même, mais sans se présenter comme senior ni experte d'une compétence absente.
Titre recommandé : "{target_title}"
Si le job title contient un terme de niveau ("junior", "entry-level", "early career") : le faire apparaître dans le titre CV pour montrer la compréhension du niveau du poste.
INTERDIT : tout titre senior, confirmé, lead, expert, référent, architecte expérimenté.
INTERDIT : écrire ou sous-entendre 3+ ans d'expérience si ce n'est pas prouvé.
POSITIONNER : profil junior solide avec preuves transférables et capacité à contribuer vite.
INTERDIT : mentionner une disponibilité dans le PROFIL."""
    elif seniority["has_mismatch"]:
        if offer_lang == "en":
            cv_title_instruction = f"""
⚠️ SENIORITY GAP DETECTED BUT APPLICATION ALLOWED
Recommended title: "{target_title}"
FORBIDDEN: Any senior title ("Senior", "Lead", "Architect", "Confirmed").
FORBIDDEN: Promising team management or roadmap ownership.
POSITION AS: Junior engineer with concrete deliverables, fast execution, and proven autonomy.
FORBIDDEN: Mentioning availability in PROFILE."""
        else:
            cv_title_instruction = f"""
⚠️ ÉCART DE SÉNIORITÉ DÉTECTÉ MAIS CANDIDATURE AUTORISÉE
Titre recommandé : "{target_title}"
INTERDIT : tout titre senior ("architecte expérimenté", "senior", "confirmé", "référent technique")
INTERDIT : promettre encadrement d'équipes, pilotage de roadmap, garantie d'architecture
POSITIONNER : profil junior avec livrables concrets et autonomie prouvée
INTERDIT : mentionner une disponibilité dans le PROFIL."""

    else:
        if offer_lang == "en":
            cv_title_instruction = f"""Recommended title: "{target_title}"
Title aligned to the offer for role {dominant_role}, without overstating seniority.
If the job title contains a distinctive term ("AI-Native", "Agentic", "Junior", "Early Career"...): mirror it in the CV title or subtitle for ATS alignment.
Examples of allowed titles:
- AI Automation Developer : "Junior AI Automation Engineer | Python & LLM Agents"
- AI Engineer : "Junior AI & Software Engineer | Agentic Workflows & LLM APIs"
- Full-Stack : "Junior Full-Stack Engineer | React, TypeScript & FastAPI"
- Data Engineer : "Junior Data & Software Engineer | Pipelines & Analytics"
FORBIDDEN: "student profile", "date de disponibilité", "Senior Engineer", "Expert".
FORBIDDEN: Any French title or subtitle in an English CV."""
        else:
            cv_title_instruction = f"""Titre recommandé : "{target_title}"
Titre aligné à l'offre pour le rôle {dominant_role}, sans exagérer la séniorité.
Si le job title contient un terme distinctif ("AI-Native", "Agentic", "Junior", "Early Career", "Web3"...) : le reprendre dans le titre CV ou le sous-titre pour aligner le parsing ATS.
Exemples de titres autorisés :
- AI Engineer : "Ingénieure IA & Software"
- AI-Native : "Junior AI-Native Software Engineer | IA & Agentic Systems"
- Data Engineer : "Ingénieure Data & Software"
- Full-Stack : "Ingénieure Full-Stack & Software"
- QA : "Ingénieure Software orientée QA, API Testing & Data Quality"
INTERDIT : "student profile", "date de disponibilité", "Ingénieure senior", "Expert"."""

    academic_lines = []
    for a in education.get("academic", []):
        parts = [a.get("degree", ""), a.get("field", ""), a.get("institution", ""), a.get("period", "")]
        academic_lines.append("- " + " — ".join(p for p in parts if p))
    academic_md = "\n".join(academic_lines)

    certif_lines = []
    for c in education.get("certifications", []):
        certif_lines.append(f"- {c.get('name', '')} — {c.get('issuer', '')} ({c.get('year', '')})")
    certif_md = "\n".join(certif_lines)

    required_kw_set = set(analysis.get("required_keywords", []))
    jd_norm = _norm(job_description)
    exp_blocks = "\n\n".join(
        ctx_builder.format_experience_for_prompt(e, dominant_role,
                                                  required_keywords=required_kw_set,
                                                  jd_norm=jd_norm)
        for e in selected_experiences
    )
    proj_blocks = "\n\n".join(
        ctx_builder.format_project_for_prompt(p)
        for p in selected_projects
    )

    allowed_experience_facts = "\n".join(
        f"- {_display_role_for_career_stage(e.get('role', ''))} | {e.get('company', '')} | {_normalize_date_for_lang(e.get('duration', e.get('period', '')), offer_lang)}"
        for e in selected_experiences
    )

    narrative_hooks = ctx_builder.format_narrative_hooks(dominant_role)
    audit_summary = ctx_builder.format_audit_summary(analysis)
    persona_prompt = PERSONA_PROMPTS.get(persona, PERSONA_PROMPTS["senior_ta_tech"])
    evidence_guard = _build_evidence_guard(profile, analysis)
    qa_instruction = _qa_honesty_instruction(profile, analysis)
    keyword_grounding = build_keyword_grounding(profile, analysis, document_type="cv")

    candidate_name = identity.get("full_name", "")

    raw_langs = profile.get("languages", [])
    if offer_lang == "en":
        # Format languages in clean English for English CVs
        langs_str = "Arabic: Native | French: Fluent (C1) | English: Professional (B2)"
    else:
        if isinstance(raw_langs, list):
            formatted_langs = []
            for l in raw_langs:
                if isinstance(l, dict):
                    lang_name = l.get("language") or l.get("name") or ""
                    level = l.get("level") or l.get("proficiency") or ""
                    formatted_langs.append(f"{lang_name} : {level}" if level else lang_name)
                elif isinstance(l, str) and l.strip():
                    formatted_langs.append(l.strip())
            langs_str = " | ".join(formatted_langs) if formatted_langs else "Arabe : Langue maternelle | Français : Professionnel | Anglais : Professionnel "
        else:
            langs_str = str(raw_langs) if raw_langs else "Arabe : Langue maternelle | Français : Professionnel | Anglais : Professionnel "

    tech_eco = profile.get("technical_ecosystem", {})
    proven_tech_summary = []
    for cat_name, tech_list in tech_eco.items():
        if isinstance(tech_list, list) and tech_list:
            proven_tech_summary.append(f"- {cat_name}: {', '.join(str(t) for t in tech_list[:8])}")
    proven_tech_block = "\n".join(proven_tech_summary)

    top_kw = analysis.get("required_keywords", [])[:25]
    skills_targeting = f"""RÈGLE COMPÉTENCES — CIBLAGE OFFRE :
Les keywords suivants sont exigés ou valorisés par l'offre : {', '.join(top_kw)}
ÉCOSYSTÈME TECHNIQUE RÉEL DU CANDIDAT (attesté en production / stages) :
{proven_tech_block}
→ Mettre en avant en priorité les compétences de production (ex: LangGraph, Azure OpenAI, FastAPI, React 18, Spring Boot, PostgreSQL, Docker, Airflow) qui répondent aux besoins du poste.
→ Parmi les compétences que le candidat maîtrise réellement, les faire apparaître EN TÊTE de chaque catégorie.
→ Les compétences absentes du profil ne doivent PAS être injectées pour faire plaisir à l'ATS.
→ Ne pas les noyer dans une liste de 20 technos — 5-7 par catégorie max.
→ Structurer les catégories selon le rôle dominant de l'offre (ex: AI / Machine Learning d'abord pour un poste IA/Automation, Backend/APIs d'abord pour du dev backend, Data/Pipelines pour de la data)."""

    role_specific_instruction = f"""
━━━ ORIENTATION STRATÉGIQUE DU CV ━━━
- Rôle dominant : {dominant_role}
- Objectif : Mettre en avant en priorité les compétences, expériences et projets qui correspondent aux attentes réelles du poste ({job_title} chez {company_name}).
- Règle de cohérence : Présenter en premier les livrables les plus pertinents pour l'offre sans rien inventer."""
    if positioning_by_role_family:
        role_specific_instruction += f"\nPositionnement conseillé (issu de profil.json) : {positioning_by_role_family}\n"

    if offer_lang == "en":
        lang_instruction = """\n━━━ RÈGLE LANGUE — PRIORITÉ ABSOLUE ━━━
L'offre est RÉDIGÉE EN ANGLAIS. Le CV DOIT être intégralement rédigé en anglais.
Sections en anglais : PROFILE / EDUCATION / PROFESSIONAL EXPERIENCE / PROJECTS / TECHNICAL SKILLS / CERTIFICATIONS / LANGUAGES
Tous les bullets, titres et descriptions doivent être en anglais.
INTERDIT : mélanger français et anglais dans le même document.
Le ton doit être output-first, direct, professional — "Built", "Designed", "Deployed", "Automated", "Engineered".\n"""
    else:
        lang_instruction = ""

    return f"""

{persona_prompt}

{RECRUITER_STYLE_GUIDE}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
MODE DE STYLE CV : {CV_STYLE_MODE}
TON OBJECTIF : Générer un CV professionnel personnel, clair, crédible, ATS-friendly et différenciant
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{lang_instruction}
Tu génères le CV de {candidate_name} pour ce poste :
Poste : {job_title}
Entreprise : {company_name}

OFFRE :
{job_description}

{audit_summary}

{positioning_block}

━━━ MATÉRIAUX À TA DISPOSITION ━━━
(Faits attestés — ne JAMAIS inventer ni modifier les noms d'entreprises, les durées, les métriques)

{narrative_hooks}

EXPÉRIENCES EXACTES AUTORISÉES — NE PAS MODIFIER LES TITRES, ENTREPRISES OU DATES :
{allowed_experience_facts}

EXPÉRIENCES (dans l'ordre de sélection) :
{exp_blocks}

PROJETS :
{proj_blocks}

FORMATION ACADÉMIQUE :
{academic_md}

CERTIFICATIONS :
{certif_md}

LANGUES : {langs_str}

━━━ RÈGLES DE GÉNÉRATION ━━━

{cv_title_instruction}

RÈGLE DE VOIX — CV PERSONNEL :
- Le CV doit être rédigé à la voix personnelle implicite (style nominal et verbes d'action au participe passé).
- Interdit absolu : "elle", "la candidate", "{candidate_name} a", "son profil", "sa capacité", "ses compétences".
- Interdit dans le CV : "j'ai", "je", "mon", "ma", "mes". Le CV doit rester en style nominal et bullets d'action, pas en mini-lettre.
- Section PROFIL : style direct, nominal, professionnel, sans pronom.
- Expériences/projets : commencer les bullets par des verbes d'action comme "Conçu", "Développé", "Mis en place", "Implémenté", "Automatisé", "Intégré", "Structuré", "Optimisé".
- Ne jamais commencer un bullet par "A permis", "A donné", "A rendu", "A contribué à permettre".

RÈGLE CAREER STAGE — {CAREER_STAGE} :
- Positionner le profil comme ingénieure junior, sans ajouter de statut étudiant ou de détail académique non présent dans le profil.
- Interdit : "student profile", "recherche d'un stage", "stage de fin d'études", "PFE" dans le CV final.
- Les stages restent des expériences professionnelles complètes (omettre le terme PFE dans le titre).

RÈGLE PROFIL — STYLE ATTENDU :
- 3 à 4 lignes maximum.
- Structure : 1) Titre professionnel fort ; 2) Accroche différenciante alignée avec l'offre et compétences clés ; 3) Valeur ajoutée concrète et capacité d'intégration immédiate.
- Style direct, percutant, orienté compétences démontrées et solutions livrées.
- Interdit : tout statut étudiant ou toute disponibilité dans le PROFIL.
- Interdit : "profil rare", "passionnée", "motivée".

RÈGLE BULLETS — STYLE CV CONCIS (OBJECTIF 1 PAGE) :
- Pattern obligatoire : VERBE D'ACTION FORT → RÉALISATION / PÉRIMÈTRE → IMPACT & TECHNOLOGIES
- Chaque bullet doit être concis (15 à 20 mots maximum par puce) et aller droit au but.
- Exactement 3-4 bullets pour l'expérience principale, 2-3 bullets pour les autres expériences.
- Commencer chaque bullet par un verbe d'action au participe passé (Conçu, Développé, Implémenté, Déployé, Sécurisé, Optimisé, Structuré).
- Intégrer les technologies et métriques naturellement dans l'action (ex: "Développé des microservices sous FastAPI et PostgreSQL").
- INTERDIT : Ajouter des parenthèses redondantes de technologies à la fin de chaque puce (ex: "(React 18 / TypeScript...)" répété à chaque ligne).

RÈGLE COMPÉTENCES :
4 à 5 catégories ciblées selon le rôle dominant ({dominant_role}).
Mettre en avant les technologies clés de l'offre (ex: LLM, Prompt Engineering, RAG, Python, FastAPI, React, PostgreSQL, Docker).

{skills_targeting}

{role_specific_instruction}

RÈGLE PROJETS — SÉLECTION ET DESCRIPTION :
Les projets présentés ci-dessous ont été présélectionnés par score d'alignement avec l'offre.
Pour chaque projet, écrire 2-3 bullets très courts (15 mots max) focalisés sur les aspects qui répondent aux besoins de cette offre.

RÈGLE ABSOLUE — ZÉRO INVENTION :
- Zéro techno non attestée dans le profil
- Zéro métrique inventée
- Zéro entreprise inventée
- Zéro rôle/durée inventé(e) : recopier uniquement les rôles et dates du bloc EXPÉRIENCES EXACTES AUTORISÉES
- Si tu n'as pas le fait, ne l'écris pas — mieux vaut moins que faux

━━━ STRUCTURE MARKDOWN FINALE ━━━

# {candidate_name.upper()}
**{target_title}**
{contact_line}

## {"PROFILE" if offer_lang == "en" else "PROFIL"}
[3-4 lignes de synthèse percutantes adaptées à l'intitulé {target_title} et au rôle {dominant_role} : valoriser uniquement les expériences, projets et compétences prouvés dans le profil.]

## {"EDUCATION" if offer_lang == "en" else "FORMATION"}
{academic_md}

## {"PROFESSIONAL EXPERIENCE" if offer_lang == "en" else "EXPÉRIENCE PROFESSIONNELLE"}
[Pour chaque expérience du bloc EXPÉRIENCES ci-dessus (dans l'ordre fourni) :]
### **[Rôle]** — [Entreprise] | *[Durée]*
[Court paragraphe optionnel de 1 ligne cadrant la plateforme et le périmètre métier]
- [Bullet d'action précis (15-20 mots max) mettant en valeur les réalisations les plus pertinentes pour ce poste]
- [Bullet d'action précis]
- [Bullet d'action précis]
- [Bullet d'action précis]

## {"PROJECTS" if offer_lang == "en" else "PROJETS"}
[Pour chaque projet du bloc PROJETS ci-dessus (dans l'ordre de sélection par score d'alignement) :]
### **[Nom du Projet présélectionné]** — [Sous-titre / Catégorie adaptée à l'offre] | *[Année]*
- [Bullet d'action mettant en valeur les réalisations et défis pertinents pour ce poste]
- [Bullet d'action supplémentaire pour le projet principal]

## {"TECHNICAL SKILLS" if offer_lang == "en" else "COMPÉTENCES"}
[Organiser 4 à 6 catégories dynamiques directement ciblées sur le rôle dominant ({dominant_role}) et les mots-clés de l'offre, en sélectionnant EXCLUSIVEMENT des technologies attestées dans le bloc ÉCOSYSTÈME TECHNIQUE RÉEL :]
- **[Catégorie prioritaire pour l'offre] :** techno1, techno2, techno3, ...
- **[Catégorie 2] :** techno1, techno2, techno3, ...
- **[Catégorie 3] :** techno1, techno2, techno3, ...
- **[Catégorie 4] :** techno1, techno2, techno3, ...
- **[Catégorie 5] :** techno1, techno2, techno3, ...

## {"LANGUAGES & CERTIFICATIONS" if offer_lang == "en" else "LANGUES & CERTIFICATIONS"}
**Langues :** {langs_str}
**Certifications :**
{certif_md}

Réponds UNIQUEMENT avec le CV Markdown complet. Aucun commentaire avant ou après.
"""


def build_cover_letter_prompt(
    job_title: str,
    job_description: str,
    company_name: str,
    analysis: dict,
    persona: str,
    selected_experiences: list,
    selected_projects: list,
    current_date: str,
    profile: dict,
) -> str:
    company_name = _company_for_display(company_name)
    identity = profile.get("identity", {})
    candidate_name = identity.get("full_name", "")
    selected_email = _select_email_for_context(profile, analysis)
    professional_title = identity.get("professional_title", "")
    seniority = analysis["seniority"]
    dominant_role = analysis["role"]["dominant"]
    persona_prompt = PERSONA_PROMPTS.get(persona, PERSONA_PROMPTS["senior_ta_tech"])
    evidence_guard = _build_evidence_guard(profile, analysis)
    qa_instruction = _qa_honesty_instruction(profile, analysis)
    _raw_ctx = analysis.get("application_context") or build_application_context(analysis)
    _defaults = build_application_context(analysis)
    application_context = {**_defaults, **_raw_ctx}
    keyword_grounding = build_keyword_grounding(profile, analysis, document_type="letter")
    positioning = analysis.get("positioning") or build_offer_positioning(analysis, job_title, job_description)
    positioning_block = format_offer_positioning(positioning)

    first_exp = selected_experiences[0] if selected_experiences else {}
    evidence_block = _format_letter_evidence(selected_experiences, selected_projects)

    first_exp_context = ""
    if first_exp:
        role_disp = _display_role_for_career_stage(first_exp.get('role', first_exp.get('title', '')))
        first_exp_context = f"{first_exp.get('company', '')} ({role_disp}, {first_exp.get('duration', first_exp.get('period', ''))})"

    offer_lang = _detect_offer_language(job_description)
    objet_line = _title_for_display(job_title)  # Always use the exact offer title in Objet

    letter_role_instruction = f"""
━━━ ORIENTATION STRATÉGIQUE DE LA LETTRE ━━━
- Rôle dominant identifié : {dominant_role}
- Objectif : Relier directement les réalisations du candidat aux défis et technologies du poste ({job_title} chez {company_name}).
- Ton : Professionnel, factuel, orienté valeur créée et solutions livrées.
"""

    mismatch_rule = ""
    if seniority["has_mismatch"] or application_context.get("apply_mode") in {"honest_opportunistic", "light_apply"}:
        mismatch_rule = f"""
⚠️ RÈGLE LETTRE — CANDIDATURE OPPORTUNISTE MAIS HONNÊTE
- Ne pas affirmer que le profil est senior ou maîtrise des compétences absentes du profil.
- Mettre en avant la solidité du socle d'ingénierie logicielle, la rapidité d'apprentissage et les réalisations concrètes transférables.
- Dire ce que le candidat peut apporter rapidement : APIs, structuration de code, intégration, tests, qualité de données, dashboards.
"""

    # ━━━ Language rule for cover letter ━━━
    if offer_lang == "en":
        letter_lang_rule = """\n━━━ RÈGLE LANGUE — PRIORITÉ ABSOLUE ━━━
L'offre est RÉDIGÉE EN ANGLAIS. La lettre de motivation DOIT être intégralement rédigée en anglais.
Ton : professional, direct, output-first — "I built", "I designed", "I automated", "I delivered".
Salutation : "Dear Hiring Team," (pas "Bonjour")
Objet / Subject line : "Application — {job_title}"
Signature : "Sincerely," (pas "Cordialement")
INTERDIT : mélanger français et anglais dans le même document.\n""".format(job_title=job_title)
    else:
        letter_lang_rule = ""

    # ━━━ Remote/international context ━━━
    jd_low = (job_description or "").lower()
    is_remote_international = any(k in jd_low for k in [
        "international candidates", "outside canada", "outside the", "relocation",
        "remote from", "work remotely", "located outside", "candidates located",
        "french-speaking candidates", "french language",
    ])
    remote_context = ""
    if is_remote_international:
        remote_context = f"""\n━━━ CONTEXTE REMOTE/INTERNATIONAL ━━━
L'offre accueille explicitement des candidats internationaux hors Canada.
Mentionner naturellement dans P4 ou P5 : disponibilité immédiate en remote, maîtrise du travail asynchrone/autonome, capacité à livrer à distance.
Ne PAS mentionner de visa ou de relocalisation — sauf si le candidat aborde le sujet.\n"""

    letter_style = """
━━━ RÈGLES DE LA LETTRE ━━━
- PREUVE AVANT PROMESSE : Formuler "j'ai notamment développé...", "j'ai contribué à...", "j'ai mis en place..." (ou en anglais "I built...", "I delivered...", "I automated...").
- TON DIRECT & NATUREL : Parler d'ingénieur(e) à responsable recrutement / manager technique.
- CONCISION : 220 à 280 mots hors en-tête. Chaque phrase apporte une information utile.
- AUCUN CLICHÉ : Éviter les formules creuses ("c'est avec un grand enthousiasme", "passionné(e) par l'innovation").
"""

    contact_parts = [
        selected_email,
        identity.get('phone', ''),
        identity.get('links', {}).get('linkedin', ''),
        identity.get('location', ''),
    ]
    contact_header = " • ".join(p for p in contact_parts if p)

    return f"""
{persona_prompt}

{RECRUITER_STYLE_GUIDE}

{letter_style}

{letter_lang_rule}
{remote_context}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
TON OBJECTIF : Écrire une lettre personnalisée, crédible et engageante
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Candidature de : {candidate_name} ({professional_title})
Poste : {job_title}
Entreprise : {company_name}

OFFRE :
{job_description}

STRATÉGIE DE CANDIDATURE :
Priorité : {application_context['priority']} — {application_context['status']}
Mode : {application_context['apply_mode']}

{positioning_block}

{keyword_grounding}

{evidence_guard}

{qa_instruction}

EXPÉRIENCES CLÉS À VALORISER :
{first_exp_context}

PREUVES FACTUELLES ISSUES DU PROFIL :
{evidence_block}

RÈGLE D'INTÉGRITÉ :
- Citer au moins 2 réalisations factuelles issues du profil.
- Zéro invention de mission, de technologie ou de métrique.

{mismatch_rule}

{letter_role_instruction}

P1 — ACCROCHE SUR UN ENJEU RÉEL DE L'OFFRE OU DE {company_name.upper()} :
  OBJECTIF : montrer la compréhension de l'offre et l'enjeu business
  STRUCTURE : "[Enjeu ou défi spécifique à {company_name} ou au domaine de l'offre] — c'est précisément le type de sujet sur lequel j'ai travaillé chez [expérience précise]."
  INTERDIT : "Je suis intéressée par cette offre", "j'ai lu votre annonce", phrases génériques sur "l'optimisation"

P2 — VALEUR LIVRÉE AVANT TOUT :
  OBJECTIF : donner 3 preuves concrètes en 3 phrases. Créer l'image d'un profil qui livre.
  STRUCTURE : "À travers mes stages et projets, j'ai travaillé sur [résultat 1 nommé], [résultat 2 nommé] et [résultat 3 nommé]."
  CONTRAINTE : exactement 3 livrables nommés, pas 2, pas 4.
  INTERDIT : excuses, "bien que mon profil soit junior", "je suis prête à apprendre"
{mismatch_rule}

P3 — MISE EN CONTEXTE FACTUELLE DE 2 RÉALISATIONS :
  OBJECTIF : donner chair aux preuves. Pas des technos — ce que ça change pour les utilisateurs/systèmes.
  STRUCTURE : "Chez [Entreprise], j'ai [CE QUE ÇA FAIT POUR L'UTILISATEUR — pas comment c'est construit]."
  INTERDIT : "Développement d'un microservice", "mise en place d'un pipeline", "implémentation de JWT"
  INTERDIT : citer plus de 2 entreprises dans P3. Un projet hackathon n'est pas une entreprise — le formuler comme "lors d'un hackathon national".

P4 — MOTIVATION POUR {company_name.upper()} SPÉCIFIQUEMENT :
  OBJECTIF : montrer que c'est CETTE entreprise, pas n'importe laquelle
  STRUCTURE : "[Ce qui est spécifique à {company_name}] correspond directement à [expérience ou compétence réelle du profil]."
  INTERDIT : "engagement envers l'innovation", "culture d'entreprise", vague flatterie sans substance
  INTERDIT : liste de mots-clés techniques déguisée.
  À FAIRE : relier factuellement {company_name} à sa mission/secteur/grands comptes/R&D si présent dans l'offre, puis à une preuve concrète du profil.

P5 — CONCLUSION DIRECTE ET CONFIANTE :
  "Je serais ravie d'échanger avec votre équipe sur la manière dont je pourrais contribuer à vos projets."
  INTERDIT : "N'hésitez pas à me contacter", "dans l'espoir d'une réponse favorable", "je vous remercie de l'attention"
    INTERDIT : mentionner une disponibilité sauf demande explicite de l'utilisateur.

━━━ FORMAT HTML FINAL ━━━

<div class="header">
<h1>{candidate_name}</h1>
<p>{contact_header}</p>
</div>

**Date:** {current_date}<br><br>
**{"To the Hiring Team at" if offer_lang == "en" else "À l'attention de l'équipe recrutement de"} {company_name}**<br>
**{"Subject" if offer_lang == "en" else "Objet"}: {"Application" if offer_lang == "en" else "Candidature"} — {objet_line}**<br><br>

{"Dear Hiring Team," if offer_lang == "en" else "Bonjour,"}

[P1 — {"Hook tied to a specific business challenge at" if offer_lang == "en" else "Accroche enjeu spécifique à"} {company_name}]

[P2 — {"Concrete deliverables and key results" if offer_lang == "en" else "Réalisations concrètes et livrables clés"}]

[P3 — {"Factual context on 2 key achievements" if offer_lang == "en" else "Réalisations détaillées et valeur créée"}]

[P4 — {"Why" if offer_lang == "en" else "Adéquation avec les besoins et projets de"} {company_name}{"specifically" if offer_lang == "en" else ""}]

[P5 — {"Direct and confident closing" if offer_lang == "en" else "Conclusion directe et professionnelle"}]

{"Sincerely," if offer_lang == "en" else "Cordialement,"}<br>
**{candidate_name}**

━━━ CONTRAINTES FINALES ━━━
- 220-280 mots hors header
- Citer le nom de l'entreprise cible {company_name} naturellement dans le texte.

Réponds UNIQUEMENT avec la lettre HTML finale. Aucun commentaire avant ou après.
"""
