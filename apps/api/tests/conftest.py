"""What the suite pins so that a developer's machine cannot change what it measures.

`Settings` reads `.env`, which is how a laptop is configured — and the moment one of
those settings changes behaviour, the suite stops measuring the service and starts
measuring the machine it happens to be running on.

`OPEN_LOCAL_ACCESS=true` is exactly that. Turning it on to test a drawing through the
browser made sixteen tests fail, and every one of them was right to: they assert that
an unauthenticated request is refused, and with the switch on it is not. The tests were
not wrong and neither was the setting; what was missing was the line that keeps the two
apart.

So it is forced off for every test, and the one file that is *about* it turns it back on
for itself.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_open_local_access(monkeypatch):
    """Every test runs against a service that asks who you are.

    Two things are pinned, because the setting reaches a test by two routes.

    The **live** `settings` object is what the app reads, and patching it is what
    stops sixteen ownership tests from passing for the wrong reason.

    The **field default** is what a test constructs its own `Settings` from, and
    `.env` feeds that too — a laptop with the switch on turned
    `Settings(environment="production", …)` into a validation error inside a test that
    was asking about credentials and had never heard of this setting. Clearing the
    variable and the default together means a constructed `Settings` describes the
    service rather than the machine.
    """
    from app.config import Settings, settings

    monkeypatch.delenv("OPEN_LOCAL_ACCESS", raising=False)
    monkeypatch.setattr(settings, "open_local_access", False, raising=False)
    monkeypatch.setitem(
        Settings.model_config, "env_file", None
    )
