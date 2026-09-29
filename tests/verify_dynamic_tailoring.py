"""
verify_dynamic_tailoring.py — Teste l'adaptation dynamique sur 3 profils d'offres différents :
1. Backend Java / Spring Boot
2. Frontend / Full-Stack React
3. AI / Machine Learning
"""
import os
import sys

import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from cv_tailor import CVTailor

def test_dynamic_scenarios():
    tailor = CVTailor()

    test_jobs = [
        {
            "id": "java_backend",
            "title": "Développeur Java Spring Boot",
            "company": "Capgemini",
            "description": """Nous recherchons un développeur Java / Spring Boot pour concevoir et développer des APIs REST et des microservices distribués. 
Stack : Java 17/21, Spring Boot 3, Spring Cloud, PostgreSQL, Docker, Kafka, Git, JUnit.
Missions : Conception d'architectures microservices, optimisation de requêtes SQL, sécurité JWT/OAuth2 et tests d'intégration."""
        },
        {
            "id": "frontend_react",
            "title": "Développeur Full-Stack React / TypeScript",
            "company": "TechScale",
            "description": """Rejoignez notre équipe pour construire des applications web modernes et interactives.
Stack : React 18, TypeScript, Tailwind CSS, Vite, TanStack Query, FastAPI, PostgreSQL.
Missions : Développement d'interfaces soignées, gestion d'état, consommation d'APIs REST, conception de dashboards temps réel et UX utilisateur."""
        },
        {
            "id": "ai_ml_engineer",
            "title": "Ingénieur IA & Machine Learning",
            "company": "DataMind AI",
            "description": """Nous recherchons un ingénieur IA pour développer et industrialiser des pipelines de Machine Learning et des agents intelligents.
Stack : Python, Scikit-learn, XGBoost, MLflow, LangGraph, Azure OpenAI, FastAPI, Docker.
Missions : Entraînement et évaluation de modèles prédictifs, tracking d'expérimentations MLflow, orchestration d'agents et déploiement d'APIs prédictives."""
        }
    ]

    print("=" * 70)
    print("🚀 TEST D'ADAPTATION DYNAMIQUE (3 SCÉNARIOS)")
    print("=" * 70)

    for job in test_jobs:
        print(f"\n📌 Analyse de l'offre : {job['title']} chez {job['company']}")
        analysis = tailor.analyzer.run_full_analysis(
            job["title"],
            job["description"],
            job["company"]
        )

        role_dominant = analysis["role"]["dominant"]
        profile_mode = analysis.get("positioning", {}).get("profile_mode")
        target_title = analysis.get("positioning", {}).get("target_title")

        print(f"   -> Rôle dominant détecté : {role_dominant}")
        print(f"   -> Mode de positionnement : {profile_mode}")
        print(f"   -> Titre recommandé : {target_title}")
        print(f"   -> Top keywords requis : {analysis.get('required_keywords', [])[:6]}")
        print(f"   -> Expériences classées : {[e['company'] for e in analysis.get('exp_scores', [])]}")
        print(f"   -> Projets classés : {[p['name'][:35] for p in analysis.get('proj_scores', [])]}")

    print("\n" + "=" * 70)
    print("✅ TOUS LES SCÉNARIOS D'ANALYSE DYNAMIQUE SE SONT EXÉCUTÉS AVEC SUCCÈS")
    print("=" * 70)

if __name__ == "__main__":
    test_dynamic_scenarios()