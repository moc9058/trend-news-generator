"""国会会議録検索システム API connector (design §4.3).

The NDL Diet-record API returns full speech text, so hits carry `contentText` and
R4 skips the fetch. Speech records are primary sources (発言そのもの).
Docs: https://kokkai.ndl.go.jp/api.html  (no key, free).
"""

from app.research.schemas import SourceHit, StrategyQuery
from app.research.sources.base import HttpConnector

API_URL = "https://kokkai.ndl.go.jp/api/speech"


def parse_speeches(payload: dict) -> list[SourceHit]:
    hits: list[SourceHit] = []
    for rec in payload.get("speechRecord", []) or []:
        speech = (rec.get("speech") or "").strip()
        url = rec.get("speechURL") or rec.get("meetingURL") or ""
        meeting = rec.get("nameOfMeeting") or ""
        house = rec.get("nameOfHouse") or ""
        session = rec.get("session")
        issue = rec.get("issue") or ""
        title_bits = [b for b in (f"第{session}回国会" if session else "", house, meeting, issue) if b]
        title = " ".join(title_bits) or (rec.get("speaker") or "国会会議録")
        if not url:
            continue
        speaker = rec.get("speaker") or ""
        hits.append(SourceHit(
            title=title,
            url=url,
            identifiers={k: v for k, v in {
                "kokkaiIssueId": rec.get("issueID"),
                "kokkaiSpeechId": rec.get("speechID"),
            }.items() if v},
            snippet=speech[:300],
            publishedAt=rec.get("date"),
            authors=[{"name": speaker, "role": rec.get("speakerRole") or "speaker",
                      "affiliation": rec.get("speakerGroup") or ""}] if speaker else [],
            venue="国会会議録",
            sourceType="parliamentary_record",
            tierHint="primary",
            connector="kokkai",
            contentText=speech,  # full text → R4 fetch skipped
        ))
    return hits


class KokkaiConnector(HttpConnector):
    name = "kokkai"

    def _search(self, q: StrategyQuery) -> list[SourceHit]:
        payload = self._get_json(API_URL, params={
            "any": q.query,
            "maximumRecords": min(max(q.maxResults, 1), 30),
            "recordPacking": "json",
        })
        return parse_speeches(payload)
