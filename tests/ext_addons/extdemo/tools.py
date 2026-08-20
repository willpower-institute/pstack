"""AI tool สำหรับเทส — รายงาน tenant ที่ชั้นบนผูกมากับ session

ใช้พิสูจน์ว่า MCP ส่ง tenant context ลงมาถึงตัว tool จริง
"""

from sqlalchemy.ext.asyncio import AsyncSession

from core.ai import agent_tool
from core.tenancy import bound_tenant


@agent_tool(module="extdemo", permission=None)
async def whoami_tenant(session: AsyncSession) -> str:
    """คืน tenant ที่ผูกกับ session ปัจจุบัน (ใช้ในเทสเท่านั้น)"""
    return f"tenant={bound_tenant(session) or 'none'}"
