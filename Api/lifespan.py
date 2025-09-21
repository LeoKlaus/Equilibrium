from contextlib import asynccontextmanager

from fastapi import FastAPI

from Api import logger
from DbManager.DbManager import create_db_and_tables
from RemoteController.RemoteController import RemoteController
from ZeroconfManager.ZeroconfManager import ZeroconfManager

import json

@asynccontextmanager
async def lifespan(_: FastAPI):

    logger.info("Starting up...")

    create_db_and_tables()
    logger.info("Database initialized")

    addresses: list[bytes] | None = None

    try:
        with open("config/rf_addresses.json", "r") as file:
            address_data = file.read()

        address_strings = json.loads(address_data)
        addresses = list(map(lambda x: bytes.fromhex(x), address_strings))
    except FileNotFoundError:
        logger.warning("File \"rf_addresses.json\" was not found in config folder. Starting without RF addresses...")


    ha_url: str | None = None
    ha_token: str | None = None

    try:
        with open("config/ha_credentials.json", "r") as file:
            credential_data = file.read()
            ha_credentials = json.loads(credential_data)

        ha_url = ha_credentials["url"]
        ha_token = ha_credentials["token"]
    except FileNotFoundError:
        logger.warning(
            "File \"ha_credentials.json\" was not found in config folder. Starting without HA integration...")
    except KeyError:
        logger.error(
            "Couldn't get credentials from \"ha_credentials.json\". Make sure you have both \"url\" and \"token\" set."
        )

    controller = await RemoteController.create(rf_addresses=addresses, ha_url=ha_url, ha_token=ha_token)
    logger.info("Controller initialized")

    zeroconf = ZeroconfManager()
    await zeroconf.register_service("Test-Instance")
    logger.info("Registered bonjour service")

    yield {
        "controller": controller
    }

    logger.info("Shutting down...")
    await zeroconf.unregister_service()
    logger.info("Unregistered Zeroconf/Bonjour service")
    await controller.shutdown()

@asynccontextmanager
async def lifespan_dev(_: FastAPI):

    logger.info("Starting up...")

    create_db_and_tables()
    logger.info("Database initialized")


    ha_url: str | None = None
    ha_token: str | None = None

    try:
        with open("config/ha_credentials.json", "r") as file:
            credential_data = file.read()
            ha_credentials = json.loads(credential_data)

        ha_url = ha_credentials["url"]
        ha_token = ha_credentials["token"]
    except FileNotFoundError:
        logger.warning(
            "File \"ha_credentials.json\" was not found in config folder. Starting without HA integration...")
    except KeyError:
        logger.error(
            "Couldn't get credentials from \"ha_credentials.json\". Make sure you have both \"url\" and \"token\" set."
        )

    controller = await RemoteController.create_dev(ha_url=ha_url, ha_token=ha_token)
    logger.info("Controller initialized")

    zeroconf = ZeroconfManager()
    await zeroconf.register_service("Test-Instance-Dev")
    logger.info("Registered bonjour service")

    yield {
        "controller": controller
    }

    logger.info("Shutting down...")
    await zeroconf.unregister_service()
    logger.info("Unregistered Zeroconf/Bonjour service")
    await controller.shutdown()