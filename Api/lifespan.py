import json
from contextlib import asynccontextmanager

from fastapi import FastAPI

from Api import logger
from db_manager.db_manager import create_db_and_tables
from hub.hub import Hub
from zeroconf_manager.zeroconf_manager import ZeroconfManager


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


@asynccontextmanager
async def _lifespan(app: FastAPI, dev: bool):
    logger.info("Starting up...")

    create_db_and_tables()
    logger.info("Database initialized")

    addresses = _load_rf_addresses()
    ha_url, ha_token = _load_ha_credentials()

    hub = await Hub.create(rf_addresses=addresses, ha_url=ha_url, ha_token=ha_token, dev=dev)
    await hub.start()
    hub.mount_routers(app)
    logger.info("Hub initialized")

    zeroconf = ZeroconfManager()
    await zeroconf.register_service("Test-Instance-Dev" if dev else "Test-Instance")
    logger.info("Registered bonjour service")

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
