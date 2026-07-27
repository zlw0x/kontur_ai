"""Audit a real job's resource ledger and print an acceptance report.

Run after a genuine end-to-end order, against the database the API actually
wrote to:

    python scripts/verify_resource_ledger.py <job_id> \
        --database-url postgresql+psycopg://... [--expect-repair]

Read-only. It never writes to the ledger, because a ledger that needed fixing
up to pass its own audit would prove nothing.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

root = Path(__file__).parents[1]
sys.path.insert(0, str(root / "apps" / "api"))

from app.database import create_session_factory  # noqa: E402
from app.ledger.audit import Severity, audit_job_ledger, expected_repair_shape  # noqa: E402
from app.ledger.service import ResourceLedgerService  # noqa: E402

SEVERITY_MARK = {Severity.ERROR: "FAIL", Severity.WARNING: "WARN", Severity.INFO: "info"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("job_id")
    parser.add_argument("--database-url", required=True)
    parser.add_argument(
        "--expect-repair",
        action="store_true",
        help="the run deliberately provoked a repair; require the repair counters",
    )
    arguments = parser.parse_args()

    from uuid import UUID

    _, sessions = create_session_factory(arguments.database_url)
    events = ResourceLedgerService(sessions).events(UUID(arguments.job_id))
    if not events:
        print(f"no resource events recorded for job {arguments.job_id}", file=sys.stderr)
        return 2

    starts = [event.started_at for event in events]
    finishes = [event.finished_at for event in events if event.finished_at is not None]
    audit = audit_job_ledger(
        events,
        job_started_at=min(starts),
        job_finished_at=max(finishes) if finishes else None,
    )
    findings = list(audit.findings)
    if arguments.expect_repair:
        findings += expected_repair_shape(audit.counters)

    print(f"job:               {arguments.job_id}")
    print(f"events:            {audit.event_count}")
    print(f"billable seconds:  {audit.billable_seconds}")
    print(f"naive sum:         {audit.naive_sum_seconds}")
    print(f"double counted:    {audit.double_counted_seconds}")
    print(f"token coverage:    {_render(audit.token_coverage)}")
    print("counters:")
    for name, value in audit.counters.model_dump().items():
        print(f"  {name:<28} {value}")
    print("findings:")
    for finding in findings:
        print(f"  [{SEVERITY_MARK[finding.severity]}] {finding.code}: {finding.detail}")
    if not findings:
        print("  none")

    failed = [item for item in findings if item.severity is Severity.ERROR]
    print(f"\nresult: {'FAIL' if failed else 'PASS'}")
    return 1 if failed else 0


def _render(coverage: dict) -> str:
    return ", ".join(f"{key}={value}" for key, value in sorted(coverage.items())) or "none"


if __name__ == "__main__":
    raise SystemExit(main())
