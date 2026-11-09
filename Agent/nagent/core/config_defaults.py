"""NAgent 默认配置模板（首次运行无 config.ini 时自动写入）。"""
DEFAULT_CONFIG_TEMPLATE = """# NAgent 配置文件
# 修改后重新启动生效

[llm]
# OpenAI 兼容端点（fc / prompt 两种模式都适用）
url = http://localhost:3001/api/v1/openai/chat/completions
api_key = your-api-key-here
model = your-model-id
# 工具调用模式：fc（标准 OpenAI function calling，推荐）/ prompt（JSON 协议，兼容 AnytingLLM）
mode = prompt
# 上下文窗口大小（token），无法从 API 自动获取时使用
context_window = 131072

[context]
# 压缩警告阈值（百分比），达到时自动警告
warn_ratio = 0.80
# 压缩时保留最近 N 个工具回合的原始消息
keep_rounds = 2
# 压缩摘要目标 token 数（近似）
target_summary_tokens = 5000

[agent]
# prompt 模式下最大工具调用轮数
max_tool_rounds = 10
# 是否在启动时自动加载 AGENTS.md（项目根目录下）
load_agents_md = true
# 会话保存目录（相对项目根）
sessions_dir = .agents/sessions
# 上下文归档目录（相对项目根）
context_dir = .agents/context

[search]
# 百度千帆 API Key（searchWeb 工具用）
baidu_qianfan_api_key =
"""


def generate_default_config(path: str) -> bool:
    """写入默认 config.ini。返回是否成功。"""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(DEFAULT_CONFIG_TEMPLATE)
        return True
    except OSError:
        return False
