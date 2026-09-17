"""Gemini-based meeting summarization provider.

Uses Google Gemini REST API v1beta with structured JSON schemas, secure key handling,
customizable Flash model selection, and typed error mapping.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any

import httpx

from meettrace.storage.markdown import format_timestamp_ms
from meettrace.storage.models import PersistedTranscript
from meettrace.summary.models import (
    MeetingSummary,
    SummaryAuthError,
    SummaryConfigError,
    SummaryError,
    SummaryNetworkError,
    SummaryParsingError,
    SummaryQuotaError,
)

logger = logging.getLogger(__name__)

GEMINI_API_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
AVAILABLE_GEMINI_MODELS: tuple[str, ...] = (
    "gemini-3.8-flash",
    "gemini-3.7-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-2.0-flash",
    "gemini-1.5-flash",
)
DEFAULT_GEMINI_MODEL = "gemini-3.8-flash"


def mask_api_key(key: str | None) -> str:
    """Safely mask an API key for logs and representation."""
    if not key:
        return "<none>"
    if len(key) <= 8:
        return "***"
    return f"{key[:4]}...{key[-4:]}"


@dataclass(slots=True)
class GeminiConfig:
    """Configuration options for the Gemini summary provider."""

    api_key: str | None = None
    model: str = DEFAULT_GEMINI_MODEL
    timeout_sec: float = 30.0
    temperature: float = 0.2

    def __post_init__(self) -> None:
        if self.api_key is not None and not self.api_key.strip():
            raise SummaryConfigError("API key is required.")

    def resolve_api_key(self) -> str | None:
        """Resolve API key from explicit config, .env, or environment variables."""
        if self.api_key and self.api_key.strip():
            return self.api_key.strip()
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        if env_key and env_key.strip():
            return env_key.strip()

        from meettrace.config import load_dotenv

        load_dotenv()
        env_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
        return env_key.strip() if env_key and env_key.strip() else None

    def __repr__(self) -> str:
        return (
            f"GeminiConfig(model='{self.model}', "
            f"api_key='{mask_api_key(self.resolve_api_key())}', "
            f"timeout_sec={self.timeout_sec})"
        )


def _build_transcript_text(transcript: PersistedTranscript) -> str:
    """Format transcript segments with timestamps for model consumption."""
    if not transcript.segments:
        return "(No spoken dialogue recorded in this meeting)"

    lines: list[str] = []
    for seg in transcript.segments:
        time_tag = format_timestamp_ms(seg.start_ms)
        clean_text = seg.text.strip()
        if clean_text:
            lines.append(f"{time_tag} {clean_text}")

    return "\n".join(lines)


def _resolve_target_language(
    explicit_language: str | None,
    transcript: PersistedTranscript,
) -> str:
    """Determine output language name/code for summarization prompt."""
    if explicit_language:
        lang = explicit_language.lower().strip()
    elif transcript.metadata.dominant_language:
        lang = transcript.metadata.dominant_language.lower().strip()
    else:
        lang = "en"

    # Human-friendly language hints
    language_names = {
        "en": "English (en)",
        "ru": "Russian (ru)",
        "uk": "Ukrainian (uk)",
        "de": "German (de)",
        "es": "Spanish (es)",
        "fr": "French (fr)",
    }
    return language_names.get(lang, lang)


class GeminiSummaryProvider:
    """Provider generating structured meeting summaries via Google Gemini API."""

    def __init__(
        self,
        config: GeminiConfig | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        """Initialize provider with configuration and optional HTTP client.

        Args:
            config: GeminiConfig with model, API key, and timeouts.
            client: Optional httpx.Client instance (useful for unit testing/mocking).
        """
        self._config = config or GeminiConfig()
        self._client = client

    def __repr__(self) -> str:
        return f"GeminiSummaryProvider(config={self._config!r})"

    @property
    def config(self) -> GeminiConfig:
        """Return provider configuration."""
        return self._config

    def generate_summary(
        self,
        transcript: PersistedTranscript,
        language: str | None = None,
    ) -> MeetingSummary:
        """Generate structured meeting summary using Google Gemini.

        Args:
            transcript: Persisted meeting transcript.
            language: Optional target language override.

        Returns:
            Structured MeetingSummary instance.

        Raises:
            SummaryConfigError: When no API key is available.
            SummaryAuthError: When API key is invalid or unauthorized.
            SummaryQuotaError: When rate limit or quota is exceeded.
            SummaryNetworkError: On connection errors, timeouts, or 5xx responses.
            SummaryParsingError: When model response does not conform to the schema.
        """
        api_key = self._config.resolve_api_key()
        if not api_key:
            raise SummaryConfigError(
                "No Gemini API key configured. Set the GEMINI_API_KEY environment variable "
                "or configure your API key in Settings."
            )

        target_lang = _resolve_target_language(language, transcript)
        transcript_text = _build_transcript_text(transcript)

        prompt = (
            f"You are an executive meeting assistant. Analyze the following meeting transcript and provide "
            f"a comprehensive, structured summary in {target_lang}.\n\n"
            f"Guidelines:\n"
            f"- Write all summary sections strictly in {target_lang}.\n"
            f"- Base your summary exclusively on the provided transcript without inventing external facts.\n"
            f"- Preserve domain-specific technical terminology, proper nouns, and decisions.\n"
            f"- Identify concrete decisions made, specific action items (with assignees if mentioned), "
            f"unresolved open questions, and scheduled follow-ups.\n\n"
            f"Transcript:\n{transcript_text}"
        )

        request_body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self._config.temperature,
                "responseMimeType": "application/json",
                "responseSchema": {
                    "type": "OBJECT",
                    "properties": {
                        "summary": {
                            "type": "STRING",
                            "description": "Comprehensive narrative summary of the meeting",
                        },
                        "decisions": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                            "description": "Concrete decisions agreed upon during the discussion",
                        },
                        "action_items": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                            "description": "Specific action items or tasks with owners if mentioned",
                        },
                        "open_questions": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                            "description": "Unresolved questions or topics requiring further clarification",
                        },
                        "follow_ups": {
                            "type": "ARRAY",
                            "items": {"type": "STRING"},
                            "description": "Next meetings or follow-up milestones",
                        },
                    },
                    "required": [
                        "summary",
                        "decisions",
                        "action_items",
                        "open_questions",
                        "follow_ups",
                    ],
                },
            },
        }

        url = GEMINI_API_URL_TEMPLATE.format(model=self._config.model)
        headers = {
            "x-goog-api-key": api_key,
            "Content-Type": "application/json",
        }

        logger.info(
            "Requesting summary from Gemini model '%s' (language: %s)",
            self._config.model,
            target_lang,
        )

        client = self._client or httpx.Client(timeout=self._config.timeout_sec)
        try:
            response = client.post(url, json=request_body, headers=headers)
            self._check_http_status(response)
            response_json = response.json()
        except httpx.TimeoutException as exc:
            raise SummaryNetworkError(
                f"Gemini API request timed out after {self._config.timeout_sec}s."
            ) from exc
        except httpx.ConnectError as exc:
            raise SummaryNetworkError(f"Failed to connect to Gemini API: {exc}") from exc
        except httpx.RequestError as exc:
            raise SummaryNetworkError(
                f"Network error communicating with Gemini API: {exc}"
            ) from exc
        finally:
            if self._client is None:
                client.close()

        return self._parse_gemini_response(response_json)

    def _check_http_status(self, response: httpx.Response) -> None:
        """Map HTTP status codes to typed summary exceptions."""
        if 200 <= response.status_code < 300:
            return

        status = response.status_code
        error_msg = f"HTTP {status}"
        try:
            err_data = response.json()
            if isinstance(err_data, dict) and "error" in err_data:
                error_msg = err_data["error"].get("message", error_msg)
        except (json.JSONDecodeError, ValueError, TypeError):
            logger.debug("Non-JSON error response from Gemini: %s", response.text)

        if status in (401, 403):
            raise SummaryAuthError(f"Gemini API authentication failed: {error_msg}")
        if status == 429:
            raise SummaryQuotaError(f"Gemini API quota or rate limit exceeded: {error_msg}")
        if status >= 500:
            raise SummaryNetworkError(f"Gemini API server error ({status}): {error_msg}")

        raise SummaryError(f"Gemini API error ({status}): {error_msg}")

    def _parse_gemini_response(self, data: dict[str, Any]) -> MeetingSummary:
        """Parse candidates response into MeetingSummary domain model."""
        candidates = data.get("candidates", [])
        if not candidates:
            raise SummaryParsingError("Gemini returned an empty response with no candidates.")

        candidate = candidates[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        if not parts or not isinstance(parts[0], dict) or "text" not in parts[0]:
            raise SummaryParsingError("Gemini response missing text parts in candidate.")

        raw_text = parts[0]["text"].strip()

        # Handle possible markdown code block wrapping
        if raw_text.startswith("```"):
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

        try:
            parsed = json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise SummaryParsingError(f"Failed to parse model output as JSON: {exc}") from exc

        if not isinstance(parsed, dict):
            raise SummaryParsingError("Parsed model output is not a JSON object.")

        return MeetingSummary(
            summary=str(parsed.get("summary", "")).strip(),
            decisions=tuple(str(d).strip() for d in parsed.get("decisions", []) if str(d).strip()),
            action_items=tuple(
                str(a).strip() for a in parsed.get("action_items", []) if str(a).strip()
            ),
            open_questions=tuple(
                str(q).strip() for q in parsed.get("open_questions", []) if str(q).strip()
            ),
            follow_ups=tuple(
                str(f).strip() for f in parsed.get("follow_ups", []) if str(f).strip()
            ),
            provider="gemini",
            model=self._config.model,
        )
