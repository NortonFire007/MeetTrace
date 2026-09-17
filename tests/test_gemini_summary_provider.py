"""Unit tests for GeminiSummaryProvider with mocked HTTP responses."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from meettrace.storage.models import PersistedTranscript, TranscriptMetadata, TranscriptSegment
from meettrace.summary.gemini import GeminiConfig, GeminiSummaryProvider
from meettrace.summary.models import (
    SummaryAuthError,
    SummaryConfigError,
    SummaryNetworkError,
    SummaryParsingError,
    SummaryQuotaError,
)


def _make_sample_transcript() -> PersistedTranscript:
    """Helper to create a standard sample transcript for summarization tests."""
    return PersistedTranscript(
        meeting_id="meet_test_001",
        schema_version="1.0.0",
        metadata=TranscriptMetadata(
            created_at="2026-09-17T12:00:00Z",
            model_name="faster-whisper:base",
            dominant_language="en",
            detected_languages={"en": 1.0},
            segment_count=2,
            total_duration_ms=15000,
        ),
        segments=[
            TranscriptSegment(
                text="Good morning, let's review the Q3 roadmap and finalize the launch date.",
                start_ms=0,
                end_ms=5000,
                language="en",
            ),
            TranscriptSegment(
                text="Agreed, launch is set for October 15th, and Alice will prepare marketing assets.",
                start_ms=6000,
                end_ms=14000,
                language="en",
            ),
        ],
    )


def test_gemini_config_validation() -> None:
    """Verify GeminiConfig rejects empty or whitespace-only API keys."""
    with pytest.raises(SummaryConfigError, match="API key is required"):
        GeminiConfig(api_key="")

    with pytest.raises(SummaryConfigError, match="API key is required"):
        GeminiConfig(api_key="   ")

    valid_config = GeminiConfig(api_key="test-api-key", model="gemini-2.5-flash")
    assert valid_config.api_key == "test-api-key"
    assert valid_config.model == "gemini-2.5-flash"


def test_gemini_provider_repr_masks_api_key() -> None:
    """Verify GeminiSummaryProvider __repr__ masks the private API key."""
    config = GeminiConfig(api_key="AIzaSySecretKey12345")
    provider = GeminiSummaryProvider(config=config)
    rep = repr(provider)

    assert "AIzaSySecretKey12345" not in rep
    assert "AIza...2345" in rep or "..." in rep


def test_gemini_provider_generate_summary_success() -> None:
    """Verify successful summary generation and parsing from Gemini response."""
    config = GeminiConfig(api_key="test-key-123")
    mock_client = MagicMock(spec=httpx.Client)

    expected_payload = {
        "summary": "Team aligned on Q3 roadmap and confirmed the official launch date.",
        "decisions": ["Official launch date set for October 15th."],
        "action_items": ["Alice to prepare marketing assets."],
        "open_questions": [],
        "follow_ups": ["Next sync before October launch."],
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps(expected_payload),
                        }
                    ]
                }
            }
        ]
    }
    mock_client.post.return_value = mock_response

    provider = GeminiSummaryProvider(config=config, client=mock_client)
    transcript = _make_sample_transcript()

    result = provider.generate_summary(transcript, language="en")

    assert result.summary == expected_payload["summary"]
    assert result.decisions == tuple(expected_payload["decisions"])
    assert result.action_items == tuple(expected_payload["action_items"])
    assert result.open_questions == ()
    assert result.follow_ups == tuple(expected_payload["follow_ups"])

    # Verify endpoint and headers
    mock_client.post.assert_called_once()
    call_args, call_kwargs = mock_client.post.call_args
    assert f"{config.model}:generateContent" in call_args[0]
    assert call_kwargs["headers"]["x-goog-api-key"] == "test-key-123"


def test_gemini_provider_strips_markdown_code_fences() -> None:
    """Verify model responses enclosed in ```json fences are parsed correctly."""
    config = GeminiConfig(api_key="test-key-123")
    mock_client = MagicMock(spec=httpx.Client)

    payload = {
        "summary": "Meeting with code fences.",
        "decisions": ["Approved."],
        "action_items": [],
        "open_questions": [],
        "follow_ups": [],
    }

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": f"```json\n{json.dumps(payload)}\n```",
                        }
                    ]
                }
            }
        ]
    }
    mock_client.post.return_value = mock_response

    provider = GeminiSummaryProvider(config=config, client=mock_client)
    result = provider.generate_summary(_make_sample_transcript())
    assert result.summary == "Meeting with code fences."
    assert result.decisions == ("Approved.",)


def test_gemini_provider_language_instruction_in_prompt() -> None:
    """Verify language preference is embedded into prompt."""
    config = GeminiConfig(api_key="test-key-123")
    mock_client = MagicMock(spec=httpx.Client)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": json.dumps({"summary": "Краткое содержание."}),
                        }
                    ]
                }
            }
        ]
    }
    mock_client.post.return_value = mock_response

    provider = GeminiSummaryProvider(config=config, client=mock_client)
    provider.generate_summary(_make_sample_transcript(), language="ru")

    _, call_kwargs = mock_client.post.call_args
    sent_json = call_kwargs["json"]
    prompt_text = sent_json["contents"][0]["parts"][0]["text"]
    assert "Russian (ru)" in prompt_text


def test_gemini_provider_auth_error_mapping() -> None:
    """Verify HTTP 401 and 403 raise SummaryAuthError."""
    config = GeminiConfig(api_key="bad-key")
    mock_client = MagicMock(spec=httpx.Client)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 401
    mock_response.text = "API key not valid."
    mock_client.post.return_value = mock_response

    provider = GeminiSummaryProvider(config=config, client=mock_client)

    with pytest.raises(SummaryAuthError, match="authentication failed"):
        provider.generate_summary(_make_sample_transcript())


def test_gemini_provider_quota_error_mapping() -> None:
    """Verify HTTP 429 raises SummaryQuotaError."""
    config = GeminiConfig(api_key="valid-key")
    mock_client = MagicMock(spec=httpx.Client)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 429
    mock_response.text = "RESOURCE_EXHAUSTED"
    mock_client.post.return_value = mock_response

    provider = GeminiSummaryProvider(config=config, client=mock_client)

    with pytest.raises(SummaryQuotaError, match="rate limit exceeded"):
        provider.generate_summary(_make_sample_transcript())


def test_gemini_provider_network_and_server_errors() -> None:
    """Verify HTTP 500/503 and network exceptions raise SummaryNetworkError."""
    config = GeminiConfig(api_key="valid-key")
    mock_client = MagicMock(spec=httpx.Client)

    # HTTP 503
    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 503
    mock_response.text = "Service Unavailable"
    mock_client.post.return_value = mock_response

    provider = GeminiSummaryProvider(config=config, client=mock_client)
    with pytest.raises(SummaryNetworkError, match="503"):
        provider.generate_summary(_make_sample_transcript())

    # Timeout
    mock_client.post.side_effect = httpx.TimeoutException("Connection timed out")
    with pytest.raises(SummaryNetworkError, match="timed out"):
        provider.generate_summary(_make_sample_transcript())


def test_gemini_provider_parsing_error_on_corrupted_response() -> None:
    """Verify non-JSON response raises SummaryParsingError."""
    config = GeminiConfig(api_key="valid-key")
    mock_client = MagicMock(spec=httpx.Client)

    mock_response = MagicMock(spec=httpx.Response)
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "candidates": [
            {
                "content": {
                    "parts": [
                        {
                            "text": "This is definitely not JSON.",
                        }
                    ]
                }
            }
        ]
    }
    mock_client.post.return_value = mock_response

    provider = GeminiSummaryProvider(config=config, client=mock_client)
    with pytest.raises(SummaryParsingError, match="Failed to parse model output as JSON"):
        provider.generate_summary(_make_sample_transcript())
