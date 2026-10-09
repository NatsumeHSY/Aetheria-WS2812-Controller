# WS2812 Session State Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add an `FD` sync command so a recovered client session can import the board's current light state, while local UI state is saved on shutdown and restored on the next launch.

**Architecture:** Keep the existing CRC4-framed UDP protocol and reserve `FD` for the sync request and response type `04` for a versioned binary snapshot. The board owns a locked runtime snapshot; the client controller decodes it into UI settings. A separate atomic JSON state store provides the local fallback and is used by the pywebview bridge and startup/shutdown lifecycle.

**Tech Stack:** MicroPython board runtime, Python 3 client, UDP, pywebview bridge, JSON persistence, unittest, Node `--check`.

**Spec:** `docs/superpowers/specs/2026-10-09-sync-state-design.md`

## Global Constraints

- `FD` is `SYNC_COMMAND`; `04` is `SYNC_RESPONSE`; `FE` remains health and `FF` remains handshake.
- Sync packets are CRC4-framed, use big-endian multi-byte fields, do not consume the application sequence, and remain below the 6144-byte limit.
- Snapshot version is `1`; color count is `0..32`; matrix data is row-major 864-cell RGB data.
- Board state reads and writes use a MicroPython `_thread` lock.
- Rainbow mode reports only firmware-owned mode/timing and never imports client palette colors.
- Local state is stored atomically in `client/configs/ui_state.json`; corrupt or invalid state is ignored.
- Old boards without `FD` remain usable through health/handshake and local state fallback.
- This workspace has no Git repository; per-task tests and the SDD progress ledger replace commits.

## Review Focus

- A sync response containing a full 6×144 matrix must remain under the packet limit and preserve row-major colors — Task 1 codec tests and Task 2 board packet tests.
- A health-recovered session must not advance the application sequence or trigger a second handshake — Task 3 controller tests.
- A corrupt, old-version, all-black, or dimensionally invalid persisted state must never reach the UI/device — Task 4 persistence tests.
- A board sync timeout or unsupported mode must fall back to local state without falsely marking the connection offline — Task 5 bridge tests and Task 6 startup-source tests.
- Closing during an outstanding debounced save must still issue one best-effort save, while missing bridge APIs must not block shutdown — Task 6 UI-source tests.

---

### Task 1: Client sync wire codec

**Files:**
- Modify: `client/protocol.py`
- Create: `client/sync_state.py`
- Test: `tests/test_client_protocol.py`
- Test: `tests/test_sync_state.py`

**Interfaces:**
- Produces `SYNC_COMMAND = b"\xFD"`, `SYNC_RESPONSE = b"\x04"`, `SYNC_VERSION = 1`, `build_sync_packet() -> bytes`.
- Produces `SyncSnapshot` with `mode`, `brightness_min`, `brightness_max`, `timing`, `colors`, and optional `matrix`.
- Produces `encode_sync_snapshot(snapshot: SyncSnapshot) -> bytes` and `decode_sync_snapshot(payload: bytes) -> SyncSnapshot`.

- [ ] **Step 1: Write failing tests** for the FD request framing, a full matrix round trip, all supported mode values, 32-color limit, big-endian timing, bad version, truncated payload, invalid color count, and invalid matrix length.
- [ ] **Step 2: Run the focused tests and verify RED** because the sync constants and codec do not exist yet.
- [ ] **Step 3: Implement the constants and codec** with strict length/version/enum/color/matrix validation; use the existing `build_packet`/`decode_packet` CRC4 framing.
- [ ] **Step 4: Run the focused tests and verify GREEN.**
- [ ] **Step 5: Update the SDD ledger** with the passing command and result.

### Task 2: Board snapshot model and FD response

**Files:**
- Modify: `board/main.py`
- Test: `tests/test_board_protocol.py`

**Interfaces:**
- Produces a board-side snapshot model matching Task 1's byte layout.
- Produces `copy_light_snapshot()`, `update_*_snapshot(...)`, and a bounded `build_sync_response(expected_seq)` helper suitable for AST-loaded board tests.
- Extends `loop()` to handle `HEALTH_COMMAND` and `SYNC_COMMAND` before normal sequence classification.

- [ ] **Step 1: Write failing tests** for initial/off state, fill/breathe/rainbow/matrix snapshot updates, 864-cell encoded length, CRC-valid response framing, same-IP/new-port sync response, unknown-IP rejection, and no sequence advancement.
- [ ] **Step 2: Run the board tests and verify RED.**
- [ ] **Step 3: Implement the locked snapshot** using `_thread.allocate_lock`; update the state-changing LED handlers and add FD response encoding with response type `04` and `EXPECTED_SEQ`.
- [ ] **Step 4: Ensure sync never enters `SOCKET_BUFFER`** and adopts a new source port only for the remembered client IP.
- [ ] **Step 5: Run board tests and verify GREEN.**
- [ ] **Step 6: Update the SDD ledger.**

### Task 3: Controller recovered-session sync

**Files:**
- Modify: `client/controller.py`
- Test: `tests/test_controller_health.py`
- Test: `tests/test_controller_sync.py`

**Interfaces:**
- Adds `LEDController.last_connect_recovered: bool`.
- `connect() -> bool` sets `last_connect_recovered=True` only for a successful FE/health recovery and `False` for FF handshake success.
- Adds `sync() -> SyncSnapshot` and raises `ControllerError` for timeout, malformed, unsupported, or disconnected sync responses.

- [ ] **Step 1: Write failing fake-socket tests** for health recovery followed by FD sync, sync response decoding, sequence preservation, timeout, malformed response, and FF fallback reporting `recovered=False`.
- [ ] **Step 2: Run the focused controller tests and verify RED.**
- [ ] **Step 3: Implement sync request/retry/response handling** without changing the application sequence or existing ACK/RESEND behavior.
- [ ] **Step 4: Set the recovered flag only inside `connect()`**, leaving standalone `health()` suitable for the heartbeat monitor.
- [ ] **Step 5: Run controller and protocol tests and verify GREEN.**
- [ ] **Step 6: Update the SDD ledger.**

### Task 4: Atomic local UI state store

**Files:**
- Create: `client/ui_state.py`
- Test: `tests/test_ui_state.py`

**Interfaces:**
- Produces `UiStateStore(path)` with `load() -> dict | None` and `save(state: dict) -> dict`.
- Produces `normalize_ui_state(state: dict) -> dict` for version-one state containing `source`, `mode`, `brightness`, `speed`, `colors`, `paintColor`, and a 6×144 `matrix144x6`.

- [ ] **Step 1: Write failing tests** for a valid round trip, atomic parent-directory creation, corrupt JSON, unsupported version, invalid colors, invalid dimensions, and an all-black matrix being valid for UI persistence.
- [ ] **Step 2: Run the persistence tests and verify RED.**
- [ ] **Step 3: Implement strict normalization and atomic temp-file plus `os.replace` persistence**; invalid input must raise `ValueError`, while invalid files load as `None`.
- [ ] **Step 4: Run the persistence tests and verify GREEN.**
- [ ] **Step 5: Update the SDD ledger.**

### Task 5: Bridge sync and persistence API

**Files:**
- Modify: `client/webui/webui.py`
- Test: `tests/test_webui_bridge.py`

**Interfaces:**
- `JavaScriptBridge.connect()` returns `{"ok", "connected", "recovered"}`.
- Adds `sync() -> {"ok", "connected", "state"|"error"}` and maps `SyncSnapshot` into UI state without inventing client colors for rainbow mode.
- Adds `load_state() -> {"ok", "state"|None}` and `save_state(state) -> {"ok", "state"|"error"}` backed by `UiStateStore`.

- [ ] **Step 1: Write failing bridge tests** for recovered connect metadata, sync-to-static/breathe/rainbow/matrix mappings, sync error fallback shape, state load/save, and invalid state rejection.
- [ ] **Step 2: Run bridge tests and verify RED.**
- [ ] **Step 3: Add the state store and bridge methods**; preserve `connected=True` on a sync-format failure when the transport session is still alive.
- [ ] **Step 4: Run bridge tests and verify GREEN.**
- [ ] **Step 5: Update the SDD ledger.**

### Task 6: Runtime UI restore, sync authority, and shutdown save

**Files:**
- Modify: `client/webui/scripts/index.js`
- Test: `tests/test_client_ui.py`

**Interfaces:**
- Adds `applyUiState(state)`, `applySyncedState(state, fallback)`, `restoreLocalState()`, `persistState()`, and `flushPersistedState()`.
- Startup loads local state before connecting, uses `connection.recovered` to decide whether to call `sync`, applies local state to a newly handshaken device, and starts health monitoring afterward.
- State changes use a debounced save; `beforeunload` calls a best-effort flush without waiting forever for the bridge.

- [ ] **Step 1: Write failing source-contract tests** for local-state load, recovered-session sync, new-session local apply, rainbow palette preservation, debounced persistence, beforeunload flush, and sync failure not forcing offline status.
- [ ] **Step 2: Run UI tests and verify RED.**
- [ ] **Step 3: Implement state application helpers** that update sliders, colors, paint color, output source, mode, matrix cells, and labels without triggering premature device writes.
- [ ] **Step 4: Implement the startup decision tree and persistence hooks** while retaining the existing FE health monitor and FE-to-FF recovery behavior.
- [ ] **Step 5: Run UI tests plus `node --check client/webui/scripts/index.js` and verify GREEN.**
- [ ] **Step 6: Update the SDD ledger.**

### Task 7: Full verification and self-review

**Files:**
- Modify: `docs/superpowers/specs/2026-10-09-sync-state-design.md` only if review finds a contract correction.
- Modify: `.superpowers/sdd/2026-10-08-matrix-shapes-health-status/progress.md`

- [ ] **Step 1: Run the complete Python suite:** `& .\client\.venv\Scripts\python.exe -m unittest discover -s tests -p 'test_*.py'`.
- [ ] **Step 2: Run JavaScript syntax checks:** `node --check client/webui/scripts/index.js` and `node --check client/webui/scripts/runtime_const.js`.
- [ ] **Step 3: Run Python compilation:** `& .\client\.venv\Scripts\python.exe -m compileall -q client board tests`.
- [ ] **Step 4: Review protocol compatibility, persistence failure paths, startup ordering, and shutdown behavior against the spec.**
- [ ] **Step 5: Record final results and any remaining limitations in the SDD ledger.**

