"""Base AI Provider Interface for KROVEX.

Provides a vendor-agnostic abstraction for generative AI chat and vision models,
ensuring zero lock-in and strict redaction of sensitive credentials.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class AIResponse:
    """Standardized response payload from any AI provider."""
    content: str
    model: str
    tokens_used: int = 0
    finish_reason: str = "stop"
    success: bool = True
    error: Optional[str] = None


class BaseAIProvider(ABC):
    """Abstract base class for all LLM and multimodal providers."""

    @abstractmethod
    async def generate_response(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str,
        temperature: float = 0.8,
        max_tokens: int = 400,
        timeout: float = 12.0,
    ) -> AIResponse:
        """Generate conversational reply given structured message turns and system prompt.
        
        Args:
            messages: List of dicts with 'role' ('user' or 'model'/'assistant') and 'content'.
            system_prompt: High-level instructions defining KROVEX personality and boundaries.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Upper bound on generated tokens.
            timeout: Request deadline in seconds.
        """
        pass

    @property
    @abstractmethod
    def is_configured(self) -> bool:
        """Return True if required API credentials and settings are present."""
        pass

    @abstractmethod
    async def close(self) -> None:
        """Release underlying HTTP client sessions and connection pools."""
        pass
