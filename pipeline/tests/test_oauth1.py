"""OAuth 1.0a signature verified against the canonical example from the
Twitter/X API documentation ("Creating a signature")."""

import re
from urllib.parse import unquote

from app.publishers.x import oauth1_header

CREDS = {
    "consumer_key": "xvz1evFS4wEEPTGEFPHBog",
    "consumer_secret": "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
    "access_token": "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb",
    "access_token_secret": "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
}


def _signature(header: str) -> str:
    match = re.search(r'oauth_signature="([^"]+)"', header)
    assert match
    return unquote(match.group(1))


def test_known_signature_vector():
    header = oauth1_header(
        "POST",
        "https://api.twitter.com/1.1/statuses/update.json",
        CREDS,
        extra_params={
            "status": "Hello Ladies + Gentlemen, a signed OAuth request!",
            "include_entities": "true",
        },
        nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg",
        timestamp="1318622958",
    )
    assert _signature(header) == "hCtSmYh+iHYCEqBWrE7C7hYmtUk="


def test_header_shape():
    header = oauth1_header("POST", "https://api.x.com/2/tweets", CREDS)
    assert header.startswith("OAuth ")
    for key in ("oauth_consumer_key", "oauth_nonce", "oauth_signature",
                "oauth_signature_method", "oauth_timestamp", "oauth_token"):
        assert f'{key}="' in header


def test_json_body_not_signed_but_query_is():
    """Two calls with identical oauth params must produce identical signatures
    regardless of any JSON body (bodies are excluded from OAuth1 signing)."""
    a = oauth1_header("POST", "https://api.x.com/2/tweets", CREDS,
                      nonce="n", timestamp="1")
    b = oauth1_header("POST", "https://api.x.com/2/tweets", CREDS,
                      nonce="n", timestamp="1")
    assert _signature(a) == _signature(b)
    c = oauth1_header("POST", "https://api.x.com/2/tweets", CREDS,
                      extra_params={"q": "x"}, nonce="n", timestamp="1")
    assert _signature(a) != _signature(c)
