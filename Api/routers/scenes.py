from fastapi import APIRouter, HTTPException
from sqlmodel import select
from starlette.requests import Request

from Api.models.Command import Command
from Api.models.Device import Device
from Api.models.Scene import SceneWithRelationships, ScenePost, Scene, SceneUpdate
from Api.models.UserImage import UserImage
from DbManager.DbManager import SessionDep

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

    for command_id in scene.start_command_ids:
        command_db = session.get(Command, command_id)
        if not command_db:
            raise HTTPException(status_code=500, detail=f"Command {command_id} not found")
        db_scene.start_commands.append(command_db)

    for command_id in scene.stop_command_ids:
        command_db = session.get(Command, command_id)
        if not command_db:
            raise HTTPException(status_code=500, detail=f"Command {command_id} not found")
        db_scene.stop_commands.append(command_db)

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

    #TODO: This will only append commands, not remove them
    for command_id in scene.start_command_ids:
        command_db = session.get(Command, command_id)
        if not command_db:
            raise HTTPException(status_code=500, detail=f"Command {command_id} not found")
        scene_db.start_commands.append(command_db)

    # TODO: This will only append commands, not remove them
    for command_id in scene.stop_commands_ids:
        command_db = session.get(Command, command_id)
        if not command_db:
            raise HTTPException(status_code=500, detail=f"Command {command_id} not found")
        scene_db.stop_commands.append(command_db)

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


@router.get("/{scene_id}", tags=["Scenes"], response_model=SceneWithRelationships)
def show_scene(scene_id: int, session: SessionDep) -> Scene:
    scene = session.get(Scene, scene_id)
    if not scene:
        raise HTTPException(status_code=404, detail="Scene not found")
    return scene


@router.post("/{scene_id}/start", tags=["Scenes"])
async def start_scene(scene_id: int, session: SessionDep, request: Request):
    # TODO: Implement starting scenes using RemoteController
    return


@router.get("/current", tags=["Scenes"])
def get_current_scene(session: SessionDep):
    # TODO: Implement getting current scene using RemoteController
    return


@router.post("/current", tags=["Scenes"])
async def set_current_scene(scene_id: int, session: SessionDep, request: Request):
    # TODO: Implement setting current scene using RemoteController
    return


@router.post("/stop", tags=["Scenes"])
async def stop_current_scene(session: SessionDep, request: Request):
    # TODO: Implement current scene using RemoteController
    return