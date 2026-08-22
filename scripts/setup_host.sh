#!/usr/bin/env bash
# Checks for (and installs/enables) the host-side dependencies Equilibrium
# needs when run via Docker: Docker itself, SPI enabled for the RF24
# radio, and the gpio-ir-tx/gpio-ir device tree overlays for the IR
# blaster/receiver. Everything else (Python, the app's own dependencies)
# lives inside the container - see the Docker section of the readme.
# Idempotent - safe to re-run.
#
# Usage: ./scripts/setup_host.sh

set -uo pipefail

_ok()   { printf '  [ok]      %s\n' "$1"; }
_do()   { printf '  [action]  %s\n' "$1"; }
_warn() { printf '  [!]       %s\n' "$1"; }

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
