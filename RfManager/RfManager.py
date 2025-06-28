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

        with open("RfManager/known_commands.json", "r") as file:
            command_data = file.read()

        self.known_commands = json.loads(command_data)

        atexit.register(self.cleanup)

    def cleanup(self):
        self.logger.info("Disconnecting from GPIO...")
        self.pi.stop()

    def start_listener(self, addresses=None, debug = False):
        # TODO: Implement helper to determine address
        if addresses is None:
            addresses = [b'\x08\x52\x92\x58\xCB', b'\x00\x52\x92\x58\xCB']

        self.nrf.power_up_rx()
        self.listener_thread = threading.Thread(name='listener_thread', target=self._start_listening, args=(addresses, debug))
        self.listener_thread.start()
        self.logger.debug("Started rf listener")

    def stop_listener(self):
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

                    received_hex = ':'.join(f'{i:02x}' for i in payload)

                    if len(payload) == 5:
                        if received_hex == "00:40:00:28:98":
                            #self.logger.debug(f"Repeat of {last_key}")
                            if self.repeat_callback is not None:
                                self.repeat_callback(last_key)
                        elif received_hex == "00:40:04:4c:70":
                            #print("Remote idle")
                            pass
                        else:
                            self.logger.debug("Unexpected payload:")
                            self.logger.debug(f"pipe: {pipe}, len: {len(payload)}, bytes: {received_hex}, count: {count}")
                    elif len(payload) == 10:

                        recognized_command = self.known_commands.get(received_hex)

                        if recognized_command:
                            self.logger.debug(f"Button {recognized_command} pressed!")
                            if self.callback is not None:
                                self.callback(recognized_command)
                            last_key = recognized_command
                        elif received_hex == "00:4f:03:00:00:00:00:00:00:ae":
                            self.logger.debug("Remote going to sleep")
                        elif received_hex == "00:c3:00:00:00:00:00:00:00:3d" or received_hex == "00:4f:00:04:4c:00:00:00:00:61":
                            self.logger.debug("Button released")
                            if self.release_callback is not None:
                                self.release_callback(last_key)
                        elif received_hex == "08:4f:07:00:00:00:00:00:00:a2":
                            self.logger.debug("Remote woke up")
                        elif received_hex == "00:c1:00:00:00:00:00:00:00:3f":
                            #self.logger.info("Button confirm (?)")
                            pass
                        else:
                            self.logger.warning("Unrecognized command:")
                            self.logger.warning(f"{now:%Y-%m-%d %H:%M:%S.%f}: pipe: {pipe}, len: {len(payload)}, bytes: {received_hex}, count: {count}")
                            #cmd = input("Which button was that?")
                            #self.known_commands.json[hex] = cmd
                    else:
                        self.logger.warning("Very unexpected payload:")
                        self.logger.warning(f"{now:%Y-%m-%d %H:%M:%S.%f}: pipe: {pipe}, len: {len(payload)}, bytes: {received_hex}, count: {count}")
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