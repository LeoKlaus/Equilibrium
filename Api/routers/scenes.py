from fastapi import APIRouter, HTTPException
from sqlmodel import select
from starlette.requests import Request

from Api.models import Macro
from Api.models.Command import Command
from Api.models.Device import Device
from Api.models.Scene import SceneWithRelationships, ScenePost, Scene, SceneUpdate, SceneStatusReport
from Api.models.UserImage import UserImage
from DbManager.DbManager import SessionDep
from RemoteController.RemoteController import RemoteController

router = APIRouter(
    prefix="/scenes",
    tags=["Scenes"],
    responses={404: {"description": "Not found"}}
)

@router.post("/", tags=["Scenes"], response_model=SceneWithRelationships)
def create_scene(scene: ScenePost, session: SessionDep) -> Scene:
    db_scene = Scene.model_validate(scene)
    image_id = scene.image_id
    session.add(db_scene)

    db_scene.bluetooth_address = scene.bluetooth_address

    if image_id:
        image_db = session.get(UserImage, image_id)
        if not image_db:
            raise HTTPException(status_code=404, detail=f"Image {image_id} not found")
        db_scene.image = image_db
    for device_id in scene.device_ids:
        device_db = session.get(Device, device_id)
        if not device_db:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
        db_scene.devices.append(device_db)

    start_macro = session.get(Macro, scene.start_macro_id)
    if not start_macro:
        raise HTTPException(status_code=400, detail=f"Macro {scene.start_macro_id} not found")
    db_scene.start_macro = start_macro

    stop_macro = session.get(Macro, scene.stop_macro_id)
    if not stop_macro:
        raise HTTPException(status_code=400, detail=f"Macro {scene.start_macro_id} not found")
    db_scene.stop_macro = stop_macro

    session.commit()
    session.refresh(db_scene)
    return db_scene


@router.get("/", tags=["Scenes"], response_model=list[SceneWithRelationships])
def list_scenes(session: SessionDep) -> list[Scene]:
    scenes = session.exec(select(Scene)).all()
    return scenes


@router.patch("/{scene_id}", tags=["Scenes"])
def update_scene(scene_id: int, scene: SceneUpdate, session: SessionDep):
    scene_db = session.get(Scene, scene_id)
    if not scene_db:
        raise HTTPException(status_code=404, detail="Scene not found")

    if scene.bluetooth_address:
        scene_db.bluetooth_address = scene.bluetooth_address

    if scene.start_macro_id:
        start_macro = session.get(Macro, scene.start_macro_id)
        if not start_macro:
            raise HTTPException(status_code=400, detail=f"Macro {scene.start_macro_id} not found")
        scene_db.start_macro = start_macro

    if scene.stop_macro_id:
        stop_macro = session.get(Macro, scene.stop_macro_id)
        if not stop_macro:
            raise HTTPException(status_code=400, detail=f"Macro {scene.stop_macro_id} not found")
        scene_db.stop_macro = stop_macro

    scene_data = scene.model_dump(exclude_unset=True)
    scene_db.sqlmodel_update(scene_data)
    session.add(scene_db)
    session.commit()
    session.refresh(scene_db)
    return scene_db


@router.delete("/{scene_id}", tags=["Scenes"])
def delete_scene(scene_id: int, session: SessionDep):
    scene = session.get(Scene, scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")

    session.delete(scene)
    session.commit()

    return {"message": f"Successfully deleted {scene.name}"}


@router.get("/current", tags=["Scenes"], response_model=SceneStatusReport)
def get_current_scene(request: Request) -> SceneStatusReport:
    controller: RemoteController = request.state.controller

    return controller.get_current_scene()


@router.get("/{scene_id}", tags=["Scenes"], response_model=SceneWithRelationships)
def show_scene(scene_id: int, session: SessionDep) -> Scene:
    scene = session.get(Scene, scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    return scene


@router.post("/{scene_id}/start", tags=["Scenes"])
async def start_scene(scene_id: int, request: Request):
    controller: RemoteController = request.state.controller

    await controller.start_scene(scene_id)

    return f"Started scene {scene_id}"


@router.post("/current", tags=["Scenes"])
async def set_current_scene(scene_id: int, request: Request):
    controller: RemoteController = request.state.controller

    await controller.set_current_scene(scene_id)
    return f"Set scene {scene_id} as current scene."

@router.post("/stop", tags=["Scenes"])
async def stop_current_scene(request: Request):
    controller: RemoteController = request.state.controller

    await controller.stop_current_scene()
    return "Stopped current scene."