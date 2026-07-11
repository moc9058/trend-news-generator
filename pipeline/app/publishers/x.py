"""X (Twitter) API v2 publisher with hand-rolled OAuth 1.0a user-context signing.

Posts are $0.015 each and URL-bearing posts are $0.20 — the publish
orchestrator decides whether a URL is included, not this module.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import quote, urlsplit

import httpx

from app.config import get_settings
from app.utils.retry import api_retry
from app.utils.logging import get_logger

log = get_logger(__name__)

TWEETS_URL = "https://api.x.com/2/tweets"
MEDIA_UPLOAD_URL = "https://api.x.com/2/media/upload"


def _pct(value: str) -> str:
    return quote(value, safe="~-._")


def oauth1_header(
    method: str,
    url: str,
    credentials: dict,
    *,
    extra_params: dict | None = None,
    nonce: str | None = None,
    timestamp: str | None = None,
) -> str:
    """Build an OAuth 1.0a Authorization header (HMAC-SHA1).

    extra_params: request query/form params that must be signed (NOT JSON or
    multipart bodies, which are excluded per spec).
    """
    oauth_params = {
        "oauth_consumer_key": credentials["consumer_key"],
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": credentials["access_token"],
        "oauth_version": "1.0",
    }
    sign_params = {**oauth_params, **(extra_params or {})}
    encoded = sorted((_pct(k), _pct(str(v))) for k, v in sign_params.items())
    param_string = "&".join(f"{k}={v}" for k, v in encoded)
    base_url = url.split("?")[0]
    scheme, netloc, path, _, _ = urlsplit(base_url)
    normalized_url = f"{scheme.lower()}://{netloc.lower()}{path}"
    base_string = f"{method.upper()}&{_pct(normalized_url)}&{_pct(param_string)}"
    signing_key = f"{_pct(credentials['consumer_secret'])}&{_pct(credentials['access_token_secret'])}"
    digest = hmac.new(signing_key.encode(), base_string.encode(), hashlib.sha1).digest()
    oauth_params["oauth_signature"] = base64.b64encode(digest).decode()
    header = ", ".join(
        f'{_pct(k)}="{_pct(v)}"' for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header}"


def _credentials() -> dict:
    return json.loads(get_settings().x_credentials)


@api_retry
def upload_media(data: bytes, mime: str, client: httpx.Client) -> str:
    """v2 chunkless media upload; returns media_id string."""
    creds = _credentials()
    headers = {"Authorization": oauth1_header("POST", MEDIA_UPLOAD_URL, creds)}
    resp = client.post(
        MEDIA_UPLOAD_URL,
        headers=headers,
        files={"media": ("image", data, mime)},
        data={"media_category": "tweet_image"},
    )
    resp.raise_for_status()
    payload = resp.json()
    return str(payload.get("data", payload).get("id"))


@api_retry
def post_tweet(
    text: str,
    client: httpx.Client,
    *,
    reply_to: str = "",
    media_ids: list[str] | None = None,
) -> str:
    creds = _credentials()
    body: dict = {"text": text}
    if reply_to:
        body["reply"] = {"in_reply_to_tweet_id": reply_to}
    if media_ids:
        body["media"] = {"media_ids": media_ids}
    headers = {
        "Authorization": oauth1_header("POST", TWEETS_URL, creds),
        "Content-Type": "application/json",
    }
    resp = client.post(TWEETS_URL, headers=headers, json=body)
    resp.raise_for_status()
    tweet_id = resp.json()["data"]["id"]
    log.info("tweet posted", extra={"fields": {"id": tweet_id}})
    return tweet_id


def publish(
    text: str,
    *,
    thread_parts: list[str] | None = None,
    image: tuple[bytes, str] | None = None,
) -> str:
    """Post a tweet or reply chain; returns the first tweet id."""
    with httpx.Client(timeout=30) as client:
        media_ids = None
        if image:
            media_ids = [upload_media(image[0], image[1], client)]
        parts = thread_parts if thread_parts else [text]
        first_id = ""
        prev_id = ""
        for i, part in enumerate(parts):
            tweet_id = post_tweet(
                part, client,
                reply_to=prev_id,
                media_ids=media_ids if i == 0 else None,
            )
            prev_id = tweet_id
            if not first_id:
                first_id = tweet_id
        return first_id
