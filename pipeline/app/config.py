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

    openai_model_daily: str = "gpt-5.6-luna"     # short generation & longform stage-1 (cheap model)
    openai_model_longform: str = "gpt-5.6-terra"
    gemini_model: str = "gemini-3.5-flash"

    # --- Research Agent (report format) — see docs/tech-report/05-detailed-design/10 ---
    research_planner_model: str = "gpt-5.6-sol"    # planner/critic (highest-judgement roles)
    research_model: str = "gpt-5.6-terra"          # verifier/writer/localizer
    research_fast_model: str = "gpt-5.6-luna"      # query-refine/triage/extract/theme-select
    deep_research_provider: str = "openai"     # "openai" | "gemini" | "off"
    deep_research_model: str = "o4-mini-deep-research"
    research_budget_usd_default: float = 10.0  # hard cap per report
    research_max_loops: int = 2                # retrieve→gap loop ceiling
    research_max_fetches: int = 80             # per-run fetch ceiling
    research_wall_clock_min: int = 40          # per-run soft wall-clock (within task-timeout)
    semantic_scholar_api_key: str = ""         # optional; connectors fall back without it

    # --- Research Chat (admin-only chat; see docs/tech-report/05-detailed-design/11) ---
    chat_model: str = "gpt-5.6-sol"             # sparring + deep synthesize (highest judgement)
    chat_research_model: str = "gpt-5.6-terra"  # quick synthesize
    chat_fast_model: str = "gpt-5.6-luna"       # plan/select/gap/title/handoff-theme
    chat_budget_quick_usd: float = 0.7          # hard cap per quick research message
    chat_budget_deep_usd: float = 3.0           # hard cap per deep research message
    chat_max_fetches_quick: int = 6
    chat_max_fetches_deep: int = 14
    chat_history_max_messages: int = 40         # trim window sent to the LLM
    chat_wall_clock_quick_min: int = 3
    chat_wall_clock_deep_min: int = 10

    # --- Observability (LangSmith SaaS tracing; see app/utils/observability.py) ---
    # The SDK reads the same LANGSMITH_* env vars directly, so env stays the one
    # source. Tracing needs both the flag and a key — production sets both iff the
    # optional langsmith-api-key secret exists.
    langsmith_tracing: bool = False
    langsmith_api_key: str = ""
    langsmith_project: str = "trend-news-generator"

    # threads-access-token secret name; the refresh job adds new versions.
    threads_token_secret_name: str = "threads-access-token"


@lru_cache
def get_settings() -> Settings:
    return Settings()
