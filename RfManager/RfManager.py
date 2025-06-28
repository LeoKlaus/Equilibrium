import threading
import atexit
from datetime import datetime
import time
import json
import logging

import pigpio
from nrf24 import *

class RfManager:

    logger = logging.getLogger(__package__)
    listener_thread = None

    def __init__(self, callback=None, repeat_callback=None, release_callback=None):
        self.pi = pigpio.pi()
        self.nrf = NRF24(
            self.pi,
            ce=26,
            payload_size=RF24_PAYLOAD.DYNAMIC,
            channel=5,
            data_rate=RF24_DATA_RATE.RATE_2MBPS,
            crc_bytes=RF24_CRC.BYTES_2,
            pa_level=RF24_PA.MIN
        )

        self.callback = callback
        self.repeat_callback = repeat_callback
        self.release_callback = release_callback

        with open("config/remote_keymap.json", "r") as file:
            keymap_data = file.read()

        keymap_json = json.loads(keymap_data)

        self.known_commands = {}

        for key, value in keymap_json.items():
            self.known_commands[int(value["rf_command"], 16)] = key

        atexit.register(self.cleanup)

    def cleanup(self):
        self.logger.info("Disconnecting from GPIO...")
        self.pi.stop()

    def start_listener(self, addresses: [bytes], debug = False):
        # TODO: Implement helper to determine address

        if len(addresses) == 0:
            self.logger.warning("No RF addresses specified, skipping listener startup")
            return

        self.nrf.power_up_rx()
        self.listener_thread = threading.Thread(name='listener_thread', target=self._start_listening, args=(addresses, debug))
        self.listener_thread.start()
        self.logger.debug("Started rf listener")

    def stop_listener(self):
        if self.listener_thread is not None:
            self.listener_thread.do_run = False
            self.nrf.power_down()
            self.logger.debug("Stopped rf listener")

    def _start_listening(self, addresses, debug):
        self.logger.debug("Setting addresses")
        self.nrf.set_address_bytes(len(addresses[0]))

        # Listen on the addresses specified as parameter
        self.nrf.open_reading_pipe(RF24_RX_ADDR.P0, addresses[0])
        self.nrf.open_reading_pipe(RF24_RX_ADDR.P1, addresses[1])
        self.logger.debug("Set addresses!")
        # Display the content of NRF24L01 device registers.
        if debug:
            self.nrf.show_registers()

        # Enter a loop receiving data on the address specified.
        try:
            self.logger.debug("Entering loop...")
            if debug:
                self.logger.debug(f'Receiving from {addresses[0]}, {addresses[1]}')

            count = 0
            last_key = None

            while getattr(self.listener_thread, "do_run", True):
                # As long as data is ready for processing, process it.
                while self.nrf.data_ready():
                    # Count message and record time of reception.
                    count += 1
                    now = datetime.now()

                    # Read pipe and payload for message.
                    pipe = self.nrf.data_pipe()
                    payload = self.nrf.get_payload()

                    if len(payload) >= 5:
                        command = 0
                        for i in range(1, 4):
                            command <<= 8
                            command += payload[i]

                        recognized_command = self.known_commands.get(command)

                        if recognized_command:
                            self.logger.debug(f"Button {recognized_command} pressed!")
                            if self.callback is not None:
                                self.callback(recognized_command)
                            last_key = recognized_command

                        elif command == 0x40044c:
                            # Remote Idle
                            pass

                        elif command == 0x4f0300:
                            # Remote Going to Sleep
                            self.logger.debug("Remote going to sleep")

                        elif command == 0x4f0700:
                            # Remote Woke Up
                            self.logger.debug("Remote woke up")

                        elif command == 0x400028:
                            # Repeat
                            # print(f"Repeat of {last_key}")
                            if self.repeat_callback is not None:
                                self.repeat_callback(last_key)
                            pass

                        elif command == 0x4f0004:
                            # All Buttons Released
                            self.logger.debug(f"{last_key} released")
                            if self.release_callback is not None:
                                self.release_callback(last_key)

                        elif command == 0xc10000 or command == 0xc30000:
                            # Released Button
                            # always followed by 0x4f0004, if released button was only pressed button
                            # if multiple buttons are pressed at the same time, this could be used to
                            # differentiate them (somewhat)
                            pass

                        else:
                            self.logger.warning("Unexpected payload:")
                            self.logger.warning(f"pipe: {pipe}, len: {len(payload)}, bytes: {':'.join(f'{i:02x}' for i in payload)}, count: {count}")

                    else:
                        self.logger.warning(f"Received unexpectedly short payload: {':'.join(f'{i:02x}' for i in payload)}")

                # Sleep 100 ms.
                time.sleep(0.1)

            self.logger.debug("Exiting loop...")
        except Exception as e:
            self.logger.error(e)
            self.stop_listener()

    def set_callback(self, _callback):
        self.callback = _callback

    def set_repeat_callback(self, _repeat_callback):
        self.repeat_callback = _repeat_callback

    def set_release_callback(self, _release_callback):
        self.release_callback = _release_callback