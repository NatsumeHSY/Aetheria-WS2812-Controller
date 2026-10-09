# WS2812 session state sync design

Date: 2026-10-09

## Goal

When the desktop client starts, it should restore the previous local UI state. If the
client successfully recovers an existing ESP32 session through `health`, the board's
current light state becomes authoritative and is synchronized into the client through a
new `sync` command. When the client closes, its current UI state is persisted for the
next launch.

The existing health, handshake, sequence, replay protection, CRC4, matrix-shape, and
rainbow semantics remain unchanged.

## Authority and startup behavior

There are two state sources:

1. `ui_state.json` is the local fallback. It stores the last client settings and is
   available even when the board is offline.
2. The board snapshot is authoritative only when the client recovered an existing
   session and `sync` succeeds.

Startup order:

1. Render the UI and load the local state file.
2. Call `connect()`. The controller sends `FE` first; if that succeeds, the result
   includes `recovered: true`. Otherwise it falls back to the existing `FF` handshake
   and returns `recovered: false` on success.
3. If `recovered` is true, send `FD` and apply the returned board snapshot to the UI.
4. If no recovered session exists, apply the saved local state to the newly connected
   board when one exists, then show that state in the UI.
5. Start the existing health monitor. A later health failure keeps the current local
   state, reports the failure, and uses the existing FE-to-FF recovery path.

If sync times out, has an invalid CRC, or contains an unsupported snapshot version, the
client keeps the connection alive and falls back to the validated local state.

## Protocol

### Commands and response

`FD` is reserved as `SYNC_COMMAND`. It is sent as a normal CRC4-framed packet with an
empty payload and sequence zero. It is a control command like `FE`, so it does not
consume the application sequence and is handled before normal sequence classification.

`04` is reserved as `SYNC_RESPONSE`. The board returns a CRC4-framed packet using the
current expected sequence as the response sequence without advancing it. The response
is accepted only from the remembered client IP; its source port is adopted in the same
way as health recovery.

### Snapshot payload

The payload is versioned binary data so the full 144×6 matrix fits comfortably below
the 6144-byte packet limit without depending on JSON support in MicroPython:

| Field | Size | Meaning |
| --- | ---: | --- |
| version | 1 | Currently `1` |
| mode | 1 | `0` off, `1` static, `2` breathe, `3` rainbow, `4` matrix, `255` unknown |
| brightness_min | 1 | Current low brightness, `0..255` |
| brightness_max | 1 | Current peak brightness, `0..255` |
| timing | 2 | Current interval/tempo when known, otherwise `0` |
| color_count | 1 | Number of RGB colors, `0..32` |
| colors | `color_count × 3` | RGB colors used by the current effect |
| matrix_present | 1 | `0` absent, `1` followed by 864 RGB cells |
| matrix | `864 × 3` | Row-major logical matrix, black cells encoded as `0,0,0` |

All multi-byte fields use big-endian order. If the board's effect contains more than
32 colors, it reports mode `255` for sync purposes and the client keeps its local
settings rather than truncating the effect.

The board stores source RGB values rather than brightness-scaled output values. Rainbow
mode reports its mode and timing parameters only; its color generation remains entirely
inside the firmware and does not use the client's color palette.

For effects that cannot be represented by the client presets, the board reports mode
`255`. The client keeps the local settings in that case instead of guessing a mode.

## Board state tracking

The firmware maintains a lightweight snapshot beside the LED driver. Command handlers
update it when they accept a state-changing command:

- clear resets the snapshot to off;
- fill records static RGB and brightness;
- breathe records its color list and brightness range;
- rainbow records rainbow mode, brightness, and timing;
- set-pixel/show maintain the logical matrix and matrix brightness;
- unsupported animation commands mark the mode unknown while preserving safe metadata.

Snapshot writes from command/animation workers and snapshot reads from the socket
thread are protected by a small `_thread` lock. The socket thread copies the complete
snapshot under that lock before response encoding, so it cannot expose a partially
written matrix.

## Client persistence

`client/configs/ui_state.json` is written atomically through a temporary file and
`os.replace`. Its validated version-one document stores:

- output source and mode;
- brightness and speed;
- shortcut color list;
- matrix paint color;
- the 6×144 logical color matrix.

The bridge exposes `load_state()` and `save_state(state)`. The UI saves after debounced
state changes and once more from `beforeunload`; a failed save does not block shutdown.
Invalid or corrupt state files are ignored and replaced only after the next valid save.

## Error handling and compatibility

- Old boards that do not implement `FD` remain usable through health/handshake and local
  state restoration; sync failure is non-fatal.
- Old clients ignore the new response type because it is only sent after an explicit
  `FD` request.
- CRC, length, version, matrix dimensions, color count, and enum values are validated
  before state reaches the UI or the LED driver.
- No sync response is enqueued as a lighting effect and no sync operation advances the
  application sequence.

## Testing requirements

- Client protocol tests cover the FD request, framed sync response, CRC/length rejection,
  and snapshot decoding.
- Controller tests cover recovered-session sync, sync timeout fallback, and sequence
  preservation.
- Board tests cover snapshot updates, same-IP/new-port sync recovery, and bounded packet
  encoding.
- Persistence tests cover atomic round trips, corrupt files, invalid matrices, and
  unknown versions.
- Bridge/UI source tests cover startup authority selection, local fallback, shutdown
  save, and applying matrix/effect state.
- The complete Python suite, JavaScript syntax checks, and Python compilation must pass.
