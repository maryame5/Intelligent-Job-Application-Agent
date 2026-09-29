"""
test_score_sync.py — Régression : le score hybride (LLM × déterministe) est cohérent.

Vérifie que :
1. Avec external_match_score fourni, le global_score est le hybride (50/50).
2. Sans external_match_score, le comportement est identique (backward compat).
3. Les clés de diagnostic (deterministic_score, llm_score) sont présentes.
"""

import sys
import os

# Ensure the project root is on the path so imports work from anywhere.
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)



def _make_analyzer():
    """Instancie un OfferAnalyzer avec le profil réel (profil.json)."""
    from cv_tailor import OfferAnalyzer, _load_candidate_profile
    profile = _load_candidate_profile()
    return OfferAnalyzer(profile)


# ---------------------------------------------------------------------------
#  Fixtures
# ---------------------------------------------------------------------------
JOB_TITLE = "Développeur Java/Spring Boot"
JOB_DESC = (
    "Nous recherchons un développeur Java/Spring Boot pour notre équipe backend. "
    "Stack : Java 21, Spring Boot, PostgreSQL, Docker, REST API, microservices, CI/CD."
)
COMPANY = "Acme Corp"


# ---------------------------------------------------------------------------
#  Tests
# ---------------------------------------------------------------------------

def test_hybrid_score_is_computed_when_llm_score_provided():
    """Le score global doit être la moyenne 50/50 des deux scores."""
    analyzer = _make_analyzer()

    # Sans LLM score (baseline)
    result_no_llm = analyzer.run_full_analysis(JOB_TITLE, JOB_DESC, COMPANY)
    det_score = result_no_llm["match"]["deterministic_score"]
    assert result_no_llm["match"]["llm_score"] is None, "llm_score should be None when not provided"
    assert result_no_llm["match"]["global_score"] == det_score, \
        "Without LLM score, global_score must equal deterministic_score"

    # Avec LLM score
    llm_score = 80
    result_with_llm = analyzer.run_full_analysis(JOB_TITLE, JOB_DESC, COMPANY, external_match_score=llm_score)
    actual_det_score = result_with_llm["match"]["deterministic_score"]
    expected_hybrid = round(0.5 * actual_det_score + 0.5 * llm_score)
    expected_hybrid = max(0, min(100, expected_hybrid))

    assert result_with_llm["match"]["llm_score"] == llm_score
    assert result_with_llm["match"]["global_score"] == expected_hybrid, (
        f"Hybrid mismatch: expected {expected_hybrid}, "
        f"got {result_with_llm['match']['global_score']} "
        f"(det={actual_det_score}, llm={llm_score})"
    )
    print(f"✅ Hybrid score OK — det={actual_det_score}, llm={llm_score}, hybrid={expected_hybrid}")


def test_diagnostic_keys_present():
    """Les clés de diagnostic doivent être dans le dict match."""
    analyzer = _make_analyzer()
    result = analyzer.run_full_analysis(JOB_TITLE, JOB_DESC, COMPANY, external_match_score=60)
    match = result["match"]
    for key in ("deterministic_score", "llm_score", "global_score"):
        assert key in match, f"Missing key '{key}' in match dict"
    print("✅ Diagnostic keys present")


def test_backward_compat_no_llm_score():
    """Sans external_match_score, le résultat est identique à l'ancien comportement."""
    analyzer = _make_analyzer()
    result = analyzer.run_full_analysis(JOB_TITLE, JOB_DESC, COMPANY)
    match = result["match"]
    assert match["llm_score"] is None
    assert match["global_score"] == match["deterministic_score"]
    assert "selected_exp_ids" in result
    assert "selected_proj_ids" in result
    print("✅ Backward compat OK")


if __name__ == "__main__":
    test_hybrid_score_is_computed_when_llm_score_provided()
    test_diagnostic_keys_present()
    test_backward_compat_no_llm_score()
    print("\n🎉 Tous les tests passent.")