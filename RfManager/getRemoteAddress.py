import time
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
channelId = 0

pairMessage = [242,95,1,225,154,157,218,83,40,64,30,4,2,7,12,0,0,0,0,0,102,100]
pingMessage = [242,64,1,225,236]
pingRetries = 0

print("Listening, press the pair button on your hub now.")

while True:
    if pingRetries == 0:
        radio.setChannel(channels[channelId])
        if radio.write(bytearray(pairMessage)):
            pingRetries = 10
        else:
            channelId += 1
            if channelId > 11:
                channelId = 0
    else:
        radio.write(bytearray(pingMessage))
        pingRetries -= 1


    time.sleep(0.1)

    has_payload, pipe_number = radio.available_pipe()
    if has_payload:
        payloadSize = radio.getDynamicPayloadSize()
        payload = radio.read(payloadSize)

        if payloadSize == 22:
            print("The remote RF24 address is")

            first = payload[7]-1
            second = payload[6]
            third = payload[5]
            fourth = payload[4]
            fifth = payload[3]

            print("{:02x}{:02x}{:02x}{:02x}{:02x}".format(first, second, third, fourth, fifth))
            print("{:02x}{:02x}{:02x}{:02x}{:02x}".format(0, second, third, fourth, fifth))

            print("Done")
            break