from typing import Annotated

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth import get_current_user
from core.db import get_session

from addons.storage import services

router = APIRouter(prefix="/api/storage", tags=["storage"])


class FileOut(BaseModel):
    id: int
    original_name: str
    mime: str
    size: int

    model_config = {"from_attributes": True}


@router.post("/upload", response_model=FileOut, status_code=201)
async def upload(
    file: UploadFile,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    return await services.save_upload(session, file, user.id)


@router.get("", response_model=list[FileOut])
async def list_files(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    return await services.list_owned(session, user.id)


@router.get("/{file_id}/download")
async def download(
    file_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    record = await services.get_for_user(session, file_id, user)
    return FileResponse(
        services.file_path(record),
        filename=record.original_name,
        media_type=record.mime,
    )


@router.delete("/{file_id}", status_code=204)
async def delete_file(
    file_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[object, Depends(get_current_user)],
):
    record = await services.get_for_user(session, file_id, user)
    await services.delete(session, record)
