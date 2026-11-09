"""NAgent 组合根：装配核心层与界面层，按命令行参数选择界面。

首次运行：如果 config.ini 不存在，自动写入默认模板并提示用户修改后重启。
"""
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")

from core.config import config_exists
from core.config_defaults import generate_default_config, DEFAULT_CONFIG_TEMPLATE

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.ini")


def _handle_first_run():
    """首次运行检测。如果 config.ini 不存在则自动创建并暂停。"""
    if config_exists(_CONFIG_PATH):
        return True
    print("=" * 60)
    print("⚠  首次运行 NAgent")
    print("=" * 60)
    print(f"\n未找到 config.ini，正在创建默认模板：\n  {_CONFIG_PATH}\n")
    generate_default_config(_CONFIG_PATH)
    print("模板已写入，请编辑以下内容后重新启动：")
    print("  1. [llm] url         — LLM API 端点")
    print("  2. [llm] api_key     — API Key")
    print("  3. [llm] model       — 模型 ID")
    print("  4. [llm] mode        — fc（推荐）或 prompt")
    print(f"\n编辑完成后重新运行: python {sys.argv[0]}")
    print("=" * 60)
    return False


def main():
    if not _handle_first_run():
        return

    from core.agent import Agent
    from tui.app import NAgentTUI

    UIS = {"tui": NAgentTUI}
    name = sys.argv[1] if len(sys.argv) > 1 else "tui"
    if name not in UIS:
        print(f"未知界面: {name}，可选: {', '.join(UIS)}")
        return
    UIS[name](Agent()).run()


if __name__ == "__main__":
    main()
