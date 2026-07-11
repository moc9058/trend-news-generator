"""Shared retry policy for outbound API calls: 3 attempts, exponential backoff,
retrying only on 429/5xx and transport errors. 4xx (other than 429) is permanent."""

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)


class PermanentPublishError(Exception):
    """Non-retryable failure; surfaces as channel status=failed in the admin UI."""


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return isinstance(exc, (httpx.TransportError, httpx.TimeoutException))


api_retry = retry(
    retry=retry_if_exception(_is_retryable),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=2, min=2, max=30),
    reraise=True,
)
