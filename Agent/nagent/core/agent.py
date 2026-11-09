"""核心业务层：Agent 会话。与界面完全无关，可被 TUI/Web/Desktop 任意消费。

工具调用支持两种模式（config.ini 的 [llm] mode 决定）：
  fc     — 标准 OpenAI function calling：请求带 tools，响应回 tool_calls。
  prompt — 提示词级 JSON 协议：系统提示词声明工具，模型回复 {"tool":..., "args":...}
           即视为调用请求；兼容不支持 tools 参数的端点（如 AnythingLLM）。

Skill 动态加载：
  启动时以 os.getcwd() 为项目根，扫描 .agents/skills/ 目录下各 Skill 子目录的
  SKILL.md（只读 name/description），将摘要注入 System Prompt。LLM 按需调用
  loadSkill 工具读取完整 SKILL.md 或引用的附加文件。

上下文压缩：
  用户手动触发 /compact 命令或 token 达到 80% 阈值时，将历史消息归档到
  .agents/context/<id>.jsonl，并调用 LLM 生成工作摘要替换旧消息。
  recallContext 工具允许 LLM 在压缩后检索原始归档。

AGENTS.md 注入：
  启动时如果项目根目录有 AGENTS.md，读取其内容作为一条 system 消息注入。
  只在首次加载时做一次，后续压缩后直接复用。

斜杠命令：/new /save /resume /compact /quit /help /skills /mcp /tokens /clear
"""
import json
import os
import logging
import requests

logger = logging.getLogger(__name__)

from .config import load_config
from .tools import TOOLS, TOOL_MAP, execute_tool, set_skills_context, register_mcp_tools
from .skills import scan_skills, build_skills_prompt
from .context_manager import (
    estimate_messages_tokens,
    archive_messages,
    COMPACT_SYSTEM_PROMPT,
    build_compact_user_prompt,
    build_archive_note,
    should_keep_recent_messages,
)
from .sessions import save_session, load_session, list_sessions

# 斜杠命令注册表：name -> (handler, description, aliases)
# handler(self) 是生成器，yield 进度文本
_SLASH_COMMANDS = {}


def _slash(name, desc, aliases=None):
    def _wrap(func):
        _SLASH_COMMANDS[name] = (func, desc, aliases or [])
        return func
    return _wrap


# ---------- 构建 System Prompt ----------

def _build_system_prompt(skills, agents_md_content=None):
    docs = "\n".join(
        f'- {t["function"]["name"]}: {t["function"]["description"]}；'
        f'参数 schema: {json.dumps(t["function"].get("parameters", {}), ensure_ascii=False)}'
        for t in TOOLS
    )
    skills_section = build_skills_prompt(skills)

    parts = []
    if agents_md_content:
        parts.append(agents_md_content.strip())
    if skills_section:
        parts.append(skills_section)
    parts.append(
        "你是一个具备本地工具调用能力的助手。可用工具列表：\n"
        + docs
        + "\n\n"
        + "需要调用工具时，你的回复必须且只能是一个 JSON 对象"
        "（禁止输出任何其他文字，禁止用代码块包裹）：\n"
        '{"tool": "工具名", "args": {参数对象}}\n\n'
        "收到以 TOOL_RESULT 开头的消息后：若信息足够，直接用自然语言回答用户；"
        "若还需更多信息，可再次输出工具调用 JSON。\n"
        "无需调用工具时，直接用自然语言回答用户。"
    )
    return "\n\n".join(parts)


def _parse_tool_call(text):
    """从模型回复中解析工具调用 JSON；不是合法调用则返回 None。"""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    name = obj.get("tool")
    if name in TOOL_MAP:
        return name, obj.get("args") or {}
    return None


# ---------- Agent 类 ----------

class Agent:
    """一次 Agent 会话：维护 messages 历史，提供流式对话接口。

    chat_stream() 是同步生成器，逐段产出最终回复文本；
    界面层只需消费该生成器即可，不感知工具调用细节。
    """

    def __init__(self, config_path=None, context_window=None):
        cfg = load_config(config_path)

        self.url = cfg["url"]
        self.api_key = cfg["api_key"]
        self.model = cfg["model"]
        self.mode = cfg["mode"]
        self.context_window = context_window or cfg["context_window"]
        self.max_tool_rounds = cfg["max_tool_rounds"]
        self.warn_ratio = cfg["warn_ratio"]
        self.keep_rounds = cfg["keep_rounds"]
        self.sessions_dir_rel = cfg["sessions_dir"]
        self.load_agents_md = cfg["load_agents_md"]

        # Skill 动态加载
        self.project_root = os.getcwd()
        self.skills = scan_skills(self.project_root)
        set_skills_context(self.project_root, self.skills)

        # MCP 动态注册
        mcp_count = register_mcp_tools(self.project_root)
        if mcp_count:
            logger.info(f"已注册 {mcp_count} 个 MCP 工具")

        # AGENTS.md 注入（一次注入全程复用）
        agents_md = self._load_agents_md_once()

        self._system_prompt = _build_system_prompt(self.skills, agents_md)
        self.messages = []

        # 压缩状态
        self._compact_in_progress = False
        self._last_archive_id = None

        # 当前会话 ID（/new 或 /resume 时更新）
        self.session_id = None

        # UI 回调
        self.on_context_change = None

    # ---------- 内部工具 ----------

    def _load_agents_md_once(self) -> str:
        """读取项目根目录的 AGENTS.md（仅首次加载一次）。"""
        if not self.load_agents_md:
            return ""
        path = os.path.join(self.project_root, "AGENTS.md")
        if os.path.isfile(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            except OSError:
                pass
        return ""

    def _post(self, payload):
        """向 LLM API 发送 POST 请求。"""
        return requests.post(
            self.url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={"model": self.model, **payload},
        )

    # ---------- Token 监控 ----------

    def get_token_usage(self) -> dict:
        used = estimate_messages_tokens(self.messages, self._system_prompt)
        total = self.context_window
        pct = used / total if total > 0 else 0
        return {
            "used": used,
            "total": total,
            "pct": pct,
            "warn_threshold": int(total * self.warn_ratio),
            "warn_ratio": self.warn_ratio,
        }

    def get_mcp_status(self) -> list:
        """返回 MCP 服务器连接状态（供 TUI 边栏显示）。"""
        try:
            from core.mcp_client import get_mcp_manager
            mgr = get_mcp_manager()
            result = []
            for name, sess in mgr.sessions.items():
                tools = []
                for exposed, (srv, orig) in mgr.tool_map.items():
                    if srv == name:
                        tools.append(orig)
                result.append({
                    "name": name,
                    "connected": True,
                    "tool_count": len(tools),
                    "tools": tools,
                })
            return result
        except Exception:
            return []

    # ---------- 斜杠命令 ----------

    def dispatch_slash(self, raw: str):
        """解析并执行斜杠命令。返回生成器。"""
        parts = raw.strip().split(maxsplit=1)
        name = parts[0].lstrip("/").lower()
        rest = parts[1] if len(parts) > 1 else ""

        # 精确匹配 + 别名匹配
        handler = None
        for cmd_name, (fn, desc, aliases) in _SLASH_COMMANDS.items():
            if cmd_name == name or name in aliases:
                handler = fn
                break

        if handler is None:
            yield f"未知斜杠命令: /{name}。输入 /help 查看所有可用命令。"
            return

        # handler 是生成器
        gen = handler(self, rest)
        yield from gen

    @_slash("help", "显示所有斜杠命令", aliases=["h", "?"])
    def _cmd_help(self, args):
        lines = ["可用斜杠命令："]
        for name, (fn, desc, aliases) in sorted(_SLASH_COMMANDS.items()):
            alias_str = f"（别名 {', '.join(aliases)}）" if aliases else ""
            lines.append(f"  /{name}  {desc}{alias_str}")
        yield "\n".join(lines)

    @_slash("new", "新建会话（自动保存当前会话）", aliases=["n"])
    def _cmd_new(self, args):
        if self.messages:
            saved = save_session(
                self.project_root, self.sessions_dir_rel,
                self.session_id, self.messages,
                {"mode": self.mode, "context_window": self.context_window},
            )
            yield f"已自动保存当前会话 → {saved}"
        self.messages = []
        self.session_id = None
        self._last_archive_id = None
        yield "✓ 新会话已开始"
        if self.on_context_change:
            try: self.on_context_change()
            except Exception: pass

    @_slash("save", "保存当前会话", aliases=["s"])
    def _cmd_save(self, args):
        sid = args.strip() or None
        sid = save_session(
            self.project_root, self.sessions_dir_rel,
            sid or self.session_id, self.messages,
            {"mode": self.mode, "context_window": self.context_window},
        )
        self.session_id = sid
        count = len(self.messages)
        yield f"✓ 会话已保存 → {sid}（{count} 条消息）"

    @_slash("list", "列出所有保存的会话", aliases=["ls"])
    def _cmd_list(self, args):
        sessions = list_sessions(self.project_root, self.sessions_dir_rel)
        if not sessions:
            yield "尚未保存任何会话。"
            return
        lines = [f"共 {len(sessions)} 个保存的会话："]
        for i, (sid, meta) in enumerate(sessions):
            lines.append(
                f"  [{i+1}] {sid}  "
                f"({meta['saved_at']}, {meta['message_count']} 条, "
                f"{meta['first_user']})"
            )
        yield "\n".join(lines)

    @_slash("resume", "恢复保存的会话（用 /list 查看编号或 ID）", aliases=["r"])
    def _cmd_resume(self, args):
        sessions = list_sessions(self.project_root, self.sessions_dir_rel)
        if not sessions:
            yield "尚无保存的会话。"
            return

        sid_input = args.strip()
        if not sid_input:
            # 无参数 → 恢复最近一个
            sid_input = "1"

        target = None
        # 尝试按编号
        try:
            idx = int(sid_input) - 1
            if 0 <= idx < len(sessions):
                target = sessions[idx][0]
        except ValueError:
            pass

        # 再尝试按 ID
        if target is None:
            for sid, _ in sessions:
                if sid == sid_input:
                    target = sid
                    break

        if target is None:
            yield f"找不到会话: {sid_input}。用 /list 查看。"
            return

        data = load_session(self.project_root, self.sessions_dir_rel, target)
        if data is None:
            yield f"加载失败: {target}"
            return

        # 自动保存当前会话（如果有的话）
        if self.messages:
            save_session(
                self.project_root, self.sessions_dir_rel,
                self.session_id, self.messages,
                {"mode": self.mode, "context_window": self.context_window},
            )

        self.messages = data.get("messages", [])
        self.session_id = target
        yield f"✓ 已恢复会话 {target}（{len(self.messages)} 条消息）"
        if self.on_context_change:
            try: self.on_context_change()
            except Exception: pass

    @_slash("clear", "清空当前会话（不保存，慎用）", aliases=["c"])
    def _cmd_clear(self, args):
        self.messages = []
        self.session_id = None
        self._last_archive_id = None
        yield "✓ 会话已清空（未保存）"
        if self.on_context_change:
            try: self.on_context_change()
            except Exception: pass

    @_slash("compact", "手动触发上下文压缩", aliases=["compress"])
    def _cmd_compact(self, args):
        yield from self.do_compact()

    @_slash("tokens", "显示当前上下文 token 使用情况", aliases=["t", "context"])
    def _cmd_tokens(self, args):
        info = self.get_token_usage()
        used_k = max(1, info["used"] // 1024)
        total_k = max(1, info["total"] // 1024)
        pct = info["pct"] * 100
        yield (
            f"上下文: {used_k}k / {total_k}k ({pct:.1f}%)\n"
            f"  阈值: {info['warn_ratio']*100:.0f}%\n"
            f"  消息数: {len(self.messages)}\n"
            f"  上次压缩归档: {self._last_archive_id or '无'}"
        )

    @_slash("skills", "列出当前可用 Skill", aliases=["skill"])
    def _cmd_skills(self, args):
        if not self.skills:
            yield "未发现任何 Skill。"
            return
        lines = [f"共 {len(self.skills)} 个 Skill："]
        for s in self.skills:
            lines.append(f"  - '{s['name']}': {s['description']}")
        yield "\n".join(lines)

    @_slash("mcp", "显示 MCP 服务器连接状态", aliases=["mcp_status"])
    def _cmd_mcp(self, args):
        servers = self.get_mcp_status()
        if not servers:
            yield "未连接任何 MCP 服务器（.mcp.json 不存在或全部连接失败）。"
            return
        lines = [f"共 {len(servers)} 个 MCP 服务器："]
        for s in servers:
            status = "已连接" if s["connected"] else "未连接"
            lines.append(f"  [{status}] {s['name']}  ({s['tool_count']} 个工具)")
            for t in s["tools"]:
                lines.append(f"    - {t}")
        yield "\n".join(lines)

    @_slash("quit", "退出程序（可带 'save' 参数先保存）", aliases=["exit", "q"])
    def _cmd_quit(self, args):
        if args.strip().lower() == "save" and self.messages:
            sid = save_session(
                self.project_root, self.sessions_dir_rel,
                self.session_id, self.messages,
                {"mode": self.mode, "context_window": self.context_window},
            )
            yield f"已保存 → {sid}，再见！"
        else:
            yield "再见！"
        # 设置标志让 main 退出
        import sys
        sys.exit(0)

    # ---------- 压缩主流程 ----------

    def do_compact(self):
        """执行完整上下文压缩流程。"""
        if self._compact_in_progress:
            yield "压缩正在进行中，请稍候..."
            return

        self._compact_in_progress = True
        original_messages = list(self.messages)

        try:
            yield f"[1/3] 归档原始上下文..."
            archive_id = archive_messages(self.project_root, original_messages)
            self._last_archive_id = archive_id
            yield f"     ✓ 已保存到 .agents/context/{archive_id}.jsonl（{len(original_messages)} 条消息）"

            yield f"[2/3] 调用 LLM 生成压缩摘要..."
            summary = yield from self._llm_compress(original_messages)
            if not summary:
                yield "     ✗ LLM 返回空摘要，压缩失败，保留原始上下文"
                return
            yield f"     ✓ 摘要生成完成"

            yield f"[3/3] 替换会话历史..."
            archive_note = build_archive_note(archive_id)
            self._replace_messages_with_summary(summary + archive_note)
            new_usage = self.get_token_usage()
            yield f"     ✓ 压缩完成。当前上下文 {new_usage['used']} / {new_usage['total']} tokens（{new_usage['pct']*100:.1f}%）"

            if self.on_context_change:
                try: self.on_context_change()
                except Exception: pass

        except Exception as e:
            logger.exception("压缩过程出错")
            yield f"     ✗ 压缩失败：{e}，保留原始上下文"
        finally:
            self._compact_in_progress = False

    def _llm_compress(self, original_messages) -> str:
        payload_messages = [
            {"role": "system", "content": COMPACT_SYSTEM_PROMPT},
            {"role": "user", "content": build_compact_user_prompt(original_messages)},
        ]
        try:
            resp = self._post({"messages": payload_messages})
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"].get("content", "")
            if isinstance(content, str):
                return content
            return json.dumps(content, ensure_ascii=False)
        except Exception as e:
            logger.error("LLM 压缩请求失败: %s", e)
            return ""

    def _replace_messages_with_summary(self, summary_text: str):
        if not self.messages:
            self.messages = [{"role": "assistant", "content": summary_text}]
            return
        cut_idx = should_keep_recent_messages(self.messages, keep_rounds=self.keep_rounds)
        if cut_idx == 0:
            self.messages = [{"role": "assistant", "content": summary_text}] + self.messages
        else:
            self.messages = (
                [{"role": "assistant", "content": summary_text}]
                + self.messages[cut_idx:]
            )

    # ---------- fc 模式 ----------

    def _stream_reply(self):
        resp = self._post({"messages": self.messages, "stream": True})
        resp.encoding = "utf-8"
        reply = ""
        for line in resp.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            delta = json.loads(data)["choices"][0]["delta"].get("content", "")
            if delta:
                reply += delta
                yield delta
        self.messages.append({"role": "assistant", "content": reply})
        self._check_and_warn()
        if self.on_context_change:
            try: self.on_context_change()
            except Exception: pass

    def _chat_fc(self, prompt):
        self.messages.append({"role": "user", "content": prompt})
        msg = self._post(
            {"messages": self.messages, "tools": TOOLS}
        ).json()["choices"][0]["message"]

        if not msg.get("tool_calls"):
            content = msg.get("content", "")
            self.messages.append({"role": "assistant", "content": content})
            yield content
            self._check_and_warn()
            if self.on_context_change:
                try: self.on_context_change()
                except Exception: pass
            return

        self.messages.append({
            "role": "assistant", "content": msg.get("content"),
            "tool_calls": msg["tool_calls"],
        })
        for tc in msg["tool_calls"]:
            args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
            result = execute_tool(tc["function"]["name"], args)
            self.messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
        yield from self._stream_reply()

    # ---------- prompt 模式 ----------

    def _chat_prompt(self, prompt):
        self.messages.append({"role": "user", "content": prompt})
        if not any(m.get("role") == "system" for m in self.messages):
            self.messages.insert(0, {"role": "system", "content": self._system_prompt})

        for _ in range(self.max_tool_rounds):
            msg = self._post({"messages": self.messages}).json()["choices"][0]["message"]
            content = msg.get("content", "") or ""
            call = _parse_tool_call(content)
            if call is None:
                self.messages.append({"role": "assistant", "content": content})
                yield content
                self._check_and_warn()
                if self.on_context_change:
                    try: self.on_context_change()
                    except Exception: pass
                return
            name, args = call
            result = execute_tool(name, args)
            self.messages.append({"role": "assistant", "content": content})
            self.messages.append({
                "role": "user",
                "content": (
                    f"TOOL_RESULT（{name}）：{result}\n"
                    "请基于该结果继续；若需更多信息可再次输出工具调用 JSON，否则直接回答。"
                ),
            })
        yield "（工具调用轮次达到上限，已停止）"

    def _check_and_warn(self):
        info = self.get_token_usage()
        return info

    # ---------- 对外接口 ----------

    def chat_stream(self, prompt):
        """处理一轮输入：自动分发斜杠命令或正常对话。"""
        if prompt.startswith("/"):
            yield from self.dispatch_slash(prompt)
            return

        if self.mode == "prompt":
            yield from self._chat_prompt(prompt)
        else:
            yield from self._chat_fc(prompt)


def get_slash_command_list() -> list:
    """返回所有斜杠命令列表（供 UI 补全面板用）。"""
    return [
        {"name": n, "desc": d, "aliases": a}
        for n, (_, d, a) in sorted(_SLASH_COMMANDS.items())
    ]
