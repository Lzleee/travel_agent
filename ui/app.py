import json
import os
import re

import requests
import streamlit as st
import pydeck as pdk
from dotenv import load_dotenv

load_dotenv()

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:8000")

TOOL_LABELS = {
    "get_weather": "正在查询天气预报...",
    "search_attractions": "正在搜索景点信息...",
    "search_places_google": "正在通过 Google 地图搜索地点...",
    "get_route_google": "正在通过 Google 地图计算通勤...",
}


# ── 后端通信 ──────────────────────────────────────────────────────────────

def stream_from_backend(message: str, session_id: str | None):
    with requests.post(
        f"{BACKEND_URL}/chat",
        json={"message": message, "session_id": session_id},
        stream=True,
        timeout=120,
    ) as resp:
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line and line.startswith(b"data: "):
                yield json.loads(line[6:])


def run_chat(user_message: str) -> str:
    status_box = st.empty()
    text_box = st.empty()
    result = ""

    for event in stream_from_backend(user_message, st.session_state.get("session_id")):
        etype = event.get("type")
        if etype == "session_id":
            st.session_state.session_id = event["session_id"]
        elif etype == "tool_start":
            label = event.get("label", event["name"])
            status_box.info(f"🔍 {label}...")
        elif etype == "content":
            result += event["text"]
            text_box.markdown(result + "▌")
        elif etype == "done":
            break

    status_box.empty()
    text_box.markdown(result)
    return result


def extract_places_from_text(text: str) -> list[dict]:
    places: list[dict] = []
    current_name = ""
    coord_pattern = re.compile(r"坐标[:：]\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)")

    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if re.match(r"^\d+\.\s+", line):
            current_name = re.sub(r"^\d+\.\s*", "", line).split("｜", 1)[0].strip()
            continue

        match = coord_pattern.search(line)
        if not match:
            continue

        lat = float(match.group(1))
        lon = float(match.group(2))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            continue

        places.append(
            {
                "name": current_name or "地点",
                "lat": lat,
                "lon": lon,
            }
        )
    return places


def render_places_map(reply_text: str) -> None:
    places = extract_places_from_text(reply_text)
    if not places:
        return

    unique_places: list[dict] = []
    seen: set[tuple[float, float]] = set()
    for item in places:
        key = (round(item["lat"], 6), round(item["lon"], 6))
        if key in seen:
            continue
        seen.add(key)
        unique_places.append(item)

    if not unique_places:
        return

    avg_lat = sum(item["lat"] for item in unique_places) / len(unique_places)
    avg_lon = sum(item["lon"] for item in unique_places) / len(unique_places)
    zoom = 12 if len(unique_places) <= 3 else 11

    layers: list[pdk.Layer] = [
        pdk.Layer(
            "ScatterplotLayer",
            data=unique_places,
            get_position="[lon, lat]",
            get_radius=80,
            get_fill_color=[220, 50, 47, 180],
            pickable=True,
        )
    ]
    if len(unique_places) >= 2:
        path_data = [{"path": [[p["lon"], p["lat"]] for p in unique_places]}]
        layers.append(
            pdk.Layer(
                "PathLayer",
                data=path_data,
                get_path="path",
                get_width=4,
                get_color=[30, 136, 229, 180],
                width_scale=2,
            )
        )

    st.caption("地图预览（来自 Google 地点坐标）")
    st.pydeck_chart(
        pdk.Deck(
            map_style="light",
            initial_view_state=pdk.ViewState(latitude=avg_lat, longitude=avg_lon, zoom=zoom, pitch=0),
            layers=layers,
            tooltip={"text": "{name}"},
        ),
        use_container_width=True,
    )


# ── 页面 ──────────────────────────────────────────────────────────────────

st.set_page_config(page_title="智能旅行规划", page_icon="✈️", layout="wide")
st.title("✈️ 智能旅行规划助手")
st.caption(f"后端：`{BACKEND_URL}`")

with st.sidebar:
    st.header("快速规划")
    destination = st.text_input("目的地", placeholder="例：京都、巴黎、云南")
    days = st.number_input("天数", min_value=1, max_value=14, value=3)
    budget = st.selectbox("预算", ["不限", "经济实惠", "中等", "豪华"])
    travel_style = st.multiselect(
        "旅行风格",
        ["文化历史", "自然风光", "美食探索", "购物娱乐", "休闲放松"],
        default=["文化历史"],
    )
    if st.button("生成行程", type="primary", use_container_width=True):
        if not destination:
            st.warning("请填写目的地")
        else:
            style_str = "、".join(travel_style) if travel_style else "综合"
            msg = (
                f"帮我规划 {destination} {days} 天的旅行行程，"
                f"预算{budget}，偏好{style_str}。请先查询当地天气和景点信息。"
            )
            st.session_state.setdefault("messages", [])
            st.session_state.messages.append({"role": "user", "content": msg})
            st.session_state.pending = True
            st.rerun()

    st.divider()
    if st.button("清空对话", use_container_width=True):
        st.session_state.messages = []
        st.session_state.session_id = None  # 重置 session，开启新对话
        st.rerun()

# 对话历史
if "messages" not in st.session_state:
    st.session_state.messages = []

for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg["role"] == "assistant":
            render_places_map(msg["content"])

# 侧边栏触发
if st.session_state.get("pending"):
    st.session_state.pending = False
    with st.chat_message("user"):
        st.markdown(st.session_state.messages[-1]["content"])
    with st.chat_message("assistant"):
        reply = run_chat(st.session_state.messages[-1]["content"])
        render_places_map(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})

# 自由输入
if user_input := st.chat_input("继续对话，例如：把第二天改成海边活动…"):
    st.session_state.messages.append({"role": "user", "content": user_input})
    with st.chat_message("user"):
        st.markdown(user_input)
    with st.chat_message("assistant"):
        reply = run_chat(user_input)
        render_places_map(reply)
    st.session_state.messages.append({"role": "assistant", "content": reply})
