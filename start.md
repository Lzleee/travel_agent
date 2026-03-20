我想做一个智能旅行规划的agent应用，请给我一个概括的工程路线图，我希望主要用python写，用OpenAI兼容的API接口。最好用现有的AI框架。

---

## 智能旅行规划 Agent 工程路线图

### 技术选型

| 层级 | 推荐方案 | 备注 |
|------|----------|------|
| Agent 框架 | **LangGraph** 或 **AutoGen** | LangGraph 适合有状态、多步骤流程；AutoGen 适合多 Agent 协作 |
| LLM 接入 | `openai` Python SDK（兼容模式） | 设置 `base_url` 可接入任意 OpenAI 兼容接口 |
| 工具调用 | LangChain Tools / Function Calling | 统一封装外部 API |
| 后端服务 | FastAPI | 提供 REST 接口 |
| 前端（可选） | Streamlit / Gradio | 快速搭建对话界面 |
| 数据存储 | SQLite（开发）/ PostgreSQL（生产） | 存储用户偏好、历史行程 |

---

### 核心功能模块

```
智能旅行规划 Agent
├── 意图理解        # 解析用户需求（目的地、时间、预算、偏好）
├── 行程规划        # 生成多日行程方案
├── 工具集
│   ├── 景点搜索    # 调用地图/POI API（如高德、Google Places）
│   ├── 酒店查询    # 接入 OTA API 或爬虫
│   ├── 天气查询    # OpenWeatherMap 等
│   ├── 交通查询    # 航班/火车票 API
│   └── 汇率换算    # 境外出行辅助
├── 记忆系统        # 用户偏好持久化（ConversationBufferMemory）
└── 输出格式化      # 结构化行程单（Markdown / PDF 导出）
```

---

### 开发阶段划分

#### Phase 1：基础骨架（1-2 周）
- 搭建项目结构，配置 OpenAI 兼容客户端
- 实现单轮对话的行程规划（直接 LLM 调用）
- FastAPI 提供 `/chat` 接口，Streamlit 做简单界面

```python
# 示例：配置 OpenAI 兼容客户端
from openai import OpenAI

client = OpenAI(
    api_key="your-api-key",
    base_url="https://your-compatible-endpoint/v1"
)
```

#### Phase 2：工具集成（2-3 周）
- 用 LangGraph 构建有状态的 Agent 图
- 接入 2-3 个核心工具（景点搜索、天气、地图）
- 实现 Function Calling / Tool Use 流程
- 添加对话历史管理

#### Phase 3：多轮优化（2 周）
- 增加用户偏好记忆（数据库持久化）
- 支持行程修改和迭代（"把第二天改成海边活动"）
- 错误处理与 fallback 策略

#### Phase 4：产品化（2-3 周）
- 行程导出（Markdown / PDF）
- 用户账户系统（可选）
- 性能优化、日志监控
- 部署（Docker + 云服务）

---

### 推荐项目结构

```
travel_agent/
├── main.py                  # FastAPI 入口
├── agent/
│   ├── graph.py             # LangGraph 流程定义
│   ├── nodes.py             # 各节点逻辑（规划、工具调用等）
│   └── prompts.py           # Prompt 模板
├── tools/
│   ├── attraction.py        # 景点搜索工具
│   ├── weather.py           # 天气工具
│   └── transport.py         # 交通工具
├── memory/
│   └── store.py             # 用户偏好持久化
├── ui/
│   └── app.py               # Streamlit 界面
├── requirements.txt
└── .env                     # API Key 配置
```

---

### 关键依赖

```txt
openai>=1.0
langgraph>=0.2
langchain>=0.3
langchain-openai>=0.2
fastapi
uvicorn
streamlit
sqlalchemy
python-dotenv
```

---

### 建议起步方式

1. 先用 **LangGraph + OpenAI Function Calling** 跑通一个最小 Demo：用户输入"北京3日游"，Agent 调用工具返回结构化行程。
2. 逐步增加工具数量，再考虑记忆和多轮。
3. 前期不必追求完整 UI，用 Streamlit 快速验证核心逻辑。
