"""Root pytest configuration for 담당자 B (Crew Composition Agent) scope.

Responsibilities
----------------
1. Ensure the workspace root is importable so the shared Agent contract module
   ``agent.schemas`` can be consumed by BOTH Lambda function packages
   (``backend/functions/agent_invoke`` and ``backend/functions/gap_event``).
   This mirrors the AWS Lambda Layer path during local dev/test. It is redundant with
   the ``pythonpath = ["."]`` setting in ``pyproject.toml`` and kept as a belt-and-
   suspenders measure for direct/ad-hoc invocations.
2. Register a Hypothesis settings profile suitable for the property-based tests defined
   by the spec: the per-run deadline is disabled to avoid flaky timeouts, while each
   test's own ``@settings(max_examples=100)`` still governs iteration counts.
3. Expose reusable fixtures backed by the shared stub modules in
   ``tests/mocks/shared_stubs.py``. 담당자 A's real ``backend/shared/*`` is not
   implemented here.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# --- Import path arrangement (Lambda Layer substitute) ----------------------------
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# --- Hypothesis profiles ----------------------------------------------------------
try:
    from hypothesis import HealthCheck, settings

    settings.register_profile(
        "default",
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    settings.register_profile(
        "ci",
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow],
    )
    settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "default"))
except ImportError:  # pragma: no cover - hypothesis is always present in the dev env
    pass

# --- Shared stub fixtures ---------------------------------------------------------
from tests.mocks import shared_stubs  # noqa: E402  (import after sys.path setup)


@pytest.fixture
def shared():
    """A fresh set of shared stubs (db / auth / state / response) for one test."""
    return shared_stubs.build_shared_stubs()


@pytest.fixture
def fake_db():
    """A fresh in-memory fake of 담당자 A's ``backend/shared/db`` helper."""
    return shared_stubs.FakeSharedDB()


class _InstalledShared:
    """Return value of the :func:`install_shared` fixture.

    Exposes the in-memory ``db`` (a :class:`~tests.mocks.shared_stubs.FakeSharedDB`) that
    담당자 B's code now reaches through the ``shared_gateway`` adapter. Auth is NOT stubbed
    here: 담당자 B's handlers consume the REAL ``backend.shared.auth.get_principal``, so tests
    drive authorization by passing claim-bearing API-Gateway events (see the per-file event
    builders), and ``backend.shared.responses`` stays real (handlers return proxy responses).
    """

    def __init__(self, db):
        self.db = db


@pytest.fixture
def install_shared(monkeypatch):
    """Redirect 담당자 B's high-level DB contract onto an in-memory ``FakeSharedDB``.

    Monkeypatches the ``backend.functions.agent_invoke.shared_gateway`` adapter's ten
    high-level functions onto a fresh ``FakeSharedDB`` (via
    :func:`tests.mocks.shared_stubs.install_fake_db`). Both Lambdas import the adapter as
    ``db``, so they share ONE fake instance and observe consistent state. The real
    ``backend.shared`` package is left intact (auth + responses stay real).

    Usage::

        def test_handler(install_shared):
            install_shared.db.add_work_request("REQ1", status="REQUESTED")
            ...
    """
    fake = shared_stubs.install_fake_db(monkeypatch)
    return _InstalledShared(db=fake)
