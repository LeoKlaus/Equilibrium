from starlette.requests import Request

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from Api.models import Command, Scene, Device
from Api.models.Macro import Macro, MacroPost, MacroWithRelationships
from DbManager.DbManager import SessionDep
from RemoteController.RemoteController import RemoteController

router = APIRouter(
    prefix="/macros",
    tags=["Macros"],
    responses={404: {"description": "Not found"}}
)

@router.get("/", tags=["Macros"], response_model=list[MacroWithRelationships])
def list_macros(session: SessionDep):
    macros = session.exec(select(Macro)).all()
    return macros

@router.get("/{macro_id}", tags=["Macros"], response_model=MacroWithRelationships)
def get_macro(macro_id: int, session: SessionDep) -> MacroWithRelationships:
    macro = session.get(Macro, macro_id)
    if not macro:
        raise HTTPException(status_code=404, detail="Macro not found")
    return macro

@router.post("/", tags=["Macros"], response_model=MacroWithRelationships)
def create_macro(macro: MacroPost, session: SessionDep):
    db_macro = Macro.model_validate(macro)

    if len(macro.command_ids) == 0:
        raise HTTPException(status_code=400, detail="You have to include at least one command.")

    if (len(macro.command_ids) != (len(macro.delays) + 1)) and len(macro.command_ids) > 0:
        raise HTTPException(status_code=400, detail="You have to include one delay for all but the last command (len(command_ids) == len(delays)+1).")

    session.add(db_macro)

    device_ids: [int] = []

    for command_id in macro.command_ids:
        command_db = session.get(Command, command_id)
        if command_db is None:
            raise HTTPException(status_code=404, detail=f"Command {command_id} not found")
        db_macro.commands.append(command_db)
        if command_db.device is not None:
            device_ids.append(command_db.device_id)

    for scene_id in macro.scene_ids:
        scene_db = session.get(Scene, scene_id)
        if scene_db is None:
            raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")
        db_macro.scenes.append(scene_db)

    device_id_set = set(device_ids)

    for device_id in device_id_set:
        device_db = session.get(Device, device_id)
        if device_db is None:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
        db_macro.devices.append(device_db)

    db_macro.delays = macro.delays
    db_macro.command_ids = macro.command_ids
    session.commit()
    session.refresh(db_macro)
    return db_macro

@router.patch("/{macro_id}", tags=["Macros"], response_model=MacroWithRelationships)
def update_macro(macro_id: int, macro: MacroPost, session: SessionDep) -> MacroWithRelationships:
    macro_db = session.get(Macro, macro_id)
    if not macro_db:
        raise HTTPException(status_code=404, detail="Macro not found")

    if len(macro.command_ids) == 0:
        raise HTTPException(status_code=400, detail="You have to include at least one command.")

    if (len(macro.command_ids) != (len(macro.delays) + 1)) and len(macro.command_ids) > 0:
        raise HTTPException(status_code=400, detail="You have to include one delay for all but the last command (len(command_ids) == len(delays)+1).")

    macro_db.commands = []

    device_ids: [int] = []

    for command_id in macro.command_ids:
        command_db = session.get(Command, command_id)
        if not command_db:
            raise HTTPException(status_code=404, detail=f"Command {command_id} not found")
        macro_db.commands.append(command_db)
        device_ids.append(command_db.device_id)

    macro_db.scenes = []

    for scene_id in macro.scene_ids:
        scene_db = session.get(Scene, scene_id)
        if not scene_db:
            raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")
        macro_db.scenes.append(scene_db)

    macro_db.devices = []
    device_id_set = set(device_ids)

    for device_id in device_id_set:
        device_db = session.get(Device, device_id)
        if not device_db:
            raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
        macro_db.devices.append(device_db)

    macro_db.delays = macro.delays

    macro_data = macro.model_dump(exclude_unset=True)
    macro_db.sqlmodel_update(macro_data)
    session.add(macro_db)
    session.commit()
    session.refresh(macro_db)
    return macro_db

@router.delete("/{macro_id}", tags=["Macros"])
def delete_macros(macro_id: int, session: SessionDep):
    macro = session.get(Macro, macro_id)
    if macro is None:
        raise HTTPException(status_code=404, detail="Macro not found")

    session.delete(macro)
    session.commit()
    return {"message": f"Successfully deleted {macro.name}"}

@router.post("/{macro_id}/execute", tags=["Macros"])
async def send_command(macro_id: int, session: SessionDep, request: Request):
    macro = session.get(Macro, macro_id)

    if macro is None:
        raise HTTPException(status_code=404, detail="Macro not found")

    controller: RemoteController = request.state.controller
    return await controller.execute_macro(macro=macro)