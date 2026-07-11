"""Monthly research-report generation (1st 07:00 JST). Drafts only."""

from app.jobs.longform_runner import run_longform
from app.models import Cadence


def main() -> None:
    run_longform(Cadence.monthly)


if __name__ == "__main__":
    main()
