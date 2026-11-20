from __future__ import annotations


class UploaderError(Exception):
    pass


class ConfigError(UploaderError):
    pass


class CredentialsError(UploaderError):
    pass


class ScopeError(CredentialsError):
    pass


class OAuthError(CredentialsError):
    pass


class IdentityError(UploaderError):
    pass


class WrongChannelError(IdentityError):
    pass


class ValidationError(UploaderError):
    pass


class SafetyError(UploaderError):
    pass


class DuplicateUploadError(UploaderError):
    def __init__(self, message: str, status: str | None = None) -> None:
        super().__init__(message)
        self.status = status


class UploadStateUnknown(UploaderError):
    pass


class ApiError(UploaderError):
    def __init__(
        self,
        status: int | None,
        reason: str,
        message: str,
        retryable: bool = False,
        retry_after: float | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.reason = reason
        self.message = message
        self.retryable = retryable
        self.retry_after = retry_after

    def __str__(self) -> str:
        prefix = f"HTTP {self.status} " if self.status is not None else ""
        detail = f"{self.reason}: {self.message}".strip(": ")
        return f"{prefix}{detail}".strip()
