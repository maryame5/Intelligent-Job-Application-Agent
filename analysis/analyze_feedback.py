"""
analyze_feedback.py — Script d'Analyse et de Recalibrage du Scoring CV Tailor (Problème 4)
==========================================================================================
Lit le fichier jobs_tracker.csv pour analyser la corrélation entre les scores attribués
(Deterministic Score, LLM Score, Final ATS Score) et les résultats réels des candidatures
(Outcome: no_response, rejected, interview, offer).

Émet des recommandations d'ajustement des seuils de priorité (75/55/35) et des poids de scoring.
"""

import argparse
import csv
import os
import sys


def load_tracker_data(filename: str) -> list[dict]:
    """Charge le fichier CSV du tracker de candidatures."""
    if not os.path.exists(filename):
        print(f"⚠️ Fichier tracker introuvable: {filename}")
        return []

    rows = []
    with open(filename, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)
    return rows


def analyze_outcomes(rows: list[dict]) -> dict:
    """Analyse la distribution des résultats et les statistiques de scoring."""
    total_jobs = len(rows)
    outcomes_count = {}
    priority_stats = {}
    score_correlations = {
        "positive": {"deterministic": [], "llm": [], "final_ats": []},
        "negative": {"deterministic": [], "llm": [], "final_ats": []},
    }

    for row in rows:
        outcome = (row.get("Outcome") or "pending").strip().lower()
        outcomes_count[outcome] = outcomes_count.get(outcome, 0) + 1

        priority = (row.get("Priority") or "Unknown").strip().upper()
        if priority not in priority_stats:
            priority_stats[priority] = {"total": 0, "positive": 0, "negative": 0, "pending": 0}

        priority_stats[priority]["total"] += 1

        is_positive = outcome in {"interview", "offer"}
        is_negative = outcome in {"rejected", "no_response"}

        if is_positive:
            priority_stats[priority]["positive"] += 1
        elif is_negative:
            priority_stats[priority]["negative"] += 1
        else:
            priority_stats[priority]["pending"] += 1

        # Extraire les scores
        def _parse_int(val):
            try:
                return int(val)
            except Exception:
                return None

        det_score = _parse_int(row.get("Deterministic Score"))
        llm_score = _parse_int(row.get("LLM Score"))
        final_ats = _parse_int(row.get("Final ATS Score"))

        target_dict = score_correlations["positive"] if is_positive else (score_correlations["negative"] if is_negative else None)
        if target_dict:
            if det_score is not None: target_dict["deterministic"].append(det_score)
            if llm_score is not None: target_dict["llm"].append(llm_score)
            if final_ats is not None: target_dict["final_ats"].append(final_ats)

    def _avg(lst):
        return round(sum(lst) / len(lst), 1) if lst else 0.0

    stats = {
        "total_jobs": total_jobs,
        "outcomes_count": outcomes_count,
        "priority_stats": priority_stats,
        "averages": {
            "positive": {
                "deterministic": _avg(score_correlations["positive"]["deterministic"]),
                "llm": _avg(score_correlations["positive"]["llm"]),
                "final_ats": _avg(score_correlations["positive"]["final_ats"]),
                "count": len(score_correlations["positive"]["final_ats"]),
            },
            "negative": {
                "deterministic": _avg(score_correlations["negative"]["deterministic"]),
                "llm": _avg(score_correlations["negative"]["llm"]),
                "final_ats": _avg(score_correlations["negative"]["final_ats"]),
                "count": len(score_correlations["negative"]["final_ats"]),
            },
        },
    }

    # Recommandation d'ajustement
    recommendations = []
    pos_avg_final = stats["averages"]["positive"]["final_ats"]
    neg_avg_final = stats["averages"]["negative"]["final_ats"]

    if pos_avg_final > 0 and neg_avg_final > 0:
        delta = pos_avg_final - neg_avg_final
        if delta > 15:
            recommendations.append(f"✅ Bonne discrimination des scores ATS (Écart moyen: +{round(delta, 1)} pts pour les offres converties en entretien/offre).")
        elif delta < 5:
            recommendations.append("⚠️ Faible discrimination: envisager d'augmenter le poids du score LLM sémantique ou de relever le seuil A de 75 à 80.")
    else:
        recommendations.append("ℹ️ Données de résultats encore insuffisantes (renseigner la colonne 'Outcome' avec 'interview', 'rejected', etc.).")

    stats["recommendations"] = recommendations
    return stats


def print_summary(stats: dict):
    """Affiche un résumé propre dans le terminal."""
    print("\n" + "═" * 65)
    print("📊 ANONYMOUS / RECRUITMENT FEEDBACK ANALYSIS REPORT")
    print("═" * 65)
    print(f"Total des candidatures suivies : {stats['total_jobs']}")
    print("\n[ Distribution des Résultats (Outcome) ]")
    for k, v in stats["outcomes_count"].items():
        print(f"  • {k:<15} : {v}")

    print("\n[ Performance par Priorité ]")
    for prio, s in sorted(stats["priority_stats"].items()):
        resolved = s["positive"] + s["negative"]
        rate = round(s["positive"] / resolved * 100, 1) if resolved > 0 else 0.0
        print(f"  • Priorité {prio:<2} : {s['positive']}/{resolved} convertis en entretien ({rate}% de taux de succès) | {s['pending']} en attente")

    pos = stats["averages"]["positive"]
    neg = stats["averages"]["negative"]
    print("\n[ Moyenne des Scores par Issue ]")
    print(f"  • Entretiens / Offres ({pos['count']} jobs)  : Déterministe = {pos['deterministic']}/100 | LLM = {pos['llm']}/100 | ATS Final = {pos['final_ats']}/100")
    print(f"  • Refus / Sans Réponse ({neg['count']} jobs) : Déterministe = {neg['deterministic']}/100 | LLM = {neg['llm']}/100 | ATS Final = {neg['final_ats']}/100")

    print("\n[ Recommandations d'Ajustement du Scoring ]")
    for rec in stats["recommendations"]:
        print(f"  {rec}")
    print("═" * 65 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Analyse des feedbacks de candidature CV Tailor.")
    parser.add_argument("--file", default="jobs_tracker.csv", help="Chemin du fichier jobs_tracker.csv")
    parser.add_argument("--summary", action="store_true", help="Afficher le rapport résumé")
    args = parser.parse_args()

    script_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = args.file if os.path.isabs(args.file) else os.path.join(script_dir, args.file)

    rows = load_tracker_data(file_path)
    stats = analyze_outcomes(rows)

    if args.summary or True:
        print_summary(stats)


if __name__ == "__main__":
    main()
