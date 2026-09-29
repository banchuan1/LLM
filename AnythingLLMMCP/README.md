# AnythingLLM MCP Server

基于 [AnythingLLM](http://localhost:3001) 本地实例的 MCP（Model Context Protocol）服务器，使用 **MCP 2026-07-28** 协议、**Streamable HTTP** 传输。

## 功能

提供 1 个工具：

- **`ask_first_workspace(message)`** — 对 AnythingLLM 的第一个工作区提问，基于该工作区已嵌入的文档进行 RAG 检索并由 LLM 生成回答，返回回答文本及引用来源。

## 前置条件

- Python 3.10+
- 本机已安装并运行 AnythingLLM（默认 `http://localhost:3001`）
- AnythingLLM 中至少存在一个工作区，且已上传/嵌入文档

安装依赖：

```powershell
pip install -r requirements.txt
```

## 配置

编辑 [.env](./.env)：

```env
ANYTHINGLLM_BASE_URL=http://localhost:3001/api
ANYTHINGLLM_API_KEY=你的-AnythingLLM-API-Key
MCP_PORT=8000
```

## 启动 / 停止 MCP 服务器

### 启动

在项目目录下运行：

```powershell
python server.py
```

看到 `Uvicorn running on http://127.0.0.1:8000` 即启动成功。MCP 端点为 `http://127.0.0.1:8000/mcp`。

> 该进程为前台常驻进程，关闭终端或按 `Ctrl+C` 即停止。

### 停止

- 前台运行时：在终端按 `Ctrl+C`。
- 后台运行时：找到进程并结束：

```powershell
# 查找占用 8000 端口的进程
Get-NetTCPConnection -LocalPort 8000 -State Listen | Select-Object OwningProcess
# 结束进程（替换 <PID>）
Stop-Process -Id <PID>
```

## 在 Trae 中配置项目级 MCP

Trae 的项目级 MCP 配置文件 `.trae/mcp.json` 受 IDE 保护，需通过 UI 写入：

1. 打开 **设置 → MCP**。
2. 打开 **「启用项目级 MCP」** 开关并确认。
3. 点击 **添加 → 手动添加**。
4. 粘贴以下 JSON 并确认：

```json
{
  "mcpServers": {
    "anythingllm": {
      "url": "http://127.0.0.1:8000/mcp",
      "headers": {
        "RUN_MCP_TIMEOUT_MS": "300000"
      }
    }
  }
}
```

> `RUN_MCP_TIMEOUT_MS=300000`（5 分钟）：因 AnythingLLM 本地 LLM 单次回答约 45s，需放宽工具调用超时。
> 配置写入后会在项目根目录生成 `.trae/mcp.json`。需先按上文启动 `server.py`，Trae 才能连接。

## 验证

启动服务器后，可在 Trae 对话中直接调用工具，例如：“请用一句话总结第一个工作区的文档内容”。

也可手动测试 MCP 端点（2026-07-28 无状态请求）：

```powershell
curl.exe -X POST http://127.0.0.1:8000/mcp `
  -H "Content-Type: application/json" `
  -H "Accept: application/json, text/event-stream" `
  -H "MCP-Protocol-Version: 2026-07-28" `
  -H "Mcp-Method: tools/list" `
  --data-binary "@tools_list.json"
```

其中 `tools_list.json` 内容：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list",
  "params": {
    "_meta": {
      "io.modelcontextprotocol/protocolVersion": "2026-07-28",
      "io.modelcontextprotocol/clientCapabilities": {},
      "io.modelcontextprotocol/clientInfo": { "name": "test", "version": "0.1" }
    }
  }
}
```

## 说明

- **协议版本**：MCP 2026-07-28，Streamable HTTP，`stateless_http=True`（无握手、无会话，每个请求自带协议版本与能力信息）。
- **检索模式**：默认 `mode=chat`（文档检索 + LLM 回答）。如需“仅从向量库提取、不依赖 LLM 通用知识”，将 [server.py](./server.py) 中 `"mode": "chat"` 改为 `"query"`。
- **超时**：AnythingLLM 调用 timeout 设为 300s，以应对本地模型的长生成时间。
