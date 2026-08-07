from addons.users.services import load_user
from core.runtime import ctx

# ให้ core.auth ใช้หา user จาก JWT
ctx.user_loader = load_user
