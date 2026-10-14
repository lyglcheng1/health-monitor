"""静态资源与前端规范守卫（防止 HTML 内联 JS/CSS 回潮）。"""
import re

_INDEX = "static/index.html"
_BODY3D = "static/body3d.html"

# importmap 是静态 JSON 配置（非可执行脚本），3D 大屏页允许存在；
# 其余 HTML 一律禁止不带 src 的内联 <script>
_IMPORTMAP_RE = re.compile(r"<script\s+type=[\"']importmap[\"']\s*>[\s\S]*?</script>", re.I)


def _strip_importmap(text: str) -> str:
    return _IMPORTMAP_RE.sub("", text)


async def test_static_assets(client):
    resp = await client.get("/static/css/style.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]

    resp = await client.get("/static/js/app.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]

    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


async def test_index_no_inline_js_css(client):
    text = open(_INDEX, encoding="utf-8").read()
    # 允许外部 <script src=...>，仅禁止不带 src 的内联 <script>
    assert not re.search(r"<script(?![^>]*\bsrc=)", text), "HTML 内禁止内联 <script>"
    assert "<style" not in text, "HTML 内禁止内联 <style>"
    assert "style=" not in text, "HTML 内禁止 style= 属性"
    assert not re.search(r"\son[a-z]+=", text, re.I), "HTML 内禁止 on* 事件属性"


async def test_body3d_no_inline_js_css(client):
    """3D 大屏页：仅允许 importmap 静态配置，禁止可执行内联 JS/CSS/on*。"""
    text = _strip_importmap(open(_BODY3D, encoding="utf-8").read())
    assert not re.search(r"<script(?![^>]*\bsrc=)", text), "body3d.html 内禁止可执行内联 <script>"
    assert "<style" not in text, "body3d.html 内禁止内联 <style>"
    assert "style=" not in text, "body3d.html 内禁止 style= 属性"
    assert not re.search(r"\son[a-z]+=", text, re.I), "body3d.html 内禁止 on* 事件属性"


async def test_body3d_assets_served(client):
    """3D 大屏静态资源可达。"""
    resp = await client.get("/static/body3d.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]

    resp = await client.get("/static/js/body3d.js")
    assert resp.status_code == 200
    assert "javascript" in resp.headers["content-type"]

    resp = await client.get("/static/css/body3d.css")
    assert resp.status_code == 200
    assert "text/css" in resp.headers["content-type"]


async def test_app_js_syntax_ok(client):
    """用 node --check 校验 app.js 语法（node 缺失时跳过）。"""
    import shutil
    import subprocess

    node = shutil.which("node")
    if not node:
        return
    proc = subprocess.run([node, "--check", "static/js/app.js"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr