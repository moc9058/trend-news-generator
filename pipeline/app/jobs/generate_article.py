"""Article long-form generation (Mon 07:00 JST). Drafts only — publishing
happens after approval in the admin UI."""

from app.jobs.longform_runner import run_longform
from app.models import Format


def main() -> None:
    run_longform(Format.article)


if __name__ == "__main__":
    main()
