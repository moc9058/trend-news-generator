import pytest

from app.config import get_settings

# Env wins over the dotenv file in pydantic-settings, and the LangSmith SDK reads
# these names directly too — so forcing falsy values neutralises both layers.
_LANGSMITH_OFF = {
    "LANGSMITH_TRACING": "false",
    "LANGCHAIN_TRACING_V2": "false",
    "LANGSMITH_API_KEY": "",
    "LANGCHAIN_API_KEY": "",
    "LANGSMITH_PROJECT": "",
    "LANGSMITH_ENDPOINT": "",
}


@pytest.fixture(autouse=True)
def _no_langsmith_env(monkeypatch):
    """Keep a developer's own LangSmith config out of the suite.

    Deleting the vars is not enough: `Settings` also reads `pipeline/.env`, where
    a developer may have tracing enabled with a real key (docs 10 §6.5). Without
    this, `_client()` would wrap the OpenAI client and fire real background HTTP
    — breaking respx's strict assertions and leaking test payloads to the SaaS.
    Tests that want tracing on set these themselves and clear the caches.
    """
    for name, value in _LANGSMITH_OFF.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
