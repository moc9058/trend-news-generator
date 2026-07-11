"""Weekly Threads token refresh (Mon 03:00 JST).

Long-lived tokens live 60 days; refreshing weekly gives an 8x margin. The new
token is added as a new Secret Manager version (old versions disabled) and the
expiry is written to settings/channelHealth so the admin dashboard can show a
countdown / red banner.
"""

from datetime import datetime, timedelta, timezone

from google.cloud import secretmanager

from app.config import get_settings
from app.models import Run
from app.publishers.threads import refresh_long_lived_token
from app.repo import configs, runs
from app.utils.logging import get_logger

log = get_logger(__name__)


def _rotate_secret(new_token: str) -> None:
    settings = get_settings()
    client = secretmanager.SecretManagerServiceClient()
    parent = f"projects/{settings.project_id}/secrets/{settings.threads_token_secret_name}"
    new_version = client.add_secret_version(
        request={"parent": parent, "payload": {"data": new_token.encode()}}
    )
    for version in client.list_secret_versions(request={"parent": parent}):
        if version.name != new_version.name and version.state.name == "ENABLED":
            client.disable_secret_version(request={"name": version.name})


def main() -> None:
    run_id = runs.start("refresh_threads_token")
    run = Run(jobType="refresh_threads_token")
    settings = get_settings()
    try:
        result = refresh_long_lived_token(settings.threads_access_token)
        new_token = result["access_token"]
        expires_in = int(result.get("expires_in", 60 * 24 * 3600))
        _rotate_secret(new_token)
        now = datetime.now(timezone.utc)
        configs.update_channel_health({
            "threadsLastRefreshAt": now,
            "threadsTokenExpiresAt": now + timedelta(seconds=expires_in),
            "threadsRefreshError": "",
        })
        log.info("threads token refreshed", extra={"fields": {"expires_in": expires_in}})
    except Exception as exc:
        run.ok = False
        run.errors.append(str(exc))
        configs.update_channel_health({"threadsRefreshError": str(exc)[:500]})
        log.error("threads token refresh failed", extra={"fields": {"error": str(exc)}})
    runs.finish(run_id, run)


if __name__ == "__main__":
    main()
