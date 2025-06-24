from fastapi import APIRouter, HTTPException
from sqlmodel import select

from Api.models.CommandGroup import CommandGroup, CommandGroupBase
from Api.models.Device import DeviceWithCommandGroup, DevicePost, Device, DeviceBase
from Api.models.UserImage import UserImage
from DbManager.DbManager import SessionDep

router = APIRouter(
    prefix="/devices",
    tags=["Devices"],
    responses={404: {"description": "Not found"}}
)

@router.get("/", tags=["Devices"], response_model=list[DeviceWithCommandGroup])
def list_devices(session: SessionDep) -> list[Device]:
    devices = session.exec(select(Device)).all()
    return devices

@router.get("/{device_id}", tags=["Devices"], response_model=DeviceWithCommandGroup)
def read_device(device_id: int, session: SessionDep) -> Device:
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device

@router.delete("/{device_id}", tags=["Devices"])
def delete_device(device_id: int, session: SessionDep):
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    session.delete(device)
    session.commit()
    return {"ok": True}


@router.patch("/{device_id}", tags=["Devices"])
def update_device(device_id: int, device: DeviceBase, session: SessionDep):
    device_db = session.get(Device, device_id)
    if not device_db:
        raise HTTPException(status_code=404, detail="Device not found")
    device_data = device.model_dump(exclude_unset=True)
    device_db.sqlmodel_update(device_data)
    session.add(device_db)
    session.commit()
    session.refresh(device_db)
    return device_db

@router.post("/", tags=["Devices"], response_model=DeviceWithCommandGroup)
def create_device(device: DevicePost, session: SessionDep) -> Device:
    db_device = Device.model_validate(device)
    image_id = device.image_id
    if image_id:
        image_db = session.get(UserImage, image_id)
        if not image_db:
            raise HTTPException(status_code=404, detail=f"Image {image_id} not found")
        db_device.image = image_db
    session.add(db_device)
    session.commit()
    session.refresh(db_device)
    return db_device


@router.post("/{device_id}/command_groups", tags=["Devices"], response_model=CommandGroup)
def create_command_group(command_group: CommandGroupBase, device_id: int, session: SessionDep) -> CommandGroup:
    device_db = session.get(Device, device_id)
    if not device_db:
        raise HTTPException(status_code=404, detail="Device not found")
    db_command_group = CommandGroup.model_validate(command_group)

    db_command_group.device_id = device_id
    session.add(db_command_group)
    session.commit()
    session.refresh(db_command_group)
    return db_command_group

@router.delete("/{device_id}/command_groups/{command_group_id}", tags=["Devices"])
def delete_command_group(device_id: int, command_group_id, session: SessionDep):
    command_group = session.get(CommandGroup, command_group_id)
    if not command_group:
        raise HTTPException(status_code=404, detail="Command group not found")
    session.delete(command_group)
    session.commit()
    return {"ok": True}

