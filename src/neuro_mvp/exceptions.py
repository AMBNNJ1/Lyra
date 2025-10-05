"""Custom exceptions for the Neuro MVP system."""


class NeuroMVPError(Exception):
    """Base exception for Neuro MVP system."""
    pass


class ConfigurationError(NeuroMVPError):
    """Raised when configuration is invalid or missing."""
    pass


class MemoryError(NeuroMVPError):
    """Raised when memory operations fail."""
    pass


class LLMError(NeuroMVPError):
    """Raised when LLM operations fail."""
    pass


class TTSError(NeuroMVPError):
    """Raised when TTS operations fail."""
    pass


class AuthenticationError(NeuroMVPError):
    """Raised when authentication fails."""
    pass


class WebSessionError(NeuroMVPError):
    """Raised when web session operations fail."""
    pass
