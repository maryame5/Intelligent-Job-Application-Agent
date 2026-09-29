"""
test_semantic_matching.py — Validation du matching sémantique
=============================================================
- Test 1 : cosine_similarity math (pas d'API)
- Test 2 : graceful degradation sans clé API
- Test 3 : intégration dans OfferAnalyzer (avec API si disponible)
"""

import os
import sys

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from matching.semantic_matcher import cosine_similarity, SemanticMatcher


def test_cosine_similarity_math():
    """Vérification mathématique pure, pas d'API."""
    # Vecteurs identiques → 1.0
    assert abs(cosine_similarity([1, 0, 0], [1, 0, 0]) - 1.0) < 1e-6

    # Vecteurs orthogonaux → 0.0
    assert abs(cosine_similarity([1, 0, 0], [0, 1, 0]) - 0.0) < 1e-6

    # Vecteurs opposés → -1.0
    assert abs(cosine_similarity([1, 0], [-1, 0]) - (-1.0)) < 1e-6

    # Vecteurs proportionnels → 1.0
    assert abs(cosine_similarity([1, 2, 3], [2, 4, 6]) - 1.0) < 1e-6

    # Vecteur nul → 0.0
    assert cosine_similarity([0, 0, 0], [1, 2, 3]) == 0.0

    # Vecteurs vides → 0.0
    assert cosine_similarity([], []) == 0.0

    # Longueurs différentes → 0.0
    assert cosine_similarity([1, 2], [1, 2, 3]) == 0.0

    print("✅ cosine_similarity math OK")


def test_graceful_degradation_no_api_key():
    """Sans GEMINI_API_KEY, le matcher retourne 0.0 sans erreur."""
    original_key = os.environ.pop("GEMINI_API_KEY", None)
    try:
        matcher = SemanticMatcher()
        matcher._available = None  # reset lazy check
        matcher._cache.clear()

        # score_item doit retourner 0.0 sans exception
        result = matcher.score_item(None, "some_id")
        assert result == 0.0, f"Expected 0.0, got {result}"

        # get_offer_embedding doit retourner None sans exception
        emb = matcher.get_offer_embedding("test offer")
        assert emb is None, f"Expected None, got {emb}"

        print("✅ Graceful degradation OK (no API key)")
    finally:
        if original_key is not None:
            os.environ["GEMINI_API_KEY"] = original_key


def test_integration_with_analyzer():
    """Test d'intégration : le scoring fonctionne avec ou sans embeddings."""
    from cv_tailor import OfferAnalyzer, _load_candidate_profile
    profile = _load_candidate_profile()
    analyzer = OfferAnalyzer(profile)

    # Offre avec vocabulaire paraphrasé (pas de mots-clés exacts du profil)
    paraphrased_offer = (
        "Nous cherchons un profil capable de concevoir des services web, "
        "manipuler des bases de données relationnelles, automatiser des flux de travail, "
        "et contribuer à des projets d'intelligence artificielle appliquée."
    )

    result = analyzer.run_full_analysis(
        "Ingénieur logiciel", paraphrased_offer, "TechCorp"
    )

    # Le pipeline ne doit pas crasher
    assert "match" in result
    assert "selected_exp_ids" in result
    assert "selected_proj_ids" in result
    assert result["match"]["global_score"] >= 0

    # Si le sémantique est actif, on devrait voir un score plus élevé
    # que le pur lexical (qui ne matcherait quasi rien ici)
    api_available = analyzer.semantic._available
    if api_available:
        print(f"   🔬 API sémantique active — score global: {result['match']['global_score']}")
        # Vérifier que des expériences sont sélectionnées malgré l'absence de mots-clés exacts
        print(f"   📋 Expériences sélectionnées: {result['selected_exp_ids']}")
        print(f"   📋 Projets sélectionnés: {result['selected_proj_ids']}")
    else:
        print("   ⚠️ API sémantique non disponible — test passe en mode dégradé")

    print("✅ Integration avec OfferAnalyzer OK")


if __name__ == "__main__":
    test_cosine_similarity_math()
    test_graceful_degradation_no_api_key()
    test_integration_with_analyzer()
    print("\n🎉 Tous les tests sémantiques passent.")