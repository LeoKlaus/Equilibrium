from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import RedirectResponse

from Api.lifespan import lifespan, lifespan_dev
from Api.models.ServerInfo import ServerInfo
from Api.routers import commands, devices, images, scenes, websockets, macros, bluetooth, system


def app_generator(dev: bool = False):
    if dev:
        app = FastAPI(lifespan=lifespan_dev)
    else:
        app = FastAPI(lifespan=lifespan)

    app.mount("/ui", StaticFiles(directory="web", html=True), name="ui")
    app.include_router(commands.router)
    app.include_router(devices.router)
    app.include_router(bluetooth.router)
    app.include_router(images.router)
    app.include_router(macros.router)
    app.include_router(scenes.router)
    app.include_router(websockets.router)
    app.include_router(system.router)

    @app.get("/", include_in_schema=False)
    def redirect():
        return RedirectResponse("/ui")

    @app.get("/info", tags=["Info"], response_model=ServerInfo)
    def app_info():
        return ServerInfo()

    return app