from fastapi import APIRouter, HTTPException
from sqlmodel import select

from Api.models import Command, Scene
from Api.models.Macro import Macro, MacroPost, MacroWithRelationships
from DbManager.DbManager import SessionDep

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
def create_macro(macro: MacroPost, session: SessionDep) -> MacroWithRelationships:
    db_macro = Macro.model_validate(macro)
    if len(macro.command_ids) != (len(macro.delays) + 1):
        raise HTTPException(status_code=400, detail="You have to include one delay for all but the last command (len(command_ids) == len(delays)+1).")

    session.add(db_macro)

    for command_id in macro.command_ids:
        command_db = session.get(Command, command_id)
        if not command_db:
            raise HTTPException(status_code=404, detail=f"Command {command_id} not found")
        db_macro.commands.append(command_db)

    for scene_id in macro.scene_ids:
        scene_db = session.get(Scene, scene_id)
        if not scene_db:
            raise HTTPException(status_code=404, detail=f"Scene {scene_id} not found")
        db_macro.scenes.append(scene_db)

    db_macro.delays = macro.delays
    session.commit()
    session.refresh(db_macro)
    return db_macro

@router.delete("/{macro_id}", tags=["Macros"])
def delete_macros(macro_id: int, session: SessionDep):
    macro = session.get(Macro, macro_id)
    if not macro:
        raise HTTPException(status_code=404, detail="Macro not found")

    session.delete(macro)
    session.commit()
    return {"message": f"Successfully deleted {macro.name}"}

