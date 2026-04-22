class FlexomError(Exception):
    """Base exception for the Flexom client."""


class FlexomAuthError(FlexomError):
    """Authentication failed (bad credentials, expired token, missing login)."""


class FlexomNetworkError(FlexomError):
    """Network or HTTP-level error."""


class FlexomRateLimitError(FlexomError):
    """Rate-limited by the Flexom API (HTTP 429)."""
