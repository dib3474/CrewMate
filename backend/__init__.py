"""CrewMate backend namespace.

담당자 B owns only ``backend/functions/agent_invoke`` and
``backend/functions/gap_event``.

``backend/shared/*`` (db / auth / state / response) is owned by 담당자 A and is
intentionally NOT implemented in this scope. Tests substitute it with the doubles in
``tests/mocks/shared_stubs.py``.
"""
