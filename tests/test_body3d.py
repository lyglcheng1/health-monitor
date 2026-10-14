"""V0.3 3D 人体大屏聚合 API 测试：按 body_part 聚合异常指标。

覆盖：
- mode=abnormal：只返回当前存在异常的部位，且只带异常指标
- mode=all：返回全部可映射部位（含正常部位与暂无数据部位）
- 「最近一次状态」口径：历史异常已恢复正常（吃药治好）不再标记异常
- 非法 mode → 400
- 记录按体检日期倒序、summary 拼接
- LLM 严重度判定：命中/失败回退/非法 JSON 回退/缓存复用
"""
import io

import pytest


@pytest.fixture
def tmp_settings(monkeypatch, tmp_path):
    """把 main.settings 指向临时 data/uploads 目录（避免写真实 data/）。"""
    from app import main as main_mod
    from app.config import Settings

    s = Settings(data_dir=str(tmp_path), uploads_dir=str(tmp_path / "uploads"))
    monkeypatch.setattr(main_mod, "settings", s)
    return s


@pytest.fixture
def mock_ocr(monkeypatch):
    """OCR 固定返回文本（外部依赖一律 mock，不发真实推理）。"""
    import app.ocr as ocr_mod

    def fake_ocr(data: bytes) -> str:
        return "体检报告文本"

    monkeypatch.setattr(ocr_mod, "ocr_image_bytes", fake_ocr)
    return fake_ocr


def _png_bytes() -> io.BytesIO:
    # 极小 PNG（1x1），内容对 mock OCR 无关紧要
    return io.BytesIO(
        bytes.fromhex(
            "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
            "0000000d49444154789c63600000020001000504270c0000000049454e44ae426082"
        )
    )


async def _add_exam_with_metrics(client, exam_date, hospital, metrics) -> int:
    up = await client.post(
        "/api/exams",
        files={"files": ("r.png", _png_bytes(), "image/png")},
        data={"exam_date": exam_date, "hospital": hospital},
    )
    assert up.status_code == 201
    exam_id = up.json()["data"]["results"][0]["id"]
    for m in metrics:
        resp = await client.post(f"/api/exams/{exam_id}/metrics", json=m)
        assert resp.status_code == 201
    return exam_id


async def test_body3d_abnormal_mode(client, tmp_settings, mock_ocr):
    """异常模式：只返回有异常的部位，正常部位（blood）不出现。"""
    await _add_exam_with_metrics(client, "2026-09-01", "协和医院", [
        {
            "name": "谷丙转氨酶 ALT",
            "value_text": "80",
            "unit": "U/L",
            "ref_low": "7",
            "ref_high": "40",
            "abnormal": True,
            "body_part": "liver",
        },
        {
            "name": "总胆固醇",
            "value_text": "5.2",
            "unit": "mmol/L",
            "ref_low": "",
            "ref_high": "5.2",
            "abnormal": False,
            "body_part": "blood",
        },
    ])
    await _add_exam_with_metrics(client, "2026-09-10", "市一院", [
        {
            "name": "尿蛋白",
            "value_text": "+",
            "unit": "",
            "ref_low": "-",
            "ref_high": "",
            "abnormal": True,
            "body_part": "kidney",
        },
    ])

    resp = await client.get("/api/body3d/overview?mode=abnormal")
    assert resp.status_code == 200
    parts = resp.json()["data"]["parts"]
    keys = [p["key"] for p in parts]

    assert "liver" in keys
    assert "kidney" in keys
    assert "blood" not in keys

    liver = next(p for p in parts if p["key"] == "liver")
    assert liver["name"] == "肝脏"
    assert liver["abnormal"] is True
    assert liver["severity"] == "mild"  # 1 项异常
    assert liver["conceptIds"] == ["FMA7197"]
    # 异常模式下只带异常指标
    assert all(i["status"] in ("偏高", "偏低", "异常") for i in liver["issues"])
    assert len(liver["issues"]) == 1
    assert liver["issues"][0]["name"] == "谷丙转氨酶 ALT"
    assert liver["issues"][0]["value"] == "80"
    assert liver["issues"][0]["range"] == "7~40"

    # 记录含体检日期、summary 拼接参考区间
    assert liver["records"][0]["date"] == "2026-09-01"
    assert "谷丙转氨酶 ALT 80U/L（参考 7-40）" in liver["records"][0]["summary"]
    assert liver["records"][0]["type"] == "体检"
    assert "note" in liver and liver["note"]


async def test_body3d_all_mode(client, tmp_settings, mock_ocr):
    """全部模式：正常部位也返回，abnormal=false，severity=None。"""
    await _add_exam_with_metrics(client, "2026-09-01", "协和医院", [
        {
            "name": "总胆固醇",
            "value_text": "4.2",
            "unit": "mmol/L",
            "ref_low": "",
            "ref_high": "5.2",
            "abnormal": False,
            "body_part": "blood",
        },
    ])

    resp = await client.get("/api/body3d/overview?mode=all")
    assert resp.status_code == 200
    parts = resp.json()["data"]["parts"]
    blood = next(p for p in parts if p["key"] == "blood")
    assert blood["abnormal"] is False
    assert blood["severity"] is None
    assert blood["conceptIds"] == ["ALL"]
    assert blood["issues"][0]["status"] == "正常"


async def test_body3d_invalid_mode(client):
    resp = await client.get("/api/body3d/overview?mode=bad")
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == 1002


async def test_body3d_records_sorted_desc(client, tmp_settings, mock_ocr):
    """同一指标多次异常：records 按日期倒序；严重度按「最近一次」1 项异常 → mild。"""
    for date, hospital, value in [
        ("2026-09-01", "协和医院", "80"),
        ("2026-09-10", "市一院", "95"),
        ("2026-09-20", "省人民医院", "120"),
    ]:
        await _add_exam_with_metrics(client, date, hospital, [
            {
                "name": "谷丙转氨酶 ALT",
                "value_text": value,
                "unit": "U/L",
                "ref_low": "7",
                "ref_high": "40",
                "abnormal": True,
                "body_part": "liver",
            },
        ])

    resp = await client.get("/api/body3d/overview?mode=abnormal")
    assert resp.status_code == 200
    liver = next(p for p in resp.json()["data"]["parts"] if p["key"] == "liver")
    dates = [r["date"] for r in liver["records"]]
    assert dates == ["2026-09-20", "2026-09-10", "2026-09-01"]
    # 同一指标多次异常，最近一次仍异常 → 按当前 1 项异常计 mild（不再累加历史）
    assert liver["severity"] == "mild"


async def test_body3d_latest_state_cured(client, tmp_settings, mock_ocr):
    """历史异常已恢复正常（吃药治好）：异常模式不再标记，记录时间线仍保留。"""
    await _add_exam_with_metrics(client, "2026-09-01", "协和医院", [
        {
            "name": "谷丙转氨酶 ALT",
            "value_text": "80",
            "unit": "U/L",
            "ref_low": "7",
            "ref_high": "40",
            "abnormal": True,
            "body_part": "liver",
        },
    ])
    await _add_exam_with_metrics(client, "2026-10-01", "协和医院", [
        {
            "name": "谷丙转氨酶 ALT",
            "value_text": "32",
            "unit": "U/L",
            "ref_low": "7",
            "ref_high": "40",
            "abnormal": False,
            "body_part": "liver",
        },
    ])

    # 异常模式：最近一次已正常 → 肝脏不出现
    resp = await client.get("/api/body3d/overview?mode=abnormal")
    assert resp.status_code == 200
    keys = [p["key"] for p in resp.json()["data"]["parts"]]
    assert "liver" not in keys

    # 全部模式：肝脏 abnormal=False，issues[0].status=正常，但保留历史异常记录
    resp = await client.get("/api/body3d/overview?mode=all")
    assert resp.status_code == 200
    liver = next(p for p in resp.json()["data"]["parts"] if p["key"] == "liver")
    assert liver["abnormal"] is False
    assert liver["severity"] is None
    assert liver["issues"][0]["status"] == "正常"
    assert [r["date"] for r in liver["records"]] == ["2026-09-01"]
    assert "已恢复正常" in liver["note"]


async def test_body3d_all_mode_contains_empty_parts(client, tmp_settings, mock_ocr):
    """全部模式：即使暂无数据，所有可映射部位也出现在左栏清单中。"""
    await _add_exam_with_metrics(client, "2026-09-01", "协和医院", [
        {
            "name": "总胆固醇",
            "value_text": "4.2",
            "unit": "mmol/L",
            "ref_low": "",
            "ref_high": "5.2",
            "abnormal": False,
            "body_part": "blood",
        },
    ])

    resp = await client.get("/api/body3d/overview?mode=all")
    assert resp.status_code == 200
    parts = resp.json()["data"]["parts"]
    brain = next(p for p in parts if p["key"] == "brain")
    assert brain["name"] == "脑"
    assert brain["abnormal"] is False
    assert brain["issues"] == []
    assert brain["records"] == []
    assert "暂无" in brain["note"]


# ── LLM 严重度判定 ──


@pytest.fixture(autouse=True)
def _clear_severity_cache():
    """每个测试前后清空 LLM 严重度缓存，避免跨测试污染。"""
    from app.body3d import clear_severity_cache

    clear_severity_cache()
    yield
    clear_severity_cache()


async def _fake_llm_available(session) -> bool:
    return True


async def _add_abnormal_liver(client, exam_date="2026-09-01") -> None:
    """建一条含 1 项异常指标（肝脏 ALT）的体检，用于 LLM 判定测试。"""
    await _add_exam_with_metrics(client, exam_date, "协和医院", [
        {
            "name": "谷丙转氨酶 ALT",
            "value_text": "80",
            "unit": "U/L",
            "ref_low": "7",
            "ref_high": "40",
            "abnormal": True,
            "body_part": "liver",
        },
    ])


async def _add_enabled_custom_model(client) -> int:
    """测试库无自定义模型 → 先添加并启用一个，让 resolve_model 返回 {name}@{id}。"""
    resp = await client.post(
        "/api/models/custom",
        json={
            "name": "u2-test",
            "base_url": "https://api.example.com/anthropic/v1/messages",
            "api_key": "sk-test",
            "protocol": "anthropic",
        },
    )
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    await client.post(f"/api/models/u2-test@{mid}/enable")
    return mid


async def test_llm_severity_used(client, tmp_settings, mock_ocr, monkeypatch):
    """LLM 可用时：严重度取 AI 判定，且带 severity_reason。"""
    import app.body3d as body3d_mod
    import app.llm as llm_mod

    await _add_abnormal_liver(client)

    # 测试库无自定义模型 → 先添加并启用一个，让 resolve_model 返回 {name}@{id}
    resp = await client.post(
        "/api/models/custom",
        json={
            "name": "u2-test",
            "base_url": "https://api.example.com/anthropic/v1/messages",
            "api_key": "sk-test",
            "protocol": "anthropic",
        },
    )
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]
    await client.post(f"/api/models/u2-test@{mid}/enable")

    async def fake_chat_text(model, messages, **kwargs):
        assert model == f"u2-test@{mid}"  # 路由到启用中的自定义模型
        return '{"severity": "severe", "reason": "谷丙转氨酶显著升高，提示肝功能损害"}'

    monkeypatch.setattr(body3d_mod, "_llm_available", _fake_llm_available)
    monkeypatch.setattr(llm_mod, "chat_text", fake_chat_text)

    resp = await client.get("/api/body3d/overview?mode=abnormal")
    assert resp.status_code == 200
    liver = next(p for p in resp.json()["data"]["parts"] if p["key"] == "liver")
    assert liver["severity"] == "severe"  # 1 项异常但 AI 判定为严重（覆盖数量兜底 mild）
    assert "肝功能" in liver["severity_reason"]


async def test_llm_severity_fallback_on_error(client, tmp_settings, mock_ocr, monkeypatch):
    """LLM 调用抛异常 → 回退数量规则（1 项异常 = mild），severity_reason 为空。"""
    import app.body3d as body3d_mod
    import app.llm as llm_mod

    await _add_abnormal_liver(client)
    await _add_enabled_custom_model(client)

    async def fake_chat_text(model, messages, **kwargs):
        raise RuntimeError("LLM 网关不可达")

    monkeypatch.setattr(body3d_mod, "_llm_available", _fake_llm_available)
    monkeypatch.setattr(llm_mod, "chat_text", fake_chat_text)

    resp = await client.get("/api/body3d/overview?mode=abnormal")
    assert resp.status_code == 200
    liver = next(p for p in resp.json()["data"]["parts"] if p["key"] == "liver")
    assert liver["severity"] == "mild"
    assert liver["severity_reason"] == ""


async def test_llm_severity_fallback_on_invalid_json(client, tmp_settings, mock_ocr, monkeypatch):
    """LLM 返回非 JSON → 回退数量规则。"""
    import app.body3d as body3d_mod
    import app.llm as llm_mod

    await _add_abnormal_liver(client)
    await _add_enabled_custom_model(client)

    async def fake_chat_text(model, messages, **kwargs):
        return "我不是JSON"

    monkeypatch.setattr(body3d_mod, "_llm_available", _fake_llm_available)
    monkeypatch.setattr(llm_mod, "chat_text", fake_chat_text)

    resp = await client.get("/api/body3d/overview?mode=abnormal")
    assert resp.status_code == 200
    liver = next(p for p in resp.json()["data"]["parts"] if p["key"] == "liver")
    assert liver["severity"] == "mild"
    assert liver["severity_reason"] == ""


async def test_llm_severity_cached(client, tmp_settings, mock_ocr, monkeypatch):
    """同一份数据重复请求不重复调用 LLM（进程内缓存命中）。"""
    import app.body3d as body3d_mod
    import app.llm as llm_mod

    await _add_abnormal_liver(client)
    await _add_enabled_custom_model(client)

    calls: list[int] = []

    async def fake_chat_text(model, messages, **kwargs):
        calls.append(1)
        return '{"severity": "moderate", "reason": "建议近期复查"}'

    monkeypatch.setattr(body3d_mod, "_llm_available", _fake_llm_available)
    monkeypatch.setattr(llm_mod, "chat_text", fake_chat_text)

    r1 = await client.get("/api/body3d/overview?mode=abnormal")
    r2 = await client.get("/api/body3d/overview?mode=all")
    assert r1.status_code == r2.status_code == 200
    assert len(calls) == 1  # 第二次请求命中缓存，不再调用 LLM
    liver = next(p for p in r2.json()["data"]["parts"] if p["key"] == "liver")
    assert liver["severity"] == "moderate"
    assert "复查" in liver["severity_reason"]