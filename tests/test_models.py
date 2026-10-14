"""模型管理 API 测试：清单/自定义模型增删改/启停/连通探测（LLM 一律 mock）。"""


async def test_models_list_custom_only(client):
    """模型清单只含自定义模型；无自定义时列表为空。"""
    resp = await client.get("/api/models")
    assert resp.status_code == 200
    models = resp.json()["data"]["models"]
    assert models == []  # 测试库无自定义模型 → 空清单

    # 添加自定义模型后出现在清单中，且没有 env 条目
    resp = await client.post(
        "/api/models/custom",
        json={
            "name": "my-llm",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test",
            "protocol": "openai",
        },
    )
    assert resp.status_code == 201
    resp = await client.get("/api/models")
    assert resp.status_code == 200
    models = resp.json()["data"]["models"]
    assert len(models) == 1
    assert models[0]["custom"] is True
    assert models[0]["name"] == "my-llm"
    assert not any(not m["custom"] for m in models)


async def test_custom_model_crud(client):
    # 添加
    resp = await client.post(
        "/api/models/custom",
        json={
            "name": "my-llm",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test",
            "protocol": "openai",
        },
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    model_id = body["id"]
    assert body["has_key"] is True
    assert body["base_url"].endswith("/chat/completions")

    # 管理列表
    resp = await client.get("/api/models/admin")
    assert resp.status_code == 200
    custom = [it for it in resp.json()["data"]["items"] if it["custom"]]
    assert len(custom) == 1
    assert custom[0]["has_key"] is True

    # 修改（换 Key + 换端点）
    resp = await client.put(
        f"/api/models/custom/{model_id}",
        json={"api_key": "", "base_url": "https://api2.example.com/v1"},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["has_key"] is False
    assert "api2.example.com" in resp.json()["data"]["base_url"]

    # 启用（路由值 {name}@{id}）
    resp = await client.post(f"/api/models/my-llm@{model_id}/enable")
    assert resp.status_code == 200
    admin = (await client.get("/api/models/admin")).json()["data"]
    assert admin["enabled"] == f"my-llm@{model_id}"

    # 停用
    resp = await client.post(f"/api/models/my-llm@{model_id}/disable")
    assert resp.status_code == 200
    admin = (await client.get("/api/models/admin")).json()["data"]
    assert admin["enabled"] is None

    # 删除
    resp = await client.delete(f"/api/models/custom/{model_id}")
    assert resp.status_code == 200
    admin = (await client.get("/api/models/admin")).json()["data"]
    custom = [it for it in admin["items"] if it["custom"]]
    assert len(custom) == 0


async def test_custom_model_duplicate_rejected(client):
    payload = {
        "name": "dup-llm",
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-1",
        "protocol": "openai",
    }
    resp = await client.post("/api/models/custom", json=payload)
    assert resp.status_code == 201
    resp = await client.post("/api/models/custom", json=payload)
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == 1006


async def test_delete_missing_custom_model_404(client):
    # 不存在的自定义模型 id → 404
    resp = await client.delete("/api/models/custom/999999")
    assert resp.status_code == 404
    assert resp.json()["detail"]["code"] == 2004


async def test_model_test_mocked(client, monkeypatch):
    """连通探测端点：mock llm.test_model，不发真实请求。"""
    import app.main as main_mod

    async def fake_test(model: str) -> dict:
        return {"ok": True, "latency_ms": 12, "message": "连通成功"}

    monkeypatch.setattr(main_mod.llm, "test_model", fake_test)

    # 先添加自定义模型，再测它的连通性
    resp = await client.post(
        "/api/models/custom",
        json={
            "name": "my-llm",
            "base_url": "https://api.example.com/v1",
            "api_key": "sk-test",
            "protocol": "openai",
        },
    )
    assert resp.status_code == 201
    mid = resp.json()["data"]["id"]

    resp = await client.post(f"/api/models/my-llm@{mid}/test")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["ok"] is True
    assert body["model"] == f"my-llm@{mid}"


async def test_model_detect_mocked(client, monkeypatch):
    """协议探测端点：mock detect_protocols，不发真实请求。"""
    import app.main as main_mod

    async def fake_detect(base_url: str, api_key: str, model: str) -> list[dict]:
        return [
            {
                "protocol": "openai",
                "endpoint_url": f"{base_url}/v1/chat/completions",
                "ok": True,
                "latency_ms": 5,
                "message": "",
            }
        ]

    monkeypatch.setattr(main_mod.llm, "detect_protocols", fake_detect)

    resp = await client.post(
        "/api/models/custom/detect",
        json={"name": "x", "base_url": "https://api.example.com/v1", "api_key": ""},
    )
    assert resp.status_code == 200
    assert resp.json()["data"]["results"][0]["ok"] is True


async def test_model_detect_invalid_url(client):
    resp = await client.post(
        "/api/models/custom/detect",
        json={"name": "x", "base_url": "not-a-url", "api_key": ""},
    )
    assert resp.status_code == 400
    assert resp.json()["detail"]["code"] == 1006