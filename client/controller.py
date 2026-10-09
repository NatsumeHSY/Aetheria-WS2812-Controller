from __future__ import annotations

import socket
import threading
from collections.abc import Iterable, Sequence

try:
    from .protocol import (
        ACK,
        HANDSHAKE,
        HEALTH_ACK,
        MAINTENANCE_COMMAND,
        PARAM_BRIGHTNESS_COMMAND,
        PARAM_TIMING_COMMAND,
        RESET_STATE_COMMAND,
        RESTART_COMMAND,
        RESEND,
        SYNC_RESPONSE,
        build_health_packet,
        build_packet,
        build_sync_packet,
        decode_packet,
        next_sequence,
        parse_response,
    )
    from .sync_state import SyncSnapshot, decode_sync_snapshot
except ImportError:
    from protocol import (
        ACK,
        HANDSHAKE,
        HEALTH_ACK,
        MAINTENANCE_COMMAND,
        PARAM_BRIGHTNESS_COMMAND,
        PARAM_TIMING_COMMAND,
        RESET_STATE_COMMAND,
        RESTART_COMMAND,
        RESEND,
        SYNC_RESPONSE,
        build_health_packet,
        build_packet,
        build_sync_packet,
        decode_packet,
        next_sequence,
        parse_response,
    )
    from sync_state import SyncSnapshot, decode_sync_snapshot


class ControllerError(RuntimeError):
    pass


def _byte(value: int, name: str) -> int:
    value = int(value)
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must be between 0 and 255")
    return value


def _word(value: int, name: str) -> bytes:
    value = int(value)
    if not 0 <= value <= 0xFFFF:
        raise ValueError(f"{name} must be between 0 and 65535")
    return value.to_bytes(2, "big")


def _rgb(color: Sequence[int]) -> bytes:
    if len(color) != 3:
        raise ValueError("color must contain exactly three channels")
    return bytes(_byte(channel, "color channel") for channel in color)


class LEDController:
    def __init__(
        self,
        host: str = "192.168.4.1",
        port: int = 7807,
        timeout: float = 0.5,
        retries: int = 3,
        sock: socket.socket | None = None,
    ) -> None:
        self.host = host
        self.port = int(port)
        self.timeout = float(timeout)
        self.retries = max(1, int(retries))
        self._socket = sock
        self._owns_socket = sock is None
        self._lock = threading.RLock()
        self._sequence = 0
        self._history: dict[int, bytes] = {}
        self.connected = False
        self.last_connect_recovered = False

    @property
    def sequence(self) -> int:
        return self._sequence

    def _ensure_socket(self) -> socket.socket:
        if self._socket is None:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._owns_socket = True
        self._socket.settimeout(self.timeout)
        return self._socket

    def connect(self) -> bool:
        with self._lock:
            self.last_connect_recovered = False
            if self.health():
                self.last_connect_recovered = True
                return True

            sock = self._ensure_socket()
            for _ in range(self.retries):
                try:
                    sock.sendto(HANDSHAKE, (self.host, self.port))
                    data, _ = sock.recvfrom(32)
                    if data == b"ok":
                        self.connected = True
                        self._sequence = 0
                        self._history.clear()
                        self.last_connect_recovered = False
                        return True
                except (OSError, TimeoutError):
                    continue
        self.connected = False
        return False

    def sync(self) -> SyncSnapshot:
        with self._lock:
            if not self.connected:
                raise ControllerError("controller is not connected")

            sock = self._ensure_socket()
            packet = build_sync_packet()
            expected_sequence = self._sequence

            for _ in range(self.retries):
                try:
                    sock.sendto(packet, (self.host, self.port))
                    while True:
                        response, _ = sock.recvfrom(6144)
                        try:
                            command, response_sequence, payload = decode_packet(response)
                            if command != SYNC_RESPONSE or response_sequence != expected_sequence:
                                continue
                            return decode_sync_snapshot(payload)
                        except (ValueError, TypeError):
                            continue
                except (OSError, TimeoutError):
                    continue

            raise ControllerError("无法同步 ESP32 当前状态")

    def health(self) -> bool:
        with self._lock:
            sock = self._ensure_socket()
            packet = build_health_packet()

            for _ in range(self.retries):
                try:
                    sock.sendto(packet, (self.host, self.port))
                    while True:
                        response, _ = sock.recvfrom(32)
                        try:
                            response_type, expected_sequence = parse_response(response)
                        except ValueError:
                            continue

                        if response_type == HEALTH_ACK:
                            self._sequence = expected_sequence
                            self._history.clear()
                            self.connected = True
                            return True
                except (OSError, TimeoutError):
                    continue

            self.connected = False
            return False

    def disconnect(self) -> None:
        with self._lock:
            self.connected = False
            self._history.clear()
            if self._owns_socket and self._socket is not None:
                self._socket.close()
                self._socket = None

    def _send_packet(self, command: int, payload: bytes | bytearray | list[int]) -> int:
        with self._lock:
            if not self.connected:
                raise ControllerError("controller is not connected")

            sock = self._ensure_socket()
            sequence = self._sequence
            packet = build_packet(command, payload, sequence)
            self._history[sequence] = packet

            for _ in range(self.retries):
                try:
                    sock.sendto(packet, (self.host, self.port))
                    while True:
                        response, _ = sock.recvfrom(32)
                        try:
                            response_type, response_seq = parse_response(response)
                        except ValueError:
                            continue

                        if response_type == ACK and response_seq == sequence:
                            self._sequence = next_sequence(sequence)
                            self._history.pop(sequence, None)
                            return sequence

                        if response_type == RESEND:
                            requested = self._history.get(response_seq)
                            if requested is None:
                                raise ControllerError(
                                    f"board requested unavailable sequence {response_seq}"
                                )
                            sock.sendto(requested, (self.host, self.port))
                except (OSError, TimeoutError):
                    continue

            raise ControllerError(f"no ACK for sequence {sequence}")

    def clear(self) -> int:
        return self._send_packet(0x00, b"")

    def fill(self, color: Sequence[int], brightness: int = 255) -> int:
        return self._send_packet(0x01, bytes([_byte(brightness, "brightness")]) + _rgb(color))

    def blink(
        self,
        color: Sequence[int],
        dark_brightness: int = 0,
        bright_brightness: int = 255,
        count: int = 1,
        interval: int = 500,
    ) -> int:
        payload = (
            bytes([
                _byte(dark_brightness, "dark_brightness"),
                _byte(bright_brightness, "bright_brightness"),
                _byte(count, "count"),
            ])
            + _word(interval, "interval")
            + _rgb(color)
        )
        return self._send_packet(0x02, payload)

    def fade(self, color: Sequence[int], start_brightness: int = 0, end_brightness: int = 255) -> int:
        payload = bytes([
            _byte(start_brightness, "start_brightness"),
            _byte(end_brightness, "end_brightness"),
        ]) + _rgb(color)
        return self._send_packet(0x03, payload)

    def transition(self, target: Sequence[int], duration: int = 500) -> int:
        if len(target) != 4:
            raise ValueError("target must contain RGB and brightness")
        payload = _rgb(target[:3]) + bytes([_byte(target[3], "brightness")]) + _word(duration, "duration")
        return self._send_packet(0x09, payload)

    def breathe(
        self,
        colors: Iterable[Sequence[int]],
        dark_brightness: int = 0,
        bright_brightness: int = 255,
    ) -> int:
        color_list = list(colors)
        if not color_list:
            raise ValueError("breathe requires at least one color")
        payload = bytes([
            _byte(dark_brightness, "dark_brightness"),
            _byte(bright_brightness, "bright_brightness"),
        ]) + b"".join(_rgb(color) for color in color_list)
        return self._send_packet(0x04, payload)

    def rainbow(
        self,
        start_x: int = 0,
        end_x: int = 143,
        brightness: int = 255,
        interval: int = 500,
        duration: int = 1,
        pingpong: bool = False,
    ) -> int:
        payload = bytes([
            _byte(start_x, "start_x"),
            _byte(end_x, "end_x"),
            _byte(brightness, "brightness"),
        ]) + _word(interval, "interval") + _word(duration, "duration") + bytes([
            255 if pingpong else 0,
        ])
        return self._send_packet(0x05, payload)

    def floor_tile_x(
        self,
        color: Sequence[int],
        start_x: int = 0,
        end_x: int = 143,
        brightness: int = 255,
        loop: bool = False,
        fade: bool = True,
        fade_reverse: bool = False,
        duration: int = 1,
        fade_delay: int = 1,
        interval: int = 500,
    ) -> int:
        payload = bytes([
            _byte(start_x, "start_x"),
            _byte(end_x, "end_x"),
            _byte(brightness, "brightness"),
            255 if loop else 0,
            255 if fade else 0,
            255 if fade_reverse else 0,
        ]) + _word(duration, "duration") + _word(fade_delay, "fade_delay") + _word(interval, "interval") + _rgb(color)
        return self._send_packet(0x06, payload)

    def set_pixels(self, pixels: Iterable[Sequence[int]], coordinate_mode: bool = True) -> int:
        payload = bytearray([1 if coordinate_mode else 0])
        for pixel in pixels:
            if len(pixel) != 6:
                raise ValueError("each pixel must be (x_or_index, y, brightness, r, g, b)")
            first, second, brightness, red, green, blue = pixel
            payload.extend([
                _byte(first, "pixel coordinate"),
                _byte(second, "pixel coordinate"),
                _byte(brightness, "brightness"),
                _byte(red, "red"),
                _byte(green, "green"),
                _byte(blue, "blue"),
            ])
        if len(payload) < 7:
            raise ValueError("set_pixels requires at least one pixel")
        return self._send_packet(0x07, payload)

    def show(self) -> int:
        return self._send_packet(0x08, b"")

    def enter_maintenance(self) -> int:
        """Stop board-side work after ACK and release the client socket."""
        sequence = self._send_packet(MAINTENANCE_COMMAND[0], b"")
        lock = getattr(self, "_lock", None)
        if lock is None:
            self.connected = False
            self._history.clear()
            if self._owns_socket and self._socket is not None:
                self._socket.close()
                self._socket = None
            return sequence

        with lock:
            self.connected = False
            self._history.clear()
            if self._owns_socket and self._socket is not None:
                self._socket.close()
                self._socket = None
        return sequence

    def set_brightness(self, brightness: int) -> int:
        return self._send_packet(
            PARAM_BRIGHTNESS_COMMAND[0],
            bytes([_byte(brightness, "brightness")]),
        )

    def set_timing(self, timing_ms: int) -> int:
        timing_ms = int(timing_ms)
        if not 1 <= timing_ms <= 0xFFFF:
            raise ValueError("timing_ms must be between 1 and 65535")
        return self._send_packet(
            PARAM_TIMING_COMMAND[0],
            timing_ms.to_bytes(2, "big"),
        )

    def restart(self) -> int:
        """Ask the board to ACK and then restart without deleting saved state."""
        sequence = self._send_packet(RESTART_COMMAND[0], b"")
        self.disconnect()
        return sequence

    def reset_state(self) -> int:
        """Ask the board to delete saved state, ACK, and then restart."""
        sequence = self._send_packet(RESET_STATE_COMMAND[0], b"")
        self.disconnect()
        return sequence
