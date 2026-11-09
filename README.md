# LLM 技术与应用 · 课程项目

《大语言模型技术与应用》期末项目：一条从"把 REST 服务变成 MCP"到"让 Agent 真正用起来"的完整链路。
四个子项目各自独立、可单独运行，也可以串起来用——Agent 通过 MCP 客户端把前三个服务的工具挂到自己身上。

## 项目地图

| 目录 | 角色 | 技术栈 | 端口 / 入口 |
| --- | --- | --- | --- |
| `PetHospitalMCP/` | 宠物医院 MCP 服务：把 Go REST API 暴露为 MCP 工具 | Python 3.11+ · `mcp==2.0.0` · Starlette | `127.0.0.1:8765/mcp` |
| `AnythingLLMMCP/` | AnythingLLM MCP 服务：把本地知识库问答封装为 MCP 工具 | Python 3.10+ · `mcp` · httpx | `127.0.0.1:8000/mcp` |
| `AnythingLLMSever/` | AnythingLLM 网页：上传文档并完成向量化嵌入 | 单文件 HTML + 原生 JS | `http://localhost:8080/upload.html` |
| `Agent/` | 多界面 Agent（NAgent）：工具调用、技能包、上下文压缩、MCP 客户端 | Python 3.10+ · requests · Textual | `python main.py`（TUI） |
| `Agent/Practice01`、`Agent/Practice02` | 前两轮练习，标注架构演进过程 | Python | `python main.py` |

### 模块关系

```
            ┌─────────────────────────────────────────────┐
            │  Agent/nagent（NAgent，core + tui）          │
            │  core: Agent 循环 / 18 工具 / Skill / 压缩   │
            └───────┬───────────────────────────┬─────────┘
        MCP 客户端  │ stdio / Streamable HTTP     │ OpenAI 兼容 API
                    ▼                             ▼
   ┌────────────────────────────┐      ┌──────────────────────┐
   │ PetHospitalMCP (8765/mcp)  │      │ AnythingLLM (3001)   │
   └──────────┬─────────────────┘      └──────────┬───────────┘
              ▼ HTTP GET /api/v1/pets              ▲ 文档上传
   ┌────────────────────────────┐      ┌──────────┴───────────┐
   │ Go 宠物医院 REST (8080)     │      │ AnythingLLMMCP(8000) │
   └────────────────────────────┘      └──────────────────────┘
                                              ▲
                                   AnythingLLMSever/upload.html
```

## 环境依赖

- Python 3.10+（`PetHospitalMCP` 要求 3.11+）
- Node 无需；网页为单文件原生 JS
- 上游服务：AnythingLLM 本地实例（`localhost:3001`）、Go 宠物医院 REST API（`127.0.0.1:8080`）

各子项目依赖：

```bash
# PetHospitalMCP
pip install mcp==2.0.0 httpx pydantic uvicorn starlette python-json-logger

# AnythingLLMMCP
pip install -r AnythingLLMMCP/requirements.txt

# NAgent
pip install requests textual trafilatura python-dotenv
```

## 配置方式（密钥一律不入库）

| 模块 | 配置文件 | 需要填的项 |
| --- | --- | --- |
| `PetHospitalMCP` | 环境变量（见 `README.md`） | `PET_HOSPITAL_BASE_URL`、`MCP_PORT`（可选） |
| `AnythingLLMMCP` | `AnythingLLMMCP/.env`（模板 `.env.example`） | `ANYTHINGLLM_BASE_URL`、`ANYTHINGLLM_API_KEY`、`MCP_PORT` |
| `AnythingLLMSever` | 页面内输入框（存 `localStorage`） | API Key、服务地址 |
| `Agent/nagent` | `Agent/nagent/config.ini`（模板 `core/config_defaults.py`） | `[llm] url/api_key/model/mode`、`[search] baidu_qianfan_api_key` |
| `Agent/nagent` MCP | `Agent/nagent/.mcp.json`（模板 `.mcp.json.example`） | 各 server 的 `command`/`args` 或 `url`/`headers` |

> 复制模板后填入自己的密钥：`cp AnythingLLMMCP/.env.example AnythingLLMMCP/.env`。
> `.env`、`config.ini`、`.mcp.json` 均已写入 `.gitignore`，不会被提交。

## 分步启动

### 1. 宠物医院 MCP

```bash
# 前置：Go 后端已在 127.0.0.1:8080 运行
cd PetHospitalMCP
python -m venv .venv
.venv/Scripts/activate          # Windows；Unix 用 source .venv/bin/activate
pip install mcp==2.0.0 httpx pydantic uvicorn starlette python-json-logger
.venv/Scripts/python -m pet_hospital_mcp
# 健康检查：curl http://127.0.0.1:8765/health
```

### 2. AnythingLLM MCP

```bash
cd AnythingLLMMCP
pip install -r requirements.txt
cp .env.example .env            # 填入 API Key
python server.py                # 端点 http://127.0.0.1:8000/mcp
```

### 3. AnythingLLM 网页

```bash
cd AnythingLLMSever
python -m http.server 8080
# 浏览器打开 http://localhost:8080/upload.html，页面内粘贴 API Key
```

### 4. NAgent

```bash
cd Agent/nagent
pip install requests textual trafilatura python-dotenv
python main.py                  # 首次运行会生成 config.ini 模板，填好后重启
```

把两个 MCP 服务挂到 Agent 上：复制 `.mcp.json.example` 为 `.mcp.json`，按示例填入 `url` 或 `command`，重启后输入 `/mcp` 查看连接状态。

## 验证

| 模块 | 验证方式 |
| --- | --- |
| PetHospitalMCP | `python -m pytest -q`（4 个测试文件，覆盖工具契约、REST 客户端、无状态 HTTP、server 装配） |
| AnythingLLMMCP | 页面/客户端调用 `ask_first_workspace`，或在 Trae 中 `tools/list` |
| AnythingLLMSever | 上传一份 Markdown，页面显示"上传并完成向量化嵌入"及文档摘要 |
| NAgent | `/help` 查看命令；`/skills`、`/mcp` 查看技能与 MCP 状态；`/tokens` 查看上下文占用 |

## 目录结构

```
llm/
├── PetHospitalMCP/          # 宠物医院 MCP（src + tests + README）
├── AnythingLLMMCP/          # AnythingLLM MCP（server.py + .env.example）
├── AnythingLLMSever/        # 上传网页（upload.html + README）
└── Agent/
    ├── Practice01/          # 练习一：最小对话脚本
    ├── Practice02/          # 练习二：单文件 Agent + 架构图
    └── nagent/              # NAgent：core / tui / installer
        ├── core/            # agent、tools、skills、mcp_client、context_manager、sessions
        ├── tui/             # Textual 终端界面
        ├── installer/       # Inno Setup 打包脚本
        └── main.py          # 组合根
```

## 已知边界

- `PetHospitalMCP` 目前只实现 `list_pets`（阶段一）；其余端点见 `UPGRADE_PROMPT.md`，尚未实现。
- `AnythingLLMMCP` 只封装了"第一个工作区问答"一类能力，工作区管理与文档上传走网页或 AnythingLLM 原生界面。
- `Agent/nagent` 目前只有终端界面；`core` 与界面通过 `BaseUI` 解耦，新增 Web/桌面端无需改核心代码。
