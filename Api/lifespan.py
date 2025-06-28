from contextlib import asynccontextmanager

from fastapi import FastAPI

from Api import logger
from RemoteController.RemoteController import RemoteController
from ZeroconfManager.ZeroconfManager import ZeroconfManager

import json

@asynccontextmanager
async def lifespan(_: FastAPI):

    logger.info("Starting up...")

    addresses = []

    try:
        with open("../config/rf_addresses.json", "r") as file:
            address_data = file.read()

        address_strings = json.loads(address_data)
        addresses = list(map(lambda x: bytes.fromhex(x), address_strings))
    except FileNotFoundError:
        logger.warning("File \"rf_addresses.json\" was not found in config folder. Starting without RF addresses...")

    controller = await RemoteController.create(rf_addresses=addresses)
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


    controller = await RemoteController.create_dev()
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