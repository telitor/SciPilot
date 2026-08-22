"""Run read-only Supabase migration, schema and index checks.

The project must already be linked with ``supabase link``. This script never
calls ``db push``, ``db reset`` or ``migration repair``; remediation remains an
explicit operator decision after the report has been reviewed.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AUDITS = (
    ("migration history", ("migration", "list", "--linked")),
    (
        "schema warnings",
        ("db", "lint", "--linked", "--level", "warning", "--fail-on", "warning"),
    ),
    ("index usage", ("inspect", "db", "index-usage", "--linked")),
    ("unused indexes", ("inspect", "db", "unused-indexes", "--linked")),
    ("sequential scans", ("inspect", "db", "seq-scans", "--linked")),
)


def main() -> int:
    executable = shutil.which("supabase")
    if not executable:
        print(
            "Supabase CLI is not installed. Install it, authenticate, and link "
            "the project before running this read-only audit.",
            file=sys.stderr,
        )
        return 2

    failed: list[str] = []
    for label, arguments in AUDITS:
        print(f"\n[{label}]")
        completed = subprocess.run(
            [executable, *arguments],
            cwd=ROOT,
            check=False,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode != 0:
            failed.append(label)

    if failed:
        print("\nAudit reported warnings or errors: " + ", ".join(failed))
        return 1
    print("\nSupabase read-only audit completed without reported warnings.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
