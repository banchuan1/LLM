# NAgent — 分层架构的多界面 Agent

基于 Practice02 改造的工程化版本：**core（核心业务层）与前端界面目录彻底分离**，通过依赖注入和统一的流式接口解耦。当前提供 `tui/`（Textual 终端界面），未来可平级新增 `web/`、`desktop/`、`mobile/` 等前端目录。

## 分层架构

```
nagent/
├── core/                  # 核心业务层（零界面实现依赖，只用 requests + 标准库）
│   ├── base_ui.py         # 界面契约 BaseUI（core 定义端口，各前端目录实现）
│   ├── config.py          # 配置加载：config.ini → {url, api_key, model, mode, search}
│   ├── config_defaults.py # 首次运行写入的 config.ini 模板
│   ├── tools.py           # 工具集：TOOLS schema 声明 + 18 个工具实现 + execute_tool 统一入口
│   ├── agent.py           # Agent 类：messages 历史 + 工具调用循环 + chat_stream 流式生成器
│   ├── skills.py          # Skill 扫描 / 按需加载 / 创建（.agents/skills/）
│   ├── mcp_client.py      # MCP 客户端：stdio + Streamable HTTP，失败降级
│   ├── context_manager.py # token 估算、JSONL 归档、recallContext 检索
│   └── sessions.py        # 会话保存 / 加载 / 列表
├── tui/                   # 终端前端（Textual）
│   └── app.py             # NAgentTUI：线程 worker 消费流式接口
├── main.py                # 组合根：装配 Agent + 前端，按命令行参数选择界面
├── config.ini             # LLM 配置（含密钥，已被 .gitignore 排除）
└── .gitignore

# 未来平级新增前端目录（各自独立，互不依赖）:
# web/ desktop/ mobile/ ...
```

### 依赖关系（端口-适配器模式，自上而下单向）

```
main.py (组合根) ──装配──> tui/app.py ──实现──> core/base_ui.py (端口契约)
       │                        只依赖注入的 agent 与 chat_stream 契约
       └──────────────────> core/agent.py ──> core/tools.py ──> core/config.py
```

- **core 层**：不感知任何界面实现。`Agent.chat_stream(prompt)` 是同步生成器，逐段 yield 最终回复文本，工具调用循环（探测调用 → 执行工具 → 回传结果 → 最终回复）全部封装在内；`base_ui.py` 定义所有前端必须实现的 BaseUI 契约。
- **前端目录**（tui/web/desktop/mobile）：各自独立平级，只依赖 core 的契约，互不引用。每个目录一个 `app.py` 实现界面类。
- **main.py**：唯一同时认识 core 和各前端的地方（组合根），通过 `UIS` 注册表按参数装配。

## 运行

```bash
pip install requests textual trafilatura   # 首次运行前安装依赖
python main.py                 # 启动 TUI
python main.py tui             # 同上
```

界面内输入问题即可对话，`Ctrl+C` / `Ctrl+Q` 退出。AnythingLLM 需在 `localhost:3001` 运行。

## 内置工具（18 个）

| 工具 | 功能 | 实现方式 |
| --- | --- | --- |
| `getDate` | 当前日期时间 | 本地 `date` / `time` 命令 |
| `isLeapYear` | 判断闰年 | Python 计算 |
| `getCwd` | 当前工作目录 | `os.getcwd()` |
| `listDir` | 列出目录内容 | `os.listdir()` |
| `getFileType` | 文件类型 | `mimetypes` + 扩展名 |
| `readFile` | 读纯文本文件 | 二进制读取后 utf-8 解码，非文本报错 |
| `createFile` | 创建文件 | `open(..., "w")` |
| `editFile` | 覆盖写文件 | `open(..., "w").write()` |
| `createDir` | 创建目录 | `os.makedirs(exist_ok=True)` |
| `deleteDir` | 删除目录（含非空） | `shutil.rmtree()` |
| `deleteFile` | 删除文件 | `os.remove()` |
| `rename` | 重命名 | `os.rename()` |
| `searchWeb` | 联网搜索 | 百度千帆 `ai_search/web_search` API，返回前 8 条（标题/URL/日期/摘要） |
| `fetchWeb` | 抓取网页正文 | `curl.exe` 拉取 HTML → `trafilatura` 提取转 Markdown（保留标题/段落/列表/表格/链接，去除导航栏广告页脚），超长截断 12000 字符 |
| `RunCli` | 执行命令行程序 | `subprocess.run(argv, shell=False)`，30 秒超时，stdout/stderr 各截断 5000 字符 |
| `loadSkill` | 按需加载技能 | 读 `.agents/skills/<name>/SKILL.md`；附 `filename` 可读技能目录内其他文件（路径限定在技能目录内） |
| `createSkill` | 创建技能 | 校验名称（小写字母/数字/连字符）→ 落盘 `.agents/skills/<name>/SKILL.md`，已存在则拒绝覆盖 |
| `recallContext` | 检索历史归档 | 在 `.agents/context/*.jsonl` 中做全文关键词检索 |

破坏性操作内置路径防护（禁止根路径/空路径）；`execute_tool` 捕获一切异常转为错误字符串回传 LLM，会话不中断。

## 技能包（Skill）

技能放在项目根目录的 `.agents/skills/<name>/SKILL.md`，frontmatter 只需 `name` 与 `description`：

```markdown
---
name: notice
description: 起草单位通知，输出标题、正文、落款三部分
---

（这里写规则正文）
```

- **发现**：启动时扫描 `.agents/skills/`，每个技能只读前 4KB 的 frontmatter，把 `name`/`description`（以及最多 3 条规则 hint）注入 System Prompt，正文不进上下文。
- **加载**：模型判断命中后调用 `loadSkill` 读取 `SKILL.md` 全文；需要 `references/`、`checklist.md` 等附加文件时传 `filename`，路径被限定在该技能目录内。
- **创建**：调用 `createSkill` 直接把新规则落盘为技能，已存在同名技能时拒绝覆盖。
- 仓库自带 5 个示例技能：`code-review`、`notice`、`translation`、`mini-encryption`、`officecli`。

## AGENTS.md

项目根目录放 `AGENTS.md` 即为长期规则：启动时读取一次，作为 system 内容注入到 System Prompt 顶部，会话压缩/恢复后不重复注入。`config.ini` 的 `[agent] load_agents_md = true` 控制是否启用；文件缺失时静默跳过。

## 上下文管理

- token 估算按中英混排比例近似计算；达到 `warn_ratio`（默认 80%）时状态栏告警。
- `/compact` 或阈值触发压缩：原始消息归档到 `.agents/context/<id>.jsonl`，再由 LLM 生成工作摘要替换旧消息，保留最近 `keep_rounds` 轮工具交互。
- `recallContext` 工具可在压缩后回查归档原文。

## 会话与斜杠命令

会话存于 `.agents/sessions/<id>.json`（含 messages 与 mode/context_window 元信息）。

| 命令 | 作用 |
| --- | --- |
| `/help` `/h` `/ ?` | 列出全部命令 |
| `/new` `/n` | 新建会话（自动保存当前） |
| `/save` `/s`、`/list` `/ls`、`/resume` `/r`、`/clear` `/c` | 保存、列出、恢复、清空会话 |
| `/compact` `/compress` | 手动压缩上下文 |
| `/tokens` `/t` | 查看上下文占用与压缩状态 |
| `/skills`、`/mcp` | 查看技能列表、MCP 服务器连接状态 |
| `/quit` `q` | 退出（`/quit save` 先保存） |

## MCP 客户端

复制 `.mcp.json.example` 为 `.mcp.json`，支持两种传输：

```json
{
  "mcpServers": {
    "pet-hospital": { "url": "http://127.0.0.1:8765/mcp" },
    "local-tool": { "command": "python", "args": ["-m", "mcp.server.echo"] }
  }
}
```

外部工具以 `服务器名__工具名` 注册，描述前缀 `[MCP:server]` 标明来源；单个服务器连接失败时降级为一个 `__unavailable` 占位工具，不阻塞本地工具与其他服务器，`/mcp` 可查看状态。

## 未来扩展新前端

以 **Web**（FastAPI + WebSocket）为例，无需改动 core：

```python
# web/app.py
from core.base_ui import BaseUI

class WebUI(BaseUI):
    def run(self):
        # 把 agent.chat_stream(prompt) 的每个 yield 通过 WebSocket 推送给浏览器
        ...
```

然后在 `main.py` 的 `UIS` 注册表中加一行 `"web": WebUI` 即可。Desktop（PyQt/Flet/PySide）、Mobile 同理：在前端目录的 `app.py` 中实现 BaseUI，在线程中消费生成器、把增量投递回界面主线程刷新。

## config.ini 格式

```ini
[llm]
url = http://localhost:3001/api/v1/openai/chat/completions
api_key = your-api-key
model = your-workspace-slug
mode = prompt

[search]
baidu_qianfan_api_key = your-bce-v3-api-key
```

> AnythingLLM 的 OpenAI 兼容端点中，`model` 填**工作区 slug** 而非模型名。
> `[search]` 小节的 `baidu_qianfan_api_key` 用于联网搜索工具 `searchWeb`，格式为 `bce-v3/ALTAK-xxx/xxx`；缺失时搜索工具会返回明确的未配置错误信息。

### 工具调用模式（mode）

| mode | 机制 | 适用端点 |
| --- | --- | --- |
| `fc`（缺省） | 标准 OpenAI function calling：请求带 `tools`，响应回 `tool_calls` | OpenAI / DeepSeek / Qwen / Ollama 等支持 FC 的端点 |
| `prompt` | 提示词级 JSON 协议：系统提示词声明工具，模型回复 `{"tool": ..., "args": ...}` 即视为调用，core 解析执行后以 `TOOL_RESULT` 回传，最多循环 10 轮（`[agent] max_tool_rounds`，可调） | 任何 OpenAI 兼容端点，**包括不支持 tools 参数的 AnythingLLM** |

> 实测发现 AnythingLLM 的 `/api/v1/openai/chat/completions` 会丢弃 `tools` 参数（响应从不返回 `tool_calls`），因此本项目默认 `mode = prompt`。两种模式对界面层完全透明——`chat_stream` 接口不变。

