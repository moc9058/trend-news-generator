"""Hard budget control for a research run (design §4.1 budget column, §6.4).

The `Budget` wraps the run's `BudgetState` and is the single place LLM cost,
Deep-Research calls and fetches are counted. The harness checks `can_afford()` at
each phase boundary; when the remaining budget drops below a phase's minimum it
does NOT enter that phase — it graceful-degrades (proceed to write with what it
has, marking unresolved RQs as open) rather than silently truncating.
"""

from app.generators.openai_client import cost_usd
from app.research.schemas import BudgetState, Phase

# Minimum USD that must remain to ENTER a phase (rough per-phase floor from the
# ~$10 budget breakdown in §4.1). Phases not listed have no floor.
PHASE_MIN_USD: dict[Phase, float] = {
    Phase.R2: 0.30,
    Phase.R3: 0.40,
    Phase.R4: 0.50,
    Phase.R5: 0.50,
    Phase.R6: 0.10,
    Phase.R7: 0.50,
    Phase.R7L: 0.50,
    Phase.R8: 0.30,
    Phase.R9: 0.00,
}

# Deep Research auto-skips below this remaining budget (§4.3).
DEEP_RESEARCH_MIN_USD = 3.0


class Budget:
    def __init__(self, state: BudgetState):
        self.state = state

    # -- charging -------------------------------------------------------------
    def charge_llm(self, model: str, tokens_in: int, tokens_out: int) -> float:
        """Add one LLM call's cost (priced by openai_client.PRICES) and return it."""
        usd = cost_usd(model, tokens_in, tokens_out)
        self.state.usdSpent = round(self.state.usdSpent + usd, 6)
        return usd

    def charge_usd(self, usd: float) -> None:
        """Add a flat cost (e.g. a Deep Research call priced per-run)."""
        self.state.usdSpent = round(self.state.usdSpent + usd, 6)

    def note_fetch(self, n: int = 1) -> None:
        self.state.fetchUsed += n

    def note_deep_research(self) -> None:
        self.state.drCallsUsed += 1

    # -- queries --------------------------------------------------------------
    def remaining(self) -> float:
        return round(max(0.0, self.state.usdCap - self.state.usdSpent), 6)

    def can_afford(self, phase: Phase) -> bool:
        """Is there enough budget left to ENTER `phase`?"""
        return self.remaining() >= PHASE_MIN_USD.get(phase, 0.0)

    def exhausted(self) -> bool:
        """No budget left to enter even the cheapest remaining phase."""
        return self.remaining() <= 0.0

    def fetch_available(self) -> bool:
        return self.state.fetchUsed < self.state.fetchCap

    def deep_research_allowed(self) -> bool:
        """DR is a one-shot assist and auto-skips when the budget is tight."""
        return self.state.drCallsUsed < 1 and self.remaining() >= DEEP_RESEARCH_MIN_USD
