"""
semantic_matcher.py — Scoring sémantique par embeddings Gemini
================================================================
Signal complémentaire au matching lexical de OfferAnalyzer.
Utilise Gemini text-embedding-004 (gratuit, multilingue FR/EN).

Principes :
- Cache in-memory : les embeddings du profil (expériences / projets) sont
  stables entre les offres d'un même run → on ne les recalcule pas.
- Graceful degradation : si l'API échoue (offline, quota, clé manquante),
  on retourne 0.0 sans casser le pipeline.
- Pas de numpy : cosine_similarity en pur Python pour éviter une dépendance.
"""

import math
import os
from typing import Optional


# ─── Cosine similarity (pure Python) ─────────────────────────────────────────

def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Similarité cosinus entre deux vecteurs. Retourne 0.0 si un vecteur est nul."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


# ─── Gemini embedding client ─────────────────────────────────────────────────

_DEFAULT_EMBEDDING_MODEL = "models/gemini-embedding-001"
_MAX_TEXT_CHARS = 2000  # text-embedding supporte ~2048+ tokens, on tronque par sécurité

_RESOLVED_EMBEDDING_MODEL: Optional[str] = None
_GLOBAL_PROFILE_CACHE: dict[str, list[float]] = {}


def _resolve_embedding_model(client) -> str:
    """
    Identifie dynamiquement un modèle d'embedding disponible avec cache global,
    avec préférence pour GEMINI_EMBEDDING_MODEL env ou gemini-embedding-001.
    S'assure que le nom du modèle est préfixé par 'models/'.
    """
    global _RESOLVED_EMBEDDING_MODEL
    if _RESOLVED_EMBEDDING_MODEL:
        return _RESOLVED_EMBEDDING_MODEL

    env_model = os.getenv("GEMINI_EMBEDDING_MODEL")
    if env_model:
        _RESOLVED_EMBEDDING_MODEL = env_model if env_model.startswith("models/") else f"models/{env_model}"
        return _RESOLVED_EMBEDDING_MODEL

    try:
        available_models = []
        for m in client.models.list():
            name = getattr(m, "name", "") or ""
            actions = getattr(m, "supported_actions", []) or getattr(m, "supported_generation_methods", []) or []
            is_embedding = (
                any("embed" in str(a).lower() for a in actions)
                or "embedding" in name.lower()
                or "embed" in name.lower()
            )
            if is_embedding:
                available_models.append(name)

        if not available_models:
            _RESOLVED_EMBEDDING_MODEL = _DEFAULT_EMBEDDING_MODEL
            return _RESOLVED_EMBEDDING_MODEL

        # Recherche prioritaire de gemini-embedding-001
        for model_name in available_models:
            if "gemini-embedding-001" in model_name:
                _RESOLVED_EMBEDDING_MODEL = model_name if model_name.startswith("models/") else f"models/{model_name}"
                return _RESOLVED_EMBEDDING_MODEL

        # Sinon prend le premier modèle d'embedding disponible
        chosen = available_models[0]
        _RESOLVED_EMBEDDING_MODEL = chosen if chosen.startswith("models/") else f"models/{chosen}"
        return _RESOLVED_EMBEDDING_MODEL
    except Exception:
        _RESOLVED_EMBEDDING_MODEL = _DEFAULT_EMBEDDING_MODEL
        return _DEFAULT_EMBEDDING_MODEL


def _get_embedding_gemini(text: str, model_name: Optional[str] = None) -> tuple[Optional[list[float]], Optional[str]]:
    """
    Appelle Gemini embedding et retourne (vecteur, model_name_utilisé), ou (None, model_name) en cas d'erreur.
    Vérifie que model_name comporte bien le préfixe 'models/'.
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None, model_name
    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        if not model_name:
            model_name = _resolve_embedding_model(client)

        if not model_name.startswith("models/"):
            model_name = f"models/{model_name}"

        truncated = text[:_MAX_TEXT_CHARS].strip()
        if not truncated:
            return None, model_name

        result = client.models.embed_content(
            model=model_name,
            contents=truncated,
        )
        # L'API retourne result.embeddings[0].values (list[float])
        if result and result.embeddings:
            return list(result.embeddings[0].values), model_name
        return None, model_name
    except Exception:
        return None, model_name


def _get_batch_embeddings_gemini(
    texts: list[str], model_name: Optional[str] = None
) -> tuple[list[Optional[list[float]]], Optional[str]]:
    """
    Appelle Gemini embedding en mode batch (contents=[text1, text2, ...])
    et retourne (liste_de_vecteurs, model_name_utilisé).
    """
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or not texts:
        return [None] * len(texts), model_name
    try:
        from google import genai
        client = genai.Client(api_key=api_key)

        if not model_name:
            model_name = _resolve_embedding_model(client)

        if not model_name.startswith("models/"):
            model_name = f"models/{model_name}"

        truncated_texts = [t[:_MAX_TEXT_CHARS].strip() or " " for t in texts]

        result = client.models.embed_content(
            model=model_name,
            contents=truncated_texts,
        )
        if result and result.embeddings and len(result.embeddings) == len(texts):
            vectors = [
                list(e.values) if (e and hasattr(e, "values") and e.values) else None
                for e in result.embeddings
            ]
            return vectors, model_name
        return [None] * len(texts), model_name
    except Exception:
        return [None] * len(texts), model_name


# ─── SemanticMatcher ──────────────────────────────────────────────────────────

class SemanticMatcher:
    """
    Cache les embeddings du profil et calcule les similarités cosinus
    entre l'offre et chaque expérience/projet.

    Usage dans OfferAnalyzer :
        matcher = SemanticMatcher()
        matcher.precompute_profile(experiences, projects)
        sim = matcher.score_item(offer_text, item_id)
    """

    def __init__(self):
        # Réutiliser les embeddings du profil déjà calculés en mémoire globale
        self._cache: dict[str, list[float]] = dict(_GLOBAL_PROFILE_CACHE)
        self._available: Optional[bool] = None     # lazy check
        self._model_name: Optional[str] = _RESOLVED_EMBEDDING_MODEL

    def _is_available(self) -> bool:
        """Vérifie une seule fois si l'API embedding est utilisable."""
        if self._available is None:
            vec, model = _get_embedding_gemini("test", model_name=self._model_name)
            self._model_name = model
            self._available = vec is not None and len(vec) > 0
        return self._available

    def _get_or_compute(self, key: str, text: str) -> Optional[list[float]]:
        """Retourne l'embedding depuis le cache ou le calcule."""
        if key in self._cache:
            return self._cache[key]
        vec, model = _get_embedding_gemini(text, model_name=self._model_name)
        if model:
            self._model_name = model
        if vec:
            self._cache[key] = vec
        return vec

    def get_or_compute_batch(self, items: list[tuple[str, str]]) -> dict[str, Optional[list[float]]]:
        """
        Calcule et met en cache un ensemble de (cache_key, texte) en un seul appel réseau batch.
        Retourne un dictionnaire {cache_key: vecteur}.
        """
        if not items:
            return {}

        results: dict[str, Optional[list[float]]] = {}
        missing_items: list[tuple[str, str]] = []

        for key, text in items:
            if key in self._cache:
                results[key] = self._cache[key]
            else:
                missing_items.append((key, text))

        if not missing_items:
            return results

        if not self._is_available():
            for key, _ in missing_items:
                results[key] = None
            return results

        keys = [k for k, _ in missing_items]
        texts = [t for _, t in missing_items]

        vectors, model = _get_batch_embeddings_gemini(texts, model_name=self._model_name)
        if model:
            self._model_name = model

        for key, vec in zip(keys, vectors):
            if vec:
                self._cache[key] = vec
                if key.startswith("profile:"):
                    _GLOBAL_PROFILE_CACHE[key] = vec
            results[key] = vec

        return results

    def precompute_profile(self, experiences: list[dict], projects: list[dict]) -> None:
        """
        Pré-calcule les embeddings de toutes les expériences et projets du profil
        en un seul appel réseau batch (contents=[texte1, texte2, ...]).
        """
        if not self._is_available():
            return

        items_to_embed: list[tuple[str, str]] = []  # (cache_key, text)

        for exp in experiences:
            item_id = exp.get("id", "")
            if not item_id or f"profile:{item_id}" in self._cache:
                continue
            text = _item_to_text(exp, item_type="experience")
            if text:
                items_to_embed.append((f"profile:{item_id}", text))

        for proj in projects:
            item_id = proj.get("id", "")
            if not item_id or f"profile:{item_id}" in self._cache:
                continue
            text = _item_to_text(proj, item_type="project")
            if text:
                items_to_embed.append((f"profile:{item_id}", text))

        if not items_to_embed:
            return

        self.get_or_compute_batch(items_to_embed)

    def get_offer_embedding(self, offer_text: str) -> Optional[list[float]]:
        """Calcule et cache l'embedding de l'offre."""
        if not self._is_available():
            return None
        # On utilise un hash simple pour la clé cache
        key = f"offer:{hash(offer_text[:500])}"
        return self._get_or_compute(key, offer_text)

    def score_item(self, offer_embedding: Optional[list[float]], item_id: str) -> float:
        """
        Retourne la similarité cosinus [0.0, 1.0] entre l'offre et un item du profil.
        Retourne 0.0 si les embeddings ne sont pas disponibles.
        """
        if offer_embedding is None:
            return 0.0
        profile_vec = self._cache.get(f"profile:{item_id}")
        if profile_vec is None:
            return 0.0
        return max(0.0, cosine_similarity(offer_embedding, profile_vec))


def _item_to_text(item: dict, item_type: str = "experience") -> str:
    """Convertit un item profil en texte lisible pour l'embedding."""
    parts = []
    if item_type == "experience":
        parts.append(item.get("role", item.get("title", "")))
        parts.append(item.get("company", ""))
    else:
        parts.append(item.get("name", ""))
        parts.append(item.get("description", ""))

    # Stack technique
    stack = item.get("stack", [])
    if isinstance(stack, dict):
        for v in stack.values():
            if isinstance(v, list):
                parts.extend(str(x) for x in v)
            else:
                parts.append(str(v))
    elif isinstance(stack, list):
        parts.extend(str(x) for x in stack)

    # Bullets / achievements
    for bullet in item.get("story_bullets", []):
        if isinstance(bullet, dict):
            parts.append(bullet.get("context", ""))
            parts.append(bullet.get("action", ""))
            parts.append(bullet.get("result", ""))
        elif isinstance(bullet, str):
            parts.append(bullet)

    for ach in item.get("key_achievements", item.get("highlights", [])):
        if isinstance(ach, str):
            parts.append(ach)

    return " ".join(p for p in parts if p and isinstance(p, str))[:_MAX_TEXT_CHARS]
