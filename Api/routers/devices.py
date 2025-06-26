from fastapi import APIRouter, HTTPException
from sqlmodel import select
from Api.models.Device import DeviceWithRelationships, DevicePost, Device, DeviceBase
from Api.models.UserImage import UserImage
from DbManager.DbManager import SessionDep

router = APIRouter(
    prefix="/devices",
    tags=["Devices"],
    responses={404: {"description": "Not found"}}
)

@router.get("/", tags=["Devices"], response_model=list[DeviceWithRelationships])
def list_devices(session: SessionDep) -> list[Device]:
    devices = session.exec(select(Device)).all()
    return devices


@router.get("/{device_id}", tags=["Devices"], response_model=DeviceWithRelationships)
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

@router.post("/", tags=["Devices"], response_model=DeviceWithRelationships)
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
