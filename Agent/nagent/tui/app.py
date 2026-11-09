"""Textual TUI 前端实现：在线程 worker 中消费核心层流式接口，线程安全刷新界面。

布局：
  ┌─────────────────────────────────────────┐
  │  状态栏（token 使用量）                  │  dock=top
  ├─────────┬───────────────────────────────┤
  │ 边栏    │        聊天区                  │  主布局
  │ MCP/Sk  │                               │
  ├─────────┴───────────────────────────────┤
  │  输入框                                  │  dock=bottom
  └─────────────────────────────────────────┘

MCP 异步加载：Agent 初始化时 MCP 在后台事件循环线程中连接。
TUI 通过 `on_mount` 启动一个后台 worker 轮询 agent.get_mcp_status()，
拿到非空结果后 call_from_thread 刷新边栏。
"""
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll, Horizontal, Vertical
from textual.widgets import Input, Static, Label, ListView, ListItem, RichLog
from textual.reactive import reactive

from core.base_ui import BaseUI
from core.agent import get_slash_command_list


class NAgentTUI(App):
    """终端聊天界面。"""

    CSS = """
    #main-layout { height: 1fr; }
    #sidebar {
        width: 28;
        dock: left;
        background: $panel;
        border-right: solid $surface-darken-3;
        padding: 0 1;
    }
    #sidebar-title {
        text-align: center;
        padding: 0;
        height: 1;
        color: $text-muted;
        text-style: bold;
    }
    #sidebar-section-title {
        color: $text-muted;
        text-style: italic;
        margin-top: 1;
    }
    #sidebar-content {
        height: auto;
        overflow-y: auto;
    }
    #chat { height: 1fr; padding: 0 1; }
    #input { dock: bottom; }
    #status-bar {
        dock: top;
        height: 1;
        padding: 0 1;
        background: $surface;
        color: $text-muted;
    }
    #status-bar.warn {
        background: $error-darken-3;
        color: $text;
    }
    #status-bar.compacted {
        background: $success-darken-3;
        color: $text-muted;
    }
    #slash-completions {
        display: none;
        dock: bottom;
        max-height: 12;
        background: $panel;
        border-top: solid $surface-darken-3;
        padding: 0 1;
        color: $text-muted;
    }
    Static { margin-bottom: 0; }
    """

    BINDINGS = [
        ("ctrl+c", "quit", "退出"),
        ("ctrl+q", "quit", "退出"),
        ("escape", "hide_completions", "隐藏补全/取消面板"),
    ]

    def __init__(self, agent):
        App.__init__(self)
        BaseUI.__init__(self, agent)
        agent.on_context_change = self._refresh_status_bar_from_thread
        self._mcp_loaded = False

    def compose(self) -> ComposeResult:
        with Horizontal(id="status-bar"):
            yield Static("上下文: -- / -- tokens", id="status-text")

        with Horizontal(id="main-layout"):
            with Vertical(id="sidebar"):
                yield Static("📡 MCP 服务器", id="sidebar-title")
                yield Static("加载中...", id="sidebar-mcp-content")
            yield VerticalScroll(id="chat")

        yield Static("", id="slash-completions")
        yield Input(placeholder="输入问题，或输入 /help 查看命令", id="input")

    def on_mount(self) -> None:
        chat = self.query_one("#chat", VerticalScroll)
        welcome = (
            "欢迎使用 NAgent（Textual TUI）。Ctrl+C / Ctrl+Q 退出。\n"
            "输入 /help 查看斜杠命令。"
        )
        chat.mount(Static(welcome))
        self.query_one("#input", Input).focus()
        self._refresh_status_bar()

        # 异步刷新 MCP 边栏 —— 开一个 worker 轮询，直到拿到非空结果
        self.run_worker(self._async_refresh_mcp, thread=True, exclusive=False, name="mcp-load")

    # ---- MCP 边栏异步刷新 ----

    def _async_refresh_mcp(self):
        """在后台 worker 线程中等待 MCP 连接，然后刷新边栏。"""
        import time
        for _ in range(30):  # 最多等 30 × 0.5s = 15s
            servers = self.agent.get_mcp_status()
            if servers:
                self._mcp_loaded = True
                self.call_from_thread(self._refresh_mcp_sidebar, servers)
                return
            time.sleep(0.5)
        # 超时也刷新（显示"无连接"状态）
        self.call_from_thread(self._refresh_mcp_sidebar, [])

    def _refresh_mcp_sidebar(self, servers):
        """在 UI 线程里刷新 MCP 边栏。"""
        content_widget = self.query_one("#sidebar-mcp-content", Static)

        if not servers:
            content_widget.update("未连接 MCP 服务器\n（创建 .mcp.json 并重启）")
            return

        lines = []
        for s in servers:
            status = "🟢" if s["connected"] else "🔴"
            lines.append(f"{status} {s['name']}")
            for t in s["tools"][:8]:  # 最多显示 8 个工具
                lines.append(f"  • {t}")
            if len(s["tools"]) > 8:
                lines.append(f"  ... +{len(s['tools'])-8} more")
        content_widget.update("\n".join(lines))

    # ---- 状态栏刷新 ----

    def _refresh_status_bar(self):
        status_bar = self.query_one("#status-bar", Horizontal)
        text_widget = self.query_one("#status-text", Static)
        info = self.agent.get_token_usage()

        used_k = max(1, info["used"] // 1024)
        total_k = max(1, info["total"] // 1024)
        pct = info["pct"] * 100

        if pct >= info["warn_ratio"] * 100:
            cls = "warn"
            warn_text = " ⚠ 快满了，/compact 压缩"
        else:
            cls = ""
            warn_text = ""

        compact_tag = ""
        if self.agent._last_archive_id:
            compact_tag = f"  [已压缩: {self.agent._last_archive_id}]"

        label = f"上下文: {used_k}k / {total_k}k ({pct:.0f}%){warn_text}{compact_tag}"
        text_widget.update(label)

        status_bar.set_class(bool(cls), "warn")
        if self.agent._last_archive_id and pct < 80:
            status_bar.add_class("compacted")

    def _refresh_status_bar_from_thread(self):
        try:
            self.call_from_thread(self._refresh_status_bar)
        except Exception:
            pass

    # ---- 补全面板 ----

    def _show_completions(self, matches: list):
        """更新并显示补全面板（持久 widget，只切换 display）。"""
        if not matches:
            self._hide_completions()
            return
        box = self.query_one("#slash-completions", Static)
        items = [f"  ⌨  /{m['name']:<12} {m['desc']}" for m in matches]
        box.update("斜杠命令（ESC 隐藏）:\n" + "\n".join(items))
        box.display = True

    def _hide_completions(self):
        self.query_one("#slash-completions", Static).display = False

    def action_hide_completions(self):
        self._hide_completions()

    # ---- 输入事件 ----

    def on_input_changed(self, event: Input.Changed) -> None:
        """输入变化时更新补全面板。"""
        value = event.value.strip()
        if not value.startswith("/"):
            self._hide_completions()
            return

        all_cmds = get_slash_command_list()
        prefix = value.lstrip("/").lower()

        if not prefix:
            matches = all_cmds[:10]
        else:
            matches = [
                c for c in all_cmds
                if c["name"].startswith(prefix)
                or any(a.startswith(prefix) for a in c["aliases"])
                or prefix in c["desc"].lower()
            ]
            matches = matches[:10]

        self._show_completions(matches)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        prompt = event.value.strip()
        if not prompt:
            return
        event.input.value = ""
        self._hide_completions()
        event.input.disabled = True
        self.run_worker(lambda: self._chat(prompt), thread=True, exclusive=True, name="chat")

    # ---- UI 线程工具方法 ----

    def _mount_line(self, text):
        chat = self.query_one("#chat", VerticalScroll)
        line = Static(text)
        chat.mount(line)
        chat.scroll_end(animate=False)
        return line

    def _update_line(self, line, text):
        line.update(text)
        self.query_one("#chat", VerticalScroll).scroll_end(animate=False)

    def _enable_input(self):
        inp = self.query_one("#input", Input)
        inp.disabled = False
        inp.focus()
        self._refresh_status_bar()

    # ---- worker 线程内执行 ----

    def _chat(self, prompt):
        """消费 agent.chat_stream，逐段刷新回复行。"""
        box = None
        try:
            self.call_from_thread(self._mount_line, f"你: {prompt}")

            is_slash = prompt.startswith("/")
            if is_slash:
                box = self.call_from_thread(self._mount_line, "[执行中]")
                acc = ""
                for chunk in self.agent.chat_stream(prompt):
                    acc += chunk
                    self.call_from_thread(self._update_line, box, acc)
                return

            box = self.call_from_thread(self._mount_line, "助手: ")
            acc = ""
            for chunk in self.agent.chat_stream(prompt):
                acc += chunk
                self.call_from_thread(self._update_line, box, f"助手: {acc}")
        except Exception as e:
            err = f"助手: [出错] {e}"
            if box is not None:
                self.call_from_thread(self._update_line, box, err)
            else:
                self.call_from_thread(self._mount_line, err)
        finally:
            self.call_from_thread(self._enable_input)


BaseUI.register(NAgentTUI)
