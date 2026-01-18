from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Iterable, List, Optional


@dataclass(frozen=True)
class DecodedIR:
    protocol: str
    address: str
    command: str
    bits: int


def decode_raw_timings(samples: Iterable[int]) -> Optional[DecodedIR]:
    timings = _normalize_timings(list(samples))
    if len(timings) < 6:
        return None
    for decoder in (
        _decode_nec,
        _decode_nec_ext,
        _decode_samsung,
        _decode_jvc,
        _decode_sony,
        _decode_rc5,
        _decode_rc6,
        _decode_kaseikyo,
        _decode_rcmm,
        _decode_sharp,
        _decode_sanyo,
        _decode_xmp,
    ):
        decoded = decoder(timings)
        if decoded:
            return decoded
    return None


def _normalize_timings(samples: List[int]) -> List[int]:
    if not samples:
        return []
    signed = [value for value in samples if value != 0]
    if not signed:
        return []
    if signed[0] < 0:
        signed = signed[1:]
    abs_values = [abs(value) for value in signed]
    if len(abs_values) % 2 == 1:
        abs_values = abs_values[:-1]
    if abs_values and abs_values[-1] > 15000:
        abs_values = abs_values[:-1]
        if len(abs_values) % 2 == 1:
            abs_values = abs_values[:-1]
    return abs_values


def _approx(value: int, target: int, tolerance: float = 0.3) -> bool:
    if target <= 0:
        return False
    return abs(value - target) <= target * tolerance


def _match_us(value: int, target: int, tolerance_us: int) -> bool:
    return abs(value - target) <= tolerance_us


def _bits_to_int(bits: List[int], lsb_first: bool = True) -> int:
    if lsb_first:
        total = 0
        for idx, bit in enumerate(bits):
            if bit:
                total |= 1 << idx
        return total
    total = 0
    for bit in bits:
        total = (total << 1) | (1 if bit else 0)
    return total


def _format_bytes(values: List[int]) -> str:
    return " ".join(f"{value:02X}" for value in values) or "00"


def _decode_nec(samples: List[int]) -> Optional[DecodedIR]:
    if len(samples) < 2:
        return None
    pulse, space = samples[0], samples[1]
    if not (_match_us(pulse, 9000, 200) and _match_us(space, 4500, 200)):
        return None
    bits = _decode_pulse_distance(samples[2:], 560, 560, 1690, 32, 120)
    if not bits or len(bits) < 32:
        return None
    bytes_ = [_bits_to_int(bits[i : i + 8]) for i in range(0, 32, 8)]
    if (bytes_[0] ^ 0xFF) == bytes_[1] and (bytes_[2] ^ 0xFF) == bytes_[3]:
        address = _format_bytes([bytes_[0]])
        command = _format_bytes([bytes_[2]])
        return DecodedIR("NEC", address, command, 32)
    return None


def _decode_nec_ext(samples: List[int]) -> Optional[DecodedIR]:
    if len(samples) < 2:
        return None
    pulse, space = samples[0], samples[1]
    if not (_match_us(pulse, 9000, 200) and _match_us(space, 4500, 200)):
        return None
    bits = _decode_pulse_distance(samples[2:], 560, 560, 1690, 32, 120)
    if not bits or len(bits) < 32:
        return None
    bytes_ = [_bits_to_int(bits[i : i + 8]) for i in range(0, 32, 8)]
    address = _format_bytes(bytes_[:2])
    command = _format_bytes(bytes_[2:4])
    return DecodedIR("NECext", address, command, 32)


def _decode_samsung(samples: List[int]) -> Optional[DecodedIR]:
    if len(samples) < 2:
        return None
    pulse, space = samples[0], samples[1]
    if not (_match_us(pulse, 4500, 200) and _match_us(space, 4500, 200)):
        return None
    bits = _decode_pulse_distance(samples[2:], 550, 550, 1650, 32, 120)
    if not bits or len(bits) < 32:
        return None
    bytes_ = [_bits_to_int(bits[i : i + 8]) for i in range(0, 32, 8)]
    address = _format_bytes(bytes_[:2])
    command = _format_bytes(bytes_[2:4])
    return DecodedIR("Samsung32", address, command, 32)


def _decode_jvc(samples: List[int]) -> Optional[DecodedIR]:
    if len(samples) < 2:
        return None
    pulse, space = samples[0], samples[1]
    if not (_approx(pulse, 8400, 0.25) and _approx(space, 4200, 0.3)):
        return None
    bits = _decode_pulse_distance(samples[2:], 525, 525, 1575, 16, 120)
    if not bits or len(bits) < 16:
        return None
    addr = _bits_to_int(bits[0:8])
    cmd = _bits_to_int(bits[8:16])
    address = _format_bytes([addr])
    command = _format_bytes([cmd])
    return DecodedIR("JVC", address, command, 16)


def _decode_sony(samples: List[int]) -> Optional[DecodedIR]:
    if len(samples) < 2:
        return None
    pulse, space = samples[0], samples[1]
    if not (_match_us(pulse, 2400, 200) and _match_us(space, 600, 120)):
        return None
    bits: List[int] = []
    index = 2
    while index + 1 < len(samples):
        pulse = samples[index]
        space = samples[index + 1]
        if not _match_us(space, 600, 120):
            break
        if _match_us(pulse, 600, 120):
            bits.append(0)
        elif _match_us(pulse, 1200, 120):
            bits.append(1)
        else:
            break
        index += 2
    if len(bits) not in {12, 15, 20}:
        return None
    command = _bits_to_int(bits[:7])
    address_bits = bits[7:]
    address = _format_int_bytes(_bits_to_int(address_bits), len(address_bits))
    protocol = {12: "SIRC", 15: "SIRC15", 20: "SIRC20"}[len(bits)]
    return DecodedIR(protocol, address, _format_bytes([command]), len(bits))


def _decode_rc5(samples: List[int]) -> Optional[DecodedIR]:
    levels = _timings_to_levels(samples, expected_unit=889)
    if not levels:
        return None
    for offset in (0, 1):
        bits = _levels_to_bits(levels[offset:])
        if len(bits) < 14:
            continue
        if bits[0] != 1 or bits[1] != 1:
            continue
        address = _bits_to_int(bits[3:8], lsb_first=False)
        command = _bits_to_int(bits[8:14], lsb_first=False)
        if bits[1] == 0:
            command |= 0x40
        return DecodedIR("RC5", _format_bytes([address]), _format_bytes([command]), 14)
    return None


def _decode_rc6(samples: List[int]) -> Optional[DecodedIR]:
    if len(samples) < 4:
        return None
    pulse, space = samples[0], samples[1]
    if not (_match_us(pulse, 2666, 200) and _match_us(space, 889, 120)):
        return None
    levels = _timings_to_levels(samples[2:], expected_unit=444)
    if not levels or len(levels) < 40:
        return None
    bits = _levels_to_bits(levels)
    if len(bits) < 20:
        return None
    if bits[0] != 1:
        return None
    mode = _bits_to_int(bits[1:4], lsb_first=False)
    if mode != 0:
        return None
    toggle = bits[4]
    address = _bits_to_int(bits[5:13], lsb_first=False)
    command = _bits_to_int(bits[13:21], lsb_first=False)
    if toggle:
        command |= 0x100
    return DecodedIR("RC6", _format_bytes([address]), _format_bytes([command & 0xFF]), 20)


def _decode_kaseikyo(samples: List[int]) -> Optional[DecodedIR]:
    if len(samples) < 2:
        return None
    pulse, space = samples[0], samples[1]
    if not (_approx(pulse, 3500, 0.3) and _approx(space, 1750, 0.3)):
        return None
    bits = _decode_pulse_distance(samples[2:], 432, 432, 1296, 48, 120)
    if not bits or len(bits) < 48:
        return None
    values = [_bits_to_int(bits[i : i + 8]) for i in range(0, 48, 8)]
    address = _format_bytes(values[:2])
    command = _format_bytes(values[2:4])
    return DecodedIR("Kaseikyo", address, command, 48)


def _decode_rcmm(samples: List[int]) -> Optional[DecodedIR]:
    if len(samples) < 4:
        return None
    pulse, space = samples[0], samples[1]
    if not (_approx(pulse, 416, 0.4) and _approx(space, 278, 0.5)):
        return None
    symbols: List[int] = []
    index = 2
    while index + 1 < len(samples):
        pulse = samples[index]
        space = samples[index + 1]
        if not _approx(pulse, 416, 0.5):
            break
        if _approx(space, 444, 0.4):
            symbols.append(0)
        elif _approx(space, 889, 0.35):
            symbols.append(1)
        elif _approx(space, 1333, 0.35):
            symbols.append(2)
        elif _approx(space, 1778, 0.35):
            symbols.append(3)
        else:
            break
        index += 2
    if len(symbols) < 6:
        return None
    bits: List[int] = []
    for symbol in symbols:
        bits.extend([(symbol >> 1) & 1, symbol & 1])
    if len(bits) < 16:
        return None
    address = _bits_to_int(bits[:8], lsb_first=False)
    command = _bits_to_int(bits[8:16], lsb_first=False)
    return DecodedIR("RCMM", _format_bytes([address]), _format_bytes([command]), len(bits))


def _decode_sharp(samples: List[int]) -> Optional[DecodedIR]:
    if len(samples) < 2:
        return None
    pulse, space = samples[0], samples[1]
    if not (_approx(pulse, 320, 0.5) and _approx(space, 1600, 0.4)):
        return None
    bits = _decode_pulse_distance(samples[2:], 320, 320, 680, 15)
    if not bits or len(bits) < 15:
        return None
    address = _bits_to_int(bits[:5], lsb_first=False)
    command = _bits_to_int(bits[5:13], lsb_first=False)
    return DecodedIR("Sharp", _format_bytes([address]), _format_bytes([command]), 15)


def _decode_sanyo(samples: List[int]) -> Optional[DecodedIR]:
    if len(samples) < 2:
        return None
    pulse, space = samples[0], samples[1]
    if not (_match_us(pulse, 9000, 200) and _match_us(space, 4500, 200)):
        return None
    bits = _decode_pulse_distance(samples[2:], 560, 560, 1690, 42, 120)
    if not bits or len(bits) < 42:
        return None
    values = [_bits_to_int(bits[i : i + 8]) for i in range(0, 40, 8)]
    address = _format_bytes(values[:2])
    command = _format_bytes(values[2:4])
    return DecodedIR("Sanyo", address, command, 42)


def _decode_xmp(samples: List[int]) -> Optional[DecodedIR]:
    if len(samples) < 2:
        return None
    pulse, space = samples[0], samples[1]
    if not (_approx(pulse, 2090, 0.3) and _approx(space, 780, 0.35)):
        return None
    bits = _decode_pulse_distance(samples[2:], 780, 390, 1170, 32, 120)
    if not bits or len(bits) < 32:
        return None
    values = [_bits_to_int(bits[i : i + 8]) for i in range(0, 32, 8)]
    address = _format_bytes(values[:2])
    command = _format_bytes(values[2:4])
    return DecodedIR("XMP", address, command, 32)


def _decode_pulse_distance(
    samples: List[int],
    pulse_us: int,
    zero_space_us: int,
    one_space_us: int,
    expected_bits: int,
    tolerance_us: int,
) -> Optional[List[int]]:
    bits: List[int] = []
    index = 0
    while index + 1 < len(samples) and len(bits) < expected_bits:
        pulse = samples[index]
        space = samples[index + 1]
        if not _match_us(pulse, pulse_us, tolerance_us):
            break
        if _match_us(space, zero_space_us, tolerance_us):
            bits.append(0)
        elif _match_us(space, one_space_us, tolerance_us):
            bits.append(1)
        else:
            break
        index += 2
    if len(bits) < expected_bits:
        return None
    return bits


def _estimate_unit(samples: List[int], expected_unit: int) -> int:
    candidates = [value for value in samples if 200 <= value <= 2000]
    if not candidates:
        return expected_unit
    return int(median(candidates))


def _timings_to_levels(samples: List[int], expected_unit: int) -> List[int]:
    unit = _estimate_unit(samples, expected_unit)
    levels: List[int] = []
    for idx, duration in enumerate(samples):
        level = 1 if idx % 2 == 0 else 0
        count = max(1, int(round(duration / unit)))
        if count > 4:
            count = 4
        levels.extend([level] * count)
    return levels


def _levels_to_bits(levels: List[int]) -> List[int]:
    bits: List[int] = []
    pairs = len(levels) // 2
    for idx in range(pairs):
        first = levels[idx * 2]
        second = levels[idx * 2 + 1]
        if first == second:
            return []
        bits.append(1 if first == 1 and second == 0 else 0)
    return bits


def _format_int_bytes(value: int, bit_count: int) -> str:
    byte_len = max(1, (bit_count + 7) // 8)
    values = [(value >> (8 * (byte_len - 1 - idx))) & 0xFF for idx in range(byte_len)]
    return _format_bytes(values)
