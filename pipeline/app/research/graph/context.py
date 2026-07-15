"""Runtime context — the live objects a node needs but a checkpoint must not hold.

Injected via `graph.stream(..., context=...)` and read as `runtime.context`. These
are deliberately OUTSIDE the state: an httpx-backed connector or a Fetcher is not
serialisable, and a Budget must stay a single shared object rather than a value
copied per superstep (see budget note below).
"""

from dataclasses import dataclass, field

from app.research.budget import Budget


@dataclass
class ResearchRuntimeContext:
    """Per-execution collaborators, rebuilt fresh on every resume.

    `budget` is the LIVE object: mid-phase `can_afford()` checks must see charges
    the current superstep has already made, which a per-superstep state value could
    not show. Each node also snapshots it into the `budget` channel on the way out,
    so a resumed run can reconcile spend (state.merge_budget). The registry must be
    built from this SAME Budget instance — deep_research's one-shot gate reads
    drCallsUsed off it (see sources/base.build_registry).
    """

    budget: Budget
    registry: dict = field(default_factory=dict)   # connector name -> connector
    fetcher: object = None
    run_id: str = ""
