#!/usr/bin/env bash
# Checks for (and installs/enables) the host-side dependencies Equilibrium
# needs when run via Docker: Docker itself, SPI enabled for the RF24
# radio, and the gpio-ir-tx/gpio-ir device tree overlays for the IR
# blaster/receiver. Also interactively sets up the optional app-level
# config in config/: the Harmony Companion remote, the Home Assistant
# integration, and the script execution module.
# Idempotent - safe to re-run.
#
# Usage: ./scripts/setup_host.sh

set -uo pipefail

# Run from the repo root regardless of the caller's cwd, since everything
# below refers to config/, docker-compose.yml and Extras/ by relative path.
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

_ok()   { printf '  [ok]      %s\n' "$1"; }
_do()   { printf '  [action]  %s\n' "$1"; }
_warn() { printf '  [!]       %s\n' "$1"; }

# Minimal JSON string escaping (backslash and double-quote) - enough for
# the URL/token values we write below without needing jq or python on
# the host.
_json_escape() {
    local s="$1"
    s="${s//\\/\\\\}"
    s="${s//\"/\\\"}"
    printf '%s' "$s"
}

# Sets KEY=VALUE in .env, creating the file or updating an existing key
# in place. Compose auto-loads .env for ${VAR} substitution in
# docker-compose.yml.
_write_env_var() {
    local key="$1" value="$2"
    touch .env
    if grep -q "^${key}=" .env; then
        sed -i.bak "s|^${key}=.*|${key}=${value}|" .env && rm -f .env.bak
    else
        echo "${key}=${value}" >> .env
    fi
}

needs_reboot=0
needs_relogin=0

echo "=== Docker ==="
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    _ok "Docker and the Compose plugin are already installed."
else
    _do "Installing Docker (via the official get.docker.com script)..."
    curl -fsSL https://get.docker.com | sh
fi

if id -nG "$(id -un)" | tr ' ' '\n' | grep -qx docker; then
    _ok "$(id -un) is already in the docker group."
else
    _do "Adding $(id -un) to the docker group (so docker/compose don't need sudo)..."
    sudo usermod -aG docker "$(id -un)"
    needs_relogin=1
fi

echo
echo "=== SPI (for the RF24 radio) ==="
if command -v raspi-config >/dev/null 2>&1; then
    # get_spi prints "0" if enabled, "1" if disabled - via stdout, not its
    # exit code. do_spi takes the same convention as an argument: 0 to
    # enable, 1 to disable.
    if [ "$(sudo raspi-config nonint get_spi)" = "0" ]; then
        _ok "SPI is already enabled."
    else
        _do "Enabling SPI..."
        sudo raspi-config nonint do_spi 0
        needs_reboot=1
    fi
else
    _warn "raspi-config not found - this isn't Raspberry Pi OS. Enable SPI manually for your distro (Equilibrium needs /dev/spidev0.0 for the RF24 radio)."
fi

echo
echo "=== IR blaster/receiver (gpio-ir-tx / gpio-ir overlays) ==="
# Modern Raspberry Pi OS (Bookworm+) keeps the boot firmware partition at
# /boot/firmware; older releases used /boot directly. Prefer the former,
# fall back to the latter.
if [ -f /boot/firmware/config.txt ]; then
    config_txt=/boot/firmware/config.txt
elif [ -f /boot/config.txt ]; then
    config_txt=/boot/config.txt
else
    config_txt=""
fi

if [ -n "$config_txt" ]; then
    if grep -q '^dtoverlay=gpio-ir-tx,gpio_pin=18' "$config_txt" 2>/dev/null; then
        _ok "gpio-ir-tx overlay (TX, GPIO18) is already configured."
    else
        _do "Adding gpio-ir-tx overlay (TX, GPIO18) to $config_txt..."
        echo "dtoverlay=gpio-ir-tx,gpio_pin=18" | sudo tee -a "$config_txt" >/dev/null
        needs_reboot=1
    fi

    if grep -q '^dtoverlay=gpio-ir,gpio_pin=17' "$config_txt" 2>/dev/null; then
        _ok "gpio-ir overlay (RX, GPIO17) is already configured."
    else
        _do "Adding gpio-ir overlay (RX, GPIO17) to $config_txt..."
        echo "dtoverlay=gpio-ir,gpio_pin=17" | sudo tee -a "$config_txt" >/dev/null
        needs_reboot=1
    fi
else
    _warn "Couldn't find config.txt - this isn't Raspberry Pi OS. Enable the gpio-ir-tx/gpio-ir (or equivalent) overlays manually for your distro so /dev/lircX devices exist."
fi

echo
echo "=== Harmony Companion remote ==="
read -rp "  Set up the Harmony Companion remote (RF pairing + keymap)? [y/N] " setup_harmony
if [[ "$setup_harmony" =~ ^[Yy]$ ]]; then
    mkdir -p config

    if [ -f config/rf_addresses.json ]; then
        _ok "config/rf_addresses.json already exists."
        read -rp "  Redo RF pairing? [y/N] " redo_pairing
    else
        redo_pairing="y"
    fi

    if [[ "${redo_pairing:-}" =~ ^[Yy]$ ]]; then
        if command -v docker >/dev/null 2>&1 && [ -f docker-compose.yml ]; then
            image=$(sed -n 's/^[[:space:]]*image:[[:space:]]*//p' docker-compose.yml | head -1)
            if [ -z "$image" ]; then
                _warn "Couldn't find an image reference in docker-compose.yml - skipping RF pairing."
            else
                _do "Pairing with the remote - this needs the RF24 hardware and the physical remote."
                echo "  Press and hold the pair/reset button on the back of the hub when prompted."
                docker run --rm -it --privileged -v /dev:/dev \
                    -v "$(pwd)/config:/app/config" \
                    --entrypoint python "$image" -m rf_manager.get_remote_address
            fi
        else
            _warn "Docker (and/or docker-compose.yml) isn't available - can't run the RF pairing helper."
        fi
    fi

    if [ -f config/remote_keymap.json ]; then
        _ok "config/remote_keymap.json already exists."
    else
        _do "Copying the Harmony Companion remote keymap to config/remote_keymap.json..."
        cp "Extras/Config Examples/remote_keymap.json" config/remote_keymap.json
    fi
else
    _ok "Skipping Harmony Companion remote setup."
fi

echo
echo "=== Home Assistant integration ==="
if [ -f config/ha_credentials.json ]; then
    _ok "config/ha_credentials.json already exists."
    read -rp "  Reconfigure the Home Assistant integration? [y/N] " setup_ha
else
    read -rp "  Set up the Home Assistant integration? [y/N] " setup_ha
fi

if [[ "${setup_ha:-}" =~ ^[Yy]$ ]]; then
    read -rp "  Home Assistant URL (e.g. http://homeassistant.local:8123): " ha_url
    read -rsp "  Long-lived access token (input hidden): " ha_token
    echo
    ha_url="${ha_url%/}"

    if command -v curl >/dev/null 2>&1; then
        status=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 \
            -H "Authorization: Bearer $ha_token" "$ha_url/api/" 2>/dev/null || echo "000")
        if [ "$status" = "200" ]; then
            _ok "Connected to Home Assistant successfully."
        else
            _warn "Couldn't verify the Home Assistant connection (HTTP $status) - double check the URL/token. Writing the config anyway; you can fix it later in config/ha_credentials.json."
        fi
    else
        _warn "curl isn't available - skipping the connection check."
    fi

    mkdir -p config
    printf '{\n    "url": "%s",\n    "token": "%s"\n}\n' \
        "$(_json_escape "$ha_url")" "$(_json_escape "$ha_token")" > config/ha_credentials.json
    _do "Wrote config/ha_credentials.json"
elif [ -f config/ha_credentials.json ]; then
    _ok "Keeping the existing Home Assistant configuration."
else
    _ok "Skipping Home Assistant integration."
fi

echo
echo "=== Script execution module ==="
echo "  WARNING: Commands with a script_path run an executable from"
echo "  config/scripts. Commands are created through the HTTP API, so"
echo "  enabling this effectively gives anything with API access to your"
echo "  hub the ability to run arbitrary code on it (the container"
echo "  already runs --privileged). Only enable this if you trust every"
echo "  client that can reach the API."
read -rp "  Enable the script execution module? [y/N] " enable_scripts

if [[ "${enable_scripts:-}" =~ ^[Yy]$ ]]; then
    mkdir -p config/scripts
    _write_env_var ENABLE_SCRIPTS true
    _do "Enabled script execution (ENABLE_SCRIPTS=true in .env). Put executables in config/scripts."
elif [ -f .env ] && grep -q '^ENABLE_SCRIPTS=true' .env 2>/dev/null; then
    _write_env_var ENABLE_SCRIPTS false
    _do "Disabled script execution (ENABLE_SCRIPTS=false in .env)."
else
    _ok "Script execution stays disabled."
fi

echo
echo "=== Summary ==="
if [ "$needs_reboot" -eq 1 ]; then
    echo "  Config was just changed - reboot before running Equilibrium: sudo reboot"
fi
if [ "$needs_relogin" -eq 1 ]; then
    echo "  You were added to the docker group - log out and back in (or run 'newgrp docker') before using docker without sudo."
fi
if [ "$needs_reboot" -eq 0 ] && [ "$needs_relogin" -eq 0 ]; then
    echo "  All checked dependencies are already in place."
fi
