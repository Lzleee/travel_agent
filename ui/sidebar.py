import streamlit as st


def render_sidebar() -> None:
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
            st.session_state.session_id = None
            st.rerun()
