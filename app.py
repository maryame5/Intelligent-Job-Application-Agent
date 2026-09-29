import sys
import io
import threading

if sys.stdout and sys.stdout.encoding.lower() != 'utf-8':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
if sys.stderr and sys.stderr.encoding.lower() != 'utf-8':
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
import pandas as pd
import os
from integrations.sheets_manager import JobTracker


app = FastAPI()

# Configuration des chemins absolus
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CSV_FILE = os.path.join(BASE_DIR, 'jobs_tracker.csv')
LOG_FILE = os.path.join(BASE_DIR, 'scraper.log')
INDEX_HTML = os.path.join(BASE_DIR, 'index.html')
OUTPUT_DIR = os.path.join(BASE_DIR, 'output')
TRACKER = JobTracker()
JOB_STATUS_LOCKS = {}
JOB_STATUS_LOCKS_GUARD = threading.Lock()
# NOTE : verrou in-process uniquement ; il protège les threads d'un seul worker uvicorn.
# Pour un déploiement multi-worker, il faut passer à un backend transactionnel (SQLite/DB lock) ou un verrou inter-process.

# S'assurer que le dossier output existe
os.makedirs(OUTPUT_DIR, exist_ok=True)

TITLE_CORRECTIONS = {
    "Ai": "AI",
    "Ml": "ML",
    "Nlp": "NLP",
    "Pfe": "PFE",
    "J2Ee": "J2EE",
    "Api": "API",
    "Apis": "APIs",
    "Sql": "SQL",
    "Aws": "AWS",
}

KNOWN_COMPANY_ACRONYMS = {"ALTEN", "DXC", "IBM", "SQLI", "CGI", "SII", "NTT", "ATOS"}

def normalize_job_title(job_title: str) -> str:
    cleaned = (job_title or '').strip().title()
    if len(cleaned) < 3:
        raise HTTPException(status_code=400, detail="Intitulé trop court.")
    return " ".join(TITLE_CORRECTIONS.get(word, word) for word in cleaned.split())

def normalize_company_name(company_name: str) -> str:
    cleaned = (company_name or '').strip()
    if cleaned.upper() in KNOWN_COMPANY_ACRONYMS:
        return cleaned.upper()
    return cleaned.title()

class JobUpdate(BaseModel):
    job_url: str
    status: str = None
    notes: str = None
    cv_tailored: str = None

@app.get("/api/jobs")
def get_jobs():
    if not os.path.exists(CSV_FILE):
        return []
    df = pd.read_csv(CSV_FILE)
    # Remplacer les NaN par des chaînes vides pour le JSON
    return df.fillna("").to_dict(orient='records')

@app.post("/api/update")
def update_job(update: JobUpdate):
    if not os.path.exists(CSV_FILE):
        raise HTTPException(status_code=404, detail="File not found")
    
    df = pd.read_csv(CSV_FILE)
    mask = df['Job URL'] == update.job_url
    
    if not mask.any():
        raise HTTPException(status_code=404, detail="Job not found")
    
    if update.status:
        df.loc[mask, 'Application Status'] = update.status
    if update.notes is not None:
        df.loc[mask, 'Notes'] = update.notes
    if update.cv_tailored:
        df.loc[mask, 'CV Tailored'] = update.cv_tailored
        
    df.to_csv(CSV_FILE, index=False)
    return {"status": "success"}

import subprocess
import asyncio

scraper_process = None

@app.post("/api/run-scraper")
def run_scraper():
    global scraper_process
    try:
        if scraper_process and scraper_process.poll() is None:
            raise HTTPException(status_code=400, detail="Le scraper est déjà en cours d'exécution.")
            
        # Réinitialiser le log file
        with open(LOG_FILE, "w", encoding="utf-8") as f:
            f.write("Démarrage du pipeline de recherche et candidature...\n")
            
        # Lancer agent/main_agent.py en arrière-plan et rediriger les outputs vers le fichier log
        agent_script = os.path.join(BASE_DIR, 'agent', 'main_agent.py')
        if not os.path.exists(agent_script):
            agent_script = os.path.join(BASE_DIR, 'main_agent.py')
        scraper_process = subprocess.Popen(['python', '-X', 'utf8', '-u', agent_script], 
                                   stdout=open(LOG_FILE, "a", encoding="utf-8"), 
                                   stderr=subprocess.STDOUT,
                                   text=True,
                                   cwd=BASE_DIR)
        return {"status": "started", "message": "Le scraper a été lancé avec succès."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/stop-scraper")
def stop_scraper():
    global scraper_process
    if scraper_process and scraper_process.poll() is None:
        scraper_process.terminate()
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("\n🛑 [INTERRUPTION] Le scraper a été arrêté par l'utilisateur.\n")
        return {"status": "stopped", "message": "Le scraper a été arrêté."}
    else:
        return {"status": "already_stopped", "message": "Aucun scraper en cours."}

@app.get("/api/logs")
async def get_logs():
    async def log_generator():
        log_file = LOG_FILE
        if not os.path.exists(log_file):
            yield "data: En attente des logs...\n\n"
        else:
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                while True:
                    line = f.readline()
                    if line:
                        yield f"data: {line}\n\n"
                    else:
                        await asyncio.sleep(0.5)
    return StreamingResponse(log_generator(), media_type="text/event-stream")

import glob
@app.get("/api/job-details")
def get_job_details(company: str = "", job_id: str = ""):
    cv_files = []
    lm_files = []

    if job_id:
        cv_files = glob.glob(os.path.join(OUTPUT_DIR, f"cv_*_{job_id}.md")) + glob.glob(os.path.join(OUTPUT_DIR, f"cv_{job_id}.md"))
        lm_files = glob.glob(os.path.join(OUTPUT_DIR, f"lm_*_{job_id}.md")) + glob.glob(os.path.join(OUTPUT_DIR, f"lm_{job_id}.md"))

    if not cv_files and company:
        company_clean = company.replace(' ', '_')
        cv_files = glob.glob(os.path.join(OUTPUT_DIR, f"cv_*{company_clean}*.md"))
        lm_files = glob.glob(os.path.join(OUTPUT_DIR, f"lm_*{company_clean}*.md"))
    
    cv_content = "Aucun CV généré pour l'instant. Cliquez sur 'Générer CV & Postuler' pour le créer."
    if cv_files:
        latest_cv = max(cv_files, key=os.path.getmtime)
        with open(latest_cv, "r", encoding="utf-8", errors="replace") as f:
            cv_content = f.read()
            
    lm_content = "Aucune lettre de motivation générée pour l'instant."
    if lm_files:
        latest_lm = max(lm_files, key=os.path.getmtime)
        with open(latest_lm, "r", encoding="utf-8", errors="replace") as f:
            lm_content = f.read()
            
    return {"cv": cv_content, "lm": lm_content}

class JobAction(BaseModel):
    job_url: str

class ConfirmSendRequest(BaseModel):
    job_url: str


def _get_job_status_lock(job_url: str):
    with JOB_STATUS_LOCKS_GUARD:
        key = (job_url or '').strip()
        if key not in JOB_STATUS_LOCKS:
            JOB_STATUS_LOCKS[key] = threading.Lock()
        return JOB_STATUS_LOCKS[key]


def _atomic_write_csv(df):
    tmp_path = f"{CSV_FILE}.tmp"
    df.to_csv(tmp_path, index=False)
    os.replace(tmp_path, CSV_FILE)


def _job_row_to_payload(row):
    return {
        'job_url': row['Job URL'],
        'job_title': row['Job Title'],
        'company_name': row['Company Name'],
        'description': row['Job Description'] if pd.notna(row['Job Description']) else '',
        'source': row['Source'],
        'job_id': row.get('Job ID', ''),
    }


def _generate_and_persist_preview(job_url: str):

    from agent.main_agent import JobApplicationAgent
    from integrations.sheets_manager import JobTracker
    
    df = pd.read_csv(CSV_FILE)
    mask = df['Job URL'] == job_url
    if not mask.any():
        raise HTTPException(status_code=404, detail="Job not found")

    row = df[mask].iloc[0]
    job = _job_row_to_payload(row)

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"\n[ACTION MANUELLE] Prévisualisation de la candidature pour : {job['company_name']}\n")

    agent = JobApplicationAgent()

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("  🔍 Recherche des contacts...\n")

    enriched = agent.enrich_jobs_with_contacts([job])[0]

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("  ✍️ Audit et génération des documents (IA)...\n")

    enriched = agent.ensure_full_job_description(enriched)
    if len((enriched.get('description') or '').strip()) < 120:
        raise HTTPException(status_code=400, detail="Description trop courte: colle la description complète de l'offre pour éviter un CV générique.")

    enriched['job_title'] = normalize_job_title(enriched.get('job_title', ''))
    enriched['company_name'] = normalize_company_name(enriched.get('company_name', ''))

    tracker = JobTracker()
    tracker.ensure_job_id(enriched)

    result = agent.cv_tailor.generate(
        job_description=enriched.get('description', ''),
        job_title=enriched['job_title'],
        company_name=enriched['company_name'],
        verbose=False,
    )
    tailored_cv = result["cv"]
    cover_letter = result["lettre"]

    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write("  📄 Création des fichiers PDF & markdown pour prévisualisation...\n")

    filename_base = f"cv_tailored_{enriched['job_id']}"
    cl_filename_base = f"lm_{enriched['job_id']}"

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    agent.generate_pdf(tailored_cv, os.path.join(OUTPUT_DIR, f"{filename_base}.pdf"), doc_type='cv')
    agent.generate_pdf(cover_letter, os.path.join(OUTPUT_DIR, f"{cl_filename_base}.pdf"), doc_type='cover_letter')

    with open(os.path.join(OUTPUT_DIR, f"{filename_base}.md"), "w", encoding="utf-8") as f:
        f.write(tailored_cv)
    with open(os.path.join(OUTPUT_DIR, f"{cl_filename_base}.md"), "w", encoding="utf-8") as f:
        f.write(cover_letter)

    df.loc[mask, 'CV Tailored'] = 'Yes'
    df.loc[mask, 'Email Sent'] = 'No'
    df.loc[mask, 'Application Status'] = 'PENDING_CONFIRMATION'
    if enriched.get('contact_emails'):
        df.loc[mask, 'Hiring Manager Email'] = ", ".join(enriched['contact_emails'])
    df.to_csv(CSV_FILE, index=False)

    return {
        "status": "preview_ready",
        "message": "Documents générés en prévisualisation ; confirmez l'envoi pour envoyer l'email.",
        "job_url": job_url,
        "email_found": bool(enriched.get('contact_emails')),
        "contact_emails": enriched.get('contact_emails', []),
        "cv_path": os.path.join(OUTPUT_DIR, f"{filename_base}.md"),
        "lm_path": os.path.join(OUTPUT_DIR, f"{cl_filename_base}.md"),
    }


@app.post("/api/generate-preview")
def generate_preview(action: JobAction):
    try:
        return _generate_and_persist_preview(action.job_url)
    except Exception as e:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"  ❌ ERREUR PRÉVISUALISATION : {str(e)}\n\n")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate-apply")
def generate_and_apply(action: JobAction):
    return generate_preview(action)


@app.post("/api/confirm-send")
def confirm_send(action: ConfirmSendRequest):
    from agent.main_agent import JobApplicationAgent
    from integrations.email_sender import EmailOutreach

    lock = _get_job_status_lock(action.job_url)
    with lock:
        df = pd.read_csv(CSV_FILE)
        mask = df['Job URL'] == action.job_url
        if not mask.any():
            raise HTTPException(status_code=404, detail="Job not found")

        current_status = str(df.loc[mask, 'Application Status'].iloc[0] or '').strip()
        if current_status == 'Applied':
            raise HTTPException(status_code=409, detail="Cette candidature a déjà été envoyée et ne peut pas être renvoyée.")
        if current_status != 'PENDING_CONFIRMATION':
            raise HTTPException(status_code=409, detail="Aucune confirmation d'envoi en attente pour cette offre.")

        row = df[mask].iloc[0]
        job = _job_row_to_payload(row)

        df.loc[mask, 'Application Status'] = 'SENDING'
        df.loc[mask, 'Email Sent'] = 'No'
        _atomic_write_csv(df)

        try:
            agent = JobApplicationAgent()
            enriched = agent.enrich_jobs_with_contacts([job])[0]
            enriched = agent.ensure_full_job_description(enriched)

            emails = enriched.get('contact_emails') or []
            if not emails:
                df = pd.read_csv(CSV_FILE)
                df.loc[mask, 'Application Status'] = 'PENDING_CONFIRMATION'
                df.loc[mask, 'Email Sent'] = 'No'
                _atomic_write_csv(df)
                raise HTTPException(status_code=400, detail="Aucun email de contact valide détecté : impossible d'envoyer la candidature.")

            auto_send = os.getenv("JOB_AGENT_SEND_EMAILS", "false").lower().strip() in {"1", "true", "yes", "on"}
            if not auto_send:
                df = pd.read_csv(CSV_FILE)
                df.loc[mask, 'Application Status'] = 'PENDING_CONFIRMATION'
                df.loc[mask, 'Email Sent'] = 'No'
                _atomic_write_csv(df)
                raise HTTPException(status_code=400, detail="L'envoi automatique est désactivé. Active JOB_AGENT_SEND_EMAILS=true pour confirmer l'envoi.")

            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(f"\n[CONFIRMATION] Envoi validé pour : {job['company_name']} -> {emails[0]}\n")

            sender = EmailOutreach(os.getenv("GMAIL_CREDENTIALS_FILE", "gmail_credentials.json"))
            generated = agent.cv_tailor.generate(
                job_description=enriched.get('description', ''),
                job_title=normalize_job_title(job.get('job_title', '')),
                company_name=normalize_company_name(job.get('company_name', '')),
                verbose=False,
            )
            sent = sender.send_application_email(
                to_email=emails[0],
                job_title=job.get('job_title', ''),
                company_name=job.get('company_name', ''),
                cover_letter=generated["lettre"],
                resume_markdown=generated["cv"],
                hiring_manager_name=job.get('hiring_manager_name') or '',
                candidate_profile=agent.user_profile,
            )
            if not sent:
                df = pd.read_csv(CSV_FILE)
                df.loc[mask, 'Application Status'] = 'PENDING_CONFIRMATION'
                df.loc[mask, 'Email Sent'] = 'No'
                _atomic_write_csv(df)
                raise HTTPException(status_code=500, detail="L'envoi email a échoué : le job a été remis en attente de confirmation.")
        except HTTPException:
            raise
        except Exception as e:
            df = pd.read_csv(CSV_FILE)
            df.loc[mask, 'Application Status'] = 'PENDING_CONFIRMATION'
            df.loc[mask, 'Email Sent'] = 'No'
            _atomic_write_csv(df)
            raise HTTPException(status_code=500, detail=f"Échec de l'envoi : {str(e)}") from e

        df = pd.read_csv(CSV_FILE)
        df.loc[mask, 'Application Status'] = 'Applied'
        df.loc[mask, 'Email Sent'] = 'Yes'
        df.loc[mask, 'Hiring Manager Email'] = ", ".join(emails)
        _atomic_write_csv(df)

        return {
            "status": "sent",
            "message": "Email envoyé après confirmation explicite.",
            "job_url": action.job_url,
            "recipient": emails[0],
            "sent": bool(sent),
        }

class CustomTailorRequest(BaseModel):
    job_title: str
    company_name: str
    job_description: str

@app.post("/api/tailor-custom")
def tailor_custom(request: CustomTailorRequest):
    from agent.main_agent import JobApplicationAgent
    from integrations.sheets_manager import JobTracker

    from datetime import datetime
    import time
    try:
        agent = JobApplicationAgent()
        
        # Log active request
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"\n[ACTION MANUELLE] Début de la personnalisation de documents pour : {request.job_title} chez {request.company_name}\n")
            f.write("  ✍️ Audit et génération de documents (IA)...\n")
            
        if len((request.job_description or '').strip()) < 120:
            raise HTTPException(status_code=400, detail="Description trop courte: colle la description complète de l'offre.")
        request.job_title = normalize_job_title(request.job_title)
        request.company_name = normalize_company_name(request.company_name)

        result = agent.cv_tailor.generate(
            job_description=request.job_description,
            job_title=request.job_title,
            company_name=request.company_name,
            verbose=False
        )
        
        tailored_cv = result["cv"]
        cover_letter = result["lettre"]
        
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write("  📄 Génération des documents au format PDF & Markdown...\n")
            
        company_clean = request.company_name.replace(' ', '_').replace('/', '_').replace('\\', '_')
        timestamp = int(time.time())

        # 3. Add this custom job into the tracking sheet CSV
        tracker = JobTracker()
        custom_url = f"custom://{company_clean}/{timestamp}"
        
        custom_job = {
            'job_title': request.job_title,
            'company_name': request.company_name,
            'location': 'Personnalisé',
            'job_url': custom_url,
            'date_posted': datetime.now().strftime('%Y-%m-%d'),
            'date_scraped': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'source': 'Saisie Manuelle',
            'description': request.job_description,
            'salary': 'N/A',
            'contract_type': 'N/A',
            'experience_required': 'N/A',
        }
        tracker.ensure_job_id(custom_job)

        cv_filename_base = f"cv_tailored_{custom_job['job_id']}"
        cl_filename_base = f"lm_{custom_job['job_id']}"

        os.makedirs(OUTPUT_DIR, exist_ok=True)

        cv_md_path = os.path.join(OUTPUT_DIR, f"{cv_filename_base}.md")
        cv_pdf_path = os.path.join(OUTPUT_DIR, f"{cv_filename_base}.pdf")
        lm_md_path = os.path.join(OUTPUT_DIR, f"{cl_filename_base}.md")
        lm_pdf_path = os.path.join(OUTPUT_DIR, f"{cl_filename_base}.pdf")

        with open(cv_md_path, "w", encoding="utf-8") as f:
            f.write(tailored_cv)
        with open(lm_md_path, "w", encoding="utf-8") as f:
            f.write(cover_letter)

        agent.generate_pdf(tailored_cv, cv_pdf_path, doc_type='cv')
        agent.generate_pdf(cover_letter, lm_pdf_path, doc_type='cover_letter')

        tracker.add_jobs([custom_job])
        # Générer des documents ne veut pas dire que la candidature est envoyée.
        app_ctx = result.get("application_context", {})
        priority = app_ctx.get("priority", "B")
        status = app_ctx.get("status", "Documents Ready")
        
        tracker.update_job_status(
            custom_url, 
            status=f"Documents Ready — {priority} {status}", 
            cv_tailored="Yes", 
            notes=f"Documents personnalisés générés manuellement. Priority={priority}; mode={result.get('application_strategy', '')}"
        )
        
        match_score = result.get("match_score", 0)
        decision = result.get("decision", "Unknown")
        warnings = result.get("warnings", [])
        
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"  ✅ Succès ! CV & LM générés et enregistrés sous {cv_filename_base} et {cl_filename_base}.\n")
            f.write(f"  📊 Score={match_score} | Decision={decision} | Warnings={warnings}\n\n")
            
        return {
            "status": "success",
            "match_score": match_score,
            "decision": decision,
            "warnings": warnings,
            "dominant_role": result.get("dominant_role"),
            "cv_md": tailored_cv,
            "lm_md": cover_letter,
            "cv_pdf_file": f"{cv_filename_base}.pdf",
            "lm_pdf_file": f"{cl_filename_base}.pdf",
            "cv_md_file": f"{cv_filename_base}.md",
            "lm_md_file": f"{cl_filename_base}.md",
            "job_url": custom_url
        }
    except Exception as e:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"  ❌ ERREUR lors de la personnalisation manuelle : {str(e)}\n\n")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/download/{filename}")
def download_file(filename: str):
    if ".." in filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nom de fichier invalide.")
        
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="Fichier non trouvé.")
        
    return FileResponse(file_path, media_type='application/octet-stream', filename=filename)

@app.get("/")
def read_index():
    return FileResponse(INDEX_HTML)

if __name__ == "__main__":
    import uvicorn
    print("🚀 Dashboard lancé sur http://127.0.0.1:8000")
    uvicorn.run(app, host="127.0.0.1", port=8000)
