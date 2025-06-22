from fastapi import FastAPI
from starlette.responses import RedirectResponse

from Api.lifespan import lifespan, lifespan_dev
from Api.routers import commands, devices, images, scenes, websockets, macros


def app_generator(dev: bool = False):
    if dev:
        app = FastAPI(lifespan=lifespan_dev)
    else:
        app = FastAPI(lifespan=lifespan)

    app.include_router(commands.router)
    app.include_router(devices.router)
    app.include_router(images.router)
    app.include_router(scenes.router)
    app.include_router(websockets.router)
    app.include_router(macros.router)

    @app.get("/", include_in_schema=False)
    def redirect():
        return RedirectResponse("/docs")

    return app