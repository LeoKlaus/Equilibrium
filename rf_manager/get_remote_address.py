import json
import time
from pathlib import Path

from pyrf24 import RF24, RF24_2MBPS, RF24_CRC_16

address = bytearray([0x75, 0xA5, 0xDC, 0x0A, 0xBB])

CSN_PIN = 0  # aka CE0 on SPI bus 0: /dev/spidev0.0
CE_PIN = 1

radio = RF24(CE_PIN, CSN_PIN)

if not radio.begin():
    raise OSError("nRF24L01 hardware isn't responding")

radio.setDataRate(RF24_2MBPS)
radio.enableDynamicPayloads()
radio.enableAckPayload()
radio.setCRCLength (RF24_CRC_16)
radio.stopListening(address)

channels = [5,8,14,17,32,35,41,44,62,65,71,74]
channel_id = 0

pair_message = [242,95,1,225,154,157,218,83,40,64,30,4,2,7,12,0,0,0,0,0,102,100]
ping_message = [242,64,1,225,236]
ping_retries = 0

print("Listening, press the pair button on your hub now.")

while True:
    if ping_retries == 0:
        radio.setChannel(channels[channel_id])
        if radio.write(bytearray(pair_message)):
            ping_retries = 10
        else:
            channel_id += 1
            if channel_id > 11:
                channel_id = 0
    else:
        radio.write(bytearray(ping_message))
        ping_retries -= 1


    time.sleep(0.1)

    has_payload, pipe_number = radio.available_pipe()
    if has_payload:
        payload_size = radio.getDynamicPayloadSize()
        payload = radio.read(payload_size)

        if payload_size == 22:
            print("The remote RF24 address is")

            first = payload[7]-1
            second = payload[6]
            third = payload[5]
            fourth = payload[4]
            fifth = payload[3]

            exact = f"{first:02x}{second:02x}{third:02x}{fourth:02x}{fifth:02x}"
            zeroed = f"{0:02x}{second:02x}{third:02x}{fourth:02x}{fifth:02x}"
            print(exact)
            print(zeroed)

            Path("config").mkdir(parents=True, exist_ok=True)
            with open("config/rf_addresses.json", "w") as file:
                json.dump([exact, zeroed], file, indent=4)

            print("Wrote config/rf_addresses.json")
            print("Done")
            break