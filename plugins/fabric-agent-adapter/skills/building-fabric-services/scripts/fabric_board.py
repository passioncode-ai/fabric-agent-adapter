"""The project board connector, Python: the facade (fabric-project-comms/0.1).

Since 0.40.0 (FAA-65) the connector is layered modules, lowest first: fabric_board_shapes (the wire), fabric_board_link
(session, checkpoint and request; since 0.41.0), fabric_board_session (the responder) and fabric_board_fixture (a scripted
board for the probe). This file re-exports every name it defined at 0.39.1, so import fabric_board keeps working. Standard library only, Python 3.9+."""
from __future__ import annotations

import sys  # noqa: F401 - callers reach these through the facade
from pathlib import Path  # noqa: F401

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fabric_board_shapes import (  # noqa: F401
    COMMS_PROTOCOL,
    LEASE_SECONDS,
    SUMMARY_MAX,
    EVIDENCE_MAX,
    RESPOND_TOOLS,
    REFUSAL_CODES,
    REQUEST_STATES,
    EFFECT_STATES,
    HOLD_SCOPES,
    _OPAQUE,
    _PROJECT,
    _CAPABILITY,
    _SHA256,
    _KEY,
    _TIMESTAMP,
    _URI,
    _SAFE,
    BoardError,
    Stopped,
    comms_canonical,
    comms_digest,
    _is_int,
    _closed,
    _attempt_problems,
    receipt_problems,
    refusal_problems,
    directory_findings,
    directory_problems,
    hold_refuses,
    find_project,
    artifact_ref,
    evidence_problems,
    outcome_problems,
)
from fabric_board_session import (  # noqa: F401
    RENEW_SECONDS,
    POLL_SECONDS,
    POLL_JITTER_SECONDS,
    DRAIN_SECONDS,
    EVENT_SCHEMA,
    STOP_CODES,
    TERMINAL,
    HOLD_RETRY_MAX_SECONDS,
    BoardSession,
    Checkpoint,
    BoardRequest,
    WorkContext,
    _Work,
    Handler,
    Responder,
)
from fabric_board_fixture import (  # noqa: F401
    _FIXTURE_PROJECT,
    _FIXTURE_DIGEST,
    _fixture_answers,
    self_check,
)
