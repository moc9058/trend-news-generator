"""P5: research API (202/409/404), generate_report drain, cancel, select, DR."""

from types import SimpleNamespace

from fastapi.testclient import TestClient

import app.jobs.generate_report as gr
import app.main as main
import app.repo.research as rr_repo
import app.research.select as select_mod
import app.research.sources.deep_research as dr_mod
from app.research.budget import Budget
from app.research.context import RunContext
from app.research.harness import ResearchHarness
from app.research.schemas import BudgetState, ResearchRun, StrategyQuery
from app.research.sources.deep_research import DeepResearchConnector, parse_citations

client = TestClient(main.app)


# ---------- POST /api/research/runs ----------

def test_create_run_202(monkeypatch):
    captured = {}
    monkeypatch.setattr(main.research_repo, "create",
                        lambda run: (captured.update(run=run), "rr_1")[1])
    monkeypatch.setattr(main, "_trigger_job", lambda name: None)
    resp = client.post("/api/research/runs", json={"theme": "T", "requestedBy": "u", "budgetUsd": 50})
    assert resp.status_code == 202 and resp.json() == {"runId": "rr_1", "accepted": True}
    assert captured["run"].theme == "T" and captured["run"].status == "queued"
    assert captured["run"].budget.usdCap == 30.0  # capped at 30


def test_create_run_empty_body_does_not_422(monkeypatch):
    monkeypatch.setattr(main.research_repo, "create", lambda run: "rr_2")
    monkeypatch.setattr(main, "_trigger_job", lambda name: None)
    assert client.post("/api/research/runs", json={}).status_code == 202


def test_create_run_202_even_if_trigger_fails(monkeypatch):
    monkeypatch.setattr(main.research_repo, "create", lambda run: "rr_3")

    def boom(name):
        raise RuntimeError("run.invoker missing")
    monkeypatch.setattr(main, "_trigger_job", boom)
    assert client.post("/api/research/runs", json={"theme": "T"}).status_code == 202


# ---------- cancel ----------

def test_cancel_200(monkeypatch):
    monkeypatch.setattr(main.research_repo, "request_cancel", lambda rid: True)
    resp = client.post("/api/research/runs/x/cancel")
    assert resp.status_code == 200 and resp.json()["status"] == "cancel_requested"


def test_cancel_404(monkeypatch):
    monkeypatch.setattr(main.research_repo, "request_cancel", lambda rid: False)
    monkeypatch.setattr(main.research_repo, "get", lambda rid: None)
    assert client.post("/api/research/runs/x/cancel").status_code == 404


def test_cancel_409_when_terminal(monkeypatch):
    monkeypatch.setattr(main.research_repo, "request_cancel", lambda rid: False)
    monkeypatch.setattr(main.research_repo, "get",
                        lambda rid: ResearchRun(id="x", status="completed"))
    assert client.post("/api/research/runs/x/cancel").status_code == 409


# ---------- approve-plan ----------

def test_approve_plan_404(monkeypatch):
    monkeypatch.setattr(main.research_repo, "get", lambda rid: None)
    assert client.post("/api/research/runs/x/approve-plan", json={}).status_code == 404


def test_approve_plan_409_wrong_state(monkeypatch):
    monkeypatch.setattr(main.research_repo, "get",
                        lambda rid: ResearchRun(id="x", status="running"))
    assert client.post("/api/research/runs/x/approve-plan", json={}).status_code == 409


def test_approve_plan_200_requeues(monkeypatch):
    updates = {}
    monkeypatch.setattr(main.research_repo, "get",
                        lambda rid: ResearchRun(id="x", status="awaiting_plan_approval"))
    monkeypatch.setattr(main.research_repo, "update_fields", lambda rid, f: updates.update(f))
    monkeypatch.setattr(main, "_trigger_job", lambda name: None)
    resp = client.post("/api/research/runs/x/approve-plan", json={"approvedBy": "a"})
    assert resp.status_code == 200
    assert updates["planApproved"] is True and updates["status"] == "queued"


def test_generate_report_job_name_mapping():
    assert "generate_report" in main.JOB_MODULES
    assert main._cloud_run_job_name("generate_report") == "job-generate-report"


# ---------- generate_report job drains the queue ----------

def test_generate_report_drains_queue(monkeypatch):
    queue = [ResearchRun(id="r1"), ResearchRun(id="r2")]
    monkeypatch.setattr(gr.repo, "claim_next", lambda worker: queue.pop(0) if queue else None)
    ran = []
    monkeypatch.setattr(gr.ResearchHarness, "run", lambda self, rid: ran.append(rid))
    gr.main()
    assert ran == ["r1", "r2"]


# ---------- harness honours cancel (resume-adjacent) ----------

def test_harness_honours_cancel(monkeypatch):
    run = ResearchRun(id="rrc", status="running", phase="R0",
                      cancelRequested=True, budget=BudgetState(usdCap=10))
    store = {"rrc": run}
    monkeypatch.setattr(rr_repo, "get", lambda rid: store.get(rid))
    monkeypatch.setattr(rr_repo, "set_status",
                        lambda rid, status, **k: setattr(store[rid], "status", status))
    monkeypatch.setattr(rr_repo, "append_event", lambda rid, ev: None)
    harness = ResearchHarness(ctx_factory=lambda r: RunContext(run=r, budget=Budget(r.budget)))
    harness.run("rrc")
    assert store["rrc"].status == "cancelled"


# ---------- auto theme selection fallback ----------

def test_select_theme_fallback_without_items(monkeypatch):
    monkeypatch.setattr(select_mod.configs, "enabled_categories",
                        lambda: [SimpleNamespace(slug="science-technology", name="Science & Tech")])
    monkeypatch.setattr(select_mod.items, "recent_for_category", lambda slug, hours, limit: [])
    ctx = SimpleNamespace(run=SimpleNamespace(id="rr1"), budget=None)
    theme, cat = select_mod.select_theme(ctx)
    assert cat == "science-technology" and "Science & Tech" in theme


# ---------- deep research (flag-gated) ----------

def test_deep_research_parse_citations_dedups():
    resp = {"output": [{"content": [{"annotations": [
        {"type": "url_citation", "url": "https://a.go.jp/1", "title": "Doc A"},
        {"type": "other_annotation"},
        {"type": "url_citation", "url": "https://a.go.jp/1"}]}]}]}
    hits = parse_citations(resp)
    assert len(hits) == 1
    assert hits[0].deepResearchAssisted is True and hits[0].connector == "deep_research"


def test_deep_research_skips_when_provider_off(monkeypatch):
    monkeypatch.setattr(dr_mod, "get_settings",
                        lambda: SimpleNamespace(deep_research_provider="off"))
    assert DeepResearchConnector().search(StrategyQuery(rqId="rq1", query="x")) == []
