"""Government-documents connector (design §4.3).

v1: domain-restricted grounded search over go.jp / e-Gov / 国立公文書館 — official
primary sources. The e-Gov 法令 API direct lookup and 公文書館デジタルアーカイブ API
are v1.5 refinements (design §4.3 note); the grounded leg already reaches them.
"""

from app.research.sources.web_grounded import GroundedConnector


class GovDocsConnector(GroundedConnector):
    name = "gov_docs"
    source_type = "official_document"
    tier_hint = "primary"
    default_site_filters = ["go.jp", "e-gov.go.jp", "ndl.go.jp", "digital.archives.go.jp"]
