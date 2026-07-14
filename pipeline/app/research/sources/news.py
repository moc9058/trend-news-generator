"""News connector (design §4.3): grounded news search over reputable outlets.

v1 uses grounded search framed for quality reporting (secondary tier). The
existing RSS sources feed the daily/short pipeline; a GDELT DOC API leg for
historical news is a v1.5 refinement.
"""

from app.research.sources.web_grounded import GroundedConnector


class NewsConnector(GroundedConnector):
    name = "news"
    source_type = "quality_news"
    tier_hint = "secondary"
    default_site_filters: list[str] = []  # major outlets; grounding picks reputable
