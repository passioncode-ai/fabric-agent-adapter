// The project board connector, Node: the facade (fabric-project-comms/0.1; the twin of fabric_board.py).
// Since 0.40.0 (FAA-65) it is layered modules: fabric-board-shapes, fabric-board-link (since 0.41.0), fabric-board-session and
// fabric-board-fixture. This file re-exports everything it exported at 0.39.1. Node 20+, no dependency.
export {
  COMMS_PROTOCOL,
  LEASE_SECONDS,
  SUMMARY_MAX,
  EVIDENCE_MAX,
  RESPOND_TOOLS,
  REFUSAL_CODES,
  HOLD_SCOPES,
  BoardError,
  Stopped,
  commsCanonical,
  commsDigest,
  receiptProblems,
  refusalProblems,
  directoryFindings,
  directoryProblems,
  holdRefuses,
  findProject,
  artifactRef,
  evidenceProblems,
  outcomeProblems,
} from './fabric-board-shapes.mjs';
export {
  RENEW_SECONDS,
  POLL_SECONDS,
  POLL_JITTER_SECONDS,
  DRAIN_SECONDS,
  EVENT_SCHEMA,
  STOP_CODES,
  HOLD_RETRY_MAX_SECONDS,
  BoardSession,
  Checkpoint,
  BoardRequest,
  WorkContext,
  Responder,
} from './fabric-board-session.mjs';
export {
  selfCheck,
} from './fabric-board-fixture.mjs';
