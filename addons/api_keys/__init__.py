from addons.api_keys.services import resolve_api_key
from core.runtime import ctx

# เสียบเข้า kernel auth: Bearer ที่ขึ้นต้น psk_ จะถูก resolve เป็น user ผ่านตาราง api_keys
ctx.token_resolvers.append(resolve_api_key)
