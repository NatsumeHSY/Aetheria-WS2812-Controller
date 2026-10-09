# Matrix Shapes, Session Health, and Connection Status Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent matrix shapes, health-first UDP session recovery, periodic heartbeat monitoring, and a formal top-bar connection indicator.

**Architecture:** Keep packet construction and session sequencing in the existing protocol/controller layers. Add a focused JSON-backed `MatrixShapeStore` for built-ins and user shapes, expose it through the existing pywebview bridge, and let `index.js` own periodic health presentation. The board handles health packets before normal sequence classification so a restarted client can replace its UDP source port without resetting the board session.

**Tech Stack:** MicroPython board code, Python 3 client, UDP, pywebview, vanilla JavaScript/CSS, `unittest`, JSON persistence.

**Spec:** `docs/superpowers/specs/2026-10-08-matrix-shapes-health-status-design.md`

## Global Constraints

- Health request uses command `0xFE`; health acknowledgement uses `LD + 0x03 + expected_seq`.
- Health never consumes an application sequence number.
- Board health recovery only accepts a source IP matching the remembered client IP.
- Built-in matrix shapes are read-only; only user shapes are persisted and mutable.
- The old bottom status footer is removed; the formal status indicator lives in the top bar.
- Preserve the existing dynamic WebView shell and packet CRC/retry behavior.

## Review Focus

- A client restart must recover the board's current sequence without sending a second handshake first — test in Task 2.
- A health request from an unknown IP must not steal the active board session — test in Task 3.
- Corrupt or malformed shape storage must not crash startup or permit invalid data — test in Task 4.
- Built-in shapes must not expose update/delete actions and presets must use the current paint color — test in Task 6.
- A stalled health request must turn the indicator offline and show heartbeat age without leaving overlapping timers — test in Task 7.

### Task 1: Add health packet primitives

**Files:**
- Modify: `client/protocol.py`
- Test: `tests/test_client_protocol.py`

**Interfaces:**
- Produces `HEALTH_COMMAND = b"\xFE"`, `HEALTH_ACK = b"\x03"`, `build_health_packet() -> bytes`, and a `parse_response` that accepts health acknowledgements.

- [ ] **Step 1: Write failing protocol tests** for health packet CRC/shape, health response parsing, and rejection of malformed health responses.
- [ ] **Step 2: Run the targeted protocol tests** and verify they fail because the constants/helper/parser support is absent.
- [ ] **Step 3: Implement the smallest protocol additions** while leaving normal ACK/RESEND behavior unchanged.
- [ ] **Step 4: Run `tests/test_client_protocol.py`** and verify all protocol tests pass.

### Task 2: Make the client controller health-first and sequence-aware

**Files:**
- Modify: `client/controller.py`
- Test: `tests/test_client_protocol.py` or a new `tests/test_controller_health.py`

**Interfaces:**
- Adds `LEDController.health() -> bool`.
- `LEDController.connect() -> bool` tries `health()` first, adopts the acknowledged next sequence, and only then falls back to the existing handshake.

- [ ] **Step 1: Write failing controller tests** with a real fake UDP socket that proves health recovery succeeds without handshake, health does not increment sequence, handshake is used after health timeout, and a failed health marks the controller disconnected.
- [ ] **Step 2: Run the targeted controller tests** and verify they fail against the current handshake-only controller.
- [ ] **Step 3: Implement health request/retry handling under the existing controller lock**, including expected-sequence restoration and clearing stale packet history.
- [ ] **Step 4: Run the targeted controller tests plus the full client protocol suite** and verify they pass.

### Task 3: Add board-side health session recovery

**Files:**
- Modify: `board/main.py`
- Test: `tests/test_board_protocol.py`

**Interfaces:**
- Adds `HEALTH_COMMAND`, `RESPONSE_HEALTH`, and `restore_health_session(remembered_addr, received_addr, expected_seq) -> tuple[bool, tuple[str, int] | None, int]`.
- The main receive loop handles a valid health packet before `addr != CLIENT_ADDR` and sequence classification.

- [ ] **Step 1: Write failing board tests** for same-IP port replacement, `None` expected sequence becoming zero, unknown-IP rejection, and no sequence advancement.
- [ ] **Step 2: Run the targeted board tests** and verify they fail because board health recovery is absent.
- [ ] **Step 3: Implement the pure session helper and wire the receive loop** to send `LD + RESPONSE_HEALTH + expected_seq` without queueing the packet.
- [ ] **Step 4: Run the board protocol suite** and verify existing validation, replay, gap, CRC, and transition tests remain green.

### Task 4: Build the persistent matrix shape store

**Files:**
- Create: `client/matrix_shapes.py`
- Test: `tests/test_matrix_shapes.py`

**Interfaces:**
- `MatrixShapeStore(path: Path)` with `list_shapes()`, `get_shape(shape_id)`, `save_user_shape(name, matrix)`, `update_user_shape(shape_id, name, matrix)`, and `delete_user_shape(shape_id)`.
- Module helpers `validate_matrix(matrix)`, `materialize_preset(matrix_mask, paint_color)`, and `preset_shapes()`.

- [ ] **Step 1: Write failing store tests** for the six presets, immutable preset metadata, user save/reload/update/delete, invalid dimensions/colors, and corrupt JSON recovery.
- [ ] **Step 2: Run the store tests** and verify they fail because the module does not exist.
- [ ] **Step 3: Implement validation and JSON persistence** with atomic replacement through a temporary file in the same directory; keep only user shapes on disk.
- [ ] **Step 4: Run `tests/test_matrix_shapes.py`** and verify all store behavior passes.

### Task 5: Expose health and shapes through the pywebview bridge

**Files:**
- Modify: `client/webui/webui.py`
- Test: `tests/test_webui_effects.py`

**Interfaces:**
- Adds bridge methods `health()`, `list_shapes()`, `save_shape(name, matrix)`, `update_shape(shape_id, name, matrix)`, `delete_shape(shape_id)`, and `send_shape(shape_id, brightness, paint_color)`.
- Bridge shape sends use `_send_matrix`; preset masks are materialized with the provided paint color.

- [ ] **Step 1: Write failing bridge tests** for health result mapping, shape CRUD routing, preset color materialization, user-shape send routing, and structured error responses.
- [ ] **Step 2: Run the targeted bridge tests** and verify they fail because the bridge methods/store wiring are absent.
- [ ] **Step 3: Implement bridge construction of `MatrixShapeStore`**, health forwarding, shape CRUD, and shape send behavior without changing existing effect methods.
- [ ] **Step 4: Run all Python bridge and shape tests** and verify they pass.

### Task 6: Add the matrix-shape panel and top-bar status markup/styles

**Files:**
- Modify: `client/webui/scripts/runtime_const.js`
- Modify: `client/webui/templates/index.html`
- Test: `tests/test_webui_effects.py`

**Interfaces:**
- Adds shape panel selectors `shapeList`, `saveShape`, `shapeName`, and per-card `shape-send`, `shape-load`, `shape-update`, `shape-delete` actions.
- Adds formal status selectors `connectionStatus`, `connectionState`, `heartbeatAge`, and `statusMessage` with `aria-live="polite"`.

- [ ] **Step 1: Write failing source/UI tests** for the shape region, six preset/user action distinctions, top-bar status component, heartbeat labels, and removal of the bottom footer.
- [ ] **Step 2: Run the targeted UI tests** and verify they fail against the current markup.
- [ ] **Step 3: Implement matching dark-teal styles and markup** in both runtime constants and the preview template; preserve the red-box area as the matrix shape workspace and make the shape list internally scrollable.
- [ ] **Step 4: Run UI source tests and JavaScript syntax checks** for the runtime script and template inline script.

### Task 7: Implement shape interactions and health-driven status updates

**Files:**
- Modify: `client/webui/scripts/index.js`
- Test: `tests/test_webui_effects.py` and `tests/test_client_ui.py`

**Interfaces:**
- Adds `loadShapes()`, `renderShapeList(shapes)`, `sendShape(shapeId)`, `loadShape(shapeId)`, `saveCurrentShape()`, `updateCurrentShape()`, `deleteShape(shapeId)`, `startHealthMonitor()`, and `renderConnectionStatus(state, message)`.

- [ ] **Step 1: Write failing JavaScript-source tests** for shape loading/rendering calls, current-matrix save/update/delete actions, periodic health invocation, heartbeat age formatting, and offline/error state transitions.
- [ ] **Step 2: Run the targeted UI tests** and verify they fail because the interaction/status functions are absent.
- [ ] **Step 3: Implement the shape workflow**: load shapes at startup, use prompt only for a new name, track the currently loaded user shape, prevent preset mutation controls, and send with current brightness/paint color.
- [ ] **Step 4: Implement the formal status workflow**: show connecting, mark heartbeat success time, update age once per second, poll health at a fixed interval, and stop timers when unavailable.
- [ ] **Step 5: Run all UI tests and JavaScript syntax checks** and verify they pass.

### Task 8: Full verification and launch smoke test

**Files:**
- Verify: all modified files above
- Test: all files under `tests/`

- [ ] **Step 1: Run the complete unittest suite** from the project root and require zero failures.
- [ ] **Step 2: Run Python compilation and JavaScript syntax checks** for board/client/runtime scripts.
- [ ] **Step 3: Launch `client/main.py` with the project virtualenv**, confirm it remains running without startup traceback, then close the smoke-test process.
- [ ] **Step 4: Inspect the final diff and confirm no bottom status footer, no duplicate handshake before health, and no mutable controls on built-in shapes.**

Because this workspace has no Git repository, each task's test run is the
checkpoint instead of a commit; no source history operation is required.
