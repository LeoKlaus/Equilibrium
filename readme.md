# Equilibrium

Open source network attached universal remote; aiming to become a drop-in replacement for Logitech's discontinued Harmony Hub.

**This software is in a very early stage of development and every update should be considered breaking!**

**Don't use this if you're looking for a stable piece of equipment that you can rely on!**

The setup currently requires at least some basic understanding of the Linux terminal, python and GPIO hardware.

If you run into any issues, check the [Troubleshooting](#troubleshooting) section. If you think you found a bug, please create an issue here on GitHub.

## Features

- [x] Record and send infrared commands
- [x] Emulate a bluetooth keyboard to control devices like the Apple TV (WIP)
- [x] Configurable scenes (activities) with user-definable start and stop macros
- [x] Track device state to make scene switches only execute necessary commands (WIP)
- [x] iOS app to control and manage the hub
- [x] Works with the original Harmony companion remote
- [x] Frontend for Android/Web (Beta available [here](https://github.com/LeoKlaus/Equilibrium-Flutter))

### Todo
- [ ] Home Assistant integration
- [ ] Philips Hue integration?
- [ ] Amazon Alexa integration?
- [ ] Improve set up guide
- [ ] Add some form of IR database

## Hardware-Setup

### BOM

- Raspberry Pi Zero 2W (or any other Linux board with enough GPIO headers) (~20€)
- IR Receiver (I used [these](https://aliexpress.com/item/1005007857037867.html)) (~1€)
- IR Transmitter (I currently use [these](https://aliexpress.com/item/1005008385148583.html), but they are fairly directional and don't work reliable for devices directly in front of the hub) (~1€)
- (Optional but recommended) [NRF24L01+](https://aliexpress.com/item/1005005642753224.html) for communication with the Harmony Remote (~1€)
- (Optional but recommended) A fitting remote. Currently, support for the [Harmony companion](https://support.myharmony.com/en-US/companion) remote is implemented but other RF based remotes, especially the other Logitech remotes might work as well with little changes. I also plan to build my own, 3D-printable remote based on an ESP32 and the NRF24L01+, but I haven't work on that yet.
- (Optional) the matching PCB and case (see below, ~5-20€)

I designed a PCB and case to accommodate all components and the Pi Zero.
You can download the [gerber file](Extras/Gerber_Equilibrium-PCB.zip) and [easyeda project](Extras/Equilibrium-PCB.json) from the `Extras` folder in this repo.
The 3D print files for the case are in the [3D Models](Extras/3D%20Models) folder, I included the 3MF for the settings I used to print these.
I printed the top using translucent PETG and inserted heat set inserts to fixate it with screws from the bottom part, but I'm not too happy with the look and IR translucency.
I also ordered 2 versions of the top printed in clear and translucent resin ([Top-Threaded.stl](Extras/3D%20Models/Top-Threaded.stl)), images are below.

![Image of the case next to a Harmony Hub viewed from above](Extras/Images/Case%20Top.jpeg)
![Image of the case next to a Harmony Hub viewed from the front](Extras/Images/Case%20Front.jpeg)

![Image of the case using a clear resin top](Extras/Images/Case%20Clear.jpeg)

The pinout for the connected GPIO devices is currently hardcoded to the following pins (matching the PCB layout):

- IR Receiver:
    | Receiver | OUT    | GND    | VCC  |
    |----------|--------|--------|------|
    | PI       | GPIO17 | Ground | 3.3V |
- IR Transmitter:
    | Transmitter | IN     | GND    | VCC  |
    |-------------|--------|--------|------|
    | PI          | GPIO18 | Ground | 3.3V |
- RF Transceiver:
    | NRF24L01+ | IRQ      | MISO  | MOSI   | SCK    | CSN   | CE    | VCC  | GND |
    |-----------|----------|-------|--------|--------|-------|-------|------|-----|
    | PI        | Not Used | GPIO9 | GPIO10 | GPIO11 | GPIO8 | GPIO7 | 3.3V | GND |


## Software-Setup

I'm using Raspberry Pi OS lite as a base, but pretty much any Linux distro should work.

### Dependencies
- Bluez (should be preinstalled)
- PiGPIO (should be preinstalled on any Pi OS)
- Python/Pip

### Setup

Start and enable `pigpiod`:

``` bash
sudo systemctl enable --now pigpiod
```

Clone this repo and install all Python dependencies:
``` bash
git clone https://github.com/leoklaus/Equilibrium
```
``` bash
cd Equilibrium
```
``` bash
python3 -m venv .venv
```
``` bash
source .venv/bin/activate
```
``` bash
pip install -r requirements.txt
```

Start Equilibrium once to see if everything starts correctly:
``` bash
python main.py --debug
```

(Optional) Daemonize it:
``` bash
sudo nano /etc/systemd/system/equilibrium.service
```

Replace `/path/to/Equilibrium/` with the path to the cloned repo and user and group with fitting values:

``` bash
[Unit]
Description=Equilibrium
After=syslog.target

[Service]
Type=simple
User=your-username
Group=your-group
WorkingDirectory=/path/to/Equilibrium/
ExecStart=/path/to/Equilibrium/.venv/bin/python /path/to/Equilibrium/main.py
Environment="PATH=/path/to/Equilibrium/.venv/bin"
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

``` bash
sudo systemctl daemon-reload
```

``` bash
sudo systemctl daemon-reload
```

``` bash
sudo systemctl start equilibrium
```

To automatically start it whenever the Pi boots:

``` bash
sudo systemctl enable equilibrium
```

## Usage

The entire config and local database are stored in the `config` directory within the `Equilibrium` directory.
If you want to create a backup or transfer your configuration, copying the config directory is sufficient.

### Preparing your remote

Equilibrium expects you to provide a number of config files to work with an RF remote:

- `rf_addresses.json`, containing the addresses your remote uses, for example: 
    ``` json
    [
        "08529258cb",
        "00529258cb"
    ]
    ```
  To determine the address of your Harmony remote, follow [these](https://github.com/joakimjalden/Harmoino?tab=readme-ov-file#retrieve-the-unique-rf24-network-address) instructions (ESP32 and NRF24L01+ module required).
  It should be fairly easy to translate this script to python so Equilibrium can help you discover the addresses right away, but I haven't gotten around to that yet.

- `remote_keymap.json`, containing the names, types and rf_commands of the buttons. A full example for the Harmony Companion remote can be found in [Extras/Config Examples](Extras/Config%20Examples/remote_keymap.json).
  A single button should look like this:
  ``` json
  "Off": {
        "button": "power_off",
        "rf_command": "0xc3ec01"
  }
  ```
  - Where `Off` is the name of the button (to be used in keymaps)
  - `power_off` is the type of button (see [RemoteButton](Api/models/RemoteButton.py) for available keys), this is used by Equilibrium to suggest key maps when creating scenes.
  - `0xc3ec01` are bytes 2-4 of the message the remote sends via RF (this is based on the protocol the Harmony Companion uses).

- `keymap_default.json` for when no scene is active and `keymap_<name>.json` for each individual key map (multiple scenes can use the same key map, if applicable).
  - At the moment, you have to create these yourself and assign them to a remote via their name (more in [creating scenes](#4-creating-scenes))
  - Equilibrium can suggest a key map for each scene based on the associated devices and your remote.

- `keymap_scenes.json` containing the buttons on the remotes used to start the scene and their respective ids. For example:
  ``` json
  {
    "Music": 2,
    "TV": 3,
    "Movie": 1
  }
  ```

### Configuring Equilibrium

I recommend using the WebUI (available at http://<your-hub-ip>:8000/ui/) or the iOS/Android app for Equilibrium.
- The iOS app is available through TestFlight here: https://testflight.apple.com/join/dyzEZYMs<br>If you want to take a look at the source code or build it yourself, you can check out the [Equilibrium-iOS repo](https://github.com/LeoKlaus/Equilibrium-iOS).
- The Android app is only [available as an APK](https://github.com/LeoKlaus/Equilibrium-Flutter/releases/latest), as I currently don't have a Play Store developer account.<br>The source code for the Android app and WebUI is available in [Equilibrium-Flutter](https://github.com/LeoKlaus/Equilibrium-Flutter)(contributions are very welcome).


### Using the API

As Equilibrium is based on FastAPI, it features autogenerated API docs. You can either use

`http://<ip-of-your-pi>:8000/docs`

or

`http://<ip-of-your-pi>:8000/redoc`

Though I recommend `/docs` as it allows you to try commands right from the webinterface.

#### 1. Creating devices

To create a device, send a post request to the `/devices` endpoint with the following information:


- `name: string`
- `manufacturer: string` (optional)
- `model: string` (optional)
- `type: display, amplifier, player, integration or other`, see [DeviceType.py](Api/models/DeviceType.py) for reference. This is used to determine which device should handle which actions when suggesting a key map.
- `bluetooth_address: string` (optional, bluetooth MAC address of the device, will be shown in the `/bluetooth/devices` endpoint if connected or paired)
- `image_id: int` (optional) You can upload images for devices or scenes using the `/images` endpoint.

An example for the full body would be:
``` json
{
  "name": "Soundbar",
  "manufacturer": "Samsung",
  "model": "HW-Q935GC",
  "type": "amplifier"
}
```

#### 2. Recording commands

At the moment, Equilibrium supports three types of commands:
1. Infrared commands (pretty much every normal remote)
2. Bluetooth commands (Equilibrium emulates a bluetooth keyboard to control devices, this works well for things like the Apple TV)
3. Network requests (allows you to configure a network request that is sent every time the command is sent. This can be used to trigger pretty much any home automation.)

Bluetooth and network commands can be created by posting to the `/commands` endpoint. For any command, the following keys are required:
- `name: string` Name for the command, is only used for identification
- `button: string` any button from [RemoteButton.py](/Api/models/RemoteButton.py). If not applicable, use `other`.
- `type`: `bluetooth` or `network`
- `device_id: int` (optional) id of the device this command belongs to.
- `command_group: string` any of the types defined in [CommandGroupType.py](/Api/models/CommandGroupType.py). If not applicable, use `other`.

##### Bluetooth
For Bluetooth commands, you additionally have to supply either
- `bt_action: string` any from [KEY_TABLE in KeymapHelper.py](/BleKeyboard/KeymapHelper.py) or
- `bt_media_action: string` any from [MEDIA_KEYS in KeymapHelper.py](/BleKeyboard/KeymapHelper.py)

A valid example for a bluetooth command would be
``` json
{
  "name": "Volume Up",
  "button": "volume_up",
  "type": "bluetooth",
  "command_group": "volume",
  "device_id": 3
  "bt_media_action": "KEY_VOLUME_UP"
}
```

##### Network
For network commands, you additionally have to supply the following:
- `host: string` the full URL to the server that should receive the command, including the protocol (i.e. `https://github.com`)
- `method: string` any of `get`, `post`, `delete`, `patch`, `put` or `head`
- `body: string` (optional) body to be sent with the request (only applicable for `post`, `patch` and `put`)

A valid example would be
``` json
{
  "name": "Toggle Bedroom Lights",
  "button": "other",
  "type": "network",
  "command_group": "other",
  "host": "http://my-node-red-host:1880/lights",
  "method": "post",
  "body": "{\"light_id\": 3}"
}
```

##### Infrared

Infrared commands can only be created via websockets using the `/ws/commands` endpoint.
You can use any websocket client to do this, I used [Insomnia](https://insomnia.rest).
To start, open a websocket connection with
`http://<ip-of-your-pi>:8000/ws/commands` and send the body of the command to create, for example:
```json
{
	"name": "Power Toggle",
	"button": "power_toggle",
	"type": "ir",
	"command_group": "power"
}
```

All websocket responses are any one of the keys defined under `WebsocketIrResponse` in [WebsocketResponses.py](/Api/models/WebsocketResponses.py). After posting a command, the response should be:<br>
`press_key`

Now you should point the remote at the IR received on your hub and press the button you want to record.
If the signal is detected correctly, you'll receive
`repeat_key`<br>
if the received signal is too short (this usually happens if the button is held and only a repeat signal is sent by the remote), you might receive<br>
`short_code`<br>
For either, you should press the button again. Once the command was recognized twice, the response will be<br>
`done`<br>
and the command is saved.

![Screenshot of the IR command recording process](/Extras/Images/IR-Recording-Done.png)

To verify, you can look for the command by sending a `GET` request to the `/commands` endpoint. If you found its ID, you can also try sending it by sending a `POST` request to the `/commands/<ID>/send` endpoint.

#### 3. Creating macros (optional but recommended)

Equilibrium supports creating macros that consist of multiple commands with optional delays in between them. The most common use case for macros is to start and stop scenes, like
1. "turn on tv"
2. "wait 1 second"
3. "press hdmi 4 button"
4. "turn on set-top box"

To create a macro, post a json with the following keys to the `/macro` endpoint:
- `name: string`
- `command_ids: [int]` List of the ids of all commands that should be executed. Commands will be sent in the order you provide here.
- `delays: [int]` List of delays (in ms) between commands. This has to contain `n-1` integers, where `n` is the number of commands executed. If no delay should be used, use `0`.
- `scene_ids: [int]` (optional) List of ids of scenes this macro should be assigned to.

A valid macro looks like this:
``` json
{
  "name": "Toggle TV Power and Switch Input",
  "command_ids": [1, 8, 3, 3, 7],
  "delays": [1000, 250, 50, 50]
}
```

Executing this macro will send command `1`, wait for 1000ms (1s), send command `8`, wait for 250ms, and so on.

#### 4. Creating scenes

To create a scene, post a json body with the following keys to the `/scenes` endpoint:
- `name: string`
- `image_id: int` (optional) ID of the image to be associated with this scene.
- `start_macro_id: int` (optional) ID of the macro to be executed when starting this scene.
- `stop_macro_id: int` (optional) ID of the macro to be executed when stopping this scene.
- `bluetooth_address: string` (optional) Bluetooth MAC address of the bluetooth device to use with this scene. If this is provided, Equilibrium will try to automatically connect to the given device when the scene is started (device has to be paired beforehand, see [5. Pairing Bluetooth devices](#5-pairing-bluetooth-devices)).
- `device_ids: [int]` (optional) List of device IDs that should be associated with this scene. This is used to suggest key maps. Devices that are included in the start or stop macro or have the given bluetooth address will be included automatically.
- `macro_ids: [int]` (optional) List of IDs of macros other than start and stop macro that should be associated with this scene
- `keymap: string` (optional) Name of the key map to use (excluding `keymap_` and `.json`, i.e. `keymap_apple_tv.json` -> `apple_tv`)

A valid scene looks like this:
```json
{
  "name": "Watch TV",
  "start_macro_id": 1,
  "stop_macro_id": 2,
  "device_ids": [4],
  "keymap": "tv"
}
```

To create a keymap for your scene, I suggest starting with the suggested keymap. To get this, send a `GET` request to the `/scenes/<ID>/keymap_suggestions` endpoint. You'll receive a JSON containing the keys for all buttons of your remote and (if applicable) matching command IDs:
```json
{
  "0": null,
  "1": null,
  "2": null,
  "3": null,
  "4": null,
  "5": null,
  "6": null,
  "7": null,
  "8": null,
  "9": null,
  "Off": null,
  "Music": null,
  "TV": null,
  "Movie": null,
  "BulbTop": null,
  "BulbBottom": null,
  "Plus": null,
  "Minus": null,
  "SocketTop": null,
  "SocketBottom": null,
  "Red": null,
  "Green": null,
  "Yellow": null,
  "Blue": null,
  "DVR": null,
  "Guide": null,
  "Info": null,
  "Exit": 40,
  "Menu": null,
  "VolumeUp": 28,
  "VolumeDown": 29,
  "ChannelUp": null,
  "ChannelDown": null,
  "Up": 34,
  "Down": 36,
  "Left": 35,
  "Right": 37,
  "OK": 38,
  "Mute": 30,
  "Back": 39,
  "Rewind": 44,
  "FastForward": 43,
  "Play": 41,
  "Pause": 42,
  "Record": null,
  "Stop": 47,
  ".": null,
  "E": null
}
```

You can edit this JSON to your liking and save it as `keymap_<name>.json` in the config directory for Equilibrium. 
To update your scene to use the keymap, send a `PATCH` request to the `/scenes/<ID>` endpoint containing at least the `name` and `keymap` keys:
```json
{
  "name": "Watch TV",
  "keymap": "my_keymap"
}
```

To start a scene, either press the button on your remote that has that scenes ID assigned to it in `keymap_scenes.json` or send a `POST` request to the `/scenes/<scene_id>/start` endpoint.<br>
To stop a scene, either press the "Off" button on your remote or send a `POST` request to the `/scenes/stop` endpoint.

When switching between scenes, Equilibrium will attempt to only send the necessary commands (like skipping power commands for devices that are already on). To do this, it keeps track of the power state and input of your devices. You can check the current state via the `/system/status` endpoint.

#### 5. Pairing Bluetooth devices

To pair a bluetooth device, make the virtual keyboard discoverable by sending a `POST` request to the `/bluetooth/start_advertisement` endpoint.

Then you should be able to see and connect to `Equilibrium Virtual Keyboard`. On some devices (notably Apple TVs), you might not see a pairing request automatically. In that case, you have to send the pairing request manually by sending a `POST` request to the `/bluetooth/start_pairing` endpoint and then confirming the pairing request on your device.

You can verify the status of the connection via the `/bluetooth/devices` endpoint. It will return an array of all connected devices and their current status:
``` json
[
  {
    "name": "Living Room",
    "address": "AB:CD:EF:12:34:56",
    "connected": true,
    "paired": true
  }
]
```

## Troubleshooting

If an error occurs, you should check the output from Equilibrium. If you have daemonized it, you can do so via `journalctl`.
In some cases, you may want to use the `--verbose` or `--debug` flags to get more verbose logs, though I don't recommend using either for longer times due to the number of log entries they create.