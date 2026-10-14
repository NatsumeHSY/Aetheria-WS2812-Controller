try:
    from .config import (
        MAX_PACKET_SIZE,
        PROTOCOL_HEADER_SIZE,
        PROTOCOL_TRAILER_SIZE,
        SOCKET_MAGIC,
    )
except ImportError:
    from config import (
        MAX_PACKET_SIZE,
        PROTOCOL_HEADER_SIZE,
        PROTOCOL_TRAILER_SIZE,
        SOCKET_MAGIC,
    )


def next_sequence(seq: int) -> int:
    return (seq + 1) & 0xffff


def crc4_itu(value: int) -> int:
    crc = 0
    value &= 0xff

    for bit in range(8):
        mix = ((value >> (7 - bit)) & 1) ^ ((crc >> 3) & 1)
        crc = (crc << 1) & 0x0f
        if mix:
            crc ^= 0x03

    return crc


def calculate_packet_crc(seq: int, payload: list) -> int:
    xor_value = ((seq >> 8) & 0xff) ^ (seq & 0xff)
    for value in payload:
        xor_value ^= value & 0xff
    return crc4_itu(xor_value)


def validate_packet(data: bytes) -> tuple[bool, bytes | None, int | None, list | None]:
    if len(data) < PROTOCOL_HEADER_SIZE + PROTOCOL_TRAILER_SIZE or len(data) > MAX_PACKET_SIZE:
        return False, None, None, None
    if data[:2] != SOCKET_MAGIC:
        return False, None, None, None

    command = data[2:3]
    length = int.from_bytes(data[3:5], "big")
    seq = int.from_bytes(data[5:7], "big")

    if len(data) != PROTOCOL_HEADER_SIZE + length + PROTOCOL_TRAILER_SIZE:
        return False, None, None, None

    payload = list(data[PROTOCOL_HEADER_SIZE:-PROTOCOL_TRAILER_SIZE])
    checksum = data[-1]
    if checksum > 0x0f or checksum != calculate_packet_crc(seq, payload):
        return False, None, None, None

    return True, command, seq, payload


def classify_sequence(expected: int | None, received: int) -> tuple[str, int]:
    if expected is None:
        return "accept", next_sequence(received)

    distance = (received - expected) & 0xffff
    if distance == 0:
        return "accept", next_sequence(received)
    if distance < 0x8000:
        return "gap", expected
    return "replay", expected


def restore_health_session(
    remembered_addr: tuple[str, int] | None,
    received_addr: tuple[str, int],
    expected_seq: int | None,
) -> tuple[bool, tuple[str, int] | None, int]:
    next_expected = 0 if expected_seq is None else expected_seq
    if remembered_addr is None or remembered_addr[0] != received_addr[0]:
        return False, remembered_addr, next_expected
    return True, received_addr, next_expected
