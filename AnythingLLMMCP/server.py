import os
import httpx
from dotenv import load_dotenv
from mcp.server.mcpserver import MCPServer

load_dotenv()

BASE = os.getenv("ANYTHINGLLM_BASE_URL", "http://localhost:3001/api")
KEY = os.environ["ANYTHINGLLM_API_KEY"]
PORT = int(os.getenv("MCP_PORT", "8000"))
HEADERS = {"Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}

mcp = MCPServer("AnythingLLM")


@mcp.tool()
def ask_first_workspace(message: str) -> str:
    """基于 AnythingLLM 第一个工作区的文档回答问题。"""
    slug = httpx.get(
        f"{BASE}/v1/workspaces", headers=HEADERS, timeout=30
    ).json()["workspaces"][0]["slug"]
    resp = httpx.post(
        f"{BASE}/v1/workspace/{slug}/chat",
        headers=HEADERS,
        json={"message": message, "mode": "chat"},
        timeout=300,
    )
    resp.raise_for_status()
    data = resp.json()
    answer = data.get("textResponse", "")
    sources = [s.get("title", "") for s in data.get("sources", [])]
    return answer + (f"\n\n来源: {', '.join(sources)}" if sources else "")


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=PORT,
        stateless_http=True,
    )
