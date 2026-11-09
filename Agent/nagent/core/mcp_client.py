"""MCP 客户端：连接外部 MCP Server，发现并注册其工具到 nagent 的工具集合。

工作方式：
  1. 启动时读取 <project_root>/.mcp.json，解析各 MCP Server 配置。
  2. 在后台事件循环线程中异步连接所有 Server（stdio / Streamable HTTP）。
  3. 调用 list_tools() 获取工具 schema，以 "服务器名__工具名" 形式注册，
     避免跨服务器名称冲突。
  4. LLM 调用 MCP 工具时，通过后台事件循环异步转发 call_tool，同步返回结果。
  5. 单个 Server 连接失败不影响其他 Server 和本地工具。

.mcp.json 格式（兼容 Claude/标准 MCP 配置）：
{
  "mcpServers": {
    "my-stdio-server": {
      "command": "python",
      "args": ["-m", "mcp.server.echo"],
      "env": { "VAR": "value" }
    },
    "my-http-server": {
      "url": "http://localhost:3000/mcp",
      "headers": { "Authorization": "Bearer xxx" }
    }
  }
}
"""
import asyncio
import json
import os
import threading
import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------- 后台事件循环线程 ----------

_loop: Optional[asyncio.AbstractEventLoop] = None
_loop_thread: Optional[threading.Thread] = None
_loop_lock = threading.Lock()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    """确保存在一个运行中的后台事件循环；返回 loop 引用。"""
    global _loop, _loop_thread
    with _loop_lock:
        if _loop is not None and _loop.is_running():
            return _loop
        _loop = asyncio.new_event_loop()

        def _run():
            asyncio.set_event_loop(_loop)
            _loop.run_forever()

        _loop_thread = threading.Thread(target=_run, daemon=True, name="mcp-event-loop")
        _loop_thread.start()
        return _loop


def run_coro(coro, timeout: float = 30.0):
    """在后台事件循环中执行协程，同步等待结果。超时抛 TimeoutError。"""
    loop = _ensure_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=timeout)


# ---------- MCP Server 会话管理 ----------

class MCPServerSession:
    """单个 MCP Server 的连接会话（异步，在后台 loop 中使用）。"""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config
        self.session = None
        self._transport = None  # stdio: (read, write, proc); http: context manager
        self._connected = False

    async def connect(self):
        """建立连接并 initialize。异常由上层捕获。"""
        transport_type = _detect_transport(self.config)
        if transport_type == "stdio":
            await self._connect_stdio()
        elif transport_type == "http":
            await self._connect_http()
        else:
            raise ValueError(f"无法识别 Server '{self.name}' 的传输类型（缺少 command 或 url）")

    async def _connect_stdio(self):
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters

        params = StdioServerParameters(
            command=self.config["command"],
            args=self.config.get("args", []),
            env=self.config.get("env"),
        )
        self._ctx = stdio_client(params)
        read, write = await self._ctx.__aenter__()
        self.session = ClientSession(read, write)
        # ClientSession 是 async context manager，进入后才启动消息循环
        await self.session.__aenter__()
        await self.session.initialize()

    async def _connect_http(self):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client

        url = self.config["url"]
        headers = self.config.get("headers") or {}

        http_client = None
        if headers:
            # headers 通过自定义 http_client 注入
            try:
                import httpx
                http_client = httpx.AsyncClient(headers=headers, timeout=30.0)
                self._http_client = http_client
            except ImportError:
                logger.warning("httpx 未安装，无法为 MCP HTTP 连接设置自定义 headers")

        kwargs = {"url": url}
        if http_client is not None:
            kwargs["http_client"] = http_client

        self._ctx = streamable_http_client(**kwargs)
        read, write = await self._ctx.__aenter__()
        self.session = ClientSession(read, write)
        await self.session.__aenter__()
        await self.session.initialize()

    async def list_tools(self):
        result = await self.session.list_tools()
        return result.tools

    async def call_tool(self, tool_name: str, arguments: dict):
        return await self.session.call_tool(tool_name, arguments)

    async def close(self):
        if self.session is not None:
            try:
                await self.session.__aexit__(None, None, None)
            except Exception:
                pass
        ctx = getattr(self, "_ctx", None)
        if ctx is not None:
            try:
                await ctx.__aexit__(None, None, None)
            except Exception:
                pass
        http_client = getattr(self, "_http_client", None)
        if http_client is not None:
            try:
                await http_client.aclose()
            except Exception:
                pass


def _detect_transport(config: dict) -> str:
    """根据 config 字段判断传输类型。"""
    if "command" in config:
        return "stdio"
    if "url" in config:
        return "http"
    return "unknown"


# ---------- 配置加载 ----------

def load_mcp_config(project_root: str) -> Dict[str, dict]:
    """读取 .mcp.json，返回 {server_name: config} 字典。失败返回空 dict。"""
    path = os.path.join(project_root, ".mcp.json")
    if not os.path.isfile(path):
        logger.info("未找到 .mcp.json，跳过 MCP Server 连接")
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("读取 .mcp.json 失败: %s", e)
        return {}

    servers = data.get("mcpServers", {})
    if not isinstance(servers, dict):
        logger.warning(".mcp.json 中 mcpServers 必须是对象")
        return {}
    return servers


# ---------- 全局 MCP 管理器 ----------

class MCPManager:
    """管理所有 MCP Server 的连接、工具注册与调用。"""

    def __init__(self):
        self.sessions: Dict[str, MCPServerSession] = {}
        # exposed_name -> (server_name, original_tool_name)
        self.tool_map: Dict[str, Tuple[str, str]] = {}

    def connect_all(self, project_root: str) -> List[dict]:
        """连接所有配置中的 MCP Server，返回注册的工具 schema 列表。

        单个 Server 失败不影响其他 Server。返回的每个 schema 格式与本地 TOOLS
        中的 function schema 一致（type=function, function={name,description,parameters}）。
        """
        servers = load_mcp_config(project_root)
        if not servers:
            return []

        async def _connect_one(name, cfg):
            sess = MCPServerSession(name, cfg)
            try:
                await sess.connect()
                tools = await sess.list_tools()
                return name, sess, tools, None
            except Exception as e:
                return name, None, None, str(e)

        # 并发连接所有 Server
        tasks = [_connect_one(name, cfg) for name, cfg in servers.items()]

        async def _connect_all():
            return await asyncio.gather(*tasks, return_exceptions=False)

        results = run_coro(_connect_all(), timeout=60.0)

        schemas = []
        for name, sess, tools, err in results:
            if err is not None:
                logger.warning("MCP Server '%s' 连接失败: %s", name, err)
                # 暴露一个错误提示 schema，让 LLM 知道该 server 不可用
                schemas.append(self._error_schema(name, err))
                continue

            self.sessions[name] = sess
            for tool in tools:
                exposed = f"{name}__{tool.name}"
                self.tool_map[exposed] = (name, tool.name)
                schemas.append(self._tool_to_schema(exposed, name, tool))
            logger.info("MCP Server '%s' 已连接，注册 %d 个工具", name, len(tools))

        return schemas

    @staticmethod
    def _tool_to_schema(exposed_name: str, server_name: str, tool) -> dict:
        """把 MCP Tool 转为 OpenAI function schema。"""
        # 兼容 mcp v1 (inputSchema) 和 v2 (input_schema)
        input_schema = getattr(tool, "input_schema", None) or getattr(tool, "inputSchema", None) or {}
        # MCP input_schema 是 JSON Schema（含 type/properties/required），直接复用
        parameters = {
            "type": input_schema.get("type", "object"),
            "properties": input_schema.get("properties", {}),
        }
        if "required" in input_schema:
            parameters["required"] = input_schema["required"]

        desc = getattr(tool, "description", "") or ""
        # 在描述中注明来源和原始工具名，便于 LLM 理解
        prefix = f"[MCP:{server_name}] "
        full_desc = prefix + desc if desc else prefix + f"调用 MCP 工具 {tool.name}"

        return {
            "type": "function",
            "function": {
                "name": exposed_name,
                "description": full_desc,
                "parameters": parameters,
            },
        }

    @staticmethod
    def _error_schema(server_name: str, err: str) -> dict:
        """连接失败时暴露一个占位工具，调用即返回错误信息。"""
        return {
            "type": "function",
            "function": {
                "name": f"{server_name}__unavailable",
                "description": f"[MCP:{server_name}] 该 MCP Server 连接失败：{err}",
                "parameters": {"type": "object", "properties": {}},
            },
        }

    def call_tool(self, exposed_name: str, args: dict) -> str:
        """同步调用一个 MCP 工具，返回文本结果。"""
        # 连接失败的占位工具
        if exposed_name.endswith("__unavailable"):
            return f"MCP Server 不可用：{exposed_name}"

        mapping = self.tool_map.get(exposed_name)
        if mapping is None:
            return f"未知的 MCP 工具: {exposed_name}"

        server_name, original_name = mapping
        sess = self.sessions.get(server_name)
        if sess is None:
            return f"MCP Server '{server_name}' 未连接"

        async def _do_call():
            result = await sess.call_tool(original_name, args or {})
            return _serialize_tool_result(result)

        try:
            return run_coro(_do_call(), timeout=120.0)
        except asyncio.TimeoutError:
            return f"调用 MCP 工具 {exposed_name} 超时"
        except Exception as e:
            logger.exception("调用 MCP 工具 %s 失败", exposed_name)
            return f"调用 MCP 工具 {exposed_name} 出错: {e}"

    def shutdown(self):
        """关闭所有连接（退出时调用）。"""
        if not self.sessions:
            return
        async def _close_all():
            for sess in self.sessions.values():
                await sess.close()
        try:
            run_coro(_close_all(), timeout=10.0)
        except Exception:
            pass


def _serialize_tool_result(result) -> str:
    """把 MCP CallToolResult 序列化为文本。

    MCP 结果可能包含 text、image 等多种 content 类型；这里统一转成可读文本。
    """
    parts = []
    is_error = getattr(result, "isError", False)
    for item in getattr(result, "content", []):
        ctype = getattr(item, "type", "")
        if ctype == "text":
            parts.append(getattr(item, "text", ""))
        elif ctype == "image":
            # 图片用占位描述
            parts.append(f"[image data, mime={getattr(item, 'mimeType', '?')}, size={len(getattr(item, 'data', ''))} bytes]")
        else:
            # 其他类型转 JSON
            try:
                parts.append(json.dumps(getattr(item, "__dict__", item), ensure_ascii=False, default=str))
            except Exception:
                parts.append(str(item))

    text = "\n".join(parts)
    if is_error:
        text = f"[MCP 工具错误] {text}"
    return text


# 全局单例
_mcp_manager: Optional[MCPManager] = None


def get_mcp_manager() -> MCPManager:
    global _mcp_manager
    if _mcp_manager is None:
        _mcp_manager = MCPManager()
    return _mcp_manager


def init_mcp(project_root: str) -> List[dict]:
    """初始化 MCP：读取配置、连接所有 Server、返回工具 schema 列表。"""
    mgr = get_mcp_manager()
    return mgr.connect_all(project_root)


def call_mcp_tool(exposed_name: str, args: dict) -> str:
    """供 tools.py 调用的入口。"""
    return get_mcp_manager().call_tool(exposed_name, args)


def shutdown_mcp():
    if _mcp_manager is not None:
        _mcp_manager.shutdown()
