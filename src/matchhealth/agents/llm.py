"""Model access behind a small protocol so agents stay testable.

TODO: wrap these agents with Microsoft Agent Framework once wired to Foundry
(check the current Agent Framework docs for the Python API).
"""

from __future__ import annotations

import json
import os
from importlib import resources
from typing import Protocol


def mock_enabled() -> bool:
    return os.environ.get("MATCHHEALTH_MOCK_LLM", "1") != "0"


def load_prompt(name: str) -> str:
    return resources.files("matchhealth.agents.prompts").joinpath(f"{name}.md").read_text()


class LLMClient(Protocol):
    async def complete_json(self, system: str, user: dict, tier: str) -> dict: ...


class FoundryLLM:
    """Calls model deployments in Microsoft Foundry via the Azure OpenAI-compatible API."""

    def __init__(self) -> None:
        from azure.identity import DefaultAzureCredential, get_bearer_token_provider
        from openai import AsyncAzureOpenAI

        token = get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
        self._client = AsyncAzureOpenAI(
            azure_endpoint=os.environ["FOUNDRY_ENDPOINT"],
            azure_ad_token_provider=token,
            api_version=os.environ.get("FOUNDRY_API_VERSION", "2024-10-21"),
        )
        self._deployments = {
            "mini": os.environ.get("FOUNDRY_DEPLOYMENT_MINI", "gpt-4.1-mini"),
            "nano": os.environ.get("FOUNDRY_DEPLOYMENT_NANO", "gpt-4.1-nano"),
        }

    async def complete_json(self, system: str, user: dict, tier: str) -> dict:
        resp = await self._client.chat.completions.create(
            model=self._deployments[tier],
            response_format={"type": "json_object"},
            temperature=0.4,
            messages=[{"role": "system", "content": system},
                      {"role": "user", "content": json.dumps(user)}],
        )
        return json.loads(resp.choices[0].message.content or "{}")
