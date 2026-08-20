import asyncio
import json
import logging
import time
from dataclasses import dataclass
from sys import platform

from Hub.EventBus import Event, EventBus
from Hub.interfaces import InputSource

# pyrf24 only has precompiled binaries for linux. If you install it via pip on another os, the import will fail,
# even though the package seems to be installed. For development setups, this is not an issue, as this class is
# never started on non-linux platforms.
if platform == "linux":
    from pyrf24 import RF24, RF24_2MBPS, RF24_CRC_16

CSN_PIN = 0  # aka CE0 on SPI bus 0: /dev/spidev0.0
CE_PIN = 1

_IDLE = 0x40044c
_GOING_TO_SLEEP = 0x4f0300
_WOKE_UP = 0x4f0700
_REPEAT = 0x400028
_ALL_RELEASED = 0x4f0004
_RELEASED_BUTTON = (0xc10000, 0xc30000)


@dataclass
class _Signal:
    kind: str  # "pressed" | "repeated" | "released"
    button: str | None


_EVENT_TYPES = {
    "pressed": "key_pressed",
    "repeated": "key_repeated",
    "released": "key_released",
}


# This is heavily based on the great work done here: https://github.com/joakimjalden/Harmoino/tree/main
class RfInput(InputSource):
    """Reads button presses from the NRF24L01+ remote receiver.

    `run_in_executor` wraps every blocking pyrf24 call, per the golden
    rule - an async function that internally calls a blocking function
    still blocks the whole event loop.
    """

    name = "rf"

    logger = logging.getLogger(__package__)

    def __init__(self, addresses: list[bytes], config_dir: str = "config") -> None:
        self._addresses = addresses
        self._known_commands = self._load_known_commands(config_dir)
        self._rf: RF24 | None = None
        self._last_key: str | None = None
        self._running = True

    def _load_known_commands(self, config_dir: str) -> dict[int, str]:
        try:
            with open(f"{config_dir}/remote_keymap.json") as file:
                keymap_json = json.loads(file.read())
        except FileNotFoundError:
            self.logger.warning(
                f"\"{config_dir}/remote_keymap.json\" could not be opened. Listener will not respond to signals."
            )
            return {}

        return {int(value["rf_command"], 16): key for key, value in keymap_json.items()}

    async def start(self, bus: EventBus) -> None:
        loop = asyncio.get_running_loop()
        self._rf = await loop.run_in_executor(None, self._init_radio)
        if self._rf is None:
            return

        while self._running:
            signal = await loop.run_in_executor(None, self._blocking_receive)
            if signal is not None:
                await bus.publish(Event(_EVENT_TYPES[signal.kind], {"button": signal.button}))

    def stop(self) -> None:
        self._running = False
        if self._rf is not None:
            self._rf.powerDown()
            self.logger.debug("Stopped RF listener")

    def _init_radio(self) -> "RF24 | None":
        if len(self._addresses) < 2:
            self.logger.warning("No RF addresses specified, skipping listener startup")
            return None

        rf = RF24(CE_PIN, CSN_PIN)
        if not rf.begin():
            self.logger.warning("RF hardware is not responding. Listener will not respond to commands.")
            return None

        rf.setChannel(5)
        rf.setDataRate(RF24_2MBPS)
        rf.enableDynamicPayloads()
        rf.setCRCLength(RF24_CRC_16)

        rf.openReadingPipe(1, self._addresses[0])
        rf.openReadingPipe(2, self._addresses[1])
        rf.powerUp()
        rf.startListening()
        return rf

    def _blocking_receive(self) -> _Signal | None:
        while self._running:
            assert self._rf is not None  # start() already returned early if radio init failed
            if self._rf.available():
                payload_size = self._rf.getDynamicPayloadSize()
                payload = self._rf.read(payload_size)
                signal = self._decode(payload)
                if signal is not None:
                    return signal
            time.sleep(0.05)
        return None

    def _decode(self, payload: bytes | bytearray) -> _Signal | None:
        if len(payload) < 5:
            self.logger.warning(f"Received unexpectedly short payload: {':'.join(f'{i:02x}' for i in payload)}")
            return None

        command = 0
        for i in range(1, 4):
            command <<= 8
            command += payload[i]

        recognized_command = self._known_commands.get(command)
        if recognized_command:
            self.logger.debug(f"Button {recognized_command} pressed!")
            self._last_key = recognized_command
            return _Signal("pressed", recognized_command)

        if command == _IDLE:
            return None
        if command == _GOING_TO_SLEEP:
            self.logger.debug("Remote going to sleep")
            return None
        if command == _WOKE_UP:
            self.logger.debug("Remote woke up")
            return None
        if command == _REPEAT:
            # Sent continuously while a button stays held - the raw signal a
            # future long-press feature would build on (see architecture.md).
            return _Signal("repeated", self._last_key) if self._last_key is not None else None
        if command == _ALL_RELEASED:
            self.logger.debug(f"{self._last_key} released")
            return _Signal("released", self._last_key)
        if command in _RELEASED_BUTTON:
            # Always followed by _ALL_RELEASED if the released button was the only one
            # pressed. With multiple buttons held, this could differentiate them.
            return None

        self.logger.warning("Unexpected payload:")
        self.logger.warning(f"len: {len(payload)}, bytes: {':'.join(f'{i:02x}' for i in payload)}")
        return None
