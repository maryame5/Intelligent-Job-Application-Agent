"""
test_generic_validation.py — Validation de la sélection et détection génériques (Problème 3)
==========================================================================================
Vérifie les critères d'acceptation :
1. Une nouvelle expérience fictive dans profil.json avec "always_feature": true est automatiquement
   sélectionnée dans run_full_analysis() sans modifier cv_tailor.py.
2. Une expérience fictive avec role_signal est automatiquement exigée et détectée par OutputValidator
   si absente du CV sans modification de OutputValidator.
3. Rétrocompatibilité : les expériences principales du profil continuent de fonctionner.
"""

import os
import sys

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


from cv_tailor import OfferAnalyzer, OutputValidator, _load_candidate_profile, _build_profile_truth_corpus


def test_truth_corpus_building():
    """Vérifie que _build_profile_truth_corpus extrait les entreprises et dates."""
    profile = _load_candidate_profile()
    corpus = _build_profile_truth_corpus(profile)

    assert "companies" in corpus
    assert "valid_dates" in corpus
    assert len(corpus["companies"]) >= 3, "Deberait contenir au moins DXC, Lotus, MICEPP"

    # Vérifier que "always_feature" est présent sur les 3 stages principaux
    always_featured = [c for c in corpus["companies"] if c["always_feature"]]
    assert len(always_featured) >= 3, "DXC, Lotus, MICEPP doivent avoir always_feature=true"
    print("✅ _build_profile_truth_corpus OK")


def test_dynamic_experience_always_feature_selection():
    """
    Test d'extensibilité 1 :
    Ajouter une expérience fictive avec always_feature=true et vérifier qu'elle
    est automatiquement sélectionnée par OfferAnalyzer.run_full_analysis().
    """
    profile = _load_candidate_profile()

    # Expérience fictive
    fake_exp = {
        "id": "acme_corp_fake",
        "company": "Acme Innovations",
        "always_feature": True,
        "role": "AI Research Intern",
        "duration": "Janv 2025 — Mars 2025",
        "stack": ["Python", "PyTorch"],
        "role_signal": ["ai_engineer"],
    }

    # Créer un profil augmenté
    custom_profile = dict(profile)
    custom_profile["experiences"] = list(profile.get("experiences", [])) + [fake_exp]

    analyzer = OfferAnalyzer(custom_profile)
    result = analyzer.run_full_analysis(
        "Ingénieur IA",
        "Poste en intelligence artificielle et deep learning.",
        "TechCorp"
    )

    selected_ids = result["selected_exp_ids"]
    assert "acme_corp_fake" in selected_ids, (
        f"L'expérience fictive acme_corp_fake avec always_feature=True aurait dû être sélectionnée, "
        f"reçus: {selected_ids}"
    )
    print("✅ Expérience fictive sélectionnée dynamiquement (always_feature)")


def test_dynamic_experience_validation():
    """
    Test d'extensibilité 2 :
    Vérifier que OutputValidator signale le stage manquant pour une nouvelle
    expérience avec always_feature=True si elle est absente du CV généré.
    """
    profile = _load_candidate_profile()

    fake_exp = {
        "id": "acme_corp_fake",
        "company": "Acme Innovations",
        "always_feature": True,
        "role": "Software Developer Intern",
        "duration": "Janv 2025 — Mars 2025",
        "role_signal": ["software_engineer"],
    }
    custom_profile = dict(profile)
    custom_profile["experiences"] = list(profile.get("experiences", [])) + [fake_exp]

    validator = OutputValidator(custom_profile)

    # CV fictif ne contenant PAS Acme Innovations
    cv_output = "CV Candidat - Développeuse Java chez DXC Technology et Lotus Capital"
    analysis = {
        "seniority": {"has_mismatch": False},
        "role": {"dominant": "software_engineer"},
        "exp_scores": [{"company": "DXC Technology"}, {"company": "Lotus Capital"}],
    }

    issues = validator.validate(cv_output, analysis, doc_type="cv")

    # OutputValidator doit avoir détecté l'absence de Acme Innovations
    missing_acme = any("acme innovations" in issue.lower() or "stage manquant" in issue.lower() for issue in issues)
    assert missing_acme, f"OutputValidator aurait dû émettre une alerte pour Acme Innovations. Problèmes détectés: {issues}"
    print("✅ OutputValidator détecte l'absence de la nouvelle expérience fictive (générique)")


if __name__ == "__main__":
    test_truth_corpus_building()
    test_dynamic_experience_always_feature_selection()
    test_dynamic_experience_validation()
    print("\n🎉 Tous les tests de validation générique (Problème 3) passent.")