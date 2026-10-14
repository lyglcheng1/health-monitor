"""体检记录 API 测试：上传+OCR（mock）、列表/详情/图片、指标 CRUD、删除。"""
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
        return "谷丙转氨酶 ALT 25 U/L\n总胆固醇 5.2 mmol/L"

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


async def test_upload_ocr_and_list(client, tmp_settings, mock_ocr):
    resp = await client.post(
        "/api/exams",
        files={"files": ("report1.png", _png_bytes(), "image/png")},
        data={"exam_date": "2026-09-01", "hospital": "协和医院", "note": "年度体检"},
    )
    assert resp.status_code == 201
    body = resp.json()["data"]["results"][0]
    assert body["status"] == "created"
    assert body["exam_date"] == "2026-09-01"
    assert body["hospital"] == "协和医院"
    assert body["source"] == "report1.png"  # 来源/附件 = 原始文件名
    assert "谷丙转氨酶" in body["ocr_text"]
    exam_id = body["id"]

    resp2 = await client.get("/api/exams")
    assert resp2.status_code == 200
    items = resp2.json()["data"]["items"]
    assert len(items) == 1
    assert items[0]["id"] == exam_id
    assert items[0]["source"] == "report1.png"


async def test_upload_empty_files_rejected(client, tmp_settings):
    resp = await client.post("/api/exams", files={})
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == 1002


async def test_exam_detail_image_and_metrics(client, tmp_settings, mock_ocr):
    up = await client.post(
        "/api/exams",
        files={"files": ("r.png", _png_bytes(), "image/png")},
        data={"exam_date": "2026-09-02"},
    )
    exam_id = up.json()["data"]["results"][0]["id"]

    # 详情
    resp = await client.get(f"/api/exams/{exam_id}")
    assert resp.status_code == 200
    detail = resp.json()["data"]
    assert detail["metric_count"] == 0

    # 图片
    img = await client.get(f"/api/exams/{exam_id}/image")
    assert img.status_code == 200
    assert img.content

    # 添加指标
    metric = {
        "name": "谷丙转氨酶 ALT",
        "value_text": "25",
        "unit": "U/L",
        "ref_low": "7",
        "ref_high": "40",
        "abnormal": False,
        "body_part": "liver",
        "note": "",
        "sort": 0,
    }
    resp = await client.post(f"/api/exams/{exam_id}/metrics", json=metric)
    assert resp.status_code == 201
    metric_id = resp.json()["data"]["id"]

    resp = await client.get(f"/api/exams/{exam_id}")
    detail = resp.json()["data"]
    assert detail["metric_count"] == 1
    assert detail["metrics"][0]["body_part"] == "liver"

    # 修改指标
    metric["value_text"] = "30"
    resp = await client.put(f"/api/metrics/{metric_id}", json=metric)
    assert resp.status_code == 200
    assert resp.json()["data"]["value_text"] == "30"

    # 删除指标
    resp = await client.delete(f"/api/metrics/{metric_id}")
    assert resp.status_code == 200
    resp = await client.get(f"/api/exams/{exam_id}")
    assert resp.json()["data"]["metric_count"] == 0


async def test_update_and_delete_exam(client, tmp_settings, mock_ocr):
    up = await client.post(
        "/api/exams",
        files={"files": ("r.png", _png_bytes(), "image/png")},
        data={"exam_date": "2026-09-03"},
    )
    exam_id = up.json()["data"]["results"][0]["id"]

    resp = await client.put(
        f"/api/exams/{exam_id}",
        json={"exam_date": "2026-09-10", "hospital": "市一院", "note": "复查"},
    )
    assert resp.status_code == 200

    resp = await client.get(f"/api/exams/{exam_id}")
    detail = resp.json()["data"]
    assert detail["exam_date"] == "2026-09-10"
    assert detail["hospital"] == "市一院"
    assert detail["note"] == "复查"

    resp = await client.delete(f"/api/exams/{exam_id}")
    assert resp.status_code == 200

    resp = await client.get(f"/api/exams/{exam_id}")
    assert resp.status_code == 404


async def test_exam_source_detail_and_update(client, tmp_settings, mock_ocr):
    """来源/附件字段：详情可见，且可修改。"""
    raw = "连云港第一人民医院20260930检查.pdf 第6-6页（检验报告单）.png"
    up = await client.post(
        "/api/exams",
        files={"files": (raw, _png_bytes(), "image/png")},
        data={"exam_date": "2026-09-04"},
    )
    assert up.status_code == 201
    exam_id = up.json()["data"]["results"][0]["id"]
    assert up.json()["data"]["results"][0]["source"] == raw

    # 详情包含 source
    resp = await client.get(f"/api/exams/{exam_id}")
    assert resp.status_code == 200
    assert resp.json()["data"]["source"] == raw

    # PUT 可修改 source
    new_source = "连云港第一人民医院20260930检查.pdf 第1/6页（总检报告）"
    resp = await client.put(
        f"/api/exams/{exam_id}",
        json={"source": new_source},
    )
    assert resp.status_code == 200
    resp = await client.get(f"/api/exams/{exam_id}")
    assert resp.json()["data"]["source"] == new_source


async def test_metrics_missing_exam_404(client):
    resp = await client.get("/api/exams/999999")
    assert resp.status_code == 404
    resp = await client.post("/api/exams/999999/metrics", json={"name": "x"})
    assert resp.status_code == 404


async def test_body_records_crud(client):
    # 新增
    resp = await client.post(
        "/api/body-records",
        json={"record_date": "2026-09-01", "record_type": "weight", "value": 68.5, "unit": "kg", "note": "晨起"},
    )
    assert resp.status_code == 201
    record_id = resp.json()["data"]["id"]

    resp = await client.get("/api/body-records")
    assert resp.status_code == 200
    assert len(resp.json()["data"]["items"]) == 1

    resp = await client.delete(f"/api/body-records/{record_id}")
    assert resp.status_code == 200
    resp = await client.get("/api/body-records")
    assert len(resp.json()["data"]["items"]) == 0