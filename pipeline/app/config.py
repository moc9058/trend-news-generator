from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    project_id: str = "trend-news-generator"
    region: str = "asia-northeast1"
    timezone: str = "Asia/Tokyo"
    gcs_bucket: str = "trend-news-generator-media"
    pipeline_service_account: str = ""  # pipeline-sa email; required for GCS signed URLs

    # Injected via --set-secrets (Cloud Run) or .env (local).
    openai_api_key: str = ""
    gemini_api_key: str = ""
    # JSON: {"consumer_key","consumer_secret","access_token","access_token_secret"}
    x_credentials: str = ""
    threads_access_token: str = ""
    threads_user_id: str = ""
    notion_api_key: str = ""
    # optional: IEEE Xplore Metadata Search API (free key, 200 calls/day)
    ieee_api_key: str = ""
    # Meta app credentials, only needed by the token refresh job.
    threads_app_secret: str = ""

    openai_model_daily: str = "gpt-5.4-mini"
    openai_model_longform: str = "gpt-5.5"
    gemini_model: str = "gemini-3-flash"

    # threads-access-token secret name; the refresh job adds new versions.
    threads_token_secret_name: str = "threads-access-token"


@lru_cache
def get_settings() -> Settings:
    return Settings()
