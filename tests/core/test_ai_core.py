"""Offline assessment coordinator tests using the completion client contract."""

import json

import pytest

from phishreport import ai as ai_core
from phishreport.ai import ProviderFailure, ProviderFailureReason
from phishreport.errors import AIUnavailable, InvalidInput


class FakeClient:
    def __init__(self, *outcomes: str | Exception):
        self.prompts: list[str] = []
        self.outcomes = iter(outcomes)

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        outcome = next(self.outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FalseyClient(FakeClient):
    def __bool__(self) -> bool:
        return False


FINDINGS = {
    "credential_request": False,
    "suspicious": True,
    "insufficient_context": False,
    "details": {"emails": ["notice@example.test"], "phone_numbers": [], "ip_addresses": []},
}
MESSAGE = "Contact notice@example.test for assistance."


def test_assess_uses_falsey_client_to_validate_a_single_completion():
    client = FalseyClient(f"```json\n{json.dumps(FINDINGS)}\n```")
    record = {"message": MESSAGE, "sender": "unverified@example.test", "clicked": False}

    assert ai_core.AIManager(client=client).assess(record) == FINDINGS
    assert record == {"message": MESSAGE, "sender": "unverified@example.test", "clicked": False}
    assert len(client.prompts) == 1
    assert client.prompts[0].endswith(
        'Metadata (JSON object):\n{"sender": "unverified@example.test"}\n'
        'Message (JSON string):\n"Contact notice@example.test for assistance."'
    )


@pytest.mark.parametrize(
    ("record", "error"),
    [
        ([], "AI input must be a record dictionary."),
        ({"message": "  "}, "AI input must contain nonblank message text."),
        ({"message": MESSAGE, "sender": 4}, "AI metadata must be text or None: sender"),
    ],
)
def test_assess_rejects_bad_input_before_completion(record, error):
    client = FakeClient()

    with pytest.raises(InvalidInput) as failure:
        ai_core.AIManager(client=client).assess(record)

    assert str(failure.value) == InvalidInput.user_message
    assert isinstance(failure.value.__cause__, ValueError)
    assert str(failure.value.__cause__) == error
    assert client.prompts == []


@pytest.mark.parametrize(
    ("raw", "message", "error"),
    [
        ("broken JSON", MESSAGE, "AI reply is not valid JSON."),
        (
            json.dumps({**FINDINGS, "suspicious": "yes"}),
            MESSAGE,
            "AI reply key is not true/false: suspicious",
        ),
        (
            json.dumps(FINDINGS),
            "No contact details in the message.",
            "AI details have invalid fields or source occurrences.",
        ),
    ],
)
def test_assess_rejects_invalid_completion_without_retry(raw, message, error):
    client = FakeClient(raw)

    with pytest.raises(InvalidInput) as failure:
        ai_core.AIManager(client=client).assess({"message": message})

    assert str(failure.value) == InvalidInput.user_message
    assert isinstance(failure.value.__cause__, ValueError)
    assert str(failure.value.__cause__) == error
    assert len(client.prompts) == 1


def test_assess_can_succeed_after_provider_failure():
    unavailable = ProviderFailure(ProviderFailureReason.TIMEOUT)
    client = FakeClient(unavailable, json.dumps(FINDINGS))
    manager = ai_core.AIManager(client=client)

    with pytest.raises(AIUnavailable) as failure:
        manager.assess({"message": "A prior assessment."})

    assert failure.value.__cause__ is unavailable
    assert manager.assess({"message": MESSAGE}) == FINDINGS
    assert len(client.prompts) == 2
    assert client.prompts[0].endswith('"A prior assessment."')
    assert client.prompts[1].endswith('"Contact notice@example.test for assistance."')


@pytest.mark.parametrize(
    "error",
    [
        ProviderFailure(ProviderFailureReason.CONFIGURATION),
        ProviderFailure(ProviderFailureReason.HTTP, status_code=401),
        ProviderFailure(ProviderFailureReason.HTTP, status_code=503),
        ProviderFailure(ProviderFailureReason.TIMEOUT),
        ProviderFailure(ProviderFailureReason.INVALID_RESPONSE),
    ],
)
def test_assess_maps_provider_failure_without_retry_and_remains_ready(error):
    error.__cause__ = ValueError("PRIVATE_PROVIDER_DATA")
    client = FakeClient(error, json.dumps(FINDINGS))
    manager = ai_core.AIManager(client=client)

    with pytest.raises(AIUnavailable) as failure:
        manager.assess({"message": MESSAGE})

    assert failure.value.__cause__ is error
    assert str(failure.value) == AIUnavailable.user_message
    assert "PRIVATE_PROVIDER_DATA" not in str(failure.value)
    assert len(client.prompts) == 1
    assert manager.assess({"message": MESSAGE}) == FINDINGS
    assert len(client.prompts) == 2


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("private"),
        ValueError("private"),
        TypeError("defect"),
        KeyError("defect"),
        InvalidInput(),
        AIUnavailable(),
    ],
)
def test_assess_preserves_unexpected_client_errors_and_domain_error_identity(error):
    client = FakeClient(error)

    with pytest.raises(type(error)) as failure:
        ai_core.AIManager(client=client).assess({"message": MESSAGE})

    assert failure.value is error
    assert len(client.prompts) == 1
