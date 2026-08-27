"""Diagnostic logger for an already-paired remote: listens on BOTH
configured rf_addresses.json pipes simultaneously, exactly like
RfInput does, and logs which pipe (and which address) every message
arrives on alongside its decoded meaning. Unlike the promiscuous
tools elsewhere in this package, this uses real, matched addressing
with CRC enabled - the same setup RfInput itself uses - so there's no
noise/false-positive uncertainty at all: every logged line is a
genuine, correctly-received transmission.

Built to answer one specific question directly: which address does
each message type (button presses, releases, idle/sleep/wake) arrive
on - useful when both rf_addresses.json entries are already known but
what each one actually carries isn't.

Usage:
    python -m rf_manager.rf_pipe_logger
    python -m rf_manager.rf_pipe_logger --addresses config/rf_addresses.json --keymap config/remote_keymap.json
"""
import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from pyrf24 import RF24, RF24_2MBPS, RF24_CRC_16

CSN_PIN = 0  # aka CE0 on SPI bus 0: /dev/spidev0.0
CE_PIN = 1
CHANNEL = 5  # matches RfInput's fixed regular-operation channel - see rf_manager.py

_DEFAULT_ADDRESSES_PATH = "config/rf_addresses.json"
_DEFAULT_KEYMAP_PATHS = ["config/remote_keymap.json", "Extras/Config Examples/remote_keymap.json"]

# rf_manager.py's _decode() protocol-level status codes, keyed by the
# raw int rather than 3-byte form (no bit-shift searching needed here
# - reception is exact, not promiscuous).
_PROTOCOL_NAMES: dict[int, str] = {
    0x40044C: "IDLE",
    0x4F0300: "GOING_TO_SLEEP",
    0x4F0700: "WOKE_UP",
    0x400028: "REPEAT",
    0x4F0004: "ALL_RELEASED",
    0xC10000: "RELEASED_BUTTON",
    0xC30000: "RELEASED_BUTTON",
}


def _load_addresses(path: str) -> list[bytes]:
    addresses = json.loads(Path(path).read_text())
    if len(addresses) < 2:
        raise ValueError(f"{path} needs at least 2 addresses (found {len(addresses)})")
    return [bytes.fromhex(a) for a in addresses[:2]]


def _load_known_commands(path: str | None) -> dict[int, str]:
    commands = dict(_PROTOCOL_NAMES)
    candidates = [path] if path else _DEFAULT_KEYMAP_PATHS
    for candidate in candidates:
        file = Path(candidate)
        if file.is_file():
            keymap = json.loads(file.read_text())
            for name, entry in keymap.items():
                rf_command = entry.get("rf_command")
                if rf_command:
                    commands[int(rf_command, 16)] = name
            print(f"Loaded known commands from {file} (+ {len(_PROTOCOL_NAMES)} built-in protocol status codes)")
            return commands
    print(f"No remote_keymap.json found (tried {candidates}) - only protocol status codes recognized.")
    return commands


def _init_radio(addresses: list[bytes]) -> RF24:
    radio = RF24(CE_PIN, CSN_PIN)
    if not radio.begin():
        raise OSError("nRF24L01 hardware isn't responding")

    radio.setChannel(CHANNEL)
    radio.setDataRate(RF24_2MBPS)
    radio.enableDynamicPayloads()
    radio.setCRCLength(RF24_CRC_16)

    radio.openReadingPipe(1, addresses[0])
    radio.openReadingPipe(2, addresses[1])
    radio.startListening()
    return radio


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--addresses", default=_DEFAULT_ADDRESSES_PATH,
        help=f"Path to rf_addresses.json (default: {_DEFAULT_ADDRESSES_PATH}).",
    )
    parser.add_argument(
        "--keymap", default=None,
        help=f"Path to remote_keymap.json. Default: try {_DEFAULT_KEYMAP_PATHS} in order.",
    )
    args = parser.parse_args()

    addresses = _load_addresses(args.addresses)
    known_commands = _load_known_commands(args.keymap)
    radio = _init_radio(addresses)

    print(
        f"Listening on pipe1={addresses[0].hex()} and pipe2={addresses[1].hex()}, channel {CHANNEL}. "
        f"Press buttons, let it idle/sleep/wake, whatever you want to observe. Ctrl+C to stop.",
        flush=True,
    )

    seen = 0
    try:
        while True:
            has_payload, pipe_number = radio.available_pipe()
            if has_payload:
                payload_size = radio.getDynamicPayloadSize()
                payload = bytes(radio.read(payload_size))
                seen += 1
                timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]

                if len(payload) < 4:
                    print(
                        f"[{timestamp}] #{seen} pipe={pipe_number} SHORT PAYLOAD "
                        f"len={len(payload)} hex={payload.hex()}",
                        flush=True,
                    )
                    continue

                command = (payload[1] << 16) | (payload[2] << 8) | payload[3]
                name = known_commands.get(command, "UNKNOWN")
                address = addresses[pipe_number - 1].hex() if pipe_number in (1, 2) else "?"
                print(
                    f"[{timestamp}] #{seen} pipe={pipe_number} address={address} "
                    f"command={command:06x} name={name} raw={payload.hex()}",
                    flush=True,
                )
            else:
                time.sleep(0.001)
    except KeyboardInterrupt:
        print(f"\nStopped. Saw {seen} message(s) total.", flush=True)


if __name__ == "__main__":
    main()
