import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

"""
run_test_battery.py

Execute la batterie de tests de test_offers_evaluation.json contre le pipeline
cv_tailor.py (OfferAnalyzer + CVTailor + OutputValidator) et ecrit les resultats
directement dans le meme fichier JSON.

IMPORTANT : je n'ai pas vu le code exact que Antigravity a produit apres les
corrections (nouveaux noms de parametres/cles de dict pour le score hybride,
le flag semantic_bonus, etc.). Ce script est ecrit de facon defensive
(introspection via inspect.signature, plusieurs noms de champs essayes) pour
s'adapter automatiquement aux variantes les plus probables. Si une extraction
echoue ou renvoie None, ouvre extract_common_fields() et ajuste les cles selon
ce que ton run_full_analysis()/generate() renvoie reellement chez toi.

Usage :
    python run_test_battery.py                  # scoring seul (rapide, pas de generation LLM)
    python run_test_battery.py --full            # + generation complete CV/lettre (lent, appels LLM/embeddings)
    python run_test_battery.py --case T03        # ne lancer qu'un seul test
    python run_test_battery.py --file autre.json # cibler un autre fichier de tests

Prerequis :
    - A lancer depuis le dossier contenant cv_tailor.py, profile_adapter.py, profil.json
    - Variables d'environnement (cles LLM / embeddings) definies si --full est utilise
"""

import argparse
import inspect
import json
import sys
import traceback
from pathlib import Path


def load_profile():
    """Charge le profil via profile_adapter.build_candidate_master_profile (point d'entree confirme)."""
    import profile.adapter as pa

    if hasattr(pa, "build_candidate_master_profile"):
        return pa.build_candidate_master_profile("profil.json")

    # Fallback si le module a change entre-temps.
    for fn_name in ("load_profile", "get_profile", "load_candidate_profile", "adapt_profile", "build_profile"):
        fn = getattr(pa, fn_name, None)
        if callable(fn):
            try:
                return fn()
            except TypeError:
                try:
                    return fn("profil.json")
                except Exception:
                    continue

    print("[info] aucun point d'entree profile_adapter trouve, chargement brut de profil.json")
    with open("profil.json", encoding="utf-8") as f:
        return json.load(f)


def call_with_supported_kwargs(func, *args, **kwargs):
    """Appelle func avec uniquement les kwargs qu'il accepte reellement."""
    try:
        sig = inspect.signature(func)
    except (TypeError, ValueError):
        return func(*args, **kwargs)

    params = sig.parameters
    has_var_kw = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values())
    if has_var_kw:
        accepted = kwargs
    else:
        accepted = {k: v for k, v in kwargs.items() if k in params}
        dropped = set(kwargs) - set(accepted)
        if dropped:
            name = getattr(func, "__name__", str(func))
            print(f"  [info] parametres ignores (non supportes par {name}): {sorted(dropped)}")
    return func(*args, **accepted)


def instantiate(cls, profile):
    """Instancie une classe en essayant plusieurs conventions d'appel courantes."""
    try:
        return call_with_supported_kwargs(cls, profile=profile)
    except TypeError:
        pass
    try:
        return cls(profile)
    except Exception as e:
        raise RuntimeError(f"Impossible d'instancier {cls.__name__}: {e}") from e


def run_scoring(cv_tailor_module, analyzer, offer, simulate_llm_score):
    analysis = call_with_supported_kwargs(
        analyzer.run_full_analysis,
        job_title=offer["job_title"],
        job_description=offer["description"],
        company_name=offer["company_name"],
        external_match_score=simulate_llm_score,
    )
    # run_full_analysis() seul ne calcule pas application_context (priority/auto_apply) :
    # c'est build_application_context() qui le fait, separement.
    build_ctx = getattr(cv_tailor_module, "build_application_context", None)
    if callable(build_ctx):
        try:
            analysis["application_context"] = build_ctx(analysis, external_match_score=simulate_llm_score)
        except TypeError:
            analysis["application_context"] = build_ctx(analysis)
    return analysis


def _first_present(d, keys):
    for k in keys:
        if isinstance(d, dict) and d.get(k) is not None:
            return d.get(k)
    return None


def extract_common_fields(analysis):
    """Extrait les champs communs — cles confirmees dans cv_tailor.py (run_full_analysis / build_application_context)."""
    if not isinstance(analysis, dict):
        return {"manual_notes": f"analysis n'est pas un dict (type={type(analysis)})"}

    match = analysis.get("match", {}) or {}
    app_ctx = analysis.get("application_context", {}) or {}
    role = analysis.get("role", {}) or {}

    exp_scores = analysis.get("exp_scores", []) or []
    proj_scores = analysis.get("proj_scores", []) or []
    top_exp_sim = sorted(
        [{"id": e.get("id"), "semantic_similarity": e.get("semantic_similarity")} for e in exp_scores if e.get("semantic_similarity") is not None],
        key=lambda x: x["semantic_similarity"], reverse=True,
    )[:3]
    top_proj_sim = sorted(
        [{"id": p.get("id"), "semantic_similarity": p.get("semantic_similarity")} for p in proj_scores if p.get("semantic_similarity") is not None],
        key=lambda x: x["semantic_similarity"], reverse=True,
    )[:3]

    return {
        "deterministic_score": match.get("deterministic_score"),
        "llm_score": match.get("llm_score"),
        "hybrid_score": match.get("global_score"),
        "priority": app_ctx.get("priority"),
        "auto_apply_recommended": app_ctx.get("auto_apply_recommended"),
        "status": app_ctx.get("status"),
        "risk_level": app_ctx.get("risk_level"),
        "semantic_bonus_applied": bool(top_exp_sim or top_proj_sim),
        "top_experience_semantic_similarities": top_exp_sim,
        "top_project_semantic_similarities": top_proj_sim,
        "selected_experiences": analysis.get("selected_exp_ids"),
        "selected_projects": analysis.get("selected_proj_ids"),
        "dominant_role_detected": role.get("dominant"),
        "seniority_mismatch": (analysis.get("seniority", {}) or {}).get("has_mismatch"),
    }


def inject_fake_hallucination(cv_text, fake_fact="Stage chez QuantumSoft Corp (2021)"):
    """
    Insere une phrase factuelle inventee pour tester la detection generique du OutputValidator.
    Recherche le marqueur de section de facon insensible aux accents/casse, avec fallback en fin de document.
    Retourne (texte_modifie, injection_confirmee: bool).
    """
    import unicodedata

    def _strip_accents(s):
        return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")

    norm_text = _strip_accents(cv_text).lower()
    candidates = ["## experiences professionnelles", "## experience professionnelle", "experiences professionnelles"]

    for marker_norm in candidates:
        idx = norm_text.find(marker_norm)
        if idx != -1:
            # Trouve la fin de la ligne du titre dans le texte ORIGINAL (pas normalise) a la meme position
            line_end = cv_text.find("\n", idx)
            if line_end == -1:
                line_end = len(cv_text)
            modified = cv_text[:line_end] + f"\n\n{fake_fact}\n" + cv_text[line_end:]
            return modified, True

    # Fallback : ajout en fin de document si aucun marqueur trouve
    return cv_text + f"\n\n{fake_fact}\n", False


def run_full_generation(tailor, offer, simulate_llm_score):
    kwargs = dict(
        job_title=offer["job_title"],
        job_description=offer["description"],
        company_name=offer["company_name"],
        application_context={"match_score": simulate_llm_score},
    )
    return call_with_supported_kwargs(tailor.generate, **kwargs)


def main():
    default_json = Path(__file__).parent / "fixtures" / "test_offers_evaluation.json"
    if not default_json.exists():
        default_json = Path("test_offers_evaluation.json")
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default=str(default_json))
    parser.add_argument("--full", action="store_true", help="Genere aussi le CV/lettre complets (appels LLM, plus lent)")
    parser.add_argument("--case", default=None, help="Ne lancer qu'un seul id de test (ex: T03)")
    parser.add_argument("--debug", action="store_true", help="Force l'affichage du dump JSON de analysis meme sans --case")
    args = parser.parse_args()

    path = Path(args.file)
    data = json.loads(path.read_text(encoding="utf-8"))

    try:
        import cv_tailor
    except ImportError as e:
        print(f"[erreur] impossible d'importer cv_tailor.py (verifie que tu executes depuis le bon dossier) : {e}")
        sys.exit(1)

    profile = load_profile()

    try:
        analyzer = instantiate(cv_tailor.OfferAnalyzer, profile)
    except RuntimeError as e:
        print(f"[erreur] {e}")
        sys.exit(1)

    tailor = None
    if args.full:
        try:
            tailor = instantiate(cv_tailor.CVTailor, profile)
        except RuntimeError as e:
            print(f"[erreur] {e}")
            sys.exit(1)

    ran = 0
    for case in data["test_cases"]:
        if args.case and case["id"] != args.case:
            continue
        ran += 1

        print(f"\n=== {case['id']} - {case['category']} ===")
        offer = case["offer"]
        simulate_llm_score = case.get("simulate_llm_score")

        try:
            analysis = run_scoring(cv_tailor, analyzer, offer, simulate_llm_score)
            if args.case or args.debug:
                print("  --- DUMP analysis (debug) ---")
                print(json.dumps(analysis, indent=2, default=str, ensure_ascii=False))
                print("  --- FIN DUMP ---")
            fields = extract_common_fields(analysis)
            case["results"].update({k: v for k, v in fields.items() if k in case["results"] or True})
            print(
                f"  score deterministe={fields.get('deterministic_score')} "
                f"llm={fields.get('llm_score')} hybride={fields.get('hybrid_score')} "
                f"priorite={fields.get('priority')}"
            )
        except Exception:
            print("  [ERREUR scoring]")
            traceback.print_exc()
            case["results"]["manual_notes"] = "Erreur pendant le scoring - voir logs console."
            continue

        if args.full:
            try:
                gen_result = run_full_generation(tailor, offer, simulate_llm_score)
                cv_text = None
                if isinstance(gen_result, dict):
                    cv_text = gen_result.get("cv") or gen_result.get("resume_markdown") or gen_result.get("cv_markdown")
                    issues = gen_result.get("validation_issues") or gen_result.get("issues")
                    if issues:
                        case["results"]["hallucination_issues"] = issues

                if case["id"] in ("T05", "T10") and cv_text and hasattr(cv_tailor, "OutputValidator"):
                    fake_text, injection_confirmed = inject_fake_hallucination(cv_text)
                    validator = instantiate(cv_tailor.OutputValidator, profile)
                    try:
                        result = validator.validate(fake_text, analysis, "cv")
                    except TypeError:
                        try:
                            result = validator.validate(fake_text, analysis)
                        except TypeError:
                            result = validator.validate(fake_text)
                    print(f"  [test hallucination injectee] marqueur trouve={injection_confirmed} resultat validation: {result}")
                    prev = case["results"].get("manual_notes") or ""
                    note = f" | Injection confirmee={injection_confirmed}, detection hallucination: {result}"
                    case["results"]["manual_notes"] = (prev + note).strip(" |")

            except Exception:
                print("  [ERREUR generation complete]")
                traceback.print_exc()
                prev = case["results"].get("manual_notes") or ""
                case["results"]["manual_notes"] = (prev + " | Erreur pendant generate() - voir logs console.").strip(" |")

    if ran == 0:
        print(f"[attention] aucun test_case ne correspond a --case {args.case!r}")

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nResultats enregistres dans {path}")


if __name__ == "__main__":
    main()