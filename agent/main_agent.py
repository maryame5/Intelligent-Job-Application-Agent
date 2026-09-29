# main_agent.py
import csv
import os
import sys
import time
import json
import markdown
import re
from datetime import datetime
from typing import TypedDict, List, Dict, Any, Optional

# Allow absolute package imports when this file is launched directly.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
from langgraph.graph import StateGraph, END

# Charger les variables d'environnement (.env)
load_dotenv()

import warnings
try:
    from langchain_core._api import LangChainPendingDeprecationWarning
    warnings.filterwarnings("ignore", category=LangChainPendingDeprecationWarning)
except ImportError:
    pass

from matching.offer_scoring import _norm
from scrapers.linkedin import LinkedInScraper
from scrapers.rekrute import RekruteScraper
from scrapers.indeed import IndeedScraper
from scrapers.emploi_ma import EmploiMaScraper
from scrapers.bayt import BaytScraper
from integrations.sheets_manager import JobTracker
from integrations.llm_manager import LLMManager
from core.cv_tailor import CVTailor, build_full_report_markdown
from integrations.email_finder import EmailFinder
from integrations.email_sender import EmailOutreach


# Définition de l'Etat de l'Agent selon les bonnes pratiques LangGraph
class JobAgentState(TypedDict):
    search_queries: List[str]
    locations: List[str]
    max_jobs_per_source: int
    raw_jobs: List[Dict[str, Any]]
    unique_jobs: List[Dict[str, Any]]
    high_match_jobs: List[Dict[str, Any]]
    final_jobs: List[Dict[str, Any]]

class JobApplicationAgent:
    def __init__(self):
        self.linkedin = LinkedInScraper()
        self.rekrute = RekruteScraper()
        self.indeed = IndeedScraper()
        self.emploi_ma = EmploiMaScraper()
        self.bayt = BaytScraper()
        self.tracker = JobTracker()
        self.llm = LLMManager()
        self.cv_tailor = CVTailor()
        self.email_finder = EmailFinder()
        self.company_context_cache: Dict[str, str] = {}
        self.scrape_health_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scrape_health_log.csv")
        self._ensure_scrape_health_log()
        os.makedirs('output', exist_ok=True)

        self.user_profile = self.cv_tailor.profile
        semantic_active = bool(os.getenv("GEMINI_API_KEY")) and self.cv_tailor.semantic._is_available()
        print(f"✅ Profil utilisateur chargé dynamiquement via CVTailor")
        print(f"🔎 Semantic matching: {'actif' if semantic_active else 'désactivé (fallback lexique)'}")

        # Architecture LangGraph
        self.app = self._build_graph()

    def _ensure_scrape_health_log(self):
        if not os.path.exists(self.scrape_health_path):
            with open(self.scrape_health_path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["timestamp", "source", "jobs_found", "descriptions_missing", "missing_ratio"])

    def _log_scrape_health(self, source: str, jobs_found: int, descriptions_missing: int):
        try:
            row = [
                datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                str(source),
                int(jobs_found),
                int(descriptions_missing),
                round((descriptions_missing / jobs_found) if jobs_found else 0.0, 3),
            ]
            with open(self.scrape_health_path, "a", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(row)
        except Exception:
            pass

    @staticmethod
    def _normalize_title_tokens(value: Any) -> List[str]:
        text = _norm(value or "")
        text = re.sub(r"[^a-z0-9]+", " ", text)
        tokens = [token for token in text.split() if len(token) > 1]
        normalized = []
        for token in tokens:
            token = token.strip()
            if not token:
                continue
            normalized.append(token)
            for suffix in ("e", "es", "s", "aux", "ale", "ales", "elle", "elles", "eur", "eurs", "euse", "euses"):
                if token.endswith(suffix) and len(token) > len(suffix) + 2:
                    normalized.append(token[:-len(suffix)])
        return normalized

    @classmethod
    def _is_blacklisted_title(cls, title: Any) -> bool:
        blacklist = {
            "commercial", "commerciale", "commerciaux",
            "vente", "ventes", "vendeur", "vendeurs", "vendeuse", "vendeuses", "televendeur", "televendeuse", "televendeurs", "televendeuses",
            "assurance", "assurances", "assureur", "assureurs",
            "teleconseiller", "telesales", "callcenter", "call", "center", "centre",
            "sales", "clientele", "clients", "charge", "charges"
        }
        tokens = set(cls._normalize_title_tokens(title))
        return bool(tokens & blacklist)

    @staticmethod
    def _dedupe_key(job: Dict[str, Any]) -> str:
        title = _norm(job.get("job_title") or "")
        company = _norm(job.get("company_name") or "")
        title = re.sub(r"[^a-z0-9]+", " ", title).strip()
        company = re.sub(r"[^a-z0-9]+", " ", company).strip()
        if title and company:
            return f"{title}|{company}"
        return (job.get("job_url") or "").strip()

    def enrich_company_context(self, company_name: str) -> str:
        company_name = (company_name or "").strip()
        if not company_name:
            return ""
        normalized = _norm(company_name)
        if normalized in self.company_context_cache:
            return self.company_context_cache[normalized]
        context = (
            f"{company_name} évolue dans un contexte technologique/entreprise orienté livraison, collaboration cross-functional "
            "et impact métier. La lettre doit montrer une compréhension claire du besoin produit, des APIs/architecture et de la qualité de la solution."
        )
        self.company_context_cache[normalized] = context
        return context

    def _apply_feedback_guard(self, match_score: int) -> tuple[int, List[str]]:
        try:
            tracker_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jobs_tracker.csv")
            if not os.path.exists(tracker_path):
                return match_score, []
            with open(tracker_path, "r", encoding="utf-8", newline="") as fh:
                rows = list(csv.DictReader(fh))
            if len(rows) < 20:
                return match_score, []
            outcomes = [row for row in rows if (row.get("Outcome") or "").strip().lower() in {"interview", "rejected", "no_response", "offer"}]
            if len(outcomes) < 20:
                return match_score, []
            # pyrefly: ignore [missing-import]
            from matching.analyze_feedback import analyze_outcomes
            stats = analyze_outcomes(rows)
            pos = stats["averages"]["positive"]["final_ats"]
            neg = stats["averages"]["negative"]["final_ats"]
            if pos <= 0 or neg <= 0:
                return match_score, []
            delta = pos - neg
            if delta >= 10:
                adjusted = min(100, int(match_score + 4))
                return adjusted, [f"Feedback ajusté: delta de {delta} pts entre les candidatures converties et non-converties (seuil 20+ résultats)."]
            if delta <= -10:
                adjusted = max(0, int(match_score - 4))
                return adjusted, [f"Feedback ajusté: delta négatif de {delta} pts, prudence sur le score de correspondance (seuil 20+ résultats)."]
        except Exception:
            pass
        return match_score, []

    def _build_graph(self):
        """Construction du graph LangChain (Pipeline Workflow)"""
        workflow = StateGraph(JobAgentState)
        
        # Ajout des noeuds
        workflow.add_node("scrape", self.scrape_node)
        workflow.add_node("store_and_filter", self.store_and_filter_node)
        workflow.add_node("analyze_matches", self.analyze_matches_node)
        workflow.add_node("tailor_and_apply", self.tailor_and_apply_node)
        
        # Définition des arêtes (edges)
        workflow.set_entry_point("scrape")
        workflow.add_edge("scrape", "store_and_filter")
        workflow.add_edge("store_and_filter", "analyze_matches")
        workflow.add_edge("analyze_matches", "tailor_and_apply")
        workflow.add_edge("tailor_and_apply", END)
        
        return workflow.compile()

    def _preprocess_markdown_for_cv(self, markdown_text: str) -> str:
        """Nettoie et restructure le markdown CV pour un rendu HTML/PDF net et sans rupture."""
        # 1. Nettoyage encodage & tirets
        text = markdown_text.replace("\ufffd", "–")
        
        lines = []
        raw_lines = text.split("\n")
        in_header = True
        
        for idx, line in enumerate(raw_lines):
            line_str = line.strip()
            
            if line_str.startswith("## "):
                in_header = False
                
            # Titre cible sous le nom dans l'en-tête (ex: **Conversational AI Engineer**)
            if in_header and line_str.startswith("**") and line_str.endswith("**") and ":" not in line_str and not line_str.startswith("#"):
                clean_title = line_str.strip("*")
                lines.append(f'<div class="target-title">{clean_title}</div>')
                continue
                
            # Ligne de contact dans l'en-tête
            if in_header and ("@" in line_str or "linkedin" in line_str.lower()) and not line_str.startswith("#"):
                if "[" in line_str and "](" in line_str:
                    clean_contact = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', line_str)
                else:
                    clean_contact = re.sub(r'(https?://(?:www\.)?([^\s|]+))', r'<a href="\1">\2</a>', line_str)
                lines.append(f'<div class="header-contact">{clean_contact}</div>')
                continue

            # Normalisation des puces '•' en '-'
            if line_str.startswith("• "):
                line_str = "- " + line_str[2:].strip()

            # Formatage des sous-titres d'expériences / projets
            if line_str.startswith("###"):
                content = line_str.lstrip("#").strip()
                parts = [p.strip() for p in content.split("|") if p.strip()]
                if len(parts) >= 3:
                    role_part = parts[0].strip()
                    comp_part = parts[1].strip()
                    date_part = parts[2].replace("*", "").strip()
                    lines.append(f'### <span class="job-role">{role_part}</span> <span class="job-sep">—</span> <span class="job-company">{comp_part}</span> <span class="job-date">*{date_part}*</span>')
                elif len(parts) == 2:
                    left_part = parts[0].strip()
                    right_part = parts[1].replace("*", "").strip()
                    # Si la date est un mois isolé tronqué (ex: "Juil", "Juil."), compléter l'année
                    if right_part.lower() in {"juil", "juil.", "juillet", "fev", "fév", "mars", "avr", "mai", "juin", "aout", "août", "sep", "oct", "nov", "dec", "déc"}:
                        right_part = f"{right_part} 2024"
                    lines.append(f'### <span class="job-role">{left_part}</span> <span class="job-date">*{right_part}*</span>')
                else:
                    lines.append(line_str)
            elif line_str.startswith("**") and (":**" in line_str or ": **" in line_str or "**:" in line_str) and not line_str.startswith("-"):
                # Transformer les lignes de compétences isolées en puces (sauf sous-titres de langues/certifs)
                if not any(line_str.lower().startswith(p) for p in ["**langue", "**certif"]):
                    if lines and lines[-1].strip() and not lines[-1].strip().startswith(("-", "#")):
                        lines.append("")
                    lines.append(f"- {line_str}")
                else:
                    lines.append(line_str)
            elif line_str.startswith(("Diplôme", "CPGE", "Baccalauréat", "Licence", "Master", "Doctorat")) and not line_str.startswith("-"):
                # Transformer les lignes de formation isolées en puces
                if lines and lines[-1].strip() and not lines[-1].strip().startswith(("-", "#")):
                    lines.append("")
                lines.append(f"- {line_str}")
            elif line_str.startswith("- "):
                # S'assurer qu'une liste à puces est séparée d'un paragraphe précédent
                if lines and lines[-1].strip() and not lines[-1].strip().startswith(("-", "#")):
                    lines.append("")
                lines.append(line_str)
            else:
                lines.append(line_str)
        return "\n".join(lines)

    def generate_pdf(self, markdown_text, output_pdf_path, doc_type='cv'):
        try:
            if doc_type == 'cv':
                cleaned_md = self._preprocess_markdown_for_cv(markdown_text)
            else:
                cleaned_md = markdown_text.replace("\ufffd", "–")

            html_content = markdown.markdown(cleaned_md, extensions=['extra', 'tables'])

            if doc_type == 'cv':
                css = """
                @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
                * { box-sizing: border-box; margin: 0; padding: 0; }
                @page {
                    size: A4;
                    margin: 10mm 12mm 10mm 12mm;
                }
                body {
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                    font-size: 8.8pt;
                    color: #1e293b;
                    line-height: 1.35;
                    background: #ffffff;
                }
                h1 {
                    font-size: 19pt;
                    color: #0f4c81;
                    font-weight: 700;
                    margin-bottom: 2px;
                    letter-spacing: -0.3px;
                }
                .target-title {
                    font-size: 10.5pt;
                    color: #0f4c81;
                    font-weight: 600;
                    margin-bottom: 2px;
                }
                .contact-line, .header-contact {
                    font-size: 8.5pt;
                    color: #475569;
                    font-weight: 500;
                    border-bottom: 1.2px solid #cbd5e1;
                    padding-bottom: 5px;
                    margin-bottom: 7px;
                }
                h2 {
                    font-size: 9.5pt;
                    color: #0f4c81;
                    font-weight: 700;
                    text-transform: uppercase;
                    letter-spacing: 0.6px;
                    border-bottom: 1.2px solid #0f4c81;
                    padding-bottom: 2px;
                    margin-top: 8px;
                    margin-bottom: 4px;
                    page-break-after: avoid;
                }
                h3 {
                    font-size: 9pt;
                    color: #0f172a;
                    font-weight: 600;
                    display: flex;
                    justify-content: space-between;
                    align-items: baseline;
                    margin-top: 5px;
                    margin-bottom: 2px;
                    page-break-after: avoid;
                }
                .job-role {
                    font-weight: 700;
                    color: #0f172a;
                }
                .job-sep {
                    color: #94a3b8;
                    margin: 0 4px;
                    font-weight: 400;
                }
                .job-company {
                    color: #0f4c81;
                    font-weight: 600;
                }
                .job-date, h3 em {
                    font-size: 8.2pt;
                    color: #64748b;
                    font-style: italic;
                    font-weight: 500;
                    white-space: nowrap;
                    margin-left: auto;
                }
                p {
                    font-size: 8.8pt;
                    margin-bottom: 4px;
                    line-height: 1.35;
                    text-align: justify;
                }
                ul {
                    padding-left: 14px;
                    margin: 2px 0 5px 0;
                }
                li {
                    font-size: 8.5pt;
                    line-height: 1.3;
                    margin-bottom: 2px;
                    color: #334155;
                }
                li::marker { color: #0f4c81; font-size: 0.85em; }
                strong { color: #0f172a; font-weight: 600; }
                em { color: #64748b; font-style: normal; font-size: 8.5pt; font-weight: 500; }
                a { color: #0f4c81; text-decoration: none; }
                hr { display: none; }
                """
            else:
                # CSS for Cover Letter
                css = """
                @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap');
                * { box-sizing: border-box; }
                @page {
                    size: A4;
                    margin: 15mm 18mm 15mm 18mm;
                }
                body {
                    font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif;
                    font-size: 10.5pt;
                    color: #1e293b;
                    line-height: 1.6;
                    background: #ffffff;
                }
                h1 {
                    font-size: 18pt;
                    color: #0f4c81;
                    font-weight: 600;
                    margin-bottom: 6px;
                    border-bottom: 1.5px solid #cbd5e1;
                    padding-bottom: 10px;
                    margin-bottom: 18px;
                }
                h2, h3 { font-size: 11pt; color: #0f172a; font-weight: 600; margin-bottom: 6px; }
                p { margin: 0 0 10px 0; text-align: justify; }
                ul { padding-left: 18px; margin: 6px 0 12px 0; }
                li { margin-bottom: 3px; font-size: 10pt; }
                strong { color: #0f172a; font-weight: 600; }
                em { color: #475569; font-style: italic; }
                a { color: #0f4c81; text-decoration: none; }
                """

            styled_html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<style>
{css}
</style>
</head>
<body>
{html_content}
</body>
</html>"""

            # Playwright est le moteur principal (rendu Chrome, support CSS complet)
            try:
                from playwright.sync_api import sync_playwright

                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page()
                    page.set_content(styled_html, wait_until="networkidle")
                    margin_config = (
                        {"top": "10mm", "right": "12mm", "bottom": "10mm", "left": "12mm"}
                        if doc_type == 'cv'
                        else {"top": "15mm", "right": "18mm", "bottom": "15mm", "left": "18mm"}
                    )
                    page.pdf(
                        path=output_pdf_path,
                        format="A4",
                        print_background=True,
                        margin=margin_config,
                    )
                    browser.close()
                return True
            except Exception as pw_error:
                print(f"    ⚠️ Playwright failed, trying xhtml2pdf fallback: {pw_error}")
                # Fallback xhtml2pdf (CSS simplifié, pas de flex ni text-transform)
                from xhtml2pdf import pisa
                with open(output_pdf_path, "wb") as pdf_file:
                    result = pisa.CreatePDF(
                        styled_html.encode("utf-8"),
                        dest=pdf_file,
                        encoding="utf-8"
                    )
                if result.err:
                    raise RuntimeError("xhtml2pdf also failed to generate the PDF")
                return True
        except Exception as e:
            print(f"    ❌ Error generating PDF: {e}")
            return False

    def enrich_jobs_with_contacts(self, jobs):
        """Trouve les contacts pour chaque offre"""
        enriched = []
        for job in jobs:
            print(f"  🔍 Finding contact for: {job.get('company_name', 'Unknown')}...")
            contact_info = self.email_finder.find_contact_for_job(job)
            job['contact_emails'] = contact_info['emails_found']
            job['contact_confidence'] = contact_info['confidence']
            job['application_method'] = contact_info['application_method']
            job['domain'] = contact_info['domain']
            job['linkedin_queries'] = contact_info['linkedin_search_queries']
            enriched.append(job)
        return enriched

    def ensure_full_job_description(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Ensure CV tailoring uses the real job description, not a short card snippet.
        Generic CVs usually happen when the scraper stored only 1-2 lines in jobs_tracker.csv.
        """
        description = (job.get('description') or '').strip()
        is_placeholder = (
            not description 
            or "Description indisponible pour le moment" in description
            or description.lower().startswith("intérim")
            or description.lower().startswith("temps plein")
            or description.lower().startswith("cdi")
        )
        if len(description) >= 300 and not is_placeholder:
            return job

        source = job.get('source', '')
        job_url = (job.get('job_url') or '').strip()
        job_id = job.get('job_id')

        # Si LinkedIn et job_id manquant, extraire depuis l'URL
        if source == 'LinkedIn' and not job_id and job_url:
            match = re.search(r'([0-9]{8,12})', job_url)
            if match:
                job_id = match.group(1)
                job['job_id'] = job_id

        details = {}
        try:
            if source == 'LinkedIn' and job_id:
                details = self.linkedin.get_job_details(job_id)
            elif source == 'Rekrute' and job_url:
                details = self.rekrute.get_job_details(job_url)
            elif source == 'Indeed' and job_url:
                details = self.indeed.get_job_details(job_url)
            elif source == 'Bayt.com' and job_url:
                details = self.bayt.get_job_details(job_url)
            elif source == 'Emploi.ma' and job_url:
                details = self.emploi_ma.get_job_details(job_url)
        except Exception as e:
            print(f"    ⚠️ Impossible de récupérer la description complète ({source}): {e}")

        full_description = (details.get('description') or '').strip()
        if full_description and (len(full_description) > len(description) or is_placeholder):
            job['description'] = full_description
            if job_url:
                self.tracker.update_job_status(job_url, description=full_description)
        return job

    def apply_to_job(self, job, tailored_cv, cover_letter):
        """
        Postule a une offre selon le canal disponible
        """
        method = job.get('application_method', 'unknown')
        emails = job.get('contact_emails', [])
        can_email = method in {'email_direct_from_job_posting', 'email_from_company_website'}
        auto_send = os.getenv("JOB_AGENT_SEND_EMAILS", "false").lower().strip() in {"1", "true", "yes", "on"}

        if can_email and emails:
            to_email = emails[0]
            if not auto_send:
                print(f"    Email pret a envoyer a: {to_email} (JOB_AGENT_SEND_EMAILS=false)")
                return 'email_ready'
            try:
                print(f"    Envoi d'email direct a: {to_email}")
                sender = EmailOutreach(os.getenv("GMAIL_CREDENTIALS_FILE", "gmail_credentials.json"))
                sent = sender.send_application_email(
                    to_email=to_email,
                    job_title=job.get('job_title', ''),
                    company_name=job.get('company_name', ''),
                    cover_letter=cover_letter,
                    resume_markdown=tailored_cv,
                    hiring_manager_name=job.get('hiring_manager_name') or '',
                    candidate_profile=self.user_profile,
                )
                return 'email_sent' if sent else 'email_failed'
            except Exception as e:
                print(f"    Envoi email impossible: {e}")
                return 'email_failed'

        if method == 'generic_email_guess' and emails:
            print(f"    Emails generiques detectes, verification manuelle recommandee: {', '.join(emails[:3])}")
            return 'email_verification_needed'

        if method == 'email_direct_from_job_posting' and emails:
            print(f"    📧 Envoi d'email direct à: {emails[0]}")
            return 'email_sent'

        elif method == 'email_from_company_website' and emails:
            print(f"    📧 Envoi d'email direct à: {emails[0]}")
            return 'email_sent'

        elif job.get('job_url'):
            print(f"    🔗 Candidature manuelle via URL (simulé): {job['job_url']}")
            return 'manual_apply_url_opened'

        else:
            print("    ❓ Aucun contact direct trouvé. Requêtes LinkedIn à tester:")
            for q in job.get('linkedin_queries', []):
                print(f"      - {q}")
            return 'linkedin_search_needed'

    def classify_application(self, match_score: int, seniority_mismatch: bool) -> dict:
        """
        On ne bloque plus les offres senior/risquées.
        On les classe pour générer un CV honnête et décider du temps à investir.
        """
        try:
            score = max(0, min(100, int(match_score or 0)))
        except Exception:
            score = 0

        if score >= 75 and not seniority_mismatch:
            return {
                "priority": "A",
                "status": "Strong Match",
                "apply_mode": "direct_application",
                "risk_level": "low",
                "time_budget_minutes": 25,
                "auto_apply_recommended": True,
            }
        if score >= 55 and not seniority_mismatch:
            return {
                "priority": "B",
                "status": "Medium Match",
                "apply_mode": "adapted_application",
                "risk_level": "medium",
                "time_budget_minutes": 18,
                "auto_apply_recommended": True,
            }
        if seniority_mismatch or score >= 35:
            return {
                "priority": "C",
                "status": "Opportunistic Match",
                "apply_mode": "honest_opportunistic",
                "risk_level": "high",
                "time_budget_minutes": 10,
                "auto_apply_recommended": False,
            }
        return {
            "priority": "D",
            "status": "Low Match",
            "apply_mode": "light_apply",
            "risk_level": "very_high",
            "time_budget_minutes": 5,
            "auto_apply_recommended": False,
        }

    # --- NOEUDS DU GRAPH LANGCHAIN ---

    def scrape_node(self, state: JobAgentState) -> JobAgentState:
        print("\n--- PHASE 1: Scraping des offres (LangGraph Node) ---")
        search_queries = state.get("search_queries", [])
        locations = state.get("locations", [])
        max_jobs = state.get("max_jobs_per_source", 10)
        
        all_jobs = []
        for query in search_queries:
            for location in locations:
                print(f"🔍 Recherche: '{query}' à '{location}'")
                
                scrapers = [
                    (self.linkedin, "LinkedIn"),
                    (self.rekrute, "Rekrute"),
                    (self.indeed, "Indeed"),
                    (self.emploi_ma, "Emploi.ma"),
                    (self.bayt, "Bayt.com")
                ]

                for scraper_obj, name in scrapers:
                    try:
                        print(f"  Fetching {name}...")
                        jobs = scraper_obj.search_jobs(query, location, pages=1)
                        enriched_jobs = []
                        for job in jobs[:max_jobs]:
                            job = self.ensure_full_job_description(job)
                            if not (job.get('description') or '').strip():
                                job['description'] = 'Description indisponible pour le moment - consulter le lien source.'
                            enriched_jobs.append(job)
                        missing_count = sum(1 for j in enriched_jobs if not (j.get('description') or '').strip())
                        self._log_scrape_health(name, len(enriched_jobs), missing_count)
                        all_jobs.extend(enriched_jobs)
                        print(f"    {name}: {len(enriched_jobs)} jobs")
                    except Exception as e:
                        print(f"    {name} error: {e}")
                
                time.sleep(2)
        
        return {"raw_jobs": all_jobs}

    def store_and_filter_node(self, state: JobAgentState) -> JobAgentState:
        print("\n--- PHASE 2: Stockage et Filtrage (LangGraph Node) ---")
        all_jobs = state.get("raw_jobs", [])
        
        seen_urls = set()
        seen_dedupe_keys = set()
        unique_jobs = []
        for job in all_jobs:
            title = job.get('job_title', '')
            # Filtrage blacklist immédiat avant stockage pour ne pas polluer le CSV ni consommer du LLM
            if self._is_blacklisted_title(title):
                continue

            job_url = (job.get('job_url') or '').strip()
            if job_url and job_url in seen_urls:
                continue
            dedupe_key = self._dedupe_key(job)
            if dedupe_key and dedupe_key in seen_dedupe_keys:
                continue
            if job_url:
                seen_urls.add(job_url)
            if dedupe_key:
                seen_dedupe_keys.add(dedupe_key)
            unique_jobs.append(job)

        print(f"\n✨ Total unique jobs found: {len(unique_jobs)}")
        self.tracker.add_jobs(unique_jobs)

        # TRI PAR PERTINENCE
        target_roles = self.user_profile.get('career_strategy', {}).get('target_roles', [])
        important_keywords = target_roles + ["AI", "Python", "Fullstack", "Backend", "Engineer", "React", "TypeScript", "FastAPI", "Java", "Spring"]
        
        def get_relevance(job):
            title = job.get('job_title', '').lower()
            desc = job.get('description', '').lower()
            score = 0
            for kw in important_keywords:
                kw_l = kw.lower()
                if kw_l in title: score += 5 
                if kw_l in desc: score += 1  
            return score

        unique_jobs.sort(key=get_relevance, reverse=True)
        return {"unique_jobs": unique_jobs}

    def analyze_matches_node(self, state: JobAgentState) -> JobAgentState:
        unique_jobs = state.get("unique_jobs", [])
        print(f"\n--- PHASE 3: Analyse de correspondance (LangGraph Node) - {len(unique_jobs)} jobs ---")
        
        seen_urls = {j.get('job_url') for j in unique_jobs}
        # Limite à 10 pending jobs non encore scorés pour éviter l'effet boule de neige
        pending_jobs = self.tracker.get_pending_jobs(limit=10, unscored_only=True)
        
        if pending_jobs:
            print(f"  🔍 {len(pending_jobs)} jobs en attente détectés dans le CSV. Ajout à l'analyse...")
            for pj in pending_jobs:
                if pj['Job URL'] not in seen_urls:
                    job_id = None
                    if pj['Source'] == 'LinkedIn' and pj['Job URL']:
                        match = re.search(r'view/([0-9]+)', pj['Job URL'])
                        if match:
                            job_id = match.group(1)

                    unique_jobs.append({
                        'job_title': pj['Job Title'],
                        'company_name': pj['Company Name'],
                        'job_url': pj['Job URL'],
                        'job_id': job_id,
                        'source': pj['Source'],
                        'description': pj.get('Job Description', '')
                    })
                    seen_urls.add(pj['Job URL'])

        high_match_jobs = []
        
        for i, job in enumerate(unique_jobs):
            title = job.get('job_title', '')
            if self._is_blacklisted_title(title):
                print(f"    ⏭️ Offre ignorée par blacklist métier : {title}")
                if job.get('job_url'):
                    self.tracker.update_job_status(job['job_url'], status="Rejected_Blacklist")
                continue
                
            job = self.ensure_full_job_description(job)
            description = job.get('description', '')
            
            if description:
                self.tracker.update_job_status(job['job_url'], description=description)
                
                analysis = self.llm.analyze_job_match(description, self.user_profile)
                match_score = analysis.get('match_score', 0)
                adjusted_score, feedback_notes = self._apply_feedback_guard(match_score)
                if adjusted_score != match_score:
                    match_score = adjusted_score
                    print(f"    📈 Score ajusté via feedback historique: {adjusted_score}/100 ({'; '.join(feedback_notes)})")
                print(f"    Match score: {match_score}/100")

                seniority_info = self.cv_tailor.analyzer.detect_seniority_mismatch(job['job_title'], description)
                classification = self.classify_application(
                    match_score=match_score,
                    seniority_mismatch=seniority_info.get('has_mismatch', False)
                )

                job['seniority_mismatch'] = seniority_info
                job['application_strategy'] = classification['apply_mode']
                job['application_priority'] = classification['priority']
                job['application_status'] = classification['status']
                classification['match_score'] = match_score   # propagé vers CVTailor.generate()
                job['application_context'] = classification
                job['match_score'] = match_score
                job['analysis'] = analysis

                if seniority_info.get('has_mismatch'):
                    print(f"    ⚠️ Écart de séniorité détecté — on postule quand même en mode {classification['apply_mode']}")

                print(
                    f"    📌 Priorité {classification['priority']} — {classification['status']} "
                    f"| mode={classification['apply_mode']} | budget≈{classification['time_budget_minutes']}min"
                )

                # IMPORTANT : on ajoute toutes les offres analysables, même Low Match.
                high_match_jobs.append(job)
                self.tracker.update_job_status(
                    job['job_url'],
                    status=f"{classification['priority']} — {classification['status']}",
                    llm_score=match_score,
                    notes=(
                        f"Mode: {classification['apply_mode']} | Risque: {classification['risk_level']} | "
                        f"Score: {match_score}/100 | {analysis.get('reasoning', '')}"
                    )
                )
            time.sleep(2) # Temporisation 2s pour respecter les quotas Azure RPM

        print(f"\n🎯 Offres à fort potentiel: {len(high_match_jobs)}")
        return {"high_match_jobs": high_match_jobs}

    def tailor_and_apply_node(self, state: JobAgentState) -> JobAgentState:
        high_match_jobs = state.get("high_match_jobs", [])
        
        if high_match_jobs:
            print("\n--- PHASE 4: Personnalisation des CV et Recherche de Contacts (LangGraph Node) ---")
            high_match_jobs = self.enrich_jobs_with_contacts(high_match_jobs)
            
            for job in high_match_jobs:
                if job.get('cv_tailored') == 'Yes':
                    continue

                priority = job.get('application_priority', '?')
                status = job.get('application_status', 'Match')
                final_strategy = job.get('application_strategy', 'direct_application')
                strategy_label = f"{priority} — {status}"
                print(f"  [{strategy_label}] Tailoring CV for: {job['job_title']} @ {job['company_name']}")
                
                try:
                    job = self.ensure_full_job_description(job)
                    desc_clean = (job.get('description') or '').strip()
                    is_placeholder = "Description indisponible pour le moment" in desc_clean
                    if len(desc_clean) < 120 or is_placeholder:
                        print("    ⛔ Description trop courte ou indisponible: CV non généré.")
                        if job.get('job_url'):
                            self.tracker.update_job_status(job['job_url'], status="Skipped_Short_Description")
                        continue

                    # Appel du moteur v6 (Azure/Azure fallbacks)
                    result = self.cv_tailor.generate(
                        job_description=job.get('description', ''),
                        job_title=job['job_title'],
                        company_name=job['company_name'],
                        verbose=True,
                        application_context=job.get('application_context')
                    )
                    
                    tailored_cv = result["cv"]
                    cover_letter = result["lettre"]

                    self.tracker.ensure_job_id(job)
                    
                    # Noms de fichiers fondés sur l'identifiant de l'offre
                    candidate_full_name = self.user_profile.get("identity", {}).get("full_name", "candidate")
                    name_slug = re.sub(r"[^a-zA-Z0-9]+", "_", candidate_full_name).upper().strip("_")
                    cv_filename_base = f"output/cv_{name_slug}_{job['job_id']}"
                    cl_filename_base = f"output/lm_{job['job_id']}"
                    
                    # Generation PDF
                    self.generate_pdf(tailored_cv, f"{cv_filename_base}.pdf", doc_type='cv')
                    self.generate_pdf(cover_letter, f"{cl_filename_base}.pdf", doc_type='letter')
                    
                    # Sauvegarde Markdown
                    with open(f"{cv_filename_base}.md", "w", encoding="utf-8") as f:
                        f.write(tailored_cv)
                    with open(f"{cl_filename_base}.md", "w", encoding="utf-8") as f:
                        f.write(cover_letter)

                    # Rapport gap analysis + checklist ATS + score final (une pensée avancée par offre)
                    report_md = build_full_report_markdown(result, job['job_title'], job['company_name'])
                    report_path = f"output/rapport_{job['job_id']}.md"
                    with open(report_path, "w", encoding="utf-8") as f:
                        f.write(report_md)

                    final_score = result.get("scoring", {}).get("final", {}).get("final_score", 0)
                    job['final_ats_score'] = final_score
                    review_flag = " ⚠️ SCORE FAIBLE — à relire avant envoi" if final_score < 60 else ""
                    print(f"    ✅ Documents (CV + LM + rapport) sauvegardés dans output/ "
                          f"— score final {final_score}/100{review_flag}")
                    
                    # Application via le contact trouvé
                    app_ctx = job.get('application_context') or {}
                    auto_apply = (
                        bool(app_ctx.get("auto_apply_recommended", False))
                        and os.getenv("JOB_AGENT_SEND_EMAILS", "false").lower().strip() in {"1", "true", "yes", "on"}
                    )
                    method = self.apply_to_job(job, tailored_cv, cover_letter) if auto_apply else "manual_review_needed"
                    
                    # Sync Tracker
                    if method == "email_sent":
                        tracker_status = "Applied"
                    elif not auto_apply:
                        tracker_status = f"Documents Ready — Review Recommended ({priority})"
                    else:
                        tracker_status = f"Documents Ready — {priority} {status}"

                    self.tracker.update_job_status(
                        job.get('job_url', ''),
                        status=tracker_status,
                        cv_tailored="Yes",
                        email_sent="Yes" if method == "email_sent" else "No",
                        deterministic_score=result.get("analysis", {}).get("match", {}).get("deterministic_score", job.get('match_score', 0)),
                        llm_score=job.get('match_score', 0),
                        final_ats_score=final_score,
                        priority=priority,
                        notes=(
                            f"Priority={priority}; mode={final_strategy}; method={method}; "
                            f"auto_apply={auto_apply}; match_score={job.get('match_score')}/100; "
                            f"final_ats_score={final_score}/100"
                        )
                    )
                    print(f"    ✅ Stratégie appliquée : {priority} / {final_strategy} / méthode={method}")
                    
                except Exception as e:
                    print(f"    ❌ Erreur lors de la personnalisation pour {job['company_name']}: {e}")
                
                time.sleep(1)

        print("\n🚀 Pipeline LangGraph terminé!")
        return {"final_jobs": high_match_jobs}

    def run_pipeline(self, search_queries: List[str], locations: List[str], max_jobs_per_source: int = 10):
        # Entry point to execute the LangGraph Agent
        initial_state = {
            "search_queries": search_queries,
            "locations": locations,
            "max_jobs_per_source": max_jobs_per_source,
            "raw_jobs": [],
            "unique_jobs": [],
            "high_match_jobs": [],
            "final_jobs": []
        }
        
        # Invoke LangGraph Application
        result = self.app.invoke(initial_state)
        return result.get("final_jobs", [])

if __name__ == "__main__":
    agent = JobApplicationAgent()
    
    # Récupération dynamique depuis le profil
    target_roles = agent.user_profile.get('career_strategy', {}).get('target_roles', [])[:10]
    user_location = agent.user_profile.get('identity', {}).get('location', '')
    search_locations = agent.user_profile.get('optimization', {}).get('search_locations', [])
    
    locations = search_locations if search_locations else ([user_location] if user_location else ["Remote"])

    print(f"🚀 Démarrage du pipeline LangGraph pour : {agent.user_profile.get('identity', {}).get('full_name')}")
    print(f"🎯 Cibles : {len(target_roles)} rôles sur {len(locations)} zones")
    
    for role in target_roles:
        for loc in locations:
            agent.run_pipeline([role], [loc], max_jobs_per_source=5)
            print("\n⏳ Cooldown de 5s pour respecter les quotas API...")
            time.sleep(5)