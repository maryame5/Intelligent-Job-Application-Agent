"""Tests des contrats locaux des intégrations et de l'API."""

import csv

import pytest
from fastapi import HTTPException

import app as app_module
from integrations.email_finder import EmailFinder
from integrations.sheets_manager import JobTracker


def test_api_normalizers_preserve_known_acronyms_and_reject_short_titles():
    assert app_module.normalize_job_title("senior api engineer") == "Senior API Engineer"
    assert app_module.normalize_company_name("ibm") == "IBM"
    assert app_module.normalize_company_name("acme maroc") == "Acme Maroc"
    with pytest.raises(HTTPException) as error:
        app_module.normalize_job_title("AI")
    assert error.value.status_code == 400


def test_job_details_returns_safe_empty_defaults(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "OUTPUT_DIR", str(tmp_path))
    result = app_module.get_job_details(company="Unknown", job_id="missing")
    assert result["cv"].startswith("Aucun CV généré")
    assert result["lm"].startswith("Aucune lettre")


def test_tracker_deduplicates_and_updates_by_job_id(tmp_path):
    tracker = JobTracker(filename=str(tmp_path / "jobs.csv"))
    job = {
        "job_title": "Python Engineer",
        "company_name": "Acme",
        "job_url": "https://acme.example/jobs/1",
        "source": "test",
    }
    tracker.add_jobs([job, dict(job)])
    tracker.update_job_status(job["job_id"], status="Applied", outcome="interview", notes="Reviewed")

    with open(tracker.filename, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["Application Status"] == "Applied"
    assert rows[0]["Outcome"] == "interview"
    assert rows[0]["Notes"] == "Reviewed"


def test_tracker_rejects_invalid_outcome(tmp_path):
    tracker = JobTracker(filename=str(tmp_path / "jobs.csv"))
    assert tracker.update_job_outcome("missing", "unknown") is False


def test_email_finder_filters_and_generates_contact_candidates():
    finder = EmailFinder()
    assert finder._extract_emails("hr@acme.ma and bad") == ["hr@acme.ma"]
    assert finder._filter_valid_emails(["HR@ACME.MA", "info@example.com", "support@acme.ma"]) == ["hr@acme.ma"]
    permutations = finder.generate_email_permutations("Ada", "Lovelace", "acme.ma")
    assert "ada.lovelace@acme.ma" in permutations
    assert "recrutement@acme.ma" in permutations
    assert finder.google_dork_search("Acme", "acme.ma")[0].startswith("site:acme.ma")
    assert len(finder.find_hiring_manager_linkedin("Acme", ["Engineer"])) > 1


def test_email_finder_prefers_address_found_in_job_posting(monkeypatch):
    finder = EmailFinder()
    monkeypatch.setattr(finder, "_guess_domain", lambda company: "acme.ma")
    result = finder.find_contact_for_job(
        {
            "company_name": "Acme",
            "job_title": "Python Engineer",
            "description": "Envoyez votre CV a recrutement@acme.ma",
        }
    )
    assert result["emails_found"] == ["recrutement@acme.ma"]
    assert result["confidence"] == "high"
    assert result["application_method"] == "email_direct_from_job_posting"
