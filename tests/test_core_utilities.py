"""Tests unitaires des fonctions pures et des garde-fous du pipeline."""

import json

import pytest
from bs4 import BeautifulSoup

from core.context_builder import (
    _build_contact_line,
    _detect_offer_language,
    _mirror_job_title_keywords,
    _normalize_date_for_lang,
    build_ats_formatting_checklist,
    build_gap_analysis_report,
)
from core.helpers import (
    _build_evidence_guard,
    _flatten,
    _get_profile_ats_keyword_aliases,
    _strip_stray_emojis,
    _title_for_display,
    _company_for_display,
    _norm,
    build_keyword_grounding,
    normalize_tech_names,
)
from core.output_validator import OutputValidator
from integrations.llm_manager import _extract_json
from matching.offer_scoring import (
    compute_final_score,
    score_factuality,
    score_personalization,
    score_rh_readability,
)
from scrapers.bayt import BaytScraper, extract_email_from_description as extract_bayt_email
from scrapers.emploi_ma import extract_email_from_description as extract_emploi_email
from scrapers.indeed import IndeedScraper, extract_email_from_description as extract_indeed_email
from scrapers.linkedin import extract_email_from_description as extract_linkedin_email
from scrapers.rekrute import extract_email_from_description as extract_rekrute_email


PROFILE = {
    "identity": {
        "email": "candidate@university.example",
        "email_personnel": "candidate.personal@example.com",
        "phone": "+33123456789",
        "location": "Paris",
        "links": {
            "linkedin": "https://linkedin.example/candidate",
            "github": "https://github.example/candidate",
            "portfolio": "https://portfolio.example/candidate",
        },
    },
    "experiences": [
        {
            "id": "exp-1",
            "company": "Acme",
            "duration": "2024",
            "stack": ["Python", "FastAPI"],
            "story_bullets": [
                {"action": "Built an API", "result": "Reduced latency", "tech_proof": "Python FastAPI"}
            ],
            "always_feature": True,
        }
    ],
    "projects": [
        {
            "name": "Data Platform",
            "date": "2025",
            "stack": ["Pandas"],
            "description": "A data quality platform",
            "story_bullets": [{"action": "Created quality checks"}],
        }
    ],
    "optimization": {"ats_keyword_aliases": {"api testing": ["Postman", "OpenAPI"]}},
}


def test_helpers_normalize_and_format_values():
    assert _norm("Été ’Déjà") == "ete 'deja"
    assert _flatten({"a": ["one", {"b": "two"}], "c": 3}) == ["one", "two"]
    assert normalize_tech_names("postgresql and fastapi") == "PostgreSQL and FastAPI"
    assert _strip_stray_emojis("CV ✅  | Paris") == "CV | Paris"
    assert _title_for_display("ai engineer") == "AI Engineer"
    assert _company_for_display("ibm") == "IBM"


def test_helpers_grounding_uses_profile_evidence_and_aliases():
    aliases = _get_profile_ats_keyword_aliases(PROFILE)
    assert aliases["api testing"] == ["postman", "openapi"]

    analysis = {"required_keywords": ["Python", "API testing", "Selenium"]}
    grounding = build_keyword_grounding(PROFILE, analysis)
    assert "Python" in grounding
    assert "Selenium" in grounding
    assert "NON prouvées explicitement" in grounding
    assert "API testing" in _build_evidence_guard(PROFILE, analysis)


def test_context_helpers_cover_language_dates_and_contact_links():
    assert _detect_offer_language("You will join our team. Requirements and responsibilities.") == "en"
    assert _detect_offer_language("Nous recherchons un ingénieur. Votre profil et vos missions.") == "fr"
    assert _normalize_date_for_lang("jan 2024 - présent", "en") == "Jan 2024 - Present"
    assert "github.example" in _build_contact_line(PROFILE, "Please share your GitHub and portfolio", "candidate@example.com")
    assert _mirror_job_title_keywords("Junior Agentic AI Engineer", "Software Engineer") == "Software Engineer — Agentic AI | Junior"


def test_gap_report_and_ats_checklist_detect_problems():
    analysis = {
        "required_keywords": ["Python", "Selenium"],
        "match": {"keyword_coverage_pct": 50},
        "seniority": {"has_mismatch": True, "recommended_title": "Junior Engineer"},
    }
    report = build_gap_analysis_report(PROFILE, analysis)
    assert report["keywords_proven"] == ["Python"]
    assert report["keywords_missing"] == ["Selenium"]
    assert report["seniority_mismatch"] is True

    checklist = build_ats_formatting_checklist("😀 short", "")
    assert checklist["n_issues"] > 0
    assert checklist["n_total"] == 9


def test_output_validator_detects_unproven_skill_and_missing_required_stage():
    validator = OutputValidator(PROFILE)
    document = "## Profil\nCandidate\n## Compétences techniques\nSelenium\n"
    issues = validator.validate(
        document,
        {"role": {"dominant": "qa_testing"}, "exp_scores": [{"company": "Acme"}]},
        "cv",
    )
    assert any("selenium" in issue.lower() for issue in issues)
    assert any("Acme" in issue for issue in issues) is False


def test_output_validator_repair_delegates_only_when_needed():
    validator = OutputValidator(PROFILE)
    assert validator.repair("document", "cv", [], {}, lambda **_: "unused") == "document"
    calls = []

    def fake_llm(prompt, **kwargs):
        calls.append((prompt, kwargs))
        return "fixed document"

    assert validator.repair("bad document", "cv", ["issue"], {}, fake_llm) == "fixed document"
    assert calls and calls[0][1]["temperature"] == 0.1


def test_output_validator_catches_multiple_cv_integrity_rules():
    validator = OutputValidator(PROFILE)
    document = (
        "Dans l'espoir d'une réponse, elle construit un profil senior. "
        '{"company": "Unknown"} Maroc Morocco en 5 ans de stages.\n'
        "## Compétences techniques\nSelenium\n"
    )
    issues = validator.validate(
        document,
        {
            "role": {"dominant": "qa_testing"},
            "seniority": {"has_mismatch": True},
            "exp_scores": [{"company": "Acme"}],
        },
        "cv",
    )
    assert any("Formule interdite" in issue for issue in issues)
    assert any("JSON brut" in issue for issue in issues)
    assert any("Voix incorrecte" in issue for issue in issues)
    assert any("Doublon Maroc" in issue for issue in issues)
    assert any("Métrique" in issue for issue in issues)


def test_scoring_pipeline_rewards_personalization_and_combines_scores():
    analysis = {
        "job_context": {"company_name": "Acme"},
        "positioning": {
            "target_title": "Python Engineer",
            "primary_experience": "Acme",
            "primary_project": "Data Platform",
        },
        "application_context": {"priority": "A"},
        "exp_scores": [{"company": "Acme"}, {"company": "OtherCo"}],
        "match": {"global_score": 80},
    }
    cv = "Python Engineer\nAcme\nData Platform\nOtherCo"
    letter = "I am applying to Acme."
    personalization = score_personalization(cv, letter, analysis, {})
    assert personalization["personalization_score"] == 100

    factuality = score_factuality(cv, letter, [], ["non attestée", "métrique inventée"])
    assert factuality["factuality_score"] < 100
    readability = score_rh_readability(
        "## Profil\n## Formation\n## Expériences professionnelles\n## Compétences techniques\n## Projets",
        "Objet: candidature\\nCordialement",
        {},
    )
    final = compute_final_score(personalization, factuality, readability)
    assert 0 <= final["final_score"] <= 100


@pytest.mark.parametrize(
    "extractor",
    [extract_bayt_email, extract_emploi_email, extract_indeed_email, extract_linkedin_email, extract_rekrute_email],
)
def test_scraper_email_extractors_filter_blacklisted_addresses(extractor):
    text = "Contact hiring@example.com, info@example.com or noreply@example.com"
    assert extractor(text) == ["hiring@example.com"]
    assert extractor("") == []


def test_scraper_card_parsers_normalize_html_cards():
    indeed_card = BeautifulSoup(
        """
        <div><h2><a href='/viewjob?id=1'><span title='Python Engineer'>Python Engineer</span></a></h2>
        <span class='companyName'>Acme</span><div class='companyLocation'>Paris</div>
        <div class='salary-snippet-container'>50k</div><div class='job-snippet'>Build APIs</div></div>
        """,
        "html.parser",
    )
    parsed_indeed = IndeedScraper()._parse_indeed_card(indeed_card)
    assert parsed_indeed["job_title"] == "Python Engineer"
    assert parsed_indeed["job_url"].startswith("https://ma.indeed.com/")

    bayt_card = BeautifulSoup(
        "<li><h2><a href='/job/2'>Data Engineer</a></h2><div class='jb-company'>Acme</div>"
        "<div class='jb-loc'>Rabat</div><div class='jb-desc'>Build pipelines</div></li>",
        "html.parser",
    )
    parsed_bayt = BaytScraper()._parse_card(bayt_card)
    assert parsed_bayt["job_title"] == "Data Engineer"
    assert parsed_bayt["job_url"] == "https://www.bayt.com/job/2"


def test_llm_json_extraction_handles_markdown_and_fallback():
    assert _extract_json("```json\n{\"score\": 7}\n```", {}) == {"score": 7}
    assert _extract_json("not json", {"score": 0}) == {"score": 0}
    assert _extract_json("prefix {\"score\": 8} suffix", {})["score"] == 8
