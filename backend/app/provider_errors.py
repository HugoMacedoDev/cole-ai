"""Provider-neutral error type shared by answer providers."""


class AnswerProviderError(RuntimeError):
    """Raised when the configured answer provider cannot produce an answer."""
