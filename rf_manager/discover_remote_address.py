"""Discovers a Companion remote's rf_addresses.json pair without a
genuine Harmony Hub.

The pair is two addresses differing in exactly one byte: an
arbitrary, hub-assigned byte and 0x00, over an otherwise shared
4-byte remainder - e.g. 1e9c9bc1c6 / 009c9bc1c6 (the differing byte
was 1e, 08 and 08 across three independent real remotes, so it cannot
be derived; the remainder appears to be common to the product).

Discovery runs in two stages.

Stage 1 - promiscuous scan (rf_promiscuous_sniffer.py's technique):
    address_width=2 with a 0x00AA/0x0055 sync, CRC and auto-ack off,
    to learn the shared 4 bytes from any one CRC-validated frame.
    Skipped entirely when they are already known (--shared, or an
    existing config/rf_addresses.json).

Stage 2 - hardware candidate sweep:
    Measured behaviour, not theory: a 4-byte sync on the shared bytes
    captures NOTHING in either byte order, while the 2-byte 0x00AA
    sync captures steadily - and everything it decodes is on the
    0x00-prefixed address. The consistent explanation is that the
    radio only latches onto preamble-followed-by-address-start, so
    the 2-byte sync works by having its 0xAA act as the preamble and
    its 0x00 match a first address byte that happens to be 0x00.
    Nothing can be synced mid-address, which is why both 4-byte plans
    were silent, and why the 0x00 address is the only one that trick
    can ever see. The hub-assigned byte simply is not reachable that
    way.

    So stage 2 stops sniffing and uses the radio the way RfInput does
    - real 5-byte addressing with hardware CRC. It always listens on
    the known 0x00 address, and takes the unknown byte from two
    sources at once.

    The fast path is the remote telling us. Every packet carries its
    counterpart address's leading byte in payload[0]: packets on the
    0x00 address carry the hub-assigned byte, and packets on the
    hub-assigned address carry 0x00 (visible in rf_pipe_logger output
    as raw=1ec10052... on 009c9bc1c6 versus raw=00400028... on
    1e9c9bc1c6). One press is therefore enough to name the byte. It is
    still only inferred from payload structure, so it is treated as a
    hint and proven before use.

    The backstop is a sweep of all 255 candidate values. The nRF24
    requires pipes 1-5 to share their top 4 bytes and differ only in
    the byte at array index 0 - exactly the unknown byte - so four
    candidates are tested per round alongside the 0x00 pipe.

    Both paths end in the same proof: open a pipe on the candidate
    address and require real packets. Anything the hardware accepts
    has matched a full 5-byte address and passed CRC-16, so there is
    no bit alignment, brute forcing, or false-positive analysis left
    to get wrong.

Usage:
    python -m rf_manager.discover_remote_address
    python -m rf_manager.discover_remote_address --shared 9c9bc1c6
    python -m rf_manager.discover_remote_address --dwell 2.0
"""
import argparse
import json
import time
from collections import Counter, deque
from pathlib import Path

from pyrf24 import RF24_2MBPS, RF24_CRC_16

from rf_manager.rf_promiscuous_sniffer import (
    RF24,
    _bit_shift,
    _find_crc_valid_framings,
    _find_known_commands,
    _init_radio,
    _load_known_commands,
)

CHANNEL = 5  # matches RfInput's fixed regular-operation channel - see rf_manager.py

_DEFAULT_TIMEOUT = 120.0
_CONFIRMATIONS_NEEDED = 2
_STATUS_INTERVAL = 5.0
_PREAMBLE_DWELL = 4.0

_ADDRESSES_PATH = "config/rf_addresses.json"

# Pipes 2-5 carry candidates; pipe 1 is the always-on control.
_CANDIDATE_PIPES = (2, 3, 4, 5)
_CONTROL_PIPE = 1
_DEFAULT_DWELL = 1.5  # seconds per round - the idle heartbeat is ~1/s
_VERIFY_SECONDS = 15.0


def _command_hits(payload: bytes, known_commands: dict[bytes, str]) -> list[tuple[int, str]]:
    """(bit_position, name) for every known 3-byte command found in any
    of the 8 bit-shift variants. Stage 1's cheap prefilter: the CRC
    framing search costs milliseconds per packet and the promiscuous
    firehose delivers tens per second on a 3-packet-deep FIFO, so
    searching everything stalls reception and drops the rare genuine
    capture. Any recoverable real packet passes this (its command
    bytes sit in the payload); noise needs a 24-bit fluke."""
    hits = []
    for shift in range(8):
        for offset, name, _command in _find_known_commands(_bit_shift(payload, shift), known_commands):
            hits.append((offset * 8 + shift, name))
    return hits


def _stage1_find_shared(
    radio: RF24, timeout: float, known_commands: dict[bytes, str], preambles: list[int]
) -> bytes | None:
    """Promiscuous scan for any CRC-validated frame, to learn the
    shared 4 bytes. With two preambles, alternates between them every
    _PREAMBLE_DWELL seconds until a validated recovery locks one in
    (the polarity is unit-specific and the wrong one captures nothing
    from this remote at all). A single CRC hit can be a fluke, so an
    address must be seen twice before its bytes are trusted."""
    sightings: Counter[bytes] = Counter()
    pending: deque[tuple[bytes, int]] = deque()
    scanned = prefiltered = 0
    preamble_index = 0
    locked = len(preambles) == 1
    deadline = time.monotonic() + timeout
    last_status = last_switch = time.monotonic()

    while time.monotonic() < deadline or pending:
        if not locked and time.monotonic() - last_switch >= _PREAMBLE_DWELL:
            last_switch = time.monotonic()
            preamble_index = (preamble_index + 1) % len(preambles)
            radio.stopListening()
            radio.openReadingPipe(1, bytes([0x00, preambles[preamble_index]]))
            radio.startListening()

        # Drain the RX FIFO (3 packets deep) before any per-capture
        # work - a stalled read loop drops the very packets wanted.
        if time.monotonic() < deadline:
            while radio.available():
                pending.append((bytes(radio.read(32)), preambles[preamble_index]))

        if time.monotonic() - last_status >= _STATUS_INTERVAL:
            last_status = time.monotonic()
            mode = "locked" if locked else "alternating"
            print(f"  ...{scanned} captures scanned, {prefiltered} passed the command prefilter; "
                  f"preamble {preambles[preamble_index]:02x} ({mode}). Genuine captures arrive by "
                  f"luck at this stage - keep pressing buttons.")

        if not pending:
            time.sleep(0.001)
            continue

        payload, capture_preamble = pending.popleft()
        scanned += 1
        if not _command_hits(payload, known_commands):
            continue
        prefiltered += 1

        for _start, _payload_len, address in _find_crc_valid_framings(payload, max_start_bit=192):
            sightings[address] += 1
            print(f"  stage 1: recovered {address.hex()} ({sightings[address]}/{_CONFIRMATIONS_NEEDED})")

            if not locked:
                locked = True
                if preambles[preamble_index] != capture_preamble:
                    preamble_index = preambles.index(capture_preamble)
                    radio.stopListening()
                    radio.openReadingPipe(1, bytes([0x00, capture_preamble]))
                    radio.startListening()
                print(f"  stage 1: locked onto preamble {capture_preamble:02x}")

            if sightings[address] >= _CONFIRMATIONS_NEEDED:
                return address[1:]

    return None


def _init_matched_radio(radio: RF24) -> None:
    """Switches the radio from promiscuous sniffing to real reception.

    This calls begin() again to reset the whole chip to library
    defaults first, then applies exactly rf_pipe_logger's sequence.
    Undoing the promiscuous setup field by field was tried and
    received nothing at all - not even on a known-good address that
    rf_pipe_logger receives on constantly - because that setup leaves
    behind several non-default registers at once (2-byte address
    width, 32-byte static payload, CRC disabled, auto-ack off) and
    dynamic payloads in particular depend on auto-ack being on. A full
    re-init removes every leftover rather than guessing which one
    mattered."""
    radio.stopListening()
    if not radio.begin():
        raise OSError("nRF24L01 hardware stopped responding during reconfiguration")
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
    byte hinted by a control packet's payload[0] or None).

    The hint is the fast path. Packets on the 0x00 address carry the
    hub-assigned byte in payload[0], and packets on the hub-assigned
    address carry 0x00 there - each announces its counterpart. It is
    treated as a hint rather than an answer because it is still only
    inferred from payload structure; the caller proves it by opening a
    pipe on it and requiring real packets."""
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
            continue
        if pipe_number in _CANDIDATE_PIPES:
            index = _CANDIDATE_PIPES.index(pipe_number)
            if index < len(candidates):
                return candidates[index], payload, control_packets, hint
    return None, None, control_packets, hint


def _verify_candidate(
    radio: RF24, shared: bytes, candidate: int, seconds: float, known_commands: dict[bytes, str]
) -> int:
    """Opens a pipe on candidate+shared and counts the packets the
    hardware accepts on it within `seconds`. Every packet counted has
    matched a full 5-byte address and passed CRC-16, so this turns a
    guessed byte into a proven one."""
    address = bytes([candidate]) + shared
    confirmed = 0
    deadline = time.monotonic() + seconds
    while confirmed < _CONFIRMATIONS_NEEDED and time.monotonic() < deadline:
        hit, payload, _control, _hint = _listen_round(
            radio, shared, [candidate], min(2.0, deadline - time.monotonic())
        )
        if hit is None:
            continue
        confirmed += 1
        name = known_commands.get(payload[1:4], "unknown command") if len(payload) >= 4 else "short payload"
        print(f"  verified {address.hex()} carrying {name} (raw={payload.hex()}) "
              f"({confirmed}/{_CONFIRMATIONS_NEEDED})")
    return confirmed


def _stage2_sweep(
    radio: RF24, shared: bytes, timeout: float, dwell: float, known_commands: dict[bytes, str]
) -> bytes | None:
    """Sweeps every possible value of the hub-assigned byte using real
    hardware addressing. A packet arriving on a candidate pipe has
    matched a full 5-byte address and passed CRC, so it is conclusive;
    it is nonetheless re-verified on its own pipe to collect
    _CONFIRMATIONS_NEEDED packets before writing any config."""
    _init_matched_radio(radio)
    candidates = [value for value in range(1, 256)]  # 0x00 is the control, not a candidate
    rounds = (len(candidates) + len(_CANDIDATE_PIPES) - 1) // len(_CANDIDATE_PIPES)

    print(f"\nStage 2: real 5-byte addressing with hardware CRC, listening on 00{shared.hex()} "
          f"while sweeping the {len(candidates)} possible values of the hub-assigned byte in "
          f"xx{shared.hex()}, {len(_CANDIDATE_PIPES)} at a time (one full pass ~{rounds * dwell:.0f}s). "
          f"Press and release buttons: a single packet on 00{shared.hex()} names the byte outright, "
          f"and the sweep is only the backstop.")

    control_total = 0
    tried_hints: set[int] = set()
    deadline = time.monotonic() + timeout
    passes = 0

    while time.monotonic() < deadline:
        passes += 1
        for index in range(0, len(candidates), len(_CANDIDATE_PIPES)):
            if time.monotonic() >= deadline:
                break
            batch = candidates[index:index + len(_CANDIDATE_PIPES)]
            remaining = max(0.0, min(dwell, deadline - time.monotonic()))
            if remaining <= 0:
                break
            hit, payload, control_packets, hint = _listen_round(radio, shared, batch, remaining)
            control_total += control_packets

            round_number = index // len(_CANDIDATE_PIPES) + 1
            if round_number % 8 == 0 or hit is not None:
                print(f"  pass {passes}, round {round_number}/{rounds}: testing "
                      f"{', '.join(f'{c:02x}' for c in batch)} - control pipe has seen "
                      f"{control_total} packet(s) on 00{shared.hex()} so far")

            # Fast path: a packet on the 0x00 address names its
            # counterpart in payload[0], so jump straight to proving
            # that byte instead of waiting for the sweep to reach it.
            if hint is not None and hint not in tried_hints:
                tried_hints.add(hint)
                print(f"\n  a packet on 00{shared.hex()} names {hint:02x} in payload[0] - "
                      f"testing {bytes([hint]).hex()}{shared.hex()} directly...")
                if _verify_candidate(radio, shared, hint, _VERIFY_SECONDS, known_commands) >= _CONFIRMATIONS_NEEDED:
                    return bytes([hint]) + shared
                print(f"  {hint:02x} did not produce packets of its own - back to the sweep.")

            if hit is None:
                continue

            name = known_commands.get(payload[1:4], "unknown command") if len(payload) >= 4 else "short payload"
            address = bytes([hit]) + shared
            print(f"\n  HIT: {address.hex()} accepted a packet carrying {name} "
                  f"(raw={payload.hex()}) - verifying...")
            if 1 + _verify_candidate(radio, shared, hit, _VERIFY_SECONDS, known_commands) >= _CONFIRMATIONS_NEEDED:
                return address
            print(f"  {address.hex()} did not repeat within {_VERIFY_SECONDS:.0f}s - continuing the "
                  f"sweep rather than trusting a single packet.")

        print(f"  completed pass {passes} over all 255 candidates; control pipe total: "
              f"{control_total} packet(s)")

    if control_total:
        print(f"\nSwept every candidate without a single packet on any of them, while the control "
              f"pipe received {control_total} packet(s) on 00{shared.hex()}. The receiver is "
              f"working, so this remote genuinely transmits only on the 0x00 address - it has no "
              f"hub-assigned second address yet, which is expected if it has never been paired "
              f"with a real hub.")
    else:
        print(f"\nNo packets on any pipe, including the control pipe on 00{shared.hex()} - the "
              f"remote was asleep, out of range, or on another channel, so this sweep proved "
              f"nothing. Wake the remote and try again.")
    return None


def _shared_from_config() -> bytes | None:
    """Reuses the shared bytes from an existing rf_addresses.json, so a
    re-run can skip stage 1."""
    file = Path(_ADDRESSES_PATH)
    if not file.is_file():
        return None
    try:
        addresses = json.loads(file.read_text())
        return bytes.fromhex(addresses[0])[1:]
    except (ValueError, IndexError, TypeError):
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--preamble", choices=["both", "aa", "55"], default="both",
        help="Stage 1 preamble polarity - unit-specific, and the wrong one captures nothing "
             f"(default: both, alternating every {_PREAMBLE_DWELL:.0f}s until one validates).",
    )
    parser.add_argument(
        "--shared", default=None,
        help="The 4 shared address bytes as hex (e.g. 9c9bc1c6) - a known address minus its "
             f"leading byte. Skips stage 1. Default: read from {_ADDRESSES_PATH} if present.",
    )
    parser.add_argument(
        "--timeout", type=float, default=_DEFAULT_TIMEOUT,
        help=f"Seconds per stage before giving up (default: {_DEFAULT_TIMEOUT:.0f}). Stage 2 "
             f"needs roughly 96s for one full sweep at the default dwell.",
    )
    parser.add_argument(
        "--dwell", type=float, default=_DEFAULT_DWELL,
        help=f"Stage 2 seconds per candidate round (default: {_DEFAULT_DWELL}). Raise it if the "
             f"remote transmits rarely, lower it to sweep faster while holding a button down.",
    )
    parser.add_argument(
        "--keymap", default=None,
        help="Path to remote_keymap.json - known rf_commands widen stage 1's prefilter and name "
             "the packets stage 2 receives. Default: same auto-discovery as the sniffer.",
    )
    args = parser.parse_args()

    if args.shared:
        shared = bytes.fromhex(args.shared)
        if len(shared) != 4:
            parser.error(f"--shared needs exactly 4 bytes (8 hex chars), got {len(shared)}")
    else:
        shared = _shared_from_config()
        if shared is not None:
            print(f"Reusing shared bytes {shared.hex()} from {_ADDRESSES_PATH} - skipping stage 1. "
                  f"Pass --shared to override, or delete that file to rediscover.")

    preambles = [0xAA, 0x55] if args.preamble == "both" else [int(args.preamble, 16)]
    known_commands = _load_known_commands(args.keymap)
    radio = _init_radio(preambles[0])
    radio.setChannel(CHANNEL)

    try:
        if shared is None:
            print(
                "\nStage 1: promiscuous scan to learn the shared address bytes. Press and "
                "release buttons on the remote repeatedly - genuine captures arrive by luck "
                "here, so more traffic is strictly better. Ctrl+C to stop."
            )
            shared = _stage1_find_shared(radio, args.timeout, known_commands, preambles)
            if shared is None:
                print(f"\nStage 1 gave up after {args.timeout:.0f}s without recovering any frame. "
                      f"The remote must be awake and in range; if it stays silent, try "
                      f"--preamble 55 (or aa) to pin one polarity for the whole run.")
                return
            print(f"\nShared address bytes: {shared.hex()}")

        confirmed = _stage2_sweep(radio, shared, args.timeout, args.dwell, known_commands)
    except KeyboardInterrupt:
        print("\nStopped.")
        return

    if confirmed is None:
        print(f"\nNo hub-assigned address confirmed. The shared bytes {shared.hex()} are known, "
              f"so a re-run can go straight to the sweep with --shared {shared.hex()} "
              f"(and --timeout 300 for several full passes).")
        return

    zeroed = bytes([0x00]) + confirmed[1:]
    addresses = [confirmed.hex(), zeroed.hex()]

    print(f"\nConfirmed address: {confirmed.hex()}")
    print(f"Second address (leading byte zeroed): {zeroed.hex()}")

    Path("config").mkdir(parents=True, exist_ok=True)
    with open(_ADDRESSES_PATH, "w") as file:
        json.dump(addresses, file, indent=4)
    print(f"Wrote {_ADDRESSES_PATH}: {addresses}")
    print("Verify with: python -m rf_manager.rf_pipe_logger")


if __name__ == "__main__":
    main()
