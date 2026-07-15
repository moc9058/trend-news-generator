"""LangSmith wiring: gated on env, inert by default, never fatal (M0-a)."""

import os

import pytest

from app.config import get_settings
from app.generators import openai_client
from app.utils import observability


def _is_wrapped(client) -> bool:
    """True when langsmith has patched the client's chat.completions.create.

    `wrap_openai` patches the instance in place, and `functools.wraps` copies the
    SDK's metadata onto the wrapper — so `__wrapped__`, `__module__` and the
    signature are all identical before and after, and cannot discriminate.
    What does change: `create` becomes an instance attribute whose code object
    lives in langsmith's wrappers module (verified against langsmith 0.10.4).
    """
    create = client.chat.completions.create
    return "langsmith" in create.__code__.co_filename


@pytest.fixture(autouse=True)
def _clear_caches():
    for cache in (get_settings, openai_client._client, observability.ls_client):
        cache.cache_clear()
    yield
    for cache in (get_settings, openai_client._client, observability.ls_client):
        cache.cache_clear()


def _enable(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_pt_test_key")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for cache in (get_settings, openai_client._client, observability.ls_client):
        cache.cache_clear()


def test_openai_client_plain_when_langsmith_unset(monkeypatch):
    # The autouse conftest fixture already forces tracing off.
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    get_settings.cache_clear()
    openai_client._client.cache_clear()

    assert observability.langsmith_enabled() is False
    assert _is_wrapped(openai_client._client()) is False


def test_openai_client_wrapped_when_langsmith_enabled(monkeypatch):
    _enable(monkeypatch)

    assert observability.langsmith_enabled() is True
    assert _is_wrapped(openai_client._client()) is True


def test_tracing_flag_alone_does_not_enable_without_key(monkeypatch):
    """Both halves are required — a flag with no key must stay inert."""
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    for cache in (get_settings, openai_client._client, observability.ls_client):
        cache.cache_clear()

    assert observability.langsmith_enabled() is False
    assert observability.ls_client() is None
    assert _is_wrapped(openai_client._client()) is False


def test_ls_client_exports_env_so_the_sdk_actually_traces(monkeypatch):
    """Regression: wrapping the client is not enough to produce traces.

    The SDK gates every trace on os.environ at call time and never reads
    `pipeline/.env` — which pydantic-settings loads into Settings only. Before the
    export in `_export_env()`, a .env-configured local run wrapped the client and
    then emitted nothing, while production (real env vars) traced fine. The unit
    tests all passed throughout, so only this assertion pins the behaviour.
    """
    from langsmith import utils as ls_utils

    from app.config import Settings

    # Config resolved from .env: Settings sees it, the process env does not.
    # The legacy LANGCHAIN_* namespace outranks LANGSMITH_* inside the SDK, so a
    # realistic .env-only setup must have none of them present.
    for name in ("LANGSMITH_TRACING", "LANGSMITH_API_KEY", "LANGCHAIN_TRACING_V2",
                 "LANGSMITH_TRACING_V2"):
        monkeypatch.delenv(name, raising=False)
    ls_utils.get_env_var.cache_clear()
    assert ls_utils.tracing_is_enabled() is False  # precondition: SDK sees nothing

    dotenv_settings = Settings(
        langsmith_tracing=True,
        langsmith_api_key="lsv2_pt_test_key",
        langsmith_project="proj",
        _env_file=None,
    )
    monkeypatch.setattr(observability, "get_settings", lambda: dotenv_settings)
    observability.ls_client.cache_clear()

    assert observability.ls_client() is not None
    assert ls_utils.tracing_is_enabled() is True
    assert os.environ["LANGSMITH_API_KEY"] == "lsv2_pt_test_key"
    assert os.environ["LANGSMITH_PROJECT"] == "proj"


def test_export_env_survives_a_poisoned_env_cache(monkeypatch):
    """The SDK lru_caches env reads; a stale "off" must not outlive the export."""
    from langsmith import utils as ls_utils

    from app.config import Settings

    for name in ("LANGSMITH_TRACING", "LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING_V2"):
        monkeypatch.delenv(name, raising=False)
    ls_utils.get_env_var.cache_clear()
    ls_utils.tracing_is_enabled()  # poison the cache with "off"

    dotenv_settings = Settings(
        langsmith_tracing=True,
        langsmith_api_key="lsv2_pt_test_key",
        langsmith_project="proj",
        _env_file=None,
    )
    monkeypatch.setattr(observability, "get_settings", lambda: dotenv_settings)
    observability.ls_client.cache_clear()
    observability.ls_client()

    assert ls_utils.tracing_is_enabled() is True


def test_flush_langsmith_noop_when_disabled():
    assert observability.langsmith_enabled() is False
    observability.flush_langsmith()  # must not raise, must not construct a client
    assert observability.ls_client() is None


def test_flush_langsmith_swallows_errors_when_enabled(monkeypatch):
    """A tracing fault must never propagate into a run."""
    _enable(monkeypatch)
    import langsmith

    class _Boom:
        def __init__(self, *a, **k):
            pass

        def flush(self):
            raise RuntimeError("langsmith is down")

    monkeypatch.setattr(langsmith, "Client", _Boom)
    observability.ls_client.cache_clear()
    observability.flush_langsmith()  # swallowed


def test_ls_client_returns_none_and_swallows_when_construction_fails(monkeypatch):
    _enable(monkeypatch)
    import langsmith

    def _boom(*a, **k):
        raise RuntimeError("bad key")

    monkeypatch.setattr(langsmith, "Client", _boom)
    observability.ls_client.cache_clear()
    assert observability.ls_client() is None
    # A client we could not build must degrade to an unwrapped one, not crash.
    openai_client._client.cache_clear()
    assert _is_wrapped(openai_client._client()) is False
