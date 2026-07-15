"""Thread-safety of everything M2's fan-out workers share (plan §5.4).

The graph runs workers on real threads (max_concurrency), and the shared mutable
objects are the run's Budget, the Fetcher's politeness state, and each grounded
connector's genai client. Each test here races real threads and asserts an EXACT
outcome — a lost update under the GIL is rare, not impossible, and "usually
passes" is precisely the failure mode these locks exist to remove.
"""

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.research.budget import Budget
from app.research.fetch.fetcher import Fetcher
from app.research.graph.state import (
    RESET,
    append_or_reset,
    merge_budget,
    merge_hit_rqs,
    merge_hits,
)
from app.research.schemas import BudgetState, SourceHit, StrategyQuery


@pytest.fixture(autouse=True)
def _aggressive_thread_switching():
    """Shrink the GIL switch interval so the races these tests witness actually
    interleave. At the default 5ms a whole read-modify-write often fits in one
    quantum and an unlocked mutant passes — which is exactly the false comfort
    this suite exists to remove (verified: without this, removing the Budget
    lock still passed)."""
    prev = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    yield
    sys.setswitchinterval(prev)



# ---- Budget ------------------------------------------------------------------

def test_budget_try_note_fetch_atomic_under_threads():
    """cap=10, 32 racing claimants -> exactly 10 succeed, counter lands on 10."""
    budget = Budget(BudgetState(usdCap=10.0, fetchCap=10))
    barrier = threading.Barrier(32)
    results = []
    lock = threading.Lock()

    def claim():
        barrier.wait()  # maximise contention: everyone races the same instant
        ok = budget.try_note_fetch()
        with lock:
            results.append(ok)

    with ThreadPoolExecutor(max_workers=32) as pool:
        for _ in range(32):
            pool.submit(claim)

    assert sum(results) == 10
    assert budget.state.fetchUsed == 10


def test_budget_charge_concurrent_sum_exact():
    """100 racing charges must all land: usdSpent += x is read-modify-write, and
    an unlocked version loses updates (that IS the bug the lock prevents)."""
    budget = Budget(BudgetState(usdCap=100.0))
    barrier = threading.Barrier(20)

    def charge():
        barrier.wait()
        for _ in range(50):
            budget.charge_usd(0.01)

    with ThreadPoolExecutor(max_workers=20) as pool:
        for _ in range(20):
            pool.submit(charge)

    assert budget.state.usdSpent == pytest.approx(10.00)


def test_budget_charge_llm_concurrent_sum_exact():
    budget = Budget(BudgetState(usdCap=100.0))
    # gpt-5.6-luna = $1.00/$6.00 per 1M -> 1k in + 1k out = $0.007 per call
    with ThreadPoolExecutor(max_workers=16) as pool:
        for _ in range(50):
            pool.submit(budget.charge_llm, "gpt-5.6-luna", 1000, 1000)

    assert budget.state.usdSpent == pytest.approx(50 * 0.007)


def test_budget_snapshot_is_a_detached_copy():
    budget = Budget(BudgetState(usdCap=10.0))
    snap = budget.snapshot()
    budget.charge_usd(1.0)
    assert snap.usdSpent == 0.0
    assert budget.state.usdSpent == 1.0


# ---- Fetcher -----------------------------------------------------------------

class _GaugeClient:
    """Fake httpx client that measures concurrent GETs per host."""

    def __init__(self):
        self._lock = threading.Lock()
        self.active: dict[str, int] = {}
        self.peak: dict[str, int] = {}
        self.peak_total = 0
        self._active_total = 0

    def get(self, url, **kw):
        host = url.split("/")[2]
        with self._lock:
            self.active[host] = self.active.get(host, 0) + 1
            self._active_total += 1
            self.peak[host] = max(self.peak.get(host, 0), self.active[host])
            self.peak_total = max(self.peak_total, self._active_total)
        time.sleep(0.02)  # long enough for overlap to be observable
        with self._lock:
            self.active[host] -= 1
            self._active_total -= 1

        class _Resp:
            headers = {"content-type": "text/html"}
            content = b"<html>ok</html>"

            def __init__(self, u):
                self.url = u

            def raise_for_status(self):
                return None

        return _Resp(url)


def test_fetcher_same_host_serialized_cross_host_parallel():
    """The per-host lock is the 1 req/s politeness promise under concurrency:
    one host never sees overlapping requests, while different hosts overlap."""
    client = _GaugeClient()
    fetcher = Fetcher(client=client, resolve=lambda host: ["93.184.216.34"],
                      respect_robots=False, rps=0)

    urls = ([f"https://host-a.example/p{i}" for i in range(6)]
            + [f"https://host-b.example/p{i}" for i in range(6)])
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(fetcher.fetch, urls))

    assert all(r is not None for r in results)
    assert client.peak["host-a.example"] == 1, "same host must be serial"
    assert client.peak["host-b.example"] == 1
    assert client.peak_total > 1, "different hosts must actually run in parallel"


def test_fetcher_rate_gap_still_enforced_per_host():
    """With rps=1 and an injected clock, consecutive same-host fetches sleep the
    remaining gap — the pacing logic survives the locking rework unchanged."""
    now = {"t": 100.0}
    naps: list[float] = []

    def clock():
        return now["t"]

    def sleep(seconds):
        naps.append(seconds)
        now["t"] += seconds

    client = _GaugeClient()
    fetcher = Fetcher(client=client, resolve=lambda host: ["93.184.216.34"],
                      respect_robots=False, rps=1.0, sleep=sleep, clock=clock)

    fetcher.fetch("https://host-a.example/1")
    fetcher.fetch("https://host-a.example/2")  # same host, same instant -> must wait

    assert len(naps) == 1 and naps[0] == pytest.approx(1.0, abs=0.01)


def test_fetcher_domain_cap_exact_under_threads():
    """MAX_PER_DOMAIN(10) holds exactly when 20 workers race one host."""
    client = _GaugeClient()
    fetcher = Fetcher(client=client, resolve=lambda host: ["93.184.216.34"],
                      respect_robots=False, rps=0)

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(
            fetcher.fetch, [f"https://host-a.example/p{i}" for i in range(20)]))

    assert sum(1 for r in results if r is not None) == 10
    assert fetcher._domain_count["host-a.example"] == 10


# ---- grounded connector ---------------------------------------------------------

def test_grounded_connector_serializes_its_genai_client():
    """google-genai's sync client is not documented thread-safe, so one connector
    instance must never issue two generate_content calls at once (plan §5.4)."""
    from app.research.sources.web_grounded import WebGroundedConnector

    gauge = {"active": 0, "peak": 0}
    lock = threading.Lock()

    class _Models:
        def generate_content(self, **kw):
            with lock:
                gauge["active"] += 1
                gauge["peak"] = max(gauge["peak"], gauge["active"])
            time.sleep(0.02)
            with lock:
                gauge["active"] -= 1

            class _R:
                text = "[]"
                candidates = []

            return _R()

    class _Client:
        models = _Models()

    conn = WebGroundedConnector(client=_Client())
    q = StrategyQuery(rqId="rq1", query="q", language="ja")
    with ThreadPoolExecutor(max_workers=4) as pool:
        for _ in range(4):
            pool.submit(conn.search, q)

    assert gauge["peak"] == 1


# ---- reducers ---------------------------------------------------------------

def test_state_reducers_merge_worker_partials():
    """The reducer semantics the workers rely on, in one place."""
    # append_or_reset: accumulate, then RESET wipes for the next pass
    buf = append_or_reset([], ["a"])
    buf = append_or_reset(buf, ["b", "c"])
    assert buf == ["a", "b", "c"]
    assert append_or_reset(buf, RESET) == []

    # merge_hits: first write per urlHash wins across racing workers
    h1 = SourceHit(title="A", url="https://x.example/1", connector="kokkai")
    h2 = SourceHit(title="A'", url="https://x.example/1", connector="news")
    merged = merge_hits({"k1": h1}, {"k1": h2, "k2": h2})
    assert merged["k1"].connector == "kokkai" and "k2" in merged

    # merge_hit_rqs: sorted set-union per urlHash
    assert merge_hit_rqs({"k1": ["rq2"]}, {"k1": ["rq1", "rq2"]}) == {"k1": ["rq1", "rq2"]}

    # merge_budget: max-merge never loses a concurrent worker's spend
    a = BudgetState(usdCap=10.0, usdSpent=1.2, fetchUsed=3)
    b = BudgetState(usdCap=10.0, usdSpent=0.9, fetchUsed=5)
    m = merge_budget(a, b)
    assert (m.usdSpent, m.fetchUsed) == (1.2, 5)
