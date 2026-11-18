"""Protocol models live with the protocol logic that consumes them."""

import subprocess
import sys

from mrjeffagency.core.anthropic import (
    MessagesRequest as PublicMessagesRequest,
)
from mrjeffagency.core.anthropic import (
    MessagesResponse,
    TokenCountResponse,
)
from mrjeffagency.core.anthropic.models import MessagesRequest
from mrjeffagency.core.openai_responses import (
    OpenAIResponsesRequest as PublicOpenAIResponsesRequest,
)
from mrjeffagency.core.openai_responses.models import OpenAIResponsesRequest


def test_anthropic_request_model_is_core_owned_and_permissive() -> None:
    request = MessagesRequest.model_validate(
        {
            "model": "provider-model",
            "messages": [{"role": "user", "content": "hello"}],
            "provider_extension": {"enabled": True},
        }
    )

    assert MessagesRequest.__module__ == "mrjeffagency.core.anthropic.models"
    assert PublicMessagesRequest is MessagesRequest
    assert request.model_extra == {"provider_extension": {"enabled": True}}


def test_responses_request_model_is_core_owned_and_permissive() -> None:
    request = OpenAIResponsesRequest.model_validate(
        {
            "model": "provider-model",
            "input": "hello",
            "provider_extension": {"enabled": True},
        }
    )

    assert (
        OpenAIResponsesRequest.__module__
        == "mrjeffagency.core.openai_responses.models"
    )
    assert PublicOpenAIResponsesRequest is OpenAIResponsesRequest
    assert request.model_extra == {"provider_extension": {"enabled": True}}


def test_anthropic_response_models_are_protocol_owned() -> None:
    assert MessagesResponse.__module__ == "mrjeffagency.core.anthropic.models"
    assert TokenCountResponse.__module__ == "mrjeffagency.core.anthropic.models"


def test_protocol_facades_are_import_order_independent() -> None:
    import_orders = (
        (
            "mrjeffagency.core.anthropic",
            "mrjeffagency.core.openai_responses",
        ),
        (
            "mrjeffagency.core.openai_responses",
            "mrjeffagency.core.anthropic",
        ),
    )

    for modules in import_orders:
        script = "; ".join(f"import {module}" for module in modules)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True,
            check=False,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
