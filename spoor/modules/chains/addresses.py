"""Canonical forms for addresses and transaction hashes, per chain family.

Every address and hash that enters the database passes through these functions,
so equality checks anywhere in Spoor are plain string comparisons.

- EVM addresses: lowercase, 0x-prefixed, 20 bytes.
- TRON addresses: base58check (the `T...` form explorers show). Hex input, with
  the 0x41 prefix or as a bare 20-byte EVM-style value from event logs, is converted.
- EVM tx hashes: lowercase, 0x-prefixed, 32 bytes.
- TRON tx hashes: lowercase hex, 32 bytes, no prefix (as TronGrid and Tronscan show them).
"""

import hashlib
import re

from spoor.modules.chains.enums import ChainFamily

BASE58_ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
TRON_ADDRESS_PREFIX = b"\x41"

HEX_20_BYTES = re.compile(r"^(0x)?([0-9a-fA-F]{40})$")
TRON_HEX = re.compile(r"^(0x)?41([0-9a-fA-F]{40})$")
HEX_32_BYTES = re.compile(r"^(0x)?([0-9a-fA-F]{64})$")


class InvalidAddressError(ValueError):
    pass


class InvalidTxHashError(ValueError):
    pass


def normalize_address(family, value):
    value = value.strip()
    if family == ChainFamily.EVM:
        return normalize_evm_address(value)
    if family == ChainFamily.TRON:
        return normalize_tron_address(value)
    raise InvalidAddressError(f"Unsupported chain family: {family}")


def is_tx_hash(value):
    """True for a 32-byte hex value. Addresses are 20 bytes or base58, so this never matches one."""
    return bool(HEX_32_BYTES.match(value.strip()))


def normalize_tx_hash(family, value):
    match = HEX_32_BYTES.match(value.strip())
    if not match:
        raise InvalidTxHashError(f"Not a 32-byte transaction hash: {value!r}")
    digest = match.group(2).lower()
    return f"0x{digest}" if family == ChainFamily.EVM else digest


def normalize_evm_address(value):
    match = HEX_20_BYTES.match(value)
    if not match or not match.group(1):
        raise InvalidAddressError(f"Not an EVM address: {value!r}")
    return f"0x{match.group(2).lower()}"


def normalize_tron_address(value):
    if value.startswith("T"):
        payload = base58check_decode(value)
        if len(payload) != 21 or payload[:1] != TRON_ADDRESS_PREFIX:
            raise InvalidAddressError(f"Not a TRON address: {value!r}")
        return value

    match = TRON_HEX.match(value) or HEX_20_BYTES.match(value)
    if not match:
        raise InvalidAddressError(f"Not a TRON address: {value!r}")
    return base58check_encode(TRON_ADDRESS_PREFIX + bytes.fromhex(match.group(2)))


def base58check_encode(payload):
    return base58_encode(payload + double_sha256(payload)[:4])


def base58check_decode(value):
    raw = base58_decode(value)
    payload, checksum = raw[:-4], raw[-4:]
    if len(raw) < 5 or double_sha256(payload)[:4] != checksum:
        raise InvalidAddressError(f"Bad base58check checksum: {value!r}")
    return payload


def base58_encode(data):
    number = int.from_bytes(data, "big")
    encoded = ""
    while number:
        number, remainder = divmod(number, 58)
        encoded = BASE58_ALPHABET[remainder] + encoded
    leading_zeros = len(data) - len(data.lstrip(b"\x00"))
    return "1" * leading_zeros + encoded


def base58_decode(value):
    number = 0
    for char in value:
        index = BASE58_ALPHABET.find(char)
        if index < 0:
            raise InvalidAddressError(f"Invalid base58 character {char!r} in {value!r}")
        number = number * 58 + index
    leading_zeros = len(value) - len(value.lstrip("1"))
    return b"\x00" * leading_zeros + number.to_bytes((number.bit_length() + 7) // 8, "big")


def double_sha256(data):
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()
