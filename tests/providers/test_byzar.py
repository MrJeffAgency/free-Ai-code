"""Tests for the Byzar AI Gateway OpenAI-chat provider profile."""

import httpx2
import pytest
from openai import AsyncOpenAI

from mrjeffagency.application.model_metadata import ProviderModelInfo
from mrjeffagency.config.provider_catalog import BYZAR_DEFAULT_BASE
from mrjeffagency.providers.openai_chat import OpenAIChatProvider
from mrjeffagency.providers.openai_chat.profiles import OPENAI_CHAT_PROFILES
from tests.providers.support import (
    immediate_admission,
    make_provider_config,
    profiled_provider,
)

_MODEL = "claude-sonnet-4-5"


@pytest.fixture
def byzar_provider() -> OpenAIChatProvider:
    return profiled_provider(
        "byzar",
        make_provider_config(
            api_key="adminuse",
            base_url=BYZAR_DEFAULT_BASE,
        ),
        admission=immediate_admission(provider_name="byzar", max_attempts=1),
    )


def test_constructs_standard_openai_chat_provider(
    byzar_provider: OpenAIChatProvider,
) -> None:
    assert isinstance(byzar_provider, OpenAIChatProvider)
    assert byzar_provider._provider_name == "BYZAR"
    assert byzar_provider._api_key == "adminuse"
    assert byzar_provider._base_url == BYZAR_DEFAULT_BASE
    assert "byzar" in OPENAI_CHAT_PROFILES


@pytest.mark.asyncio
async def test_model_catalog_uses_documented_url_and_public_bearer_auth() -> None:
    requests: list[httpx2.Request] = []

    def handler(request: httpx2.Request) -> httpx2.Response:
        requests.append(request)
        return httpx2.Response(200, json={"data": [{"id": _MODEL}]})

    async with AsyncOpenAI(
        api_key="adminuse",
        base_url=BYZAR_DEFAULT_BASE,
        max_retries=0,
        http_client=httpx2.AsyncClient(transport=httpx2.MockTransport(handler)),
    ) as client:
        provider = OpenAIChatProvider(
            make_provider_config(
                api_key="adminuse",
                base_url=BYZAR_DEFAULT_BASE,
            ),
            profile=OPENAI_CHAT_PROFILES["byzar"],
            admission=immediate_admission(provider_name="byzar"),
            client=client,
        )
        model_infos = await provider.list_model_infos()

    assert model_infos == frozenset({ProviderModelInfo(_MODEL)})
    assert len(requests) == 1
    assert str(requests[0].url) == "https://agentapi.byzar.cyou/v1/models"
    assert requests[0].headers["authorization"] == "Bearer adminuse"
