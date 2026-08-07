from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from addons.mcp_server import services
from core.auth import get_current_user

router = APIRouter(tags=["mcp"])


@router.post("/mcp")
async def mcp_endpoint(
    request: Request,
    user: Annotated[object, Depends(get_current_user)],
):
    """MCP Streamable HTTP endpoint — ตัวอย่างต่อจาก Claude Code:

    claude mcp add pstack --transport http https://<host>/mcp \\
        --header "Authorization: Bearer psk_xxx"
    """
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            services._error(None, -32700, "parse error"), status_code=400
        )

    response = await services.handle_rpc(user, payload)
    if response is None:  # notification — ตอบรับเฉยๆ ตาม spec
        return Response(status_code=202)
    return JSONResponse(response)


@router.get("/mcp")
async def mcp_get() -> Response:
    # ไม่รองรับ server-initiated stream (spec อนุญาตให้ตอบ 405)
    return Response(status_code=405)
