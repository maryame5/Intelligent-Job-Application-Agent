from __future__ import annotations

from google import genai
from openai import OpenAI
import json
import os
import re


def _extract_json(raw: str, fallback: dict) -> dict:
    text = (raw or "").strip()
    if "```" in text:
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else parts[0]
        text = re.sub(r"^json\s*", "", text.strip(), flags=re.I)
    if "{" in text and "}" in text:
        text = text[text.find("{"): text.rfind("}") + 1]
    try:
        return json.loads(text)
    except Exception:
        return fallback


try:
    from integrations.llm_clients import get_chat_llm
except ImportError:
    from llm_clients import get_chat_llm

class LLMManager:
    def __init__(self):
        # Les opérations déterministes doivent rester utilisables sans secrets.
        try:
            self.azure_llm = get_chat_llm(temperature=0.15)
        except Exception:
            self.azure_llm = None
        
        # On garde les anciens pour compatibilité ou fallback si besoin (optionnel)
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        gemini_key = os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=gemini_key) if gemini_key else None
        nvidia_key = os.getenv("NVIDIA_API_KEY")
        self.nvidia_client = (
            OpenAI(api_key=nvidia_key, base_url="https://integrate.api.nvidia.com/v1")
            if nvidia_key
            else None
        )

    def _call(self, prompt: str, temperature: float = 0.15, max_tokens: int = 1400) -> str:
        try:
            # Azure direct via llm_clients
            if self.azure_llm is None:
                raise RuntimeError("Azure LLM non configuré")
            return self.azure_llm.invoke(prompt)
        except Exception as e:
            print(f"Azure error: {e}. Fallback Gemini...")
            try:
                if self.client is None:
                    raise RuntimeError("Gemini LLM non configuré")
                r = self.client.models.generate_content(model=self.model_name, contents=prompt)
                return r.text or ""
            except Exception as e2:
                print(f"Gemini error: {e2}. Fallback NVIDIA...")
                try:
                    if self.nvidia_client is None:
                        raise RuntimeError("NVIDIA LLM non configuré")
                    nvidia_model = os.getenv("NVIDIA_MODEL", "meta/llama-3.2-11b-vision-instruct")
                    r = self.nvidia_client.chat.completions.create(
                        model=nvidia_model,
                        messages=[{"role": "user", "content": prompt}],
                        temperature=temperature,
                        max_tokens=max_tokens,
                    )
                    return r.choices[0].message.content or ""
                except Exception as e3:
                    print(f"Fallback NVIDIA error: {e3}")
                    return ""

    def analyze_job_match(self, job_description: str, user_profile: dict) -> dict:
        """
        Score plus strict que l'ancien:
        - pas de score optimiste par défaut si erreur LLM;
        - distinction Direct / Transferable / Missing;
        - recommandation basée sur le risque recruteur.
        """
        prompt = f"""Tu es un Lead Recruiter & Engineering Manager technique. Analyse avec précision et rigueur l'adéquation entre le profil et l'offre d'emploi.

PROFIL CANDIDAT JSON:
{json.dumps(user_profile, ensure_ascii=False, indent=2)}

OFFRE D'EMPLOI:
{job_description}

Retourne UNIQUEMENT un objet JSON valide suivant exactement ce schéma:
{{
  "match_score": 0,
  "match_level": "High|Medium|Low|Reject",
  "role_family": "backend|frontend|fullstack|data|ai|cloud_devops|consulting|architecture|general",
  "direct_matches": ["compétences de l'offre directement prouvées par l'expérience ou projets"],
  "transferable_matches": ["compétences connexes transposables avec preuve"],
  "missing_critical": ["exigences clés de l'offre absentes du profil"],
  "recruiter_angle": "angle de positionnement percutant en une phrase",
  "cv_strategy": ["axe concret de mise en valeur dans le CV"],
  "cover_letter_strategy": ["argument clé pour la lettre de motivation"],
  "recommendation": "Postuler|Postuler avec adaptation|Ne pas postuler",
  "reasoning": "explication concise justifiant précisément le score attribué"
}}

Barème d'attribution du match_score (sur 100) :
- 85-100: Alignement exceptionnel (stack identique, missions déjà réalisées, rôle cible naturel).
- 70-84: Très bon profil (compétences majeures validées, légers gaps facilement comblables).
- 55-69: Profil pertinent avec adaptation (socle technique solide, quelques technos différentes mais bonne transférabilité).
- 35-54: Candidature opportuniste ou partielle (compétences généralistes communes, mais écart important sur le cœur de mission ou les outils).
- 1-34: Offre hors cible (métier sans rapport, stack totalement disjointe ou profil inadapté).
- 0: Description vide, inexploitable ou offre non technique / commerciale.

Consigne stricte de notation :
Ne pas attribuer un score rond arbitraire (évite d'arrondir par défaut à 50). Attribue une note calculée selon la proportion réelle des compétences couvertes (ex: 64, 78, 42, 88).
"""
        raw = self._call(prompt)
        fallback = {
            "match_score": 0,
            "match_level": "Review",
            "role_family": "general",
            "direct_matches": [],
            "transferable_matches": [],
            "missing_critical": ["Analyse LLM indisponible"],
            "recruiter_angle": "Vérification manuelle nécessaire.",
            "cv_strategy": [],
            "cover_letter_strategy": [],
            "recommendation": "Ne pas postuler automatiquement",
            "reasoning": "L'analyse automatique a échoué; score non fiable.",
        }
        data = _extract_json(raw, fallback)
        try:
            data["match_score"] = max(0, min(100, int(data.get("match_score", 0))))
        except Exception:
            data["match_score"] = 0
        return data

    def find_hiring_manager(self, company_name: str, job_title: str, job_description: str = "") -> dict:
        emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', job_description or "")
        valid = [e for e in emails if not any(b in e.lower() for b in ["noreply", "support"])]
        if valid:
            return {"email": valid[0], "source": "job_description", "approach_strategy": "Email trouvé dans l'offre."}

        prompt = f"""Pour l'entreprise {company_name} et le poste {job_title}, propose des requêtes pour trouver le recruteur.
Réponds uniquement en JSON:
{{
  "search_queries": ["..."],
  "likely_titles": ["Talent Acquisition", "HR Manager"],
  "company_linkedin_url": "",
  "approach_strategy": "",
  "suggested_email_formats": ["prenom.nom@domaine"]
}}
"""
        raw = self._call(prompt, temperature=0.2, max_tokens=700)
        return _extract_json(raw, {"search_queries": [], "likely_titles": [], "approach_strategy": "Vérification manuelle."})
