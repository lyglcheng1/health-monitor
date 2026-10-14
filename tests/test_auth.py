"""登录会话测试：开启登录后未带凭据拦截、登录签发 cookie、退出清除。"""
import pytest


@pytest.fixture
def auth_enabled(monkeypatch):
    """把 main.settings 与 auth.get_settings 指向开启登录的 Settings。"""
    from app import auth as auth_mod
    from app import main as main_mod
    from app.config import Settings

    s = Settings(auth_username="admin", auth_password="secret", auth_secret="test-secret")
    monkeypatch.setattr(main_mod, "settings", s)
    monkeypatch.setattr(auth_mod, "get_settings", lambda: s)
    return s


async def test_unauth_api_blocked(client, auth_enabled):
    resp = await client.get("/api/exams")
    assert resp.status_code == 401
    body = resp.json()
    assert body["detail"]["code"] == 1001


async def test_unauth_page_redirect(client, auth_enabled):
    resp = await client.get("/", follow_redirects=False)
    assert resp.status_code == 302
    assert resp.headers["location"] == "/login"


async def test_login_wrong_password(client, auth_enabled):
    resp = await client.post("/api/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401
    assert resp.json()["detail"]["code"] == 1001


async def test_login_ok_and_access(client, auth_enabled):
    resp = await client.post("/api/login", json={"username": "admin", "password": "secret"})
    assert resp.status_code == 200
    assert "hm_session" in resp.cookies

    resp2 = await client.get("/api/exams")
    assert resp2.status_code == 200


async def test_logout(client, auth_enabled):
    resp = await client.post("/api/login", json={"username": "admin", "password": "secret"})
    assert resp.status_code == 200
    resp2 = await client.post("/api/logout")
    assert resp2.status_code == 200
    # cookie 被清除后，再访问 API 应 401
    resp3 = await client.get("/api/exams")
    assert resp3.status_code == 401