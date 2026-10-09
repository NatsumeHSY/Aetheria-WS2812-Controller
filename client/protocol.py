from __future__ import annotations


MAGIC = b"LD"
HANDSHAKE = MAGIC + b"\xF0\x00\x00\x00\x00"
HEADER_SIZE = 7
TRAILER_SIZE = 1
MAX_PACKET_SIZE = 6144
ACK = b"\x01"
RESEND = b"\x02"
HEALTH_ACK = b"\x03"
HEALTH_COMMAND = b"\xF1"
SYNC_RESPONSE = b"\x04"
SYNC_COMMAND = b"\xF2"
MAINTENANCE_COMMAND = b"\xF3"
RESTART_COMMAND = b"\xF4"
RESET_STATE_COMMAND = b"\xF5"
PARAM_BRIGHTNESS_COMMAND = b"\xA0"
PARAM_TIMING_COMMAND = b"\xA1"
PARAM_WHITE_BALANCE_COMMAND = b"\xA2"


class PacketError(ValueError):
    """Raised when a packet does not match the LED controller protocol."""


def _byte(value: int, name: str) -> int:
    value = int(value)
    if not 0 <= value <= 0xFF:
        raise ValueError(f"{name} must fit in one byte")
    return value


def next_sequence(seq: int) -> int:
    return (seq + 1) & 0xFFFF


def crc4_itu(value: int) -> int:
    crc = 0
    value &= 0xFF

    for bit in range(8):
        mix = ((value >> (7 - bit)) & 1) ^ ((crc >> 3) & 1)
        crc = (crc << 1) & 0x0F
        if mix:
            crc ^= 0x03

    return crc


def packet_crc(seq: int, payload: bytes | bytearray | list[int]) -> int:
    xor_value = ((seq >> 8) & 0xFF) ^ (seq & 0xFF)
    for value in payload:
        xor_value ^= value & 0xFF
    return crc4_itu(xor_value)


def build_packet(command: int, payload: bytes | bytearray | list[int], seq: int) -> bytes:
    if not 0 <= command <= 0xFF:
        raise ValueError("command must fit in one byte")
    if not 0 <= seq <= 0xFFFF:
        raise ValueError("sequence must fit in two bytes")

    payload_bytes = bytes(payload)
    if len(payload_bytes) > 0xFFFF:
        raise ValueError("payload is too large")

    packet = (
        MAGIC
        + bytes([command])
        + len(payload_bytes).to_bytes(2, "big")
        + seq.to_bytes(2, "big")
        + payload_bytes
        + bytes([packet_crc(seq, payload_bytes)])
    )
    if len(packet) > MAX_PACKET_SIZE:
        raise ValueError("packet exceeds controller receive limit")
    return packet


def build_health_packet() -> bytes:
    return build_packet(HEALTH_COMMAND[0], b"", 0)


def build_sync_packet() -> bytes:
    return build_packet(SYNC_COMMAND[0], b"", 0)


def build_maintenance_packet(sequence: int = 0) -> bytes:
    return build_packet(MAINTENANCE_COMMAND[0], b"", sequence)


def build_restart_packet(sequence: int = 0) -> bytes:
    return build_packet(RESTART_COMMAND[0], b"", sequence)


def build_reset_state_packet(sequence: int = 0) -> bytes:
    return build_packet(RESET_STATE_COMMAND[0], b"", sequence)


def build_brightness_packet(brightness: int, sequence: int = 0) -> bytes:
    if not 0 <= int(brightness) <= 0xFF:
        raise ValueError("brightness must fit in one byte")
    return build_packet(PARAM_BRIGHTNESS_COMMAND[0], bytes([int(brightness)]), sequence)


def build_timing_packet(timing_ms: int, sequence: int = 0) -> bytes:
    timing_ms = int(timing_ms)
    if not 1 <= timing_ms <= 0xFFFF:
        raise ValueError("timing_ms must be between 1 and 65535")
    return build_packet(PARAM_TIMING_COMMAND[0], timing_ms.to_bytes(2, "big"), sequence)


def build_white_balance_packet(red: int, green: int, blue: int, sequence: int = 0) -> bytes:
    return build_packet(
        PARAM_WHITE_BALANCE_COMMAND[0],
        bytes([
            _byte(red, "white balance red"),
            _byte(green, "white balance green"),
            _byte(blue, "white balance blue"),
        ]),
        sequence,
    )


def decode_packet(data: bytes) -> tuple[bytes, int, list[int]]:
    if len(data) < HEADER_SIZE + TRAILER_SIZE or len(data) > MAX_PACKET_SIZE:
        raise PacketError("invalid packet size")
    if data[:2] != MAGIC:
        raise PacketError("invalid packet magic")

    command = data[2:3]
    payload_length = int.from_bytes(data[3:5], "big")
    seq = int.from_bytes(data[5:7], "big")
    expected_size = HEADER_SIZE + payload_length + TRAILER_SIZE
    if len(data) != expected_size:
        raise PacketError("invalid payload length")

    payload = list(data[HEADER_SIZE:-TRAILER_SIZE])
    checksum = data[-1]
    if checksum > 0x0F or checksum != packet_crc(seq, payload):
        raise PacketError("invalid CRC4")
    return command, seq, payload


def parse_response(data: bytes) -> tuple[bytes, int]:
    if len(data) != 5 or data[:2] != MAGIC or data[2:3] not in (ACK, RESEND, HEALTH_ACK):
        raise PacketError("invalid controller response")
    return data[2:3], int.from_bytes(data[3:5], "big")
