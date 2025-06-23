from contextlib import asynccontextmanager

from fastapi import FastAPI

from Api import logger
from RemoteController.RemoteController import RemoteController
from ZeroconfManager.ZeroconfManager import ZeroconfManager


@asynccontextmanager
async def lifespan(_: FastAPI):

    logger.info("Starting up...")


    controller = await RemoteController.create()
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


    controller = await RemoteController.create(dev=True)
    logger.info("Controller initialized")

    yield {
        "controller": controller
    }

    logger.info("Shutting down...")
    await controller.shutdown()