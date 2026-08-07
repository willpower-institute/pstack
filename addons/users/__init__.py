from core.runtime import ctx

from addons.users.services import load_user

# ให้ core.auth ใช้หา user จาก JWT
ctx.user_loader = load_user
