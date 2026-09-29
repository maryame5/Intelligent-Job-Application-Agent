"""Tests de démarrage sans configuration de fournisseur LLM."""

import os

import integrations.llm_clients as llm_clients
from core.cv_tailor import CVTailor, _load_candidate_profile
from integrations.llm_manager import LLMManager


def _disable_llm_configuration(monkeypatch):
    for variable in (
        "AZURE_OPENAI_ENDPOINT",
        "AZURE_OPENAI_API_KEY",
        "AZURE_OPENAI_DEPLOYMENT",
        "AZURE_OPENAI_API_VERSION",
        "GEMINI_API_KEY",
        "NVIDIA_API_KEY",
    ):
        monkeypatch.delenv(variable, raising=False)

    monkeypatch.setattr(llm_clients, "AZURE_ENDPOINT", None)
    monkeypatch.setattr(llm_clients, "AZURE_API_KEY", None)
    monkeypatch.setattr(llm_clients, "AZURE_DEPLOYMENT", None)
    monkeypatch.setattr(llm_clients, "AZURE_API_VERSION", None)


def test_llm_manager_starts_without_provider_configuration(monkeypatch):
    """Les fonctionnalités déterministes ne doivent pas exiger de clé LLM."""
    _disable_llm_configuration(monkeypatch)

    manager = LLMManager()

    assert manager.azure_llm is None
    assert manager.client is None
    assert manager.nvidia_client is None


def test_cv_tailor_starts_without_azure_configuration(monkeypatch):
    """CVTailor doit pouvoir charger le profil sans initialiser Azure."""
    _disable_llm_configuration(monkeypatch)

    tailor = CVTailor(profile=_load_candidate_profile())

    assert tailor.azure_llm is None
    assert tailor.gemini_client is None
    assert tailor.nvidia_client is None
