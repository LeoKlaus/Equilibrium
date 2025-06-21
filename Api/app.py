from fastapi import FastAPI

from Api.lifespan import lifespan, lifespan_dev
from Api.routers import images


def app_generator(dev: bool = False):
    if dev:
        app = FastAPI(lifespan=lifespan_dev)
    else:
        app = FastAPI(lifespan=lifespan)

    app.include_router(images.router)

    return app