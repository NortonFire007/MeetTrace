"""Meeting summary package for MeetTrace.

Provides provider-neutral summary models, the SummaryProvider interface,
and the GeminiSummaryProvider implementation.
"""

from __future__ import annotations

from meettrace.summary.gemini import GeminiConfig, GeminiSummaryProvider
from meettrace.summary.models import (
    MeetingSummary,
    SummaryAuthError,
    SummaryConfigError,
    SummaryError,
    SummaryNetworkError,
    SummaryParsingError,
    SummaryQuotaError,
)
from meettrace.summary.protocol import SummaryProvider

__all__ = [
    "GeminiConfig",
    "GeminiSummaryProvider",
    "MeetingSummary",
    "SummaryAuthError",
    "SummaryConfigError",
    "SummaryError",
    "SummaryNetworkError",
    "SummaryParsingError",
    "SummaryProvider",
    "SummaryQuotaError",
]
