"""env กลางของชุดเทส — ต้องตั้ง **ก่อน** import core.config ทุกกรณี

ทำไมต้องรวมไว้ที่เดียว:

1. `core.config.get_settings()` เป็น `lru_cache` — ค่าที่อ่านครั้งแรกถูกใช้ตลอดทั้ง session
   ไฟล์เทสที่ตั้ง os.environ เองตอน import จะชนกันทันทีที่มีมากกว่าหนึ่งไฟล์บูต app
   (ไฟล์ไหน import ก่อนชนะ อีกไฟล์เห็น PSTACK_MODULES ผิดแล้วพังแบบหาสาเหตุยาก —
   รันไฟล์เดียวผ่าน รันทั้งชุดแดง)

2. pydantic-settings อ่าน `.env` ของเครื่อง dev ด้วย — ค่าที่เทสพึ่งพาต้องปักหมุดไว้ที่นี่
   ไม่งั้นแค่ dev เปลี่ยน PSTACK_ADMIN_PASSWORD ใน .env เทสที่ล็อกอินด้วยรหัส admin
   ก็แดงทั้งชุดโดยที่โค้ดไม่ได้ผิดอะไร

โมดูลใหม่ที่อยากให้เทสครอบ ให้เพิ่มชื่อใน PSTACK_MODULES ด้านล่างที่เดียว
"""

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

os.environ["PSTACK_DATABASE_URL"] = "sqlite+aiosqlite:///./test_pstack.db"
os.environ["PSTACK_SECRET_KEY"] = "test-key-" + "x" * 40  # ต้องยาวพอตามที่ config บังคับ
os.environ["PSTACK_MODULES"] = (
    "users,storage,ai_agent,line_oa,faq,api_keys,mcp_server,tenancy,extdemo"
)
os.environ["PSTACK_ADDONS_PATHS"] = "addons,tests/ext_addons"  # ทดสอบ external addons path
os.environ["PSTACK_STORAGE_DIR"] = "./test_uploads"
os.environ["PSTACK_LINE_SYNC_MODE"] = "true"  # ประมวลผล webhook แบบ sync ในเทส
os.environ["PSTACK_ADMIN_EMAIL"] = "admin@example.com"
# แหล่งความจริงเดียวของรหัส admin ในชุดเทส — ไฟล์เทสให้ `from conftest import ADMIN_PASSWORD`
# อย่า hardcode ซ้ำในไฟล์เทส: PR ที่แตกกิ่งไว้ก่อนรหัสเปลี่ยนจะพาค่าเก่ากลับมาแบบเงียบ ๆ
# (เคยเกิดจริงตอน merge #28 หลัง #29 — เทสยังผ่านเพราะไม่ได้ assert สถานะ
#  แต่วิ่งอยู่บน path 401 ทั้งที่ docstring บอกว่าล็อกอินสำเร็จ)
ADMIN_PASSWORD = "test-admin-pw-9f3k2x"  # ต้องผ่านกติกาความแข็งแรงใน core/config.py
os.environ["PSTACK_ADMIN_PASSWORD"] = ADMIN_PASSWORD
# ปิด rate limit ในชุดเทสหลัก (เทสหลายตัวล็อกอินซ้ำ ๆ ด้วยบัญชีเดียวกัน)
# ตัว rate limit เองมีเทสแยกที่ tests/test_login_rate_limit.py
os.environ["PSTACK_LOGIN_RATE_LIMIT_PER_IP"] = "0"
os.environ["PSTACK_LOGIN_RATE_LIMIT_PER_ACCOUNT"] = "0"
