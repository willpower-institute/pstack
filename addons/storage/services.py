import os
import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from addons.storage.config import get_storage_settings
from addons.storage.models import StoredFile
from core.runtime import ctx


def storage_dir() -> Path:
    path = Path(get_storage_settings().dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def file_path(record: StoredFile) -> Path:
    return storage_dir() / record.stored_name


async def save_upload(session: AsyncSession, upload: UploadFile, owner_id: int) -> StoredFile:
    settings = get_storage_settings()
    data = await upload.read()
    if len(data) > settings.max_size_mb * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"ไฟล์ใหญ่เกิน {settings.max_size_mb}MB")

    # กัน path traversal: ใช้เฉพาะ basename และตั้งชื่อเก็บจริงเป็น uuid
    original = os.path.basename(upload.filename or "file")
    suffix = Path(original).suffix[:16]
    stored_name = uuid.uuid4().hex + suffix

    (storage_dir() / stored_name).write_bytes(data)

    record = StoredFile(
        original_name=original,
        stored_name=stored_name,
        mime=upload.content_type or "application/octet-stream",
        size=len(data),
        owner_id=owner_id,
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    await ctx.events.emit(
        "storage.uploaded", {"file_id": record.id, "owner_id": owner_id}
    )
    return record


async def get_for_user(session: AsyncSession, file_id: int, user) -> StoredFile:
    record = await session.get(StoredFile, file_id)
    if record is None:
        raise HTTPException(status_code=404, detail="file not found")
    if record.owner_id != user.id and not user.is_superuser:
        raise HTTPException(status_code=403, detail="not your file")
    return record


async def list_owned(session: AsyncSession, owner_id: int) -> list[StoredFile]:
    result = await session.execute(
        select(StoredFile).where(StoredFile.owner_id == owner_id).order_by(StoredFile.id.desc())
    )
    return list(result.scalars())


async def delete(session: AsyncSession, record: StoredFile) -> None:
    path = file_path(record)
    if path.exists():
        path.unlink()
    await session.delete(record)
    await session.commit()
