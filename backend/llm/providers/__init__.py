"""
Tetris LLM Providers
=====================

Provider package.  Exports the three concrete adapters and the base
class for type-checking and extension.
"""

from .base import BaseLLMProvider
from .claude import ClaudeProvider
from .gpt4 import GPT4Provider
from .groq import GroqProvider

__all__ = [
    "BaseLLMProvider",
    "ClaudeProvider",
    "GPT4Provider",
    "GroqProvider",
]
