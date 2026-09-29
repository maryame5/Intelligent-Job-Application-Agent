"""
test_feedback_and_gating.py — Tests pour Problème 4 (Feedback Loop) & Problème 5 (auto_apply_recommended discriminant)
================================================================================-----------------------------------
Vérifie :
1. JobTracker migre et gère proprement les nouvelles colonnes (Deterministic Score, LLM Score, Final ATS Score, Priority, Outcome).
2. auto_apply_recommended est réellement discriminant (True pour A/B, False pour C/D) dans main_agent.py et cv_tailor.py.
3. analyze_feedback.py traite correctement les outcomes et émet des statistiques valides.
"""

import csv
import os
import sys
import threading
import time

from fastapi import HTTPException
import pytest

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


import app as app_module
from integrations.sheets_manager import JobTracker
from cv_tailor import build_application_context
from agent.main_agent import JobApplicationAgent
from analysis.analyze_feedback import analyze_outcomes
from agent import main_agent
from integrations import email_sender


def test_tracker_structured_columns(tmp_path):
    """Vérifie que JobTracker écrit et met à jour les colonnes structurées."""
    csv_file = os.path.join(tmp_path, "test_jobs_tracker.csv")
    tracker = JobTracker(filename=csv_file)

    # 1. Vérifier la présence des nouvelles colonnes
    assert os.path.exists(csv_file)
    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        for expected_col in ['Deterministic Score', 'LLM Score', 'Final ATS Score', 'Priority', 'Outcome']:
            assert expected_col in header, f"Colonne manquante: {expected_col}"

    # 2. Ajouter un job et mettre à jour les scores
    dummy_job = {
        "job_title": "Software Engineer",
        "company_name": "TestCorp",
        "job_url": "https://testcorp.com/job/1",
        "date_posted": "2026-07-29",
    }
    tracker.add_jobs([dummy_job])

    tracker.update_job_status(
        job_url="https://testcorp.com/job/1",
        status="Applied",
        deterministic_score=70,
        llm_score=85,
        final_ats_score=78,
        priority="A",
        outcome="interview",
    )

    # 3. Relire et vérifier
    with open(csv_file, "r", encoding="utf-8") as f:
        dict_reader = csv.DictReader(f)
        row = next(dict_reader)
        assert row["Deterministic Score"] == "70"
        assert row["LLM Score"] == "85"
        assert row["Final ATS Score"] == "78"
        assert row["Priority"] == "A"
        assert row["Outcome"] == "interview"

    print("✅ JobTracker avec colonnes structurées OK")


def test_discriminant_auto_apply():
    """Vérifie que auto_apply_recommended est True pour A/B et False pour C/D."""
    # Test dans cv_tailor
    ctx_a = build_application_context({"match": {"global_score": 80}, "seniority": {"has_mismatch": False}})
    assert ctx_a["priority"] == "A"
    assert ctx_a["auto_apply_recommended"] is True

    ctx_b = build_application_context({"match": {"global_score": 60}, "seniority": {"has_mismatch": False}})
    assert ctx_b["priority"] == "B"
    assert ctx_b["auto_apply_recommended"] is True

    ctx_c = build_application_context({"match": {"global_score": 40}, "seniority": {"has_mismatch": False}})
    assert ctx_c["priority"] == "C"
    assert ctx_c["auto_apply_recommended"] is False, "Priority C doit avoir auto_apply_recommended=False"

    ctx_d = build_application_context({"match": {"global_score": 20}, "seniority": {"has_mismatch": False}})
    assert ctx_d["priority"] == "D"
    assert ctx_d["auto_apply_recommended"] is False, "Priority D doit avoir auto_apply_recommended=False"

    # Test dans main_agent.classify_application
    agent = JobApplicationAgent()
    cls_a = agent.classify_application(match_score=85, seniority_mismatch=False)
    assert cls_a["auto_apply_recommended"] is True

    cls_c = agent.classify_application(match_score=40, seniority_mismatch=True)
    assert cls_c["auto_apply_recommended"] is False

    print("✅ auto_apply_recommended discriminant OK (True pour A/B, False pour C/D)")


def test_analyze_feedback_script():
    """Vérifie le calcul des statistiques dans analyze_feedback.py."""
    dummy_rows = [
        {"Priority": "A", "Outcome": "interview", "Deterministic Score": "70", "LLM Score": "80", "Final ATS Score": "75"},
        {"Priority": "A", "Outcome": "rejected", "Deterministic Score": "65", "LLM Score": "60", "Final ATS Score": "62"},
        {"Priority": "B", "Outcome": "no_response", "Deterministic Score": "50", "LLM Score": "55", "Final ATS Score": "52"},
        {"Priority": "C", "Outcome": "rejected", "Deterministic Score": "30", "LLM Score": "40", "Final ATS Score": "35"},
    ]

    stats = analyze_outcomes(dummy_rows)
    assert stats["total_jobs"] == 4
    assert stats["priority_stats"]["A"]["positive"] == 1
    assert stats["priority_stats"]["A"]["negative"] == 1
    assert len(stats["recommendations"]) > 0
    print("✅ Script analyze_feedback.py OK")


def test_blacklisted_titles_cover_french_sales_and_call_center_variants():
    """Les variantes French/CRM sales ne doivent plus passer dans le pipeline tech."""
    assert main_agent.JobApplicationAgent._is_blacklisted_title("Chargé de clientèle") is True
    assert main_agent.JobApplicationAgent._is_blacklisted_title("Call center") is True
    assert main_agent.JobApplicationAgent._is_blacklisted_title("Télévendeuse") is True
    assert main_agent.JobApplicationAgent._is_blacklisted_title("Commercial") is True
    assert main_agent.JobApplicationAgent._is_blacklisted_title("Python Engineer") is False


def test_confirm_send_rejects_duplicate_after_first_success(tmp_path, monkeypatch):
    """Vérifie que la confirmation ne peut pas être renvoyée sur un job déjà traité."""
    csv_path = tmp_path / "jobs_tracker.csv"
    csv_path.write_text(
        "Job URL,Job Title,Company Name,Job Description,Source,Application Status,Email Sent,Hiring Manager Email\n"
        "https://example.com/jobs/42,Software Engineer,Acme,Long job description,LinkedIn,PENDING_CONFIRMATION,No,\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(app_module, "CSV_FILE", str(csv_path))
    monkeypatch.setattr(app_module, "LOG_FILE", str(tmp_path / "app.log"))
    monkeypatch.setenv("JOB_AGENT_SEND_EMAILS", "true")

    class FakeCVTailor:
        def generate(self, **kwargs):
            return {"cv": "CV content", "lettre": "Cover letter"}

    class FakeAgent:
        def __init__(self):
            self.user_profile = {"name": "Test Candidate"}
            self.cv_tailor = FakeCVTailor()

        def enrich_jobs_with_contacts(self, jobs):
            return [{**jobs[0], "contact_emails": ["hiring@acme.test"]}]

        def ensure_full_job_description(self, job):
            job["description"] = job.get("description") or "Description complète de l'offre"
            return job

    class FakeSender:
        def __init__(self, *args, **kwargs):
            pass

        def send_application_email(self, **kwargs):
            return True

    monkeypatch.setattr(main_agent, "JobApplicationAgent", FakeAgent)
    monkeypatch.setattr(email_sender, "EmailOutreach", FakeSender)

    first = app_module.confirm_send(app_module.ConfirmSendRequest(job_url="https://example.com/jobs/42"))
    assert first["status"] == "sent"

    with pytest.raises(HTTPException) as exc_info:
        app_module.confirm_send(app_module.ConfirmSendRequest(job_url="https://example.com/jobs/42"))

    assert exc_info.value.status_code == 409
    assert "déjà été envoyée" in str(exc_info.value.detail)

    rows = list(csv.DictReader(open(csv_path, "r", encoding="utf-8")))
    assert rows[0]["Application Status"] == "Applied"
    assert rows[0]["Email Sent"] == "Yes"


def test_confirm_send_restores_pending_after_email_failure(tmp_path, monkeypatch):
    """Vérifie qu'un échec d'envoi remet le job en attente plutôt que de le bloquer dans SENDING."""
    csv_path = tmp_path / "jobs_tracker.csv"
    csv_path.write_text(
        "Job URL,Job Title,Company Name,Job Description,Source,Application Status,Email Sent,Hiring Manager Email\n"
        "https://example.com/jobs/99,Software Engineer,Acme,Long job description,LinkedIn,PENDING_CONFIRMATION,No,\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(app_module, "CSV_FILE", str(csv_path))
    monkeypatch.setattr(app_module, "LOG_FILE", str(tmp_path / "app.log"))
    monkeypatch.setenv("JOB_AGENT_SEND_EMAILS", "true")

    class FakeCVTailor:
        def generate(self, **kwargs):
            return {"cv": "CV content", "lettre": "Cover letter"}

    class FakeAgent:
        def __init__(self):
            self.user_profile = {"name": "Test Candidate"}
            self.cv_tailor = FakeCVTailor()

        def enrich_jobs_with_contacts(self, jobs):
            return [{**jobs[0], "contact_emails": ["hiring@acme.test"]}]

        def ensure_full_job_description(self, job):
            job["description"] = job.get("description") or "Description complète de l'offre"
            return job

    class FailingSender:
        def __init__(self, *args, **kwargs):
            pass

        def send_application_email(self, **kwargs):
            return False

    monkeypatch.setattr(main_agent, "JobApplicationAgent", FakeAgent)
    monkeypatch.setattr(email_sender, "EmailOutreach", FailingSender)

    with pytest.raises(HTTPException) as exc_info:
        app_module.confirm_send(app_module.ConfirmSendRequest(job_url="https://example.com/jobs/99"))

    assert exc_info.value.status_code == 500
    rows = list(csv.DictReader(open(csv_path, "r", encoding="utf-8")))
    assert rows[0]["Application Status"] == "PENDING_CONFIRMATION"
    assert rows[0]["Email Sent"] == "No"


def test_confirm_send_serializes_concurrent_same_job_requests(tmp_path, monkeypatch):
    """Même job_url soumis en parallèle => un seul envoi réel, le second est rejeté en 409."""
    csv_path = tmp_path / "jobs_tracker.csv"
    csv_path.write_text(
        "Job URL,Job Title,Company Name,Job Description,Source,Application Status,Email Sent,Hiring Manager Email\n"
        "https://example.com/jobs/77,Software Engineer,Acme,Long job description,LinkedIn,PENDING_CONFIRMATION,No,\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(app_module, "CSV_FILE", str(csv_path))
    monkeypatch.setattr(app_module, "LOG_FILE", str(tmp_path / "app.log"))
    monkeypatch.setenv("JOB_AGENT_SEND_EMAILS", "true")

    send_calls = []
    first_sender_started = threading.Event()
    allow_first_sender_to_finish = threading.Event()

    class FakeCVTailor:
        def generate(self, **kwargs):
            return {"cv": "CV content", "lettre": "Cover letter"}

    class FakeAgent:
        def __init__(self):
            self.user_profile = {"name": "Test Candidate"}
            self.cv_tailor = FakeCVTailor()

        def enrich_jobs_with_contacts(self, jobs):
            return [{**jobs[0], "contact_emails": ["hiring@acme.test"]}]

        def ensure_full_job_description(self, job):
            job["description"] = job.get("description") or "Description complète de l'offre"
            return job

    class FakeSender:
        def __init__(self, *args, **kwargs):
            pass

        def send_application_email(self, **kwargs):
            if not first_sender_started.is_set():
                first_sender_started.set()
                allow_first_sender_to_finish.wait(timeout=2)
            send_calls.append(1)
            return True

    monkeypatch.setattr(main_agent, "JobApplicationAgent", FakeAgent)
    monkeypatch.setattr(email_sender, "EmailOutreach", FakeSender)

    results = []

    def worker():
        try:
            results.append(app_module.confirm_send(app_module.ConfirmSendRequest(job_url="https://example.com/jobs/77")))
        except HTTPException as exc:
            results.append(exc)

    t1 = threading.Thread(target=worker)
    t2 = threading.Thread(target=worker)
    t1.start()
    assert first_sender_started.wait(timeout=2)
    t2.start()
    time.sleep(0.05)
    allow_first_sender_to_finish.set()
    t1.join()
    t2.join()

    sent_results = [r for r in results if isinstance(r, dict)]
    rejected_results = [r for r in results if isinstance(r, HTTPException)]
    assert len(send_calls) == 1
    assert len(sent_results) == 1
    assert len(rejected_results) == 1
    assert rejected_results[0].status_code == 409
    rows = list(csv.DictReader(open(csv_path, "r", encoding="utf-8")))
    assert rows[0]["Application Status"] == "Applied"


if __name__ == "__main__":
    import tempfile

    with tempfile.TemporaryDirectory() as tmp_dir:
        test_tracker_structured_columns(tmp_dir)
    test_discriminant_auto_apply()
    test_analyze_feedback_script()
    print("\n🎉 Tous les tests des Problèmes 4 et 5 passent.")