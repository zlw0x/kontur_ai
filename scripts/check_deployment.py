"""Is what is deployed built from what is checked out?

    python scripts/check_deployment.py
    python scripts/check_deployment.py --api http://localhost:8000 --web http://localhost:3000

Three images make up this service and **two of them were stale on the same day**, in
ways that looked like nothing at all:

- the engine image spoke CAD-IR 1.12 against a contract at 1.15, so every document was
  refused at its first line — a worker that registers, heartbeats and then fails. That is
  the third time (`P0-RUN-2026-08-09`, `-09b`, `-12`);
- the web image was built before accounts existed, so the studio had **no way to sign
  in**. Every visitor got the demonstration banner and downloads stayed disabled, and
  nothing anywhere said why. Nine days, and the only symptom was a page that looked
  finished.

Neither failure is a crash and neither is visible in a test suite, because a suite runs
against the working tree and the bug is that the deployment does not. This is the check
that compares them, and it is meant to be run after `docker compose up` and before
believing anything.

It asks each component what it *is* rather than what a tag says it is — the launcher's
rule (`what a component is beats what something upstream believes about it`), applied to
the deployment.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def contract_version() -> str:
    """The CAD-IR version this checkout defines, read without importing the package."""
    source = (ROOT / "packages" / "cad-ir" / "cad_ir" / "canonical.py").read_text("utf-8")
    found = re.search(r'^CAD_IR_VERSION = "([^"]+)"', source, re.MULTILINE)
    if not found:
        raise SystemExit("cannot find CAD_IR_VERSION in cad_ir/canonical.py")
    return found.group(1)


def fetch(url: str, timeout: int = 15) -> tuple[int, bytes]:
    request = urllib.request.Request(url)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as failure:
        return failure.code, failure.read()
    except Exception as error:  # noqa: BLE001 - a check reports, it does not raise
        return 0, str(error).encode()


def check_engine(image: str, expected: str) -> tuple[bool, str]:
    """What CAD-IR version is really inside the engine image."""
    try:
        answer = subprocess.run(
            ["docker", "run", "--rm", "--read-only", "--network", "none", "--tmpfs", "/tmp",
             image, "describe"],
            capture_output=True, timeout=300, check=False,
        )
    except FileNotFoundError:
        return False, "docker is not on PATH"
    except subprocess.TimeoutExpired:
        return False, f"{image} did not answer `describe` within 300s"
    if answer.returncode != 0:
        return False, f"{image} exited {answer.returncode}: {answer.stderr.decode()[:200]}"
    try:
        # stdout only. The image writes a cache warning to stderr under `--read-only`,
        # and merging the two is how a machine-readable answer stops being one.
        described = json.loads(answer.stdout)
    except json.JSONDecodeError:
        return False, f"{image} did not print JSON on stdout"
    got = described.get("cad_ir_version")
    if got != expected:
        return False, (
            f"{image} speaks CAD-IR {got}, this checkout defines {expected} — "
            "the image is stale and nothing is wrong with the code"
        )
    return True, f"{image} speaks CAD-IR {got}, {len(described.get('capabilities', {}))} capabilities"


def check_api(base: str) -> tuple[bool, str]:
    status, body = fetch(f"{base}/api/v1/health")
    if status != 200:
        return False, f"{base}/api/v1/health answered {status or 'nothing'}"
    # The endpoints accounts brought with them. An API that does not offer them is
    # older than P0-1 and cannot own an order.
    status, _ = fetch(f"{base}/api/v1/auth/me")
    if status not in (200, 401):
        return False, f"{base}/api/v1/auth/me answered {status}, so this API predates accounts"
    return True, f"{base} is up and offers /auth/me"


def check_web(base: str) -> tuple[bool, str]:
    """Does the *served bundle* know how to sign somebody in?

    This is the check that would have caught nine days of a studio nobody could use.
    It reads the scripts the page actually loads rather than the source on disk, because
    the source on disk was right the whole time.
    """
    status, page = fetch(base)
    if status != 200:
        return False, f"{base} answered {status or 'nothing'}"
    scripts = re.findall(rb'src="(/_next/[^"]+\.js)"', page)
    if not scripts:
        return False, f"{base} served no scripts; is this the app?"
    for script in scripts:
        code, body = fetch(base + script.decode())
        if code == 200 and b"auth/register" in body:
            return True, f"{base} serves a bundle that can sign somebody in"
    return False, (
        f"{base} serves {len(scripts)} scripts and none of them calls /auth/register — "
        "the web image was built before accounts existed, so the studio has no way in "
        "and every visitor sees the demonstration"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000")
    parser.add_argument("--web", default="http://localhost:3000")
    parser.add_argument("--engine-image", default="cad-ai/cad-worker:latest")
    parser.add_argument("--skip-engine", action="store_true",
                        help="when there is no docker daemon to ask")
    options = parser.parse_args()

    expected = contract_version()
    print(f"this checkout defines CAD-IR {expected}\n")

    results = [("api", check_api(options.api)), ("web", check_web(options.web))]
    if not options.skip_engine:
        results.insert(0, ("engine", check_engine(options.engine_image, expected)))

    worst = 0
    for name, (ok, detail) in results:
        print(f"  {'OK  ' if ok else 'STALE'}  {name:7} {detail}")
        worst = worst or (0 if ok else 1)
    print()
    if worst:
        print("Rebuild what is stale:")
        print("  docker build -f apps/cad-worker/Dockerfile -t cad-ai/cad-worker:latest .")
        print("  docker compose --env-file ../.env build api web && "
              "docker compose --env-file ../.env up -d")
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
