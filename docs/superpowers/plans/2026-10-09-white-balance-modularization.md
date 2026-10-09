# WS2812 White Balance and Board Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add persistent, synchronized board-side white-balance correction using `A2`, while splitting the board firmware into focused modules directly under `board/` and establishing Git rollback points.

**Architecture:** Keep logical RGB values unchanged across the client, protocol, snapshots, persistence, and sync. Apply three-channel white-balance gains only in the board LED driver immediately before brightness scaling and NeoPixel output. Extract board constants, protocol helpers, runtime state, persistence, driver, and effects into sibling modules in `board/`; leave socket lifecycle and command orchestration in `board/main.py`.

**Tech Stack:** MicroPython on ESP32-C3, NeoPixel, UDP, Python client, unittest/pytest-compatible tests, Git.

**Spec:** `docs/superpowers/specs/2026-10-09-white-balance-design.md`

## Global Constraints

- White-balance gains are three bytes in the range `0~255`, defaulting to `(255, 255, 255)`.
- `0xA2` is reserved for white-balance parameters; `0xA0` and `0xA1` remain brightness and timing.
- Client and sync state store uncorrected logical RGB values.
- Board persistence version `1` remains readable; new files use version `2`.
- Sync version `1` remains readable by the client; the board emits version `2` after implementation.
- New board modules live directly in `board/`; do not create `board/src`, `board/lib`, or another nested firmware package.
- `board/dev/` is legacy code and must be removed as the first project action, before Git initialization and before creating the new board modules.
- The existing client must continue to support both package imports and script-mode imports used by the tests.

## Review Focus

- A white-balance update must affect every output path, including board-generated animations, without changing stored logical RGB; test the driver boundary and an active-effect frame.
- A version-1 persistence file must restore with default white balance, while a version-2 file must round-trip all three gains; test both formats and checksum rejection.
- A version-1 sync payload must remain decodable and a version-2 payload must expose white balance; test both client decoder paths.
- Static/matrix output must redraw after a white-balance change without clearing the strip; test the command handler with fake driver calls.
- The destructive cleanup must target only `board/dev/`; the first Git commit is created after cleanup and becomes the rollback point for all subsequent work.

---

### Task 1: Remove only the legacy `board/dev/` tree before project work

**Files:**
- Delete: `board/dev/` and its contents

**Interfaces:**
- Produces a clean `board/` root for the new firmware modules.
- Because this action intentionally precedes Git initialization, the later Git history cannot restore `board/dev/`; Git rollback begins after this approved cleanup point.

- [ ] **Step 1: Inspect the workspace and confirm the exact deletion target**

Run `Get-Location`, `Get-ChildItem -Force board`, and `Test-Path board/dev`. Confirm the only destructive target is the exact path `D:\WS2812_ESP32-C3\board\dev` and that the new `board/*.py` firmware files are outside the target.

- [ ] **Step 2: Delete the explicitly approved legacy directory**

After rechecking the resolved absolute path is exactly `D:\WS2812_ESP32-C3\board\dev`, remove only that directory. Do not use a workspace-wide recursive delete.

- [ ] **Step 3: Verify cleanup before continuing**

Confirm `Test-Path board/dev` is false and `Get-ChildItem board -File` contains only the existing active firmware files. Stop if any path outside `board/dev` changed.

### Task 2: Initialize Git and create the post-cleanup rollback point

**Files:**
- Create: `.gitignore`
- Create: `.git/` via Git initialization
- Commit: all current non-ignored project files after legacy cleanup

**Interfaces:**
- Consumes the cleaned workspace from Task 1.
- Produces the first Git rollback point for modularization and white-balance work.

- [ ] **Step 1: Create `.gitignore` before staging**

Ignore Python caches, `client/.venv/`, board runtime state files (`board/state.bin`, `board/state.tmp`), and other generated temporary files without ignoring source, tests, or design documents.

- [ ] **Step 2: Initialize Git and commit the post-cleanup baseline**

Run `git init -b main`, `git add -A`, and `git commit -m "chore: capture post-cleanup baseline"`. If Git identity is not configured, stop and report the exact configuration requirement.

- [ ] **Step 3: Verify the rollback point**

Run `git log --oneline -1`, `git status --short`, and `git ls-tree -r --name-only HEAD board`. The tree must contain no `board/dev/` path and the working tree must be clean.

### Task 3: Extract board constants and protocol helpers

**Files:**
- Create: `board/config.py`
- Create: `board/protocol.py`
- Modify: `board/main.py`
- Test: `tests/test_board_protocol.py`

**Interfaces:**
- `config.py` exports protocol constants, command bytes, LED dimensions, effect constants, and `PARAM_WHITE_BALANCE_COMMAND = b"\\xA2"`.
- `protocol.py` exports `next_sequence`, `crc4_itu`, `calculate_packet_crc`, `validate_packet`, `classify_sequence`, and `restore_health_session` with the current signatures.
- `main.py` imports these names from the sibling modules and keeps existing call sites behaviorally compatible.

- [ ] **Step 1: Move protocol constant definitions without changing values**

Move the existing constants to `config.py`, add `PARAM_WHITE_BALANCE_COMMAND`, and keep all F-segment control command values unchanged.

- [ ] **Step 2: Move pure packet/sequence helpers**

Move the CRC4, exact packet validation, sequence wrap/classification, and health-session helpers to `protocol.py`. Keep the CRC algorithm and `0xFFFF -> 0x0000` behavior byte-for-byte compatible.

- [ ] **Step 3: Update the board entrypoint imports**

Use same-directory imports that work when `main.py` runs on MicroPython and when the board directory is added to the host test path. Do not import `machine` from the extracted pure modules.

- [ ] **Step 4: Run protocol regression tests**

Run `pytest tests/test_board_protocol.py -q`. Expected: all existing packet, CRC, sequence, health, and snapshot tests that still target protocol behavior pass; update only import/fixture paths where extraction requires it.

- [ ] **Step 5: Commit the extraction**

Run `git add board/config.py board/protocol.py board/main.py tests/test_board_protocol.py` and commit with `refactor: extract board protocol helpers`.

### Task 4: Extract runtime state and persistence with white-balance fields

**Files:**
- Create: `board/state.py`
- Create: `board/persistence.py`
- Modify: `board/main.py`
- Modify: `tests/test_board_persistence.py`
- Modify: `tests/test_board_protocol.py`

**Interfaces:**
- `state.py` exports snapshot normalization/copy helpers, snapshot update/copy/reset functions, global brightness/timing accessors, and:
  - `get_global_white_balance() -> tuple[int, int, int]`
  - `set_global_white_balance(red: int, green: int, blue: int) -> tuple[int, int, int]`
  - `initialize_runtime_params(snapshot: dict, white_balance: tuple[int, int, int] = (255, 255, 255)) -> None`
- `persistence.py` exports `persistence_checksum`, `encode_persisted_state(snapshot, effect_params=None, white_balance=(255,255,255))`, `decode_persisted_state(data)`, and `atomic_write_persisted_state(...)`.
- `decode_persisted_state()` returns `white_balance` alongside `snapshot` and `effect_params`; version-1 data returns `(255,255,255)`.

- [ ] **Step 1: Write state tests for white-balance validation and atomic updates**

Cover default values, per-channel bounds, rejection of invalid values, and the fact that changing white balance does not modify logical snapshot colors or matrix values.

- [ ] **Step 2: Extract snapshot/runtime state**

Move the state globals and pure snapshot/runtime functions out of `main.py`. Keep `main.py` responsible for hardware redraw orchestration and effect startup.

- [ ] **Step 3: Add persistence format version 2**

Add three white-balance bytes after timing, make new encodings version `2`, accept version `1` with default gains, and retain the existing checksum and atomic temp-file replacement behavior.

- [ ] **Step 4: Update startup/save callers**

Make `main.py` pass the current white-balance tuple into persistence encoding and restore it before replaying saved output or restarting an effect.

- [ ] **Step 5: Run persistence and state tests**

Run `pytest tests/test_board_persistence.py tests/test_board_protocol.py -q`. Expected: round-trip, old-version compatibility, checksum, matrix, state, and restore tests pass.

- [ ] **Step 6: Commit state and persistence extraction**

Run `git add board/state.py board/persistence.py board/main.py tests/test_board_persistence.py tests/test_board_protocol.py` and commit with `refactor: extract board state and persistence`.

### Task 5: Extract the LED driver and apply white balance at the output boundary

**Files:**
- Create: `board/led_driver.py`
- Modify: `board/main.py`
- Create/Modify: `tests/test_board_white_balance.py`

**Interfaces:**
- `led_driver.py` exports `LedDriver` with the existing `begin`, `set_pixel`, `show`, `fill`, and `clear` methods.
- It exports a pure helper `apply_white_balance(color, white_balance) -> tuple[int, int, int]` for host tests.
- `LedDriver` reads one atomic white-balance tuple from `state.get_global_white_balance()` for each output operation.

- [ ] **Step 1: Write failing driver tests**

Assert that `(255,255,255)` leaves output unchanged, `(255,255,255)` gains preserve old behavior, channel-specific gains affect only their channels, and `fill()` and `set_pixel()` produce the same transformed values before brightness scaling.

- [ ] **Step 2: Extract `LedDriver`**

Move the class to `led_driver.py` without changing its public method signatures or logical `current_state` semantics.

- [ ] **Step 3: Implement output-stage correction**

Apply per-channel gains before brightness scaling in both output methods. Do not rewrite colors stored in snapshots or `current_state`.

- [ ] **Step 4: Wire the driver into `main.py` and test**

Run `pytest tests/test_board_white_balance.py -q`. Expected: all transform and regression assertions pass.

- [ ] **Step 5: Commit driver correction**

Run `git add board/led_driver.py board/main.py tests/test_board_white_balance.py` and commit with `feat: add board-side white balance correction`.

### Task 6: Extract effects and preserve effect behavior

**Files:**
- Create: `board/effects.py`
- Modify: `board/main.py`
- Modify: `tests/test_board_effects.py`
- Modify: `tests/test_board_transition.py`

**Interfaces:**
- `effects.py` exports `Effector`, `xy2pos`, `rainbow_color`, and `interpolate_color_state` with their current signatures.
- `Effector` consumes the extracted `LedDriver` and state accessors; effect names and payload semantics remain unchanged.

- [ ] **Step 1: Update effect tests to import the extracted module**

Keep coverage for stop/generation behavior, transition, breathe, rainbow, scan-line, and timing behavior while removing AST dependence on the monolithic `main.py`.

- [ ] **Step 2: Move `Effector` and effect utilities**

Extract only the hardware/effect class and its directly related utility functions. Keep socket command handlers in `main.py` to avoid introducing a command-dispatch dependency cycle.

- [ ] **Step 3: Run effect regression tests**

Run `pytest tests/test_board_effects.py tests/test_board_transition.py -q`. Expected: existing behavior passes and all output calls still flow through `LedDriver`.

- [ ] **Step 4: Commit the effects extraction**

Run `git add board/effects.py board/main.py tests/test_board_effects.py tests/test_board_transition.py` and commit with `refactor: extract board effects`.

### Task 7: Add the `A2` board command and versioned sync response

**Files:**
- Modify: `board/main.py`
- Modify: `board/config.py`
- Modify: `client/protocol.py`
- Modify: `client/sync_state.py`
- Modify: `tests/test_board_protocol.py`
- Modify: `tests/test_sync_state.py`
- Create/Modify: `tests/test_client_protocol.py`

**Interfaces:**
- Board handler: `led_set_white_balance(length: int, payload: list) -> None`, accepting exactly three bytes.
- Client protocol helper: `build_white_balance_packet(red: int, green: int, blue: int, sequence: int = 0) -> bytes`.
- `SyncSnapshot.white_balance: tuple[int, int, int]`.
- `encode_sync_snapshot()` emits version `2`; `decode_sync_snapshot()` accepts versions `1` and `2`.

- [ ] **Step 1: Write failing packet and sync tests**

Pin `A2` with a three-byte payload, reject wrong lengths, round-trip sync version 2 with white balance, and decode a legacy version-1 payload with default gains.

- [ ] **Step 2: Implement board command handling**

Register `A2` in the board effect map. On success, update global gains, redraw static/matrix state without clearing, save persistence, and ACK through the existing path.

- [ ] **Step 3: Extend board sync encoding**

Add version 2 and the three gain bytes while continuing to return logical colors and matrix bytes unchanged.

- [ ] **Step 4: Implement client protocol and sync decoding**

Add the packet builder, extend `SyncSnapshot`, and preserve version-1 compatibility. Keep packet CRC and sequence handling unchanged.

- [ ] **Step 5: Run protocol/sync tests**

Run `pytest tests/test_board_protocol.py tests/test_client_protocol.py tests/test_sync_state.py -q`. Expected: all command, CRC, sequence, sync version, and legacy compatibility tests pass.

- [ ] **Step 6: Commit protocol integration**

Run `git add board client/protocol.py client/sync_state.py tests/test_board_protocol.py tests/test_client_protocol.py tests/test_sync_state.py` and commit with `feat: add white balance protocol synchronization`.

### Task 8: Add controller, bridge, and UI controls

**Files:**
- Modify: `client/controller.py`
- Modify: `client/webui/webui.py`
- Modify: `client/webui/scripts/index.js`
- Modify: `client/webui/scripts/runtime_const.js`
- Modify: `client/webui/templates/index.html`
- Modify: `tests/test_controller_sync.py`
- Modify: `tests/test_webui_bridge.py`
- Modify: `tests/test_ui_state.py`
- Modify: `tests/test_webui_effects.py`

**Interfaces:**
- `LEDController.set_white_balance(red: int, green: int, blue: int) -> int`.
- `WebUIBridge.set_white_balance(red, green, blue) -> dict`.
- UI state contains `whiteBalance: [number, number, number]` and renders three controls plus reset-to-default.

- [ ] **Step 1: Write failing controller/bridge/UI tests**

Assert packet payload ordering, bridge error handling, sync application of board gains, and that UI color/matrix logical values remain unchanged when gains change.

- [ ] **Step 2: Implement controller and bridge methods**

Send the complete three-byte gain tuple through `A2`, preserve existing connection recovery behavior, and expose sync values to the runtime UI state.

- [ ] **Step 3: Add the themed UI section**

Add R/G/B sliders and a reset button in the existing light-parameter panel, using the same button/hover/modal theme already used by the current UI. Use a short debounce while dragging and only update local confirmed values after a successful bridge response.

- [ ] **Step 4: Update dynamic markup and preview template together**

Keep `runtime_const.js` as the production dynamic UI source and `templates/index.html` as its preview counterpart; do not reintroduce static HTML loading into the WebView.

- [ ] **Step 5: Run client tests and syntax checks**

Run `pytest tests/test_controller_sync.py tests/test_webui_bridge.py tests/test_ui_state.py tests/test_webui_effects.py -q`, `python -m py_compile client/controller.py client/protocol.py client/sync_state.py client/webui/webui.py`, and a Node syntax check for the changed JavaScript files.

- [ ] **Step 6: Commit client integration**

Run `git add client tests/test_controller_sync.py tests/test_webui_bridge.py tests/test_ui_state.py tests/test_webui_effects.py` and commit with `feat: expose white balance controls in client`.

### Task 9: Full verification and MicroPython upload review

**Files:**
- Modify only files required by test fixes or documentation

**Interfaces:**
- Produces a directly uploadable `board/` directory containing `main.py` and its sibling modules, with no dependency on `board/dev/`.

- [ ] **Step 1: Run the complete automated suite**

Run `pytest -q`. Expected: all tests pass.

- [ ] **Step 2: Run source and import checks**

Run `python -m compileall -q client tests`, import each pure board module from a host test path, and check that `board/main.py` contains no `board.dev` or legacy module imports.

- [ ] **Step 3: Review the upload set**

List `board/*.py` and verify every imported sibling module is present directly in that directory. Confirm `board/dev/` is absent and runtime state files are ignored.

- [ ] **Step 4: Commit final verification adjustments**

Commit only if verification required a source/test adjustment, using a focused message; otherwise leave the previous feature commit as the final code commit.

- [ ] **Step 5: Report the Git recovery points**

Report the baseline commit, legacy cleanup commit, and feature commits so the user can roll back the board structure or white-balance implementation independently.
