"""Error hierarchy for the unified AI gateway."""


class AIError(Exception):
    """Base error for all AI gateway errors."""


class AIAuthError(AIError):
    """Authentication failed. Check API keys or ADC setup.

    For Vertex AI: use Settings to complete browser OAuth or upload a
    service-account JSON file.
    For AI Studio: set ``GOOGLE_API_KEY``
    """


class AITimeoutError(AIError):
    """Request timed out."""


class AIQuotaError(AIError):
    """Rate limit or quota exceeded."""
