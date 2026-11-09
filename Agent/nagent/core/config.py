"""配置加载：从 config.ini 读取，所有硬编码值移到配置。"""
import configparser
import os

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.ini"
)


def load_config(path=None):
    """读取配置，返回扁平化的 dict。缺失字段用默认值。"""
    cfg = configparser.ConfigParser()
    cfg.read(path or _DEFAULT_PATH, encoding="utf-8")

    def _get(section, key, default=None):
        return cfg.get(section, key, fallback=default)

    def _getint(section, key, default):
        try:
            return int(_get(section, key, str(default)))
        except (ValueError, TypeError):
            return default

    def _getfloat(section, key, default):
        try:
            return float(_get(section, key, str(default)))
        except (ValueError, TypeError):
            return default

    def _getbool(section, key, default):
        v = _get(section, key, None)
        if v is None:
            return default
        return v.strip().lower() in ("1", "true", "yes", "on")

    return {
        # LLM
        "url": _get("llm", "url", "http://localhost:3001/api/v1/openai/chat/completions"),
        "api_key": _get("llm", "api_key", ""),
        "model": _get("llm", "model", ""),
        "mode": _get("llm", "mode", "prompt").strip().lower(),
        "context_window": _getint("llm", "context_window", 131072),

        # Context / Compression
        "warn_ratio": _getfloat("context", "warn_ratio", 0.80),
        "keep_rounds": _getint("context", "keep_rounds", 2),
        "target_summary_tokens": _getint("context", "target_summary_tokens", 5000),

        # Agent
        "max_tool_rounds": _getint("agent", "max_tool_rounds", 10),
        "load_agents_md": _getbool("agent", "load_agents_md", True),
        "sessions_dir": _get("agent", "sessions_dir", ".agents/sessions"),
        "context_dir": _get("agent", "context_dir", ".agents/context"),

        # Search
        "search": {
            "baidu_qianfan_api_key": _get("search", "baidu_qianfan_api_key", None),
        },
    }


def config_exists(path=None):
    """检查 config.ini 是否存在。"""
    return os.path.isfile(path or _DEFAULT_PATH)
