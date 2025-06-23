import os
from io import BytesIO
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, UploadFile, HTTPException
from sqlmodel import select
from starlette.responses import FileResponse

from Api.models.UserImage import UserImage
from DbManager.DbManager import SessionDep

from PIL import Image

router = APIRouter(
    prefix="/images",
    tags=["Images"],
    responses={404: {"description": "Not found"}}
)

@router.get("/", tags=["Images"])
def get_all_images(session: SessionDep):
    images = session.exec(select(UserImage)).all()
    return images

@router.get("/{image_id}", tags=["Images"])
def get_image(image_id: int, session: SessionDep):
    image = session.get(UserImage, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(image.path)

@router.post("/", tags=["Images"])
async def upload_image(file: UploadFile, session: SessionDep):
    try:
        contents = await file.read()
        pil_img = Image.open(BytesIO(contents))
        pil_img.thumbnail((512,512))
        path = Path("./config/images/" + str(uuid4()) + ".png")
        Path("./config/images").mkdir(exist_ok=True)
        image = UserImage()
        image.filename = file.filename
        image.path = str(path)
        pil_img.save(path, "PNG")
        db_image = UserImage.model_validate(image)
        session.add(db_image)
        session.commit()
        return {"message": f"Successfully uploaded {file.filename}", "id": db_image.id}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'Something went wrong: {e}')
    finally:
        file.file.close()

@router.delete("/{image_id}", tags=["Images"])
def delete_image(image_id: int, session: SessionDep):
    image = session.get(UserImage, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")
    path = Path(image.path)
    session.delete(image)
    session.commit()
    if path.is_file():
        path.unlink()
    return {"message": f"Successfully deleted {image.filename}"}

