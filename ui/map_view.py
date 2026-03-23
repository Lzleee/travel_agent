import re

import pydeck as pdk
import streamlit as st


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

        places.append({"name": current_name or "地点", "lat": lat, "lon": lon})
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
