import os
from typing import Annotated

import requests
from agents import function_tool
from dotenv import load_dotenv
from pydantic import Field

load_dotenv()

GOOGLE_PLACE_TEXTSEARCH_URL = "https://maps.googleapis.com/maps/api/place/textsearch/json"
GOOGLE_DIRECTIONS_URL = "https://maps.googleapis.com/maps/api/directions/json"


def _get_api_key() -> str:
    return os.getenv("GOOGLE_MAPS_API_KEY", "").strip()


def _require_api_key() -> tuple[str | None, str]:
    key = _get_api_key()
    if key:
        return None, key
    return "未配置 GOOGLE_MAPS_API_KEY，暂时无法使用 Google 地图工具。", ""


def _google_error_message(prefix: str, status: str, data: dict, http_status: int | None = None) -> str:
    detail = str(data.get("error_message") or "").strip()
    http_part = f"HTTP {http_status}，" if http_status else ""
    base = f"{prefix}失败，{http_part}状态：{status}"
    if detail:
        base += f"；原因：{detail}"
    if status == "REQUEST_DENIED":
        base += "。请检查：API Key 是否正确、是否启用 Places/Directions API、是否绑定结算、Key 限制（IP/HTTP referrer）是否匹配当前环境。"
    return base


@function_tool
async def search_places_google(
    city: Annotated[str, Field(description="城市名，例如：Tokyo、Paris、上海")],
    query: Annotated[str, Field(description="搜索关键词，例如：museum、sushi、park")],
    limit: Annotated[int, Field(description="返回数量，建议 3-8")] = 5,
) -> str:
    """使用 Google Places Text Search 搜索地点，返回名称、评分、地址和坐标。"""
    missing, api_key = _require_api_key()
    if missing:
        return missing

    safe_limit = max(1, min(limit, 8))
    params = {
        "query": f"{query} in {city}",
        "language": "zh-CN",
        "key": api_key,
    }
    try:
        resp = requests.get(GOOGLE_PLACE_TEXTSEARCH_URL, params=params, timeout=12)
        data = resp.json()
    except Exception as exc:
        return f"Google Places 查询失败：{exc}"

    if resp.status_code != 200:
        return _google_error_message("Google Places 查询", "HTTP_ERROR", data, resp.status_code)

    status = data.get("status", "UNKNOWN_ERROR")
    if status not in {"OK", "ZERO_RESULTS"}:
        return _google_error_message("Google Places 查询", status, data)
    if status == "ZERO_RESULTS":
        return f"{city} 没有找到与“{query}”相关地点。"

    results = data.get("results", [])[:safe_limit]
    lines = [f"**Google 地点搜索：{query}（{city}）**"]
    for idx, item in enumerate(results, start=1):
        name = item.get("name", "未知地点")
        rating = item.get("rating", "无评分")
        address = item.get("formatted_address", "无地址")
        location = item.get("geometry", {}).get("location", {})
        lat = location.get("lat")
        lng = location.get("lng")
        types = ", ".join(item.get("types", [])[:3]) if item.get("types") else "未知分类"
        lines.append(
            f"{idx}. {name}｜评分：{rating}｜类型：{types}\n"
            f"   地址：{address}\n"
            f"   坐标：{lat}, {lng}"
        )
    return "\n".join(lines)


@function_tool
async def get_route_google(
    origin: Annotated[str, Field(description="起点，例如：Tokyo Station")],
    destination: Annotated[str, Field(description="终点，例如：Senso-ji Temple")],
    mode: Annotated[str, Field(description="出行方式：walking/driving/transit/bicycling")] = "transit",
) -> str:
    """使用 Google Directions 估算两地通勤时间与距离。"""
    missing, api_key = _require_api_key()
    if missing:
        return missing

    transport_mode = mode if mode in {"walking", "driving", "transit", "bicycling"} else "transit"
    params = {
        "origin": origin,
        "destination": destination,
        "mode": transport_mode,
        "language": "zh-CN",
        "key": api_key,
    }
    try:
        resp = requests.get(GOOGLE_DIRECTIONS_URL, params=params, timeout=12)
        data = resp.json()
    except Exception as exc:
        return f"Google 路线查询失败：{exc}"

    if resp.status_code != 200:
        return _google_error_message("Google 路线查询", "HTTP_ERROR", data, resp.status_code)

    status = data.get("status", "UNKNOWN_ERROR")
    if status != "OK":
        return _google_error_message("Google 路线查询", status, data)

    routes = data.get("routes", [])
    if not routes:
        return "未找到可用路线。"

    leg = routes[0].get("legs", [{}])[0]
    distance = leg.get("distance", {}).get("text", "未知距离")
    duration = leg.get("duration", {}).get("text", "未知时长")
    start_addr = leg.get("start_address", origin)
    end_addr = leg.get("end_address", destination)
    return (
        f"**Google 通勤估算（{transport_mode}）**\n"
        f"- 起点：{start_addr}\n"
        f"- 终点：{end_addr}\n"
        f"- 距离：{distance}\n"
        f"- 预计时长：{duration}"
    )
