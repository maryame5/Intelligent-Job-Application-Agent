"""
Client LLM Centralisé - Azure OpenAI
Point d'entrée unique pour tous les agents du projet.
"""

import json
import os
import logging
from typing import Optional

from dotenv import load_dotenv
from openai import AzureOpenAI, AsyncAzureOpenAI
from openai import (
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    BadRequestError,
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
)

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s - %(message)s"
)
logger = logging.getLogger("llm_client")

# ── Configuration ─────────────────────────────────────────────────────────────
load_dotenv()

AZURE_ENDPOINT    = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_API_KEY     = os.getenv("AZURE_OPENAI_API_KEY")
AZURE_DEPLOYMENT  = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_API_VERSION = os.getenv("AZURE_OPENAI_API_VERSION")

# ── Exceptions Personnalisées ─────────────────────────────────────────────────
class LLMConfigError(Exception):
    """Variables d'environnement manquantes ou invalides."""

class LLMAuthError(Exception):
    """Clé API invalide ou expirée."""

class LLMDeploymentError(Exception):
    """Déploiement Azure introuvable."""

class LLMRateLimitError(Exception):
    """Quota API dépassé."""

class LLMConnectionError(Exception):
    """Impossible de joindre l'API Azure."""

class LLMResponseError(Exception):
    """Réponse inattendue ou vide du modèle."""


# ── Validation de la configuration ───────────────────────────────────────────
def _validate_config():
    """Vérifie que toutes les variables d'environnement sont présentes."""
    missing = []
    if not AZURE_ENDPOINT:    missing.append("AZURE_OPENAI_ENDPOINT")
    if not AZURE_API_KEY:     missing.append("AZURE_OPENAI_API_KEY")
    if not AZURE_DEPLOYMENT:  missing.append("AZURE_OPENAI_DEPLOYMENT")
    if not AZURE_API_VERSION: missing.append("AZURE_OPENAI_API_VERSION")

    if missing:
        raise LLMConfigError(
            f"Variables manquantes dans .env : {', '.join(missing)}\n"
            f"Consultez .env.example pour la configuration."
        )


# ── Singleton Client ──────────────────────────────────────────────────────────
_client: Optional[AzureOpenAI] = None

def get_client() -> AzureOpenAI:
    """Retourne le client AzureOpenAI (singleton)."""
    global _client

    if _client is None:
        _validate_config()
        try:
            _client = AzureOpenAI(
                api_version=AZURE_API_VERSION,
                azure_endpoint=AZURE_ENDPOINT,
                api_key=AZURE_API_KEY,
            )
            logger.info("Client AzureOpenAI initialisé avec succès.")
        
        except Exception as e:
            raise LLMConfigError(f"Échec initialisation client Azure : {e}") from e
    
    return _client


# ──  LLM  Wrapper ───────────────────────────────────────────────────────────────
class LLMWrapper:
    """
    Wrapper  autour d'AzureOpenAI avec gestion claire des exceptions.

    Attributes:
        deployment (str): Nom du deploiement Azure.
        temperature (float): Creativite du modele (0=deterministe, 1=creatif).
        max_completion_tokens (int): Limite de tokens en sortie.
    
    """

    def __init__(self, deployment: str, temperature: float, max_completion_tokens: int, json_mode: bool = False):
        self.deployment            = deployment
        self.temperature           = temperature
        self.max_completion_tokens = max_completion_tokens
        self.json_mode             = json_mode

    # ── Appel API central ─────────────────────────────────────────────────────
    def bind(self, **kwargs) -> "LLMWrapper":
        """Permet la compatibilité avec l'interface LangChain .bind(...)"""
        temp = kwargs.get("temperature", self.temperature)
        max_tok = kwargs.get("max_tokens", kwargs.get("max_completion_tokens", self.max_completion_tokens))
        json_m = kwargs.get("json_mode", self.json_mode)
        dep = kwargs.get("deployment", self.deployment)
        return LLMWrapper(
            deployment=dep,
            temperature=temp,
            max_completion_tokens=max_tok,
            json_mode=json_m,
        )

    def _call(self, messages: list, max_completion_tokens: Optional[int] = None, temperature: Optional[float] = None) -> str:
        """
        Appelle l'API et convertit les exceptions OpenAI en exceptions métier.
        
        Args:
            messages (list[dict]): Historique de messages au format OpenAI.

        Returns:
            str: Contenu textuel de la reponse du modele.

        Raises:
            LLMAuthError:       Cle API invalide.
            LLMDeploymentError: Deploiement introuvable.
            LLMRateLimitError:  Quota depasse.
            LLMConnectionError: Reseau ou serveur inaccessible.
            LLMResponseError:   Reponse vide ou erreur inattendue.
        """
        try:
            temp = temperature if temperature is not None else self.temperature
            max_tok = max_completion_tokens if max_completion_tokens is not None else self.max_completion_tokens
            logger.debug(f"Appel LLM - deployment={self.deployment}, temp={temp}, max_tokens={max_tok}")
            client   = get_client()
            kwargs = {
                "model": self.deployment,
                "messages": messages,
                "temperature": temp,
                "max_completion_tokens": max_tok,
            }
            if self.json_mode:
                kwargs["response_format"] = {"type": "json_object"}
                
            response = client.chat.completions.create(**kwargs)

            content = response.choices[0].message.content
            
            if not content or not content.strip():
                raise LLMResponseError("Le modèle a retourné une réponse vide.")

            logger.debug(f"Réponse reçue ({len(content)} caractères)")
            return content

        except AuthenticationError as e:
            raise LLMAuthError(
                "Clé API invalide ou expirée. Vérifiez AZURE_OPENAI_API_KEY."
            ) from e

        except NotFoundError as e:
            raise LLMDeploymentError(
                f"Déploiement '{self.deployment}' introuvable. "
                f"Vérifiez AZURE_OPENAI_DEPLOYMENT dans .env."
            ) from e

        except RateLimitError as e:
            raise LLMRateLimitError(
                "Quota API dépassé. Réessayez dans quelques instants."
            ) from e

        except BadRequestError as e:
            raise ValueError(
                f"Requête invalide : {e}. Vérifiez le prompt ou les paramètres."
            ) from e

        except (APIConnectionError, APITimeoutError) as e:
            raise LLMConnectionError(
                f"Impossible de joindre l'API Azure ({type(e).__name__})."
            ) from e

        except InternalServerError as e:
            raise LLMConnectionError(
                "Erreur serveur Azure (500). Réessayez dans quelques instants."
            ) from e

        except (LLMResponseError, LLMConfigError):
            raise  # déjà nos exceptions, on laisse remonter

        except Exception as e:
            raise LLMResponseError(
                f"Erreur inattendue : {type(e).__name__} - {e}"
            ) from e

    # ── API Publique ──────────────────────────────────────────────────────────
    def invoke(self, prompt: str) -> str:
        """
        Appel simple avec un prompt utilisateur.

        Args:
            prompt (str): Question ou instruction a envoyer au modele.

        Returns:
            str: Reponse textuelle du modele.

        Raises:
            ValueError: Si le prompt est vide.
        
        """
        if not prompt or not prompt.strip():
            raise ValueError("Le prompt ne peut pas être vide.")
        return self._call([{"role": "user", "content": prompt}])

    def invoke_with_system(self, system: str, user: str) -> str:
        """
        Appel avec un message système (persona/contexte) + message utilisateur.
        
        Args:
            system (str): Instruction systeme definissant le role du modele.
            user (str):   Message de l'utilisateur.

        Returns:
            str: Reponse textuelle du modele.

        Raises:
            ValueError: Si system ou user est vide.
        """
        if not system or not system.strip():
            raise ValueError("Le message système ne peut pas être vide.")
        if not user or not user.strip():
            raise ValueError("Le message utilisateur ne peut pas être vide.")
        
        return self._call([
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ])

    def invoke_with_history(self, messages: list[dict]) -> str:
        """
        Appel avec historique complet de conversation.

        Args:
            messages (list[dict]): Liste de messages avec les cles
                'role' (user|assistant|system) et 'content'.

        Returns:
            str: Reponse textuelle du modele.

        Example:
            llm.invoke_with_history([
                {"role": "system",    "content": "Tu es un expert data."},
                {"role": "user",      "content": "Qu'est-ce que le ML?"},
                {"role": "assistant", "content": "Le ML est..."},
                {"role": "user",      "content": "Donne un exemple."},
            ])
        """
        if not messages:
            raise ValueError("L'historique de messages ne peut pas être vide.")
        
        valid_roles = {"user", "assistant", "system"}
        
        for i, msg in enumerate(messages):
            if "role" not in msg or "content" not in msg:
                raise ValueError(f"Message {i} invalide : 'role' et 'content' requis.")
            if msg["role"] not in valid_roles:
                raise ValueError(f"Message {i} : rôle '{msg['role']}' invalide. Utiliser: {valid_roles}")
        return self._call(messages)

    def invoke_json(self, prompt: str, system: Optional[str] = None) -> dict:
        """
        Appel LLM avec retour JSON parse automatiquement.

        Le modele est force a repondre en JSON pur via le message systeme.
        Utile pour les agents qui ont besoin de donnees structurees.

        Args:
            prompt (str):          Instruction ou question a envoyer.
            system (str, optional): Contexte systeme additionnel.

        Returns:
            dict: Reponse du modele parsee en dictionnaire Python.

        Raises:
            ValueError:      Si le prompt est vide.
            LLMResponseError: Si la reponse n'est pas un JSON valide.

        Example:
            result = llm.invoke_json(
                prompt="Liste 3 etapes pour nettoyer un dataset.",
                system="Tu es un expert data science."
            )
            print(result["steps"])
        """
        if not prompt or not prompt.strip():
            raise ValueError("Le prompt ne peut pas etre vide.")

        json_instruction = (
            "Tu reponds UNIQUEMENT en JSON valide. "
            "Sans markdown, sans backticks, sans explication."
        )
        full_system = (
            f"{system}\n\n{json_instruction}" if system else json_instruction
        )

        raw = self.invoke_with_system(system=full_system, user=prompt)

        cleaned = (
            raw.strip()
            .removeprefix("```json")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            raise LLMResponseError(
                f"Reponse non JSON recue : {e}\n"
                f"Contenu brut : {raw[:200]}"
            ) from e

    async def ainvoke(self, prompt: str) -> str:
        """
        Version async de invoke().

        Args:
            prompt (str): Question ou instruction a envoyer au modele.

        Returns:
            str: Reponse textuelle du modele.

        Raises:
            ValueError:      Si le prompt est vide.
            LLMResponseError: Si la reponse est vide ou invalide.
        
        """
        if not prompt or not prompt.strip():
            raise ValueError("Le prompt ne peut pas être vide.")
        return await self._acall([{"role": "user", "content": prompt}])

    async def ainvoke_with_system(self, system: str, user: str) -> str:
        """Version async de invoke_with_system()."""
        if not system or not system.strip():
            raise ValueError("Le message système ne peut pas être vide.")
        if not user or not user.strip():
            raise ValueError("Le message utilisateur ne peut pas être vide.")
        return await self._acall([
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ])

    async def ainvoke_with_history(self, messages: list[dict]) -> str:
        """Version async de invoke_with_history()."""
        if not messages:
            raise ValueError("L'historique de messages ne peut pas être vide.")
        return await self._acall(messages)

    async def _acall(self, messages: list) -> str:
        """Appel async central avec gestion d'erreurs."""
        try:
            async_client = AsyncAzureOpenAI(
                api_version=AZURE_API_VERSION,
                azure_endpoint=AZURE_ENDPOINT,
                api_key=AZURE_API_KEY,
            )
            kwargs = {
                "model": self.deployment,
                "messages": messages,
                "temperature": self.temperature,
                "max_completion_tokens": self.max_completion_tokens,
            }
            if self.json_mode:
                kwargs["response_format"] = {"type": "json_object"}

            response = await async_client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            
            if not content or not content.strip():
                raise LLMResponseError("Le modèle a retourné une réponse vide.")
            return content

        except (LLMAuthError, LLMDeploymentError, LLMRateLimitError,
                LLMConnectionError, LLMResponseError, ValueError):
            raise

        except Exception as e:
            raise LLMResponseError(f"Erreur async inattendue : {type(e).__name__} - {e}") from e


# ── Point d'entrée public — LLMWrapper (openai natif) ───────────────────────
def get_chat_llm(
    temperature: float = 0,
    max_completion_tokens: int = 4000,
    deployment: Optional[str] = None,
    json_mode: bool = False,
) -> LLMWrapper:
    """
    Retourne un wrapper LLM configuré. À appeler depuis chaque agent.

    Args:
        temperature:            Créativité (0=déterministe, 1=créatif)
        max_completion_tokens:  Limite de tokens en sortie
        deployment:             Nom du déploiement (défaut: AZURE_OPENAI_DEPLOYMENT)

    Returns:
        LLMWrapper: Instance configuree exposant
            .invoke(), .invoke_with_system(),
            .invoke_with_history(), .invoke_json(), .ainvoke()

    Raises:
        LLMConfigError:     Configuration manquante
        LLMAuthError:       Clé API invalide
        LLMDeploymentError: Déploiement introuvable
        LLMRateLimitError:  Quota dépassé
        LLMConnectionError: Réseau/serveur inaccessible
        LLMResponseError:   Réponse inattendue
    """
    _validate_config()
    return LLMWrapper(
        deployment=deployment or AZURE_DEPLOYMENT,
        temperature=temperature,
        max_completion_tokens=max_completion_tokens,
        json_mode=json_mode,
    )


# ── Point d'entrée public — LangChain BaseChatModel ──────────────────────────
def get_langchain_llm(
    temperature: float = 0,
    max_tokens: int = 4000,
    deployment: Optional[str] = None,
):
    """
    Retourne un AzureChatOpenAI (LangChain) configuré depuis les variables d'env.

    À utiliser pour les agents qui s'appuient sur LangChain / LangGraph
    et qui appellent llm.invoke(messages) avec des objets HumanMessage/SystemMessage.

    Args:
        temperature:  Créativité (0=déterministe, 1=créatif)
        max_tokens:   Limite de tokens en sortie
        deployment:   Nom du déploiement (défaut: AZURE_OPENAI_DEPLOYMENT)

    Returns:
        AzureChatOpenAI: Instance LangChain compatible BaseChatModel.

    Raises:
        LLMConfigError: Configuration manquante dans .env
        ImportError:    Si langchain-openai n'est pas installé
    """
    _validate_config()
    try:
        from langchain_openai import AzureChatOpenAI
    except ImportError as exc:
        raise ImportError(
            "langchain-openai est requis pour get_langchain_llm(). "
            "Installez-le avec : pip install langchain-openai"
        ) from exc

    return AzureChatOpenAI(
        azure_endpoint=AZURE_ENDPOINT,
        azure_deployment=deployment or AZURE_DEPLOYMENT,
        api_version=AZURE_API_VERSION,
        api_key=AZURE_API_KEY,
        temperature=temperature,
        max_tokens=max_tokens,
    )

