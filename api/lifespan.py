import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api import logger
from db_manager.db_manager import run_migrations
from hub.hub import Hub
from zeroconf_manager.zeroconf_manager import ZeroconfManager

_DEFAULT_INSTANCE_NAME = "Equilibrium"


def _instance_name(dev: bool) -> str:
    """The name this hub advertises over mDNS/Bonjour - configurable via
    the INSTANCE_NAME env var (see docker-compose.yml/setup_host.sh)
    since two hubs on the same network need different names to be
    told apart. Falls back to the default on an unset or blank value.
    The dev/prod suffix is kept regardless, so running both against
    the same configured name still doesn't collide on one machine."""
    name = os.environ.get("INSTANCE_NAME", "").strip() or _DEFAULT_INSTANCE_NAME
    return f"{name}-Dev" if dev else name


def _load_rf_addresses() -> list[bytes] | None:
    try:
        with open("config/rf_addresses.json") as file:
            address_strings = json.loads(file.read())
        return [bytes.fromhex(address) for address in address_strings]
    except FileNotFoundError:
        logger.warning("File \"rf_addresses.json\" was not found in config folder. Starting without RF addresses...")
        return None


def _load_ha_credentials() -> tuple[str | None, str | None]:
    try:
        with open("config/ha_credentials.json") as file:
            ha_credentials = json.loads(file.read())
        return ha_credentials["url"], ha_credentials["token"]
    except FileNotFoundError:
        logger.warning(
            "File \"ha_credentials.json\" was not found in config folder. Starting without HA integration...")
        return None, None
    except KeyError:
        logger.error(
            "Couldn't get credentials from \"ha_credentials.json\". Make sure you have both \"url\" and \"token\" set."
        )
        return None, None


def _scripts_dir_from_env() -> str | None:
    """ENABLE_SCRIPTS is the explicit opt-in for the script module - set
    via setup_host.sh (writes it to .env) or by hand. Absent/false keeps
    script commands disabled, matching Hub.create()'s own default."""
    enabled = os.environ.get("ENABLE_SCRIPTS", "").strip().lower() in ("1", "true", "yes")
    return "config/scripts" if enabled else None


@asynccontextmanager
async def _lifespan(app: FastAPI, dev: bool):
    logger.info("Starting up...")

    run_migrations()
    logger.info("Database initialized")

    addresses = _load_rf_addresses()
    ha_url, ha_token = _load_ha_credentials()
    scripts_dir = _scripts_dir_from_env()

    hub = await Hub.create(
        rf_addresses=addresses, ha_url=ha_url, ha_token=ha_token, scripts_dir=scripts_dir, dev=dev
    )
    await hub.start()
    hub.mount_routers(app)
    logger.info("Hub initialized")

    zeroconf = ZeroconfManager()
    instance_name = _instance_name(dev)
    await zeroconf.register_service(instance_name)
    logger.info(f"Registered bonjour service as '{instance_name}'")

    yield {
        "status_store": hub.status_store,
        "keymap_resolver": hub.keymap_resolver,
        "scene_manager": hub.scene_manager,
        "command_dispatcher": hub.command_dispatcher,
        "ble_keyboard": hub.executors.get("bluetooth"),
        "ir_manager": hub.executors.get("ir"),
        "modules_manifest": hub.build_modules_manifest(),
    }

    logger.info("Shutting down...")
    await zeroconf.unregister_service()
    logger.info("Unregistered Zeroconf/Bonjour service")
    await hub.shutdown()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with _lifespan(app, dev=False) as state:
        yield state


@asynccontextmanager
async def lifespan_dev(app: FastAPI):
    async with _lifespan(app, dev=True) as state:
        yield state
