from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.responses import RedirectResponse

from api.lifespan import lifespan, lifespan_dev
from api.models.server_info import ServerInfo
from api.routers import commands, devices, images, macros, scenes, system, websockets


def app_generator(dev: bool = False, port: int = 8000):
    app = FastAPI(title="Equilibrium", lifespan=lifespan_dev if dev else lifespan)
    app.state.port = port

    app.mount("/ui", StaticFiles(directory="web", html=True), name="ui")
    app.include_router(commands.router)
    app.include_router(devices.router)
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