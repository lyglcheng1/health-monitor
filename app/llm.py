# ===============================================================
# 文件: llm.py
# 项目: 健康数据监控（health-monitor）
# 说明: LLM 模型路由——模型全部来自「模型设置」页自定义模型（OpenAI 兼容 /
#       Anthropic 端点，base_url + api_key 存本地 SQLite）。提供端点归一、
#       协议探测、连通测试、模型解析与 chat_text。AI 提取/分析复用本模块。
# ===============================================================
import asyncio
import logging
import re
import time
from typing import Any
from urllib.parse import urlsplit

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app import crud

logger = logging.getLogger(__name__)

# 进程内单例（get_llm_client 首次调用时填充）
_client: httpx.AsyncClient | None = None


def get_llm_client() -> httpx.AsyncClient:
    """LLM 客户端单例（懒创建；默认超时取 .env 配置）。"""
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=get_settings().llm_timeout)
    return _client


def reset_llm_client() -> None:
    """重置单例（测试隔离用）。"""
    global _client
    _client = None




# 自定义模型路由注册表（id → {name, base_url, api_key, protocol}）。
# 数据以 model_settings 表为准，API 层在请求入口刷新；问答用 resolve_model。
_custom_models: dict[int, dict[str, str]] = {}


def set_custom_models(mapping: dict[int, dict[str, str]]) -> None:
    """刷新自定义模型注册表（增删改后与各 /api/models* 请求入口调用）。"""
    global _custom_models
    _custom_models = {k: dict(v) for k, v in mapping.items()}


def custom_models() -> dict[int, dict[str, str]]:
    """当前注册的自定义模型 id → 路由信息。"""
    return {k: dict(v) for k, v in _custom_models.items()}


def _parse_route(model: str) -> tuple[str, int | None]:
    """把路由值拆成 (模型名, 自定义行 id|None)。

    路由值约定：自定义模型为 {name}@{id}（name 白名单不含 @）。
    """
    if "@" in model:
        name, _, suffix = model.rpartition("@")
        if name and suffix.isdigit():
            return name, int(suffix)
    return model, None


def route_model_name(model: str) -> str:
    """发给 LLM 的真实模型名：剥离路由值的 @id 后缀。"""
    name, _ = _parse_route(model)
    return name


def _custom_row(model: str) -> dict[str, str] | None:
    """按路由值查自定义模型行：优先 id 精确匹配；无 id 时按名字找唯一行（旧版兼容）。"""
    name, mid = _parse_route(model)
    if mid is not None:
        info = _custom_models.get(mid)
        if info is not None and info.get("name") == name:
            return info
        return None
    matched = [info for info in _custom_models.values() if info.get("name") == name]
    return matched[0] if len(matched) == 1 else None


# ── 添加模型「测试协议」：输入 base URL → 两协议候选端点 ──
_PROBE_TIMEOUT = 5.0


def _endpoint_candidates(raw: str) -> list[tuple[str, str]] | None:
    """用户填的 base URL → 有序候选端点 [(url, protocol)]（OpenAI 兼容优先）。

    protocol ∈ {"openai", "anthropic"}。返回 None = 非法地址（非 http(s)/含凭据/
    query/fragment）。
    """
    u = (raw or "").strip()
    if not u or "://" not in u:
        return None
    parsed = urlsplit(u)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None
    if parsed.username or parsed.password or "?" in u or "#" in u:
        return None
    host = f"{parsed.scheme}://{parsed.netloc}"
    path = parsed.path.rstrip("/")

    cands: list[tuple[str, str]] = []
    if path.endswith("/chat/completions"):
        cands.append((u, "openai"))
        cands.append((f"{host}/anthropic/v1/messages", "anthropic"))
    elif path.endswith("/v1/messages") or path.endswith("/anthropic/v1/messages"):
        cands.append((u, "anthropic"))
        cands.append((f"{host}/v1/chat/completions", "openai"))
    elif path.endswith("/anthropic"):
        cands.append((f"{u}/v1/messages", "anthropic"))
        cands.append((f"{host}/v1/chat/completions", "openai"))
        parent = path[: -len("/anthropic")]
        if parent:
            cands.append((f"{host}{parent}/v1/chat/completions", "openai"))
    elif re.search(r"/v\d+$", path):
        cands.append((f"{u}/chat/completions", "openai"))
        cands.append((f"{host}/anthropic/v1/messages", "anthropic"))
    elif path == "":
        cands.append((f"{host}/v1/chat/completions", "openai"))
        cands.append((f"{host}/anthropic/v1/messages", "anthropic"))
    else:
        cands.append((f"{u}/chat/completions", "openai"))
        cands.append((f"{host}/anthropic/v1/messages", "anthropic"))
    return cands


def _endpoint_for_protocol(raw: str, protocol: str) -> str | None:
    """按协议取该输入的首选候选端点（入库用）；非法地址/无该协议候选 → None。"""
    cands = _endpoint_candidates(raw)
    if not cands:
        return None
    for url, proto in cands:
        if proto == protocol:
            return url
    return None


def resolve_protocol(model: str) -> str:
    """返回模型调用协议（openai|anthropic）。自定义行以存储为准，其余一律 openai。"""
    info = _custom_row(model)
    if info and info.get("protocol") in ("openai", "anthropic"):
        return info["protocol"]  # type: ignore[return-value]
    return "openai"


async def detect_protocols(raw_base_url: str, api_key: str, model: str) -> list[dict[str, Any]]:
    """探测输入的 base URL 支持哪种调用协议（诊断语义，不抛异常）。"""
    cands = _endpoint_candidates(raw_base_url)
    if not cands:
        return []
    by_proto: dict[str, str] = {}
    for url, proto in cands:
        by_proto.setdefault(proto, url)

    async def _probe(protocol: str, url: str) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        if protocol == "anthropic":
            payload = {
                "model": model,
                "max_tokens": 16,
                "messages": [{"role": "user", "content": "ping"}],
            }
        else:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "ping"}],
                "max_tokens": 4,
                "temperature": 0,
            }
        start = time.perf_counter()

        def _done(ok: bool, message: str) -> dict[str, Any]:
            return {
                "protocol": protocol,
                "endpoint_url": url,
                "ok": ok,
                "latency_ms": int((time.perf_counter() - start) * 1000),
                "message": message,
            }

        try:
            resp = await get_llm_client().post(url, json=payload, headers=headers, timeout=_PROBE_TIMEOUT)
            if resp.status_code < 200 or resp.status_code >= 300:
                return _done(False, f"HTTP {resp.status_code}")
            try:
                data = resp.json()
            except Exception:
                return _done(False, "响应格式异常")
            if protocol == "anthropic":
                return _done(bool(data.get("content")), "" if data.get("content") else "响应缺少 content")
            return _done(bool(data.get("choices")), "" if data.get("choices") else "响应缺少 choices")
        except httpx.TimeoutException:
            return _done(False, "超时")
        except Exception as e:
            return _done(False, f"{e.__class__.__name__}")

    protos = [p for p in ("openai", "anthropic") if p in by_proto]
    return list(await asyncio.gather(*[_probe(p, by_proto[p]) for p in protos]))


def all_models() -> list[str]:
    """全部可路由模型的路由值：自定义模型（{name}@{id}）。"""
    return [f"{info['name']}@{mid}" for mid, info in _custom_models.items()]


def resolve_endpoint(model: str) -> tuple[str, float, dict[str, str]]:
    """按模型路由到对应端点，返回 (url, timeout, headers)。

    仅支持自定义模型：base_url 已是完整 chat/completions 或 /v1/messages URL，
    api_key 非空则 Bearer 鉴权。无匹配自定义行 → 抛 ValueError。
    """
    settings = get_settings()
    info = _custom_row(model)
    if info is not None and info.get("base_url"):
        headers = {}
        if info.get("api_key"):
            headers["Authorization"] = f"Bearer {info['api_key']}"
        return info["base_url"], settings.llm_timeout, headers
    raise ValueError(f"未配置自定义模型「{model}」：请先在模型设置中添加并启用")


async def resolve_model(session: AsyncSession, model: str | None) -> str | None:
    """确定实际问答模型的路由值：请求显式指定 > 模型管理启用项；无启用 → None。"""
    llm_map = await crud.custom_models_map(session)
    set_custom_models(llm_map)
    if model:
        return model
    enabled = await crud.get_enabled_model(session)
    if enabled is not None and enabled.kind == "custom":
        return f"{enabled.name}@{enabled.id}"
    return None


MODEL_TEST_TIMEOUT = 30.0


async def test_model(model: str) -> dict[str, Any]:
    """连通探测：向该模型端点发一条最小请求，返回 {ok, latency_ms, message}。

    诊断语义（不抛 HTTPException）：任何失败都以 ok=False + 原因返回。
    """
    url, _configured_timeout, headers = resolve_endpoint(model)
    protocol = resolve_protocol(model)
    payload_model = route_model_name(model)
    if protocol == "anthropic":
        payload = {
            "model": payload_model,
            "max_tokens": 16,
            "messages": [{"role": "user", "content": "ping"}],
        }
    else:
        payload = {
            "model": payload_model,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 4,
            "temperature": 0,
        }
    start = time.perf_counter()

    def _result(ok: bool, message: str) -> dict[str, Any]:
        return {
            "ok": ok,
            "latency_ms": int((time.perf_counter() - start) * 1000),
            "message": message,
        }

    try:
        resp = await get_llm_client().post(url, json=payload, headers=headers, timeout=MODEL_TEST_TIMEOUT)
        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            reason = ""
            try:
                body = e.response.json()
                err = body.get("error") or {}
                reason = str(err.get("message") or err.get("code") or "")[:200].strip()
            except Exception:
                pass
            return _result(False, f"服务可达但返回 HTTP {e.response.status_code}" + (f"：{reason}" if reason else ""))
        try:
            data: dict[str, Any] = resp.json()
        except Exception:
            return _result(False, "响应格式异常")
        if protocol == "anthropic":
            if not data.get("content"):
                return _result(False, "响应缺少 content 内容")
            return _result(True, "连通成功")
        try:
            choices = data["choices"]
        except (KeyError, TypeError):
            return _result(False, "响应格式异常（非 OpenAI 兼容的 chat/completions）")
        if not choices:
            return _result(False, "响应缺少 choices 内容")
        return _result(True, "连通成功")
    except httpx.TimeoutException:
        return _result(False, f"探测超时（{MODEL_TEST_TIMEOUT:.0f}s，模型可能未加载或服务未就绪）")
    except Exception as e:
        return _result(False, f"连接失败：{e.__class__.__name__}")


# ── LLM 调用（后续 AI 提取/分析复用）──


async def chat_text(
    model: str,
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 4096,
    disable_thinking: bool = False,
) -> str:
    """向指定模型发一轮对话，返回文本答案。失败抛异常（上层按业务包装）。

    max_tokens: Anthropic 协议必填，OpenAI 协议不传（用服务端默认）。
    disable_thinking: Anthropic 协议下禁用思考模式（对结构化提取更快更稳）；
      对 OpenAI 协议无影响。
    """
    url, _timeout, headers = resolve_endpoint(model)
    protocol = resolve_protocol(model)
    payload_model = route_model_name(model)
    if protocol == "anthropic":
        payload = {"model": payload_model, "max_tokens": max_tokens, "messages": messages}
        if disable_thinking:
            payload["thinking"] = {"type": "disabled"}
    else:
        payload = {"model": payload_model, "messages": messages}
    resp = await get_llm_client().post(url, json=payload, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    if protocol == "anthropic":
        parts = data.get("content") or []
        return "".join(str(p.get("text", "")) for p in parts if isinstance(p, dict))
    return data["choices"][0]["message"]["content"]