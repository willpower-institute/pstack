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


CHUNK_SIZE = 1024 * 1024


async def save_upload(session: AsyncSession, upload: UploadFile, owner_id: int) -> StoredFile:
    settings = get_storage_settings()
    limit = settings.max_size_mb * 1024 * 1024
    too_big = HTTPException(
        status_code=413, detail=f"ไฟล์ใหญ่เกิน {settings.max_size_mb}MB"
    )

    # ด่านที่ 1: ตัดตั้งแต่ก่อนอ่าน — starlette ใส่ size มาให้จาก content-length ของ part
    if upload.size is not None and upload.size > limit:
        raise too_big

    # กัน path traversal: ใช้เฉพาะ basename และตั้งชื่อเก็บจริงเป็น uuid
    original = os.path.basename(upload.filename or "file")
    suffix = Path(original).suffix[:16]
    stored_name = uuid.uuid4().hex + suffix
    target = storage_dir() / stored_name

    # ด่านที่ 2: อ่านทีละ chunk แล้วเขียนลงดิสก์เลย ไม่ถือทั้งไฟล์ไว้ใน RAM
    # (ของเดิมอ่านทั้งก้อนก่อนค่อยเช็คขนาด -> ไฟล์ 600MB ทำ RSS พุ่ง ~600MB
    #  ทั้งที่สุดท้ายตอบ 413 กลับไป = ใครที่ล็อกอินได้ก็ทำ OOM ให้ server ได้)
    size = 0
    try:
        with target.open("wb") as fh:
            while chunk := await upload.read(CHUNK_SIZE):
                size += len(chunk)
                if size > limit:
                    raise too_big
                fh.write(chunk)
    except BaseException:
        target.unlink(missing_ok=True)  # ไม่ทิ้งไฟล์ค้างเมื่อยกเลิกกลางคัน
        raise

    record = StoredFile(
        original_name=original,
        stored_name=stored_name,
        mime=upload.content_type or "application/octet-stream",
        size=size,
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
