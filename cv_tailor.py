"""
cv_tailor.py (Root Bridge)
==========================
Redirige vers le package modulaire `core.cv_tailor`.
Permet la rétrocompatibilité complète pour les scripts existants.
"""

from core.cv_tailor import (
    CVTailor,
    generate_application,
    build_full_report_markdown,
    _load_candidate_profile,
)
from core.offer_analyzer import (
    OfferAnalyzer,
    build_application_context,
    build_offer_positioning,
    detect_profile_mode,
)
from core.helpers import (
    normalize_tech_names,
    _strip_stray_emojis,
    _build_profile_truth_corpus,
    _split_keywords_by_evidence,
    _norm,
)
from core.context_builder import (
    ContextBuilder,
    build_gap_analysis_report,
    build_ats_formatting_checklist,
)
from core.output_validator import OutputValidator
from core.prompt_builder import build_cv_prompt, build_cover_letter_prompt
from core.personas import PERSONA_PROMPTS
from core.lexicons import (
    TECH_CANONICAL,
    ROLE_DETECTION_SIGNALS,
    COMPANY_PERSONA_SIGNALS,
    FORBIDDEN_PHRASES,
)

__all__ = [
    "CVTailor",
    "generate_application",
    "build_full_report_markdown",
    "_load_candidate_profile",
    "OfferAnalyzer",
    "build_application_context",
    "build_offer_positioning",
    "detect_profile_mode",
    "normalize_tech_names",
    "_strip_stray_emojis",
    "_build_profile_truth_corpus",
    "_split_keywords_by_evidence",
    "_norm",
    "ContextBuilder",
    "build_gap_analysis_report",
    "build_ats_formatting_checklist",
    "OutputValidator",
    "build_cv_prompt",
    "build_cover_letter_prompt",
    "PERSONA_PROMPTS",
    "TECH_CANONICAL",
    "ROLE_DETECTION_SIGNALS",
    "COMPANY_PERSONA_SIGNALS",
    "FORBIDDEN_PHRASES",
]