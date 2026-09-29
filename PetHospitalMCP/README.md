# Pet Hospital MCP Service（宠物医院 MCP 服务）

一个独立的 Python MCP 服务，将 Go 宠物医院 REST API 暴露给 AI Agent。当前为**阶段一**，仅实现一个工具 `list_pets`，对应后端 `GET /api/v1/pets`（过滤 / 排序 / 分页）。

## 关键信息

| 项 | 值 |
| --- | --- |
| Python 版本 | 3.11+ |
| MCP SDK | `mcp==2.0.0`（官方 Python SDK） |
| 服务端类 | `mcp.server.MCPServer`（非 1.x 的 `FastMCP`） |
| 协议版本 | `2026-07-28`（无状态 Streamable HTTP 核心） |
| 传输方式 | 无状态 Streamable HTTP，端点 `/mcp`，JSON 响应（非 SSE） |
| 健康检查 | `GET /health`（自定义路由，MCP 之外） |
| 后端服务 | Go 宠物医院 REST API，默认 `http://127.0.0.1:8080` |
| 监听地址 | 默认 `127.0.0.1:8765` |

## MCP 配置字符串

**端点 URL：**

```
http://127.0.0.1:8765/mcp
```

**通用 JSON 配置（Cursor / Claude Desktop / Cline 等）：**

```json
{
  "mcpServers": {
    "pet-hospital-mcp": {
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

**各客户端落地路径：**

| 客户端 | 路径 |
| --- | --- |
| Cursor | `<项目>/.cursor/mcp.json` 或 `~/.cursor/mcp.json` |
| Claude Desktop | `%APPDATA%\Claude\claude_desktop_config.json` |
| Cline (VSCode) | Settings → Cline → MCP Settings |

## 无状态协议说明（2026-07-28）

本服务遵循 2026-07-28 协议的无状态核心：

- 无 `initialize` 握手。
- 无 `Mcp-Session-Id` 请求/响应头。
- 无会话存储或 SSE 恢复。
- 协议版本与客户端信息放在每个请求的 `_meta` 信封里（键：`io.modelcontextprotocol/protocolVersion`、`io.modelcontextprotocol/clientInfo`、`io.modelcontextprotocol/clientCapabilities`）。
- 方法名放在 `Mcp-Method` 头；工具名放在 `Mcp-Name` 头。

支持 `server/discover`，在 `supportedVersions` 中通告 `2026-07-28`。

## 安装

服务与测试均从源码运行，依赖锁定在 `pyproject.toml`。测试无需 `pip install -e .`（pytest 已配置 `pythonpath = ["src"]`）。

运行服务需要先创建虚拟环境：

```bash
cd D:\llm\PetHospitalMCP
python -m venv .venv
# Windows: .venv\Scripts\activate
# Unix:   source .venv/bin/activate
pip install mcp==2.0.0 httpx pydantic uvicorn starlette python-json-logger
```

## 运行

### 1. 启动 Go 后端（127.0.0.1:8080）

```bash
cd <pet-hospital-go-project>
go run .
# 如需种子数据：go run . -seed -count 2000
```

### 2. 启动 MCP 服务（127.0.0.1:8765）

另开终端：

```bash
cd D:\llm\PetHospitalMCP
.venv\Scripts\python -m pet_hospital_mcp
```

可用环境变量覆盖默认值：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `MCP_HOST` | `127.0.0.1` | MCP 监听地址 |
| `MCP_PORT` | `8765` | MCP 监听端口 |
| `PET_HOSPITAL_BASE_URL` | `http://127.0.0.1:8080` | Go 后端地址 |
| `BACKEND_TIMEOUT_SECONDS` | `10` | httpx 超时秒数 |
| `BACKEND_MAX_RETRIES` | `2` | 5xx/网络错误重试次数 |

## 验证（curl）

```powershell
# 健康检查
curl http://127.0.0.1:8765/health

# server/discover（确认协议版本 2026-07-28）
curl -X POST http://127.0.0.1:8765/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -H "Mcp-Method: server/discover" `
  -H "Mcp-Name: client-1" `
  -d "{\"jsonrpc\":\"2.0\",\"id\":1,\"_meta\":{\"io.modelcontextprotocol/protocolVersion\":\"2026-07-28\",\"io.modelcontextprotocol/clientInfo\":{\"name\":\"curl\",\"version\":\"1.0\"},\"io.modelcontextprotocol/clientCapabilities\":{}}}"

# tools/list（应返回 list_pets）
curl -X POST http://127.0.0.1:8765/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -H "Mcp-Method: tools/list" `
  -H "Mcp-Name: client-1" `
  -d "{\"jsonrpc\":\"2.0\",\"id\":2,\"_meta\":{\"io.modelcontextprotocol/protocolVersion\":\"2026-07-28\",\"io.modelcontextprotocol/clientInfo\":{\"name\":\"curl\",\"version\":\"1.0\"},\"io.modelcontextprotocol/clientCapabilities\":{}}}"
```

## 工具：`list_pets`

适配后端 `GET /api/v1/pets`，支持 14 个查询参数：

| 参数 | 类型 | 约束 |
| --- | --- | --- |
| `page` | int | `ge=1`，默认 1 |
| `pageSize` | int | `ge=1, le=500`，默认 20 |
| `q` | str | 关键词模糊搜索 |
| `species` | Literal | `犬` / `猫` / `鸟` / `兔` / `其他` |
| `status` | Literal | `healthy` / `sick` / `treatment` / `recovered` / `deceased` |
| `breed` | str | 品种 |
| `minAge` / `maxAge` | float | 年龄范围，`minAge <= maxAge` |
| `gender` | Literal | `male` / `female` / `unknown` |
| `ownerName` | str | 主人姓名 |
| `chipNo` | str | 芯片号 |
| `sortBy` | Literal | `id` / `name` / `age` / `createdAt` |
| `order` | Literal | `asc` / `desc` |
| `vaccinated` | bool | 是否已接疫苗 |

Pydantic 严格校验：`extra="forbid"` 拒绝未知字段，`Literal` 枚举校验，NaN/Infinity 被拒。

## 错误处理

统一错误信封：

```json
{ "error": { "code": "...", "message": "...", "details": {} } }
```

错误码：

| 码 | 含义 |
| --- | --- |
| `VALIDATION_ERROR` | 输入校验失败 |
| `BACKEND_TIMEOUT` | 后端超时 |
| `BACKEND_UNAVAILABLE` | 后端不可达 |
| `BACKEND_API_ERROR` | 后端返回非 200 |
| `BACKEND_INVALID_RESPONSE` | 后端响应格式不合法 |
| `INTERNAL_ERROR` | 内部异常 |

> **已知限制**：SDK 在调用 handler 前对参数做 Pydantic 校验，这部分错误按 Pydantic 风格返回，无法替换为统一信封。所有 handler 内部错误（后端异常、响应模型校验失败、内部异常）一律走统一信封。

## 日志

JSON 结构化日志，递归脱敏 `ownerPhone` / `ownerAddr` / `chipNo` 字段（替换为 `***`）。

字段：`timestamp` / `level` / `logger` / `message` / `tool_name` / `params` / `status` / `duration_ms` / `error_code` / `details`。

## 测试

```bash
cd D:\llm\PetHospitalMCP
.venv\Scripts\python -m pytest -q
```

预期结果：`47 passed`（11 + 21 + 7 + 8）。测试不依赖真实 Go 服务，使用 httpx MockTransport 模拟后端。

## 目录结构

```
D:\llm\PetHospitalMCP\
├── pyproject.toml                  # 依赖 + pytest 配置
├── README.md                       # 本文件
├── UPGRADE_PROMPT.md               # 阶段二扩展指南
├── src/
│   └── pet_hospital_mcp/
│       ├── __init__.py             # 导出 app / create_app / mcp
│       ├── __main__.py             # uvicorn 启动入口
│       ├── config.py               # Settings（环境变量）
│       ├── errors.py               # PetHospitalToolError + 6 个错误码
│       ├── logging_config.py       # JSON 日志 + 字段递归脱敏
│       ├── rest_client.py          # httpx 超时 + 重试 + 信封解析
│       ├── server.py               # MCPServer + streamable_http_app + /health
│       └── tools/
│           ├── __init__.py         # REST 客户端单例 + register_all()
│           └── list_pets.py        # 14 参数 Pydantic 模型 + handler
└── tests/
    ├── conftest.py                 # with_client() / mock transport / fixtures
    ├── test_rest_client.py         # 11 个测试
    ├── test_list_pets.py           # 21 个测试
    ├── test_server.py              # 7 个测试
    └── test_stateless_http.py      # 8 个测试
```

## 阶段二声明

**阶段二工具未实现。** 当前服务仅包含 `list_pets` 一个工具。其它候选工具（`get_pet`、`create_pet`、`update_pet`、`delete_pet`、`list_medical_records`、`create_medical_record`、`list_treatments`、`create_treatment`、`search_owner` 等）均未实现，可按 `UPGRADE_PROMPT.md` 的扩展配方逐步添加。
