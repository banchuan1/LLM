"""上下文压缩与历史检索模块。

职责：
  1. 轻量 token 估算（近似，不依赖 tiktoken）
  2. JSONL 归档：压缩前把原始 messages 保存到 .agents/context/<id>.jsonl
  3. recallContext 工具：本地全文关键词检索历史归档
  4. 压缩 Prompt 模板
  5. 压缩后消息替换策略（保留 system prompt + 摘要 + 最近工具回合）

不依赖向量数据库、Embedding 或复杂检索框架。
"""
import json
import os
import re
import glob
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

# ---------- Token 估算 ----------

# 近似换算：中文约 1.5 char/token，英文约 4 char/token
# 混合文本取中间值 2.5 char/token，对工具 JSON 消息用更保守的比例
_CHARS_PER_TOKEN = 2.5


def estimate_tokens(text: str) -> int:
    """估算一段文本的 token 数（近似值）。"""
    if not text:
        return 0
    return max(1, int(len(text) / _CHARS_PER_TOKEN))


def estimate_messages_tokens(messages: list, system_prompt: str = "") -> int:
    """估算整组消息的 token 数（含 system prompt）。"""
    total = estimate_tokens(system_prompt)
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total += estimate_tokens(content)
        elif isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    total += estimate_tokens(item.get("text", ""))
        # tool_calls 也计入
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            total += estimate_tokens(fn.get("arguments", ""))
            total += estimate_tokens(fn.get("name", ""))
    # 每条消息额外加 4 token 的 role/header 开销
    total += len(messages) * 4
    return total


# ---------- 归档 ----------

def _context_dir(project_root: str) -> str:
    d = os.path.join(project_root, ".agents", "context")
    os.makedirs(d, exist_ok=True)
    return d


def generate_archive_id() -> str:
    """生成归档 ID：YYYYMMDD-HHMMSS。"""
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def archive_messages(project_root: str, messages: list) -> str:
    """把 messages 写入 JSONL 归档文件，返回归档 ID。

    每行一个完整消息对象（含 role, content, tool_calls, tool_call_id 等），
    保留原始顺序。
    """
    archive_id = generate_archive_id()
    path = os.path.join(_context_dir(project_root), f"{archive_id}.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for msg in messages:
            # 做一个可序列化的深拷贝
            clean = {}
            for k, v in msg.items():
                if v is not None:
                    clean[k] = v
            f.write(json.dumps(clean, ensure_ascii=False) + "\n")
    return archive_id


def list_archives(project_root: str) -> List[str]:
    """列出所有归档 ID（按时间倒序）。"""
    d = _context_dir(project_root)
    files = glob.glob(os.path.join(d, "*.jsonl"))
    ids = sorted([os.path.splitext(os.path.basename(f))[0] for f in files], reverse=True)
    return ids


def _read_archive(project_root: str, archive_id: str) -> List[dict]:
    path = os.path.join(_context_dir(project_root), f"{archive_id}.jsonl")
    if not os.path.isfile(path):
        return []
    msgs = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    msgs.append(json.loads(line))
                except json.JSONDecodeError:
                    pass
    return msgs


# ---------- recallContext 检索 ----------

def recall_context(project_root: str, text: str, archive_id: Optional[str] = None,
                   max_results: int = 10, max_chars: int = 4000) -> str:
    """在历史归档中全文检索关键词。

    返回格式化的检索结果文本；若无匹配则返回提示。
    """
    if not text or not text.strip():
        return "请提供要检索的关键词（text 参数）。"

    if archive_id:
        archives = [archive_id]
    else:
        archives = list_archives(project_root)

    if not archives:
        return f"未找到任何历史归档（在 {_context_dir(project_root)}）。"

    keyword = text.strip()
    # 简单不区分大小写的包含匹配
    kw_lower = keyword.lower()

    hits = []  # (archive_id, msg_index, role, snippet)

    for aid in archives:
        msgs = _read_archive(project_root, aid)
        for i, msg in enumerate(msgs):
            content = msg.get("content", "")
            if isinstance(content, str) and kw_lower in content.lower():
                snippet = _extract_snippet(content, keyword)
                hits.append((aid, i, msg.get("role", "?"), snippet))
            # 也搜 tool_call 的参数
            for tc in msg.get("tool_calls", []) or []:
                args = tc.get("function", {}).get("arguments", "")
                if isinstance(args, str) and kw_lower in args.lower():
                    snippet = _extract_snippet(args, keyword)
                    hits.append((aid, i, f"tool_call:{tc.get('function',{}).get('name','?')}", snippet))

    if not hits:
        return (
            f"在 {len(archives)} 个历史归档中未找到包含 '{keyword}' 的记录。"
            f"\n归档列表: {', '.join(archives[:10])}"
        )

    # 按 archive_id + msg_index 排序，保留前 max_results 条
    hits.sort(key=lambda x: (x[0], x[1]))
    hits = hits[:max_results]

    # 组装结果
    parts = [f"找到 {len(hits)} 条匹配（关键词: '{keyword}'）：\n"]
    total_chars = 0
    for aid, idx, role, snippet in hits:
        entry = f"[归档 {aid} · 消息 #{idx} · {role}]\n{snippet}\n"
        if total_chars + len(entry) > max_chars:
            parts.append(f"...（还有 {len(hits) - len(parts) + 1} 条未显示）")
            break
        parts.append(entry)
        total_chars += len(entry)

    return "\n".join(parts)


def _extract_snippet(text: str, keyword: str, context: int = 150) -> str:
    """从长文本中提取包含关键词的片段。"""
    kw_lower = keyword.lower()
    pos = text.lower().find(kw_lower)
    if pos == -1:
        return text[:300]

    start = max(0, pos - context)
    end = min(len(text), pos + len(keyword) + context)
    snippet = text[start:end]
    if start > 0:
        snippet = "...(" + str(start) + " chars)... " + snippet
    if end < len(text):
        snippet = snippet + " ...(" + str(len(text) - end) + " chars)..."
    return snippet


# ---------- 压缩 Prompt ----------

COMPACT_SYSTEM_PROMPT = """你是一名 AI Agent 的上下文管理助手。当前会话即将达到上下文窗口限制，需要将历史对话压缩为一份高质量的工作摘要，以便 Agent 在新的上下文中继续执行任务。

请认真阅读提供的历史上下文，提取对后续工作仍然有价值的信息，并生成一份约 5,000 Tokens 的 Markdown 摘要。

摘要应重点保留以下内容：

1. **用户目标与要求**：用户希望完成什么任务？有哪些必须遵守的约束、偏好和验收条件？
2. **已经完成的工作**：哪些任务已经完成？实现了哪些功能？获得了哪些已经验证的结果？
3. **当前工作状态**：Agent 正在处理什么任务？当前进展到哪一步？是否存在尚未解决的问题？
4. **关键技术信息**：保留重要的文件路径、函数名称、接口定义、配置项、执行命令、错误信息和必要的代码片段。
5. **关键决策与原因**：记录用户和 Agent 已经确定的技术方案，以及重要的设计取舍。
6. **下一步任务**：明确接下来应该执行的操作，以及需要继续验证的事项。

请遵守以下要求：

- 优先保留对后续任务有直接影响的信息，删除寒暄、重复讨论、过时的尝试和无关内容。
- 对已经验证的事实与尚未验证的推测作出明确区分。
- 不要将计划完成的任务描述为已经完成。
- 重要的文件路径、函数名称、配置名称和命令应保留准确原文。
- 对失败的尝试，只保留有助于避免重复错误的信息。
- 如果信息存在冲突，应优先保留用户最新确认的要求，并简要说明仍然存在的冲突。
- 如果某些历史细节无法在摘要中完整保留，可简要说明它们已保存到原始上下文归档中，后续可以通过 recallContext 工具重新检索。
- 使用清晰的 Markdown 结构输出摘要，不要附加解释或无关内容。

**最终目标：使一个从未阅读过原始对话的 Agent，仅凭这份摘要，就能够理解当前任务、继承关键决策，并继续开展工作。**"""


def build_compact_user_prompt(messages: list, max_chars: int = 15000) -> str:
    """把历史消息拼成压缩 Prompt 的用户输入部分。

    过长的消息（通常是大段工具输出）会被截断到 max_chars 每条，
    但 tool_call 的 arguments 不截断（参数 JSON 通常短小且重要）。
    """
    parts = ["以下是需要压缩的历史对话（按时间顺序）：\n"]
    for i, msg in enumerate(messages):
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str):
            text = content
        else:
            text = json.dumps(content, ensure_ascii=False, default=str)

        # 长内容截断
        if len(text) > max_chars:
            text = text[:max_chars] + f"\n...[截断，省略 {len(text) - max_chars} 字符]"

        parts.append(f"--- 消息 #{i} (role={role}) ---")
        parts.append(text)

        # tool_calls 也拼进来
        for tc in msg.get("tool_calls", []) or []:
            fn = tc.get("function", {})
            parts.append(f"  [tool_call] {fn.get('name', '?')}({fn.get('arguments', '')[:2000]})")

        parts.append("")

    parts.append("请生成 Markdown 摘要：")
    return "\n".join(parts)


def build_archive_note(archive_id: str) -> str:
    """压缩完成后追加到摘要末尾的归档说明。"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"\n\n---\n\n"
        f"**此前上下文已于 {ts} 完成压缩**，原始上下文保存在编号为 `{archive_id}` 的归档文件中。"
        f"如需查找历史信息，请使用 `recallContext` 工具。"
    )


# ---------- 消息替换策略 ----------

def should_keep_recent_messages(messages: list, keep_rounds: int = 2) -> int:
    """计算尾部应保留的消息数量。

    保留最近 N 个"工具回合"——一个回合是：
      assistant(tool_calls) + tool(result) + ... + assistant(最终回复)
    或者普通的 user + assistant 对。
    """
    if not messages:
        return 0

    count = 0
    # 从尾部往前找最近 keep_rounds 个 user 消息
    user_positions = []
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            user_positions.append(i)
            if len(user_positions) >= keep_rounds:
                break

    if not user_positions:
        return 0

    first_keep_idx = user_positions[-1]  # 最早的那个 user 位置
    # 检查是否在中间切断了 tool_call/tool_result 配对
    # 如果截断点正好在 assistant(tool_calls) 之后、tool(result) 之前，
    # 往前挪到完整 tool_call 消息
    idx = first_keep_idx
    while idx < len(messages):
        m = messages[idx]
        if m.get("role") == "assistant" and m.get("tool_calls"):
            # 检查后面是否有对应的 tool_result
            tool_ids = {tc["id"] for tc in m["tool_calls"]}
            next_tool_ids = set()
            j = idx + 1
            while j < len(messages) and messages[j].get("role") == "tool":
                next_tool_ids.add(messages[j].get("tool_call_id"))
                j += 1
            if not tool_ids.issubset(next_tool_ids):
                idx = j  # 挪到配对完成之后
                continue
        break

    return idx
