# ===============================================================
# 文件: auth.py
# 项目: 健康数据监控（health-monitor）
# 说明: 登录会话（itsdangerous 签名 cookie），无第三方令牌
# ===============================================================
"""登录会话：.env 配置用户名密码 + itsdangerous 签名 cookie。

- 单用户（AUTH_USERNAME/AUTH_PASSWORD），配置 AUTH_PASSWORD 即开启登录；
  未配置时 auth_enabled=False，全部请求放行（保持单机自用的零门槛）
- 会话是签名 cookie（SERVER_SECRET 密钥 + 时序安全比较校验），无服务端存储；
  cookie 属性 HttpOnly + SameSite=Lax；有效期 SESSION_TTL_HOURS（默认 7 天）
- 校验用 hmac.compare_digest（防口令碰撞提前返回）
"""
import hmac
import time

from itsdangerous import BadSignature, URLSafeTimedSerializer

from app.config import get_settings

# 签名会话的 salt（与用途绑定，防其他场景的 token 复用）
_SALT = "hm.session.v1"
COOKIE_NAME = "hm_session"


def _serializer():
    secret = get_settings().auth_secret
    return URLSafeTimedSerializer(secret, salt=_SALT)


def verify_credentials(username: str, password: str) -> bool:
    """核对用户名与口令（时序安全比较，长度差异也不提前返回）。"""
    s = get_settings()
    user_ok = hmac.compare_digest(
        (username or "").encode("utf-8"), (s.auth_username or "").encode("utf-8")
    )
    pass_ok = hmac.compare_digest(
        (password or "").encode("utf-8"), (s.auth_password or "").encode("utf-8")
    )
    return user_ok and pass_ok


def issue_token(username: str) -> str:
    """签发会话 token：载荷只有用户名与签发时间。"""
    return _serializer().dumps({"u": username, "t": int(time.time())})


def read_token(token: str | None) -> str | None:
    """校验会话 token；无效/过期返回 None（max_age 秒级过期由 itsdangerous 处理）。"""
    if not token:
        return None
    s = get_settings()
    try:
        data = _serializer().loads(token, max_age=s.session_ttl_hours * 3600)
    except BadSignature:
        return None
    except Exception:
        return None
    return data.get("u")