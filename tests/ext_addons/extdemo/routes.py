from fastapi import APIRouter

router = APIRouter(prefix="/api/extdemo", tags=["extdemo"])


@router.get("/ping")
async def ping() -> dict:
    return {"module": "extdemo", "status": "ok"}
