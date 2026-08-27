"""Discovers a Companion remote's rf_addresses.json pair without a
genuine Harmony Hub.
As a fallback, get_remote_address.py can be used
which gets the same result by pairing against the real Harmony hub.


The pair is two addresses differing in exactly one byte: an arbitrary,
hub-assigned byte and 0x00, over an otherwise shared 4-byte remainder
- e.g. 1e9c9bc1c6 / 009c9bc1c6.

Step 1 finds the shared bytes by sniffing: address_width
set to an "illegal" 2 bytes matching 0x00AA (or 0x0055 - the polarity
is unit-specific), CRC and auto-ack off, so the radio latches onto a
preamble followed by a literal 0x00 first address byte.

Step 2 finds the hub-assigned byte using real 5-byte addressing with
hardware CRC-16, the way RfInput does, so anything received has
matched a full address and passed CRC. The remote hands the byte over
directly: every packet carries its counterpart address's leading byte
in payload[0], so a packet on the known 0x00 address names the
hub-assigned one. That is still
inferred from payload structure, so it is treated as a hint and proven
before use, with a sweep of all 255 candidates alongside as the
backstop - the nRF24 requires pipes 1-5 to share their top 4 bytes and
differ only in the byte at array index 0, exactly the unknown byte, so
four are tested per round.

Step 3 simulates RfInput to validate the captured addresses.

Usage:
    python -m rf_manager.discover_remote_address
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, deque
from datetime import datetime
from pathlib import Path

from pyrf24 import RF24, RF24_2MBPS, RF24_CRC_16, RF24_CRC_DISABLED

CSN_PIN = 0  # aka CE0 on SPI bus 0: /dev/spidev0.0
CE_PIN = 1
CHANNEL = 5  # matches RfInput's fixed regular-operation channel - see rf_manager.py

_ADDRESSES_PATH = "config/rf_addresses.json"
_KEYMAP_PATH = "config/remote_keymap.json"
# Checked in order before falling back to the download - setup_host.sh
# can run without cloning, so the repo copy may not be there.
_KEYMAP_LOCAL_PATHS = (_KEYMAP_PATH, "Extras/Config Examples/remote_keymap.json")
_KEYMAP_URL = ("https://raw.githubusercontent.com/LeoKlaus/Equilibrium/main/"
               "Extras/Config%20Examples/remote_keymap.json")
_KEYMAP_TIMEOUT = 15.0
# Button to ask for at the end, if the keymap has it; otherwise the
# keymap's first entry is used.
_PREFERRED_BUTTON = "ok"

_CONFIRMATIONS_NEEDED = 2
_DEFAULT_TIMEOUT = 120.0
_STATUS_INTERVAL = 10.0

# Step 1
_PREAMBLES = (0xAA, 0x55)
_PREAMBLE_DWELL = 4.0
_ADDRESS_BITS = 40
_PCF_BITS = 9  # 6-bit length + 2-bit PID + 1-bit NO_ACK
_PREFIX_BITS = _ADDRESS_BITS + _PCF_BITS
_CRC_POLY = 0x1021
_CRC_INIT = 0xFFFF
# The remote always seems to use a payload length of 10
_MIN_PAYLOAD_LEN = 9
_MAX_PAYLOAD_LEN = 11
_MAX_START_BIT = 192

# Step 2
_CONTROL_PIPE = 1  # the known 0x00 address
_CANDIDATE_PIPES = (2, 3, 4, 5)
_DEFAULT_DWELL = 1.5  # seconds per sweep round - the idle heartbeat is ~1/s
_PROVE_SECONDS = 15.0

_REMINDER_SECONDS = 15.0
_MAX_LINES_SHOWN = 10
_MESSAGES_WANTED = 3  # only used when there is no keymap to name a button from

# rf_manager.py's _decode() protocol-level status codes, enough to name
# what arrives without needing remote_keymap.json.
_PROTOCOL_NAMES: dict[int, str] = {
    0x40044C: "idle",
    0x4F0300: "going to sleep",
    0x4F0700: "woke up",
    0x400028: "button held",
    0x4F0004: "all buttons released",
    0xC10000: "button released",
    0xC30000: "button released",
}


def _command_of(payload: bytes) -> int | None:
    """The 3-byte command rf_manager's _decode() reads from a payload."""
    if len(payload) < 4:
        return None
    return int.from_bytes(payload[1:4], "big")


def _describe(payload: bytes, names: dict[int, str]) -> str:
    command = _command_of(payload)
    if command is None:
        return "unrecognised message"
    return names.get(command, "button press")


def _read_keymap(text: str) -> dict[str, int]:
    """{button name: command} from a remote_keymap.json, keeping file
    order so "the first button" means what it looks like in the file."""
    keymap = {}
    for name, entry in json.loads(text).items():
        command = entry.get("rf_command")
        if command:
            keymap[name] = int(command, 16)
    return keymap


def _load_keymap() -> dict[str, int]:
    """Uses a local remote_keymap.json if there is one, otherwise
    fetches the stock one from the project repo and saves it to
    config/ - the app needs it there anyway. Returns {} if it cannot
    be had, which only costs the button prompt in step 3."""
    for candidate in _KEYMAP_LOCAL_PATHS:
        path = Path(candidate)
        if path.is_file():
            try:
                return _read_keymap(path.read_text())
            except (ValueError, AttributeError):
                print(f"  {candidate} is not readable as a keymap - ignoring it.")

    print(f"  No {_KEYMAP_PATH} yet - downloading the standard one for the Harmony Companion remote...")
    try:
        with urllib.request.urlopen(_KEYMAP_URL, timeout=_KEYMAP_TIMEOUT) as response:
            text = response.read().decode("utf-8")
        keymap = _read_keymap(text)
    except (urllib.error.URLError, ValueError, UnicodeDecodeError, OSError) as error:
        print(f"  Couldn't download it ({error}). Carrying on without it.")
        return {}

    Path("config").mkdir(parents=True, exist_ok=True)
    Path(_KEYMAP_PATH).write_text(text)
    print(f"  Saved {_KEYMAP_PATH} ({len(keymap)} buttons).")
    return keymap


def _pick_button(keymap: dict[str, int]) -> tuple[str, int] | None:
    """The button to ask the user to press: OK if the keymap has one,
    otherwise whichever comes first in the file."""
    for name in keymap:
        if name.strip().lower() == _PREFERRED_BUTTON:
            return name, keymap[name]
    for name in keymap:
        return name, keymap[name]
    return None


def _bytes_to_bits(data: bytes) -> list[int]:
    return [(byte >> i) & 1 for byte in data for i in range(7, -1, -1)]


def _bits_to_int(bits: list[int]) -> int:
    value = 0
    for bit in bits:
        value = (value << 1) | bit
    return value


def _crc16_extend(crc: int, bits: list[int]) -> int:
    """Feeds bits into an in-progress CRC-16/CCITT-FALSE (poly=0x1021,
    init=0xFFFF) - verified against the reference vector
    CRC16("123456789") == 0x29B1. Incremental so the framing search
    below doesn't restart it for every candidate payload length."""
    for bit in bits:
        msb = (crc >> 15) & 1
        crc = (crc << 1) & 0xFFFF
        if msb ^ bit:
            crc ^= _CRC_POLY
    return crc


def _find_addresses(capture: bytes) -> list[bytes]:
    """Returns the address of every framing in a promiscuous capture
    whose real nRF24 CRC-16 validates, byte-reversed to the order
    openReadingPipe() expects. Searches every starting bit, not just
    byte-aligned ones, since address+PCF is 49 bits."""
    bits = _bytes_to_bits(capture)
    total = len(bits)
    found = []
    for start in range(_MAX_START_BIT):
        if start + _PREFIX_BITS > total:
            break
        crc = _crc16_extend(_CRC_INIT, bits[start:start + _PREFIX_BITS])
        pos = start + _PREFIX_BITS
        for payload_len in range(_MAX_PAYLOAD_LEN + 1):
            if pos + 16 > total:
                break
            if payload_len >= _MIN_PAYLOAD_LEN and crc == _bits_to_int(bits[pos:pos + 16]):
                address = bytes(_bits_to_int(bits[i:i + 8])
                                for i in range(start, start + _ADDRESS_BITS, 8))
                found.append(address[::-1])
            if pos + 8 > total:
                break
            crc = _crc16_extend(crc, bits[pos:pos + 8])
            pos += 8
    return found


def _init_promiscuous(radio: RF24, preamble: int) -> None:
    # begin() first: it opens the GPIO/SPI pins, so nothing else may
    # touch the radio before it - including stopListening().
    if not radio.begin():
        raise OSError("nRF24L01 hardware isn't responding")
    radio.stopListening()
    radio.setChannel(CHANNEL)
    radio.setDataRate(RF24_2MBPS)
    radio.set_auto_ack(False)
    radio.crc_length = RF24_CRC_DISABLED
    radio.address_width = 2  # "illegal" per the datasheet, but that's the trick
    radio.payload_size = 32  # dynamic payload framing is meaningless without CRC
    radio.openReadingPipe(1, bytes([0x00, preamble]))
    radio.startListening()


def _find_shared_bytes(radio: RF24, timeout: float) -> bytes | None:
    """Promiscuous scan until the same 0x00-prefixed address has been
    CRC-recovered _CONFIRMATIONS_NEEDED times; returns its 4 shared
    bytes. Alternates preamble polarity until something validates -
    the wrong one captures nothing from a given remote at all."""
    print("\nStep 1 of 3: looking for your remote.")
    print("  Press and release a button on the remote. If it isn't recognized, press the button again every 5-10s.")

    sightings: Counter[bytes] = Counter()
    pending: deque[bytes] = deque()
    index = 0
    locked = False
    _init_promiscuous(radio, _PREAMBLES[index])
    started = time.monotonic()
    deadline = started + timeout
    last_status = last_switch = time.monotonic()

    while time.monotonic() < deadline or pending:
        if not locked and time.monotonic() - last_switch >= _PREAMBLE_DWELL:
            last_switch = time.monotonic()
            index = (index + 1) % len(_PREAMBLES)
            radio.stopListening()
            radio.openReadingPipe(1, bytes([0x00, _PREAMBLES[index]]))
            radio.startListening()

        # Drain the RX FIFO (3 packets deep) before any per-capture
        # work - a stalled read loop drops the packets being waited for.
        if time.monotonic() < deadline:
            while radio.available():
                pending.append(bytes(radio.read(32)))

        if time.monotonic() - last_status >= _STATUS_INTERVAL:
            last_status = time.monotonic()
            print(f"  still looking ({time.monotonic() - started:.0f}s) - keep pressing buttons.")

        if not pending:
            time.sleep(0.001)
            continue

        for address in _find_addresses(pending.popleft()):
            # This sync can only latch onto a 0x00-prefixed address, so
            # anything else is a CRC fluke rather than a real recovery.
            if address[0] != 0x00:
                continue
            locked = True
            sightings[address] += 1
            print(f"  found {address.hex()} ({sightings[address]} of {_CONFIRMATIONS_NEEDED})")
            if sightings[address] >= _CONFIRMATIONS_NEEDED:
                return address[1:]

    return None


def _init_matched(radio: RF24) -> None:
    """Exactly rf_pipe_logger's setup. begin() re-inits the whole chip
    first: unwinding the promiscuous registers one by one leaves the
    radio deaf even on a known-good address, since dynamic payloads
    depend on auto-ack and several defaults change at once."""
    if not radio.begin():
        raise OSError("nRF24L01 hardware isn't responding")
    radio.stopListening()
    radio.setChannel(CHANNEL)
    radio.setDataRate(RF24_2MBPS)
    radio.enableDynamicPayloads()
    radio.setCRCLength(RF24_CRC_16)


def _listen_round(
    radio: RF24, shared: bytes, candidates: list[int], seconds: float
) -> tuple[int | None, bytes | None, int, int | None]:
    """Opens the control pipe plus one pipe per candidate and listens
    for `seconds`. Returns (candidate byte that received a packet or
    None, that packet's payload, packets seen on the control pipe,
    byte hinted by a control packet's payload[0] or None)."""
    radio.stopListening()
    for pipe in (_CONTROL_PIPE,) + _CANDIDATE_PIPES:
        radio.closeReadingPipe(pipe)
    radio.openReadingPipe(_CONTROL_PIPE, bytes([0x00]) + shared)
    for pipe, candidate in zip(_CANDIDATE_PIPES, candidates):
        radio.openReadingPipe(pipe, bytes([candidate]) + shared)
    radio.startListening()

    control_packets = 0
    hint: int | None = None
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        has_payload, pipe_number = radio.available_pipe()
        if not has_payload:
            time.sleep(0.001)
            continue
        payload = bytes(radio.read(radio.getDynamicPayloadSize()))
        if pipe_number == _CONTROL_PIPE:
            control_packets += 1
            if payload and payload[0] != 0x00 and hint is None:
                hint = payload[0]
        elif pipe_number in _CANDIDATE_PIPES:
            position = _CANDIDATE_PIPES.index(pipe_number)
            if position < len(candidates):
                return candidates[position], payload, control_packets, hint
    return None, None, control_packets, hint


def _prove(radio: RF24, shared: bytes, candidate: int, already_seen: int) -> bool:
    """Opens a pipe on candidate+shared alone and counts the packets
    the hardware accepts. Every one has matched a full 5-byte address
    and passed CRC-16, which turns a hinted byte into a proven one."""
    confirmed = already_seen
    deadline = time.monotonic() + _PROVE_SECONDS
    while confirmed < _CONFIRMATIONS_NEEDED and time.monotonic() < deadline:
        hit, _payload, _control, _hint = _listen_round(
            radio, shared, [candidate], min(2.0, deadline - time.monotonic())
        )
        if hit is not None:
            confirmed += 1
    return confirmed >= _CONFIRMATIONS_NEEDED


def _find_assigned_byte(radio: RF24, shared: bytes, timeout: float, dwell: float) -> bytes | None:
    """Listens on the known 0x00 address for a packet naming its
    counterpart, while sweeping candidate values as the backstop."""
    _init_matched(radio)
    candidates = list(range(1, 256))  # 0x00 is the control, not a candidate
    rounds = (len(candidates) + len(_CANDIDATE_PIPES) - 1) // len(_CANDIDATE_PIPES)
    print("\nStep 2 of 3: confirming remote addresses.")
    print("  Press and release a button on the remote - one press is usually enough.")

    control_total = 0
    tried: set[int] = set()
    started = time.monotonic()
    deadline = started + timeout
    last_status = time.monotonic()

    while time.monotonic() < deadline:
        for index in range(0, len(candidates), len(_CANDIDATE_PIPES)):
            remaining = min(dwell, deadline - time.monotonic())
            if remaining <= 0:
                break
            batch = candidates[index:index + len(_CANDIDATE_PIPES)]
            hit, _payload, control_packets, hint = _listen_round(radio, shared, batch, remaining)
            control_total += control_packets

            if time.monotonic() - last_status >= _STATUS_INTERVAL:
                last_status = time.monotonic()
                done = index // len(_CANDIDATE_PIPES) + 1
                print(f"  still working ({time.monotonic() - started:.0f}s, {done * 100 // rounds}% "
                      f"through this pass) - press another button.")

            for candidate, seen in ((hint, 0), (hit, 1)):
                if candidate is None or candidate in tried:
                    continue
                tried.add(candidate)
                address = bytes([candidate]) + shared
                print(f"  trying {address.hex()}...")
                if _prove(radio, shared, candidate, seen):
                    print(f"  confirmed {address.hex()}")
                    return address

    if control_total:
        print("\n  Heard the remote, but only ever on one address.")
    else:
        print("\n  Heard nothing from the remote. Make sure it is awake and close to the Pi.")
    return None


def _check_pair(radio: RF24, assigned: bytes, zeroed: bytes, keymap: dict[str, int]) -> bool:
    """Final check: both addresses open on the two pipes exactly as
    RfInput opens them, decoding payload[1:4] the way its _decode()
    does. This is what the app will do, so passing here means the
    config is usable - and nothing is written if it fails.

    Waits for one specific button, so the check ends on a deliberate
    press rather than on whatever happened to be in the air. Without a
    keymap there is no button to name, so it settles for a few
    messages including one recognised status message."""
    _init_matched(radio)
    radio.openReadingPipe(1, assigned)
    radio.openReadingPipe(2, zeroed)
    radio.startListening()

    names = dict(_PROTOCOL_NAMES)
    names.update({command: name for name, command in keymap.items()})
    wanted = _pick_button(keymap)

    print("\nStep 3 of 3: checking the addresses actually work.")
    if wanted:
        print(f"  Press the {wanted[0]} button on the remote. Ctrl+C to give up.")
    else:
        print("  Press a few buttons on the remote. Ctrl+C to give up.")

    seen: Counter[bytes] = Counter()
    recognised = 0
    started = time.monotonic()
    last_reminder = time.monotonic()

    while True:
        has_payload, pipe_number = radio.available_pipe()
        if not has_payload:
            if time.monotonic() - last_reminder >= _REMINDER_SECONDS:
                last_reminder = time.monotonic()
                if not seen:
                    print("  Nothing is coming through at all. Wake the remote and hold it near "
                          "the Pi - Ctrl+C to give up.")
                elif wanted:
                    print(f"  Still waiting for {wanted[0]} ({time.monotonic() - started:.0f}s).")
            time.sleep(0.001)
            continue

        payload = bytes(radio.read(radio.getDynamicPayloadSize()))
        command = _command_of(payload)
        address = assigned if pipe_number == 1 else zeroed
        seen[address] += 1
        recognised += command in _PROTOCOL_NAMES
        if sum(seen.values()) <= _MAX_LINES_SHOWN:  # a wrong address can flood this
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"  [{timestamp}] Received {_describe(payload, names)} on {address.hex()}")

        if wanted and command == wanted[1]:
            print(f"  Got {wanted[0]}.")
            break
        if not wanted and sum(seen.values()) >= _MESSAGES_WANTED and recognised:
            break

    for address, count in seen.items():
        print(f"  {address.hex()}: {count} message(s)")
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Find your Companion remote's addresses and save them to "
                    f"{_ADDRESSES_PATH}. No Harmony Hub needed - just the remote.",
    )
    parser.add_argument(
        "--shared", default=None,
        help="Skip step 1 by supplying the last 4 bytes of a known address. Rarely needed.",
    )
    parser.add_argument(
        "--timeout", type=float, default=_DEFAULT_TIMEOUT,
        help=f"Seconds to spend on each step before giving up (default: {_DEFAULT_TIMEOUT:.0f}).",
    )
    parser.add_argument(
        "--dwell", type=float, default=_DEFAULT_DWELL, help=argparse.SUPPRESS,
    )
    args = parser.parse_args()

    shared = None
    if args.shared:
        shared = bytes.fromhex(args.shared)
        if len(shared) != 4:
            parser.error(f"--shared needs exactly 4 bytes (8 hex chars), got {len(shared)}")

    print("Finding your remote's addresses. Have the remote to hand - you will be asked to press "
          "buttons on it a few times.")
    keymap = _load_keymap()

    radio = RF24(CE_PIN, CSN_PIN)
    try:
        if shared is None:
            shared = _find_shared_bytes(radio, args.timeout)
            if shared is None:
                print("\nCouldn't find the remote. Make sure it is awake and close to the Pi, "
                      "then run this again.")
                sys.exit(1)

        assigned = _find_assigned_byte(radio, shared, args.timeout, args.dwell)
        if assigned is None:
            print(f"\nGave up. Nothing was saved, so {_ADDRESSES_PATH} is unchanged.")
            sys.exit(1)

        zeroed = bytes([0x00]) + shared
        if not _check_pair(radio, assigned, zeroed, keymap):
            print(f"\nNothing was saved, so {_ADDRESSES_PATH} is unchanged. Try again with the "
                  "remote awake and close by.")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\nStopped. Nothing was saved.")
        sys.exit(130)  # 128 + SIGINT, the conventional exit code for Ctrl+C

    addresses = [assigned.hex(), zeroed.hex()]
    Path("config").mkdir(parents=True, exist_ok=True)
    with open(_ADDRESSES_PATH, "w") as file:
        json.dump(addresses, file, indent=4)

    print(f"\nDone. Your remote's addresses are {assigned.hex()} and {zeroed.hex()},")
    print(f"saved to {_ADDRESSES_PATH}. You can start Equilibrium now.")


if __name__ == "__main__":
    main()
