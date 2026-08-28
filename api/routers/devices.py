from collections.abc import Sequence

from fastapi import APIRouter, HTTPException
from sqlmodel import select

from api.models.device import Device, DevicePost, DeviceWithRelationships
from api.models.user_image import UserImage
from db_manager.db_manager import SessionDep

router = APIRouter(
    prefix="/devices",
    tags=["Devices"],
    responses={404: {"description": "Not found"}}
)

@router.get("/", response_model=list[DeviceWithRelationships])
def list_devices(session: SessionDep) -> Sequence[Device]:
    devices = session.exec(select(Device)).all()
    return devices


@router.get("/{device_id}", response_model=DeviceWithRelationships)
def read_device(device_id: int, session: SessionDep) -> Device:
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device

@router.delete("/{device_id}")
def delete_device(device_id: int, session: SessionDep):
    device = session.get(Device, device_id)
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    session.delete(device)
    session.commit()
    return {"ok": True}

@router.patch("/{device_id}")
def update_device(device_id: int, device: DevicePost, session: SessionDep):
    device_db = session.get(Device, device_id)
    if not device_db:
        raise HTTPException(status_code=404, detail="Device not found")
    device_data = device.model_dump(exclude_unset=True)

    if device.image_id is not None:
        image_db = session.get(UserImage, device.image_id)
        if not image_db:
            raise HTTPException(status_code=404, detail=f"Image {device.image_id} not found")
        device_db.image = image_db

    device_db.sqlmodel_update(device_data)
    session.add(device_db)
    session.commit()
    session.refresh(device_db)
    return device_db

@router.post("/", response_model=DeviceWithRelationships)
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