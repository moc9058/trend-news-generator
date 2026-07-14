"""R8 machine citation check (design §8.1 引用妥当性).

v1: every evidenceId the draft cites must exist in the run's evidence set — a
hallucinated citation (a footnote pointing at nothing) is detected here and its
sentence is deleted/demoted by the critic. The stronger check — that a quoted
string literally appears in the GCS snapshot addressed by its sha256 (design §6.2)
— runs in staging where snapshots are readable; the sha256 is already recorded on
every EvidenceRecord for it.
"""

from app.research.schemas import AuditFinding, AuditReport


def verify_quotes(draft, evidence) -> AuditReport:
    ev_ids = {e.evidenceId for e in (evidence or [])}
    refs = list(draft.references) if draft else []
    findings: list[AuditFinding] = []
    ok = 0
    for ref in refs:
        if ref in ev_ids:
            ok += 1
        else:
            findings.append(AuditFinding(
                kind="hallucinated_citation", location=f"reference {ref}",
                detail="cited evidenceId not present in run evidence", action="delete"))
    rate = (ok / len(refs)) if refs else 1.0
    return AuditReport(citeCheckPassRate=round(rate, 4), findings=findings,
                       passed=(rate >= 0.98 and not findings))
