import asyncio
import atexit
import logging
from asyncio import Task
from typing import Callable, Awaitable

import pigpio

from Api.models.WebsocketResponses import WebsocketIrResponse

AsyncCallback = Callable[[str], Awaitable[None]]

PRE = 20
POST = 20
RXGPIO = 17
GLIT = 100
PRE_US = PRE * 1000

TXGPIO = 18
FREQ = 38


class IrManager:

    logger = logging.getLogger(__package__)
    recordingTask: Task|None = None

    def __init__(self):
        self.logger.info("Connecting...")
        self.pi = pigpio.pi()
        self.logger.info("Done")

        self.repeating = False

        atexit.register(self.cleanup)

    def cleanup(self):
        self.logger.info("Disconnecting from GPIO...")
        self.pi.stop()

    async def send_and_repeat(self, code: [int]):
        self.repeating = True
        while self.repeating:
            await self.send_command(code)
            await asyncio.sleep(0.25)

    def stop_repeating(self):
        self.repeating = False

    async def send_command(self, code: [int]):
        def carrier(gpio, frequency, micros, dutycycle=0.5):
            """
            Generate cycles of carrier on gpio with frequency and dutycycle.
            """
            nonlocal wf
            wf = []
            cycle = 1000.0 / frequency
            cycles = int(round(micros / cycle))
            on = int(round(cycle * dutycycle))
            sofar = 0
            for c in range(cycles):
                target = int(round((c + 1) * cycle))
                sofar += on
                off = target - sofar
                sofar += off
                wf.append(pigpio.pulse(1 << gpio, 0, on))
                wf.append(pigpio.pulse(0, 1 << gpio, off))
            return wf

        self.pi.set_mode(TXGPIO, pigpio.OUTPUT)  # IR TX connected to this GPIO.

        self.pi.wave_add_new()

        # Check marks
        marks = {}
        for i in range(0, len(code), 2):
            if code[i] not in marks:
                marks[code[i]] = -1

        for i in marks:
            wf = carrier(TXGPIO, FREQ, i)
            self.pi.wave_add_generic(wf)
            wid = self.pi.wave_create()
            marks[i] = wid

        # Check spaces
        spaces = {}
        for i in range(1, len(code), 2):
            if code[i] not in spaces:
                spaces[code[i]] = -1

        for i in spaces:
            self.pi.wave_add_generic([pigpio.pulse(0, 0, i)])
            wid = self.pi.wave_create()
            spaces[i] = wid

        # Create wave
        wave = [0] * len(code)
        for i in range(0, len(code)):
            if i & 1:  # Space
                wave[i] = spaces[code[i]]
            else:  # Mark
                wave[i] = marks[code[i]]

        self.pi.wave_chain(wave)

        while self.pi.wave_tx_busy():
            await asyncio.sleep(0.05)

        for i in marks:
            self.pi.wave_delete(marks[i])
        for i in spaces:
            self.pi.wave_delete(spaces[i])

        self.logger.debug("Sent IR command")


    async def record_command(self, name: str, _callback: AsyncCallback = None) -> [int]:
        self.cancel_recording()
        self.recordingTask = asyncio.create_task(self._record_command(name, _callback))
        return await self.recordingTask

    async def _record_command(self, name: str, _callback: AsyncCallback = None) -> [int]:

        last_tick = None
        in_code = False
        code = []
        code_done = False

        async def send_message(msg: str):
            self.logger.debug(msg)
            if _callback is not None:
                await _callback(msg)

        def normalise(c):
            entries = len(c)
            p = [0] * entries  # Set all entries not processed.
            for i in range(entries):
                if not p[i]:  # Not processed?
                    v = c[i]
                    tot = v
                    similar = 1.0
                    for j in range(i + 2, entries, 2):  # Find unprocessed similar.
                        if not p[j]:  # Unprocessed.
                            if c[j] * 0.8 < v < c[j] * 1.2:  # Similar.
                                tot = tot + c[j]
                                similar += 1.0
                    newv = tot / similar
                    c[i] = newv
                    for j in range(i + 2, entries, 2):  # Normalise similar.
                        if not p[j]:  # Unprocessed.
                            if c[j] * 0.8 < v < c[j] * 1.2:  # Similar.
                                c[j] = newv
                                p[j] = 1

        def end_of_code():
            nonlocal code, code_done
            if len(code) > 8:
                normalise(code)
                code_done = True
            else:
                code = []
                asyncio.run(send_message(WebsocketIrResponse.SHORT_CODE))
                # send_websocket_message("Short code, probably a repeat. Please try again.")

        def cbf(_, level, tick):
            nonlocal last_tick, in_code, code, code_done
            if last_tick is not None:
                if level != pigpio.TIMEOUT:
                    edge = pigpio.tickDiff(last_tick, tick)
                    if edge > PRE_US:  # Start or stop of a code.
                        if in_code:
                            in_code = False
                            self.pi.set_watchdog(RXGPIO, 0)  # Cancel watchdog.
                            end_of_code()
                        else:
                            if not code_done:
                                in_code = True
                                self.pi.set_watchdog(RXGPIO, POST)  # Start watchdog.
                    else:
                        if in_code:
                            code.append(edge)
                else:  # Timeout.
                    self.pi.set_watchdog(RXGPIO, 0)  # Cancel watchdog.
                    if in_code:
                        in_code = False
                        end_of_code()
            if level != pigpio.TIMEOUT:
                last_tick = tick

        def compare(p1, p2):
            if len(p1) != len(p2):
                return False
            for i in range(len(p1)):
                if p2[i] == 0:
                    return False
                v = p1[i] / p2[i]
                if (v < 0.8) or (v > 1.2):
                    return False
            for i in range(len(p1)):
                p1[i] = int(round((p1[i] + p2[i]) / 2.0))
            return True

        self.pi.set_mode(RXGPIO, pigpio.INPUT) # IR RX connected to this GPIO.
        self.pi.set_glitch_filter(RXGPIO, GLIT) # Ignore glitches.

        _ = self.pi.callback(RXGPIO, pigpio.EITHER_EDGE, cbf)

        code = []
        code_done = False

        await send_message(WebsocketIrResponse.PRESS_KEY)

        while not code_done:
            await asyncio.sleep(0.1)

        press_1 = code[:]
        match = False
        tries = 0

        while not match:
            code = []
            code_done = False
            if tries > 4:
                await send_message(WebsocketIrResponse.TOO_MANY_RETRIES)
                return None

            await send_message(WebsocketIrResponse.REPEAT_KEY)

            while not code_done:
                await asyncio.sleep(0.1)

            press_2 = code[:]
            the_same = compare(press_1, press_2)

            if the_same:
                match = True

            tries += 1

        return press_1

    def cancel_recording(self):
        if self.recordingTask is not None:
            self.recordingTask.cancel()
        self.logger.info("Cancelled Task")
