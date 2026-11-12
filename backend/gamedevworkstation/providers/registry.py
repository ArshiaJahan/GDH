"""Provider instances per (provider, profile)."""
from __future__ import annotations

from ..config import Config
from .base import ChatProvider


class ProviderRegistry:
    def __init__(self, config: Config):
        self.config = config
        self._chat: dict[tuple[str, str], ChatProvider] = {}
        self._overrides: dict[tuple[str, str], ChatProvider] = {}

    def override(self, provider: str, profile: str, instance: ChatProvider) -> None:
        """Tests and fakes: install a provider instance."""
        self._overrides[(provider, profile)] = instance

    def chat(self, provider: str, profile: str = "default") -> ChatProvider:
        key = (provider, profile)
        if key in self._overrides:
            return self._overrides[key]
        if key not in self._chat:
            if provider == "anthropic":
                from .anthropic_provider import AnthropicProvider

                self._chat[key] = AnthropicProvider(profile, self.config)
            elif provider == "openai":
                from .openai_provider import OpenAIProvider

                self._chat[key] = OpenAIProvider(profile, self.config)
            else:
                raise ValueError(f"no chat provider {provider!r}")
        return self._chat[key]

    def for_model(self, model: str, profile: str = "default") -> ChatProvider:
        return self.chat(self.config.model(model).provider, profile)

    def reset(self) -> None:
        """Drop cached clients (e.g. after a key change)."""
        self._chat.clear()
