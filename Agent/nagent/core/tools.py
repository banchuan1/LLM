"""工具集：TOOLS 声明（给 LLM 的 schema）、工具实现、统一执行入口。"""
import os
import shutil
import subprocess
import sys
import mimetypes
import json
import requests

from .config import load_config
from .skills import load_skill_file, create_skill_file
from .mcp_client import init_mcp, call_mcp_tool
from .context_manager import recall_context as _recall_context_impl

# loadSkill 的上下文（由 Agent 初始化时注入）
_skills_ctx = {"project_root": None, "skills": []}


def set_skills_context(project_root, skills):
    """Agent 初始化时调用，为 loadSkill 工具注入运行时上下文。"""
    _skills_ctx["project_root"] = project_root
    _skills_ctx["skills"] = skills


def register_mcp_tools(project_root):
    """连接 .mcp.json 中配置的所有 MCP Server，将其工具动态注册到 TOOLS/TOOL_MAP。

    必须在 Agent 初始化阶段调用（构建 System Prompt 之前）。
    单个 Server 失败不影响其他 Server 和本地工具。
    """
    schemas = init_mcp(project_root)
    for schema in schemas:
        name = schema["function"]["name"]
        TOOLS.append(schema)
        # 闭包捕获 name，使每个 MCP 工具都能正确转发
        TOOL_MAP[name] = lambda _name=name, **args: call_mcp_tool(_name, args)
    return len(schemas)

# trafilatura 可选依赖：网页正文提取
try:
    import trafilatura
    _HAS_TRAFILATURA = True
except ImportError:
    _HAS_TRAFILATURA = False

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "getDate",
            "description": "获取当前电脑的日期和时间",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "判断指定年份是否是闰年",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "要判断的年份"}
                },
                "required": ["year"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getCwd",
            "description": "获取当前工作目录",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "listDir",
            "description": "列出指定目录下所有文件和子目录",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "getFileType",
            "description": "获取指定文件的文件类型",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "readFile",
            "description": "获取指定文件的内容（仅支持纯文本文件）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createFile",
            "description": "根据指定的目录和文件名创建新文件",
            "parameters": {
                "type": "object",
                "properties": {
                    "dir": {"type": "string", "description": "目录路径"},
                    "filename": {"type": "string", "description": "文件名"},
                },
                "required": ["dir", "filename"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "editFile",
            "description": "编辑指定文件的内容（仅支持纯文本文件），写入内容会覆盖原内容",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "文件路径"},
                    "content": {"type": "string", "description": "要写入的文本内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createDir",
            "description": "创建新目录",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteDir",
            "description": "删除目录（可删除非空目录）",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "目录路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deleteFile",
            "description": "删除文件",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "文件路径"}},
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename",
            "description": "重命名文件或目录",
            "parameters": {
                "type": "object",
                "properties": {
                    "old": {"type": "string", "description": "原路径"},
                    "new": {"type": "string", "description": "新路径"},
                },
                "required": ["old", "new"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "searchWeb",
            "description": "通过百度千帆联网搜索 API 获取互联网最新信息，返回搜索摘要、参考来源的标题及 URL。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词或问题"},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "fetchWeb",
            "description": "获取指定网页的主要内容：调用 curl 拉取 HTML，用 trafilatura 提取正文并转换为 Markdown，保留标题/段落/列表/表格/链接，去除导航栏广告页脚。",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "网页 URL，必须以 http:// 或 https:// 开头"},
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "RunCli",
            "description": "执行本地已安装的命令行程序（CLI），返回标准输出、标准错误和退出码。程序名与参数以列表方式传给 subprocess（shell=False），超时 30 秒自动终止，过长输出会被截断。",
            "parameters": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "程序名称，如 python、git、dir 对应的程序等（需在 PATH 中）"},
                    "args": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "命令参数列表，如 [\"-la\"]；无参数可省略",
                    },
                },
                "required": ["command"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "loadSkill",
            "description": "加载 Skill（技能包）的完整说明。当用户请求涉及某个 Skill 领域时（如撰写通知、代码审查、中英翻译），必须先调用此工具获取 SKILL.md 全文，再按 Skill 规则执行。禁止跳过此工具直接凭常识回答。【重要】同一个 Skill 只需调用一次。拿到结果后直接基于其中规则行动（输出答案或追问用户），禁止重复调用 loadSkill 加载同一个 Skill。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "要加载的 Skill 名称（与 System Prompt 中列出的 skill 名称完全一致，如 '撰写通知'）"},
                    "filename": {
                        "type": "string",
                        "description": "可选。Skill 目录内的附加文件（如 checklist.md、examples/ 下的示例）。不提供则返回该 Skill 的 SKILL.md 全文。支持相对于 Skill 目录的路径、项目相对路径、或仅文件名（将在 Skill 目录内递归搜索）",
                    },
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "createSkill",
            "description": "创建一个新的 Skill（技能包）。当用户要求创建/添加/新增 Skill 时使用此工具。工具会在 .agents/skills/ 下创建 Skill 子目录并写入 SKILL.md。Skill 名称必须使用小写字母、数字和连字符（如 code-review、api-doc、my-skill-1）。",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Skill 名称：只能包含小写字母 a-z、数字 0-9 和连字符 -，不能以连字符开头或结尾。例如：code-review、weekly-report、api-doc-v2",
                    },
                    "skillContext": {
                        "type": "string",
                        "description": "要写入 SKILL.md 的完整内容，应包含 YAML Frontmatter（至少 name 和 description 两个字段）加上 Skill 规则正文。如果不写 Frontmatter 或字段缺失，工具会自动补齐。",
                    },
                },
                "required": ["name", "skillContext"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recallContext",
            "description": "从历史上下文归档中检索关键词。当对话已被压缩（系统提示压缩前的完整上下文已归档），而你需要查找压缩摘要中没有的历史细节时，使用此工具在 .agents/context/ 下的 JSONL 归档文件中做全文关键词搜索。返回相关片段、归档编号和位置。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要查找的关键词或文本内容（必需）",
                    },
                    "id": {
                        "type": "string",
                        "description": "可选。指定要在哪个归档中检索（归档编号如 20261022-153000）。不提供则搜索所有归档。",
                    },
                },
                "required": ["text"],
            },
        },
    },
]


def getDate():
    if sys.platform == "win32":
        d = subprocess.run("date /t", shell=True, capture_output=True, text=True).stdout.strip()
        t = subprocess.run("time /t", shell=True, capture_output=True, text=True).stdout.strip()
        return f"{d} {t}"
    return subprocess.run(["date"], capture_output=True, text=True).stdout.strip()


def isLeapYear(year):
    if year % 4 == 0 and year % 100 != 0 or year % 400 == 0:
        return f"{year} 是闰年"
    return f"{year} 不是闰年"


def _safe(path):
    """破坏性操作的路径防护：禁止根路径与空路径。"""
    real = os.path.abspath(path)
    if not path.strip() or len(real) <= len(os.path.abspath(os.sep)):
        raise ValueError("禁止对根路径或空路径执行破坏性操作")


def getCwd():
    return os.getcwd()


def listDir(path):
    return "\n".join(os.listdir(path))


def getFileType(path):
    t = mimetypes.guess_type(path)[0]
    ext = os.path.splitext(path)[1] or "无扩展名"
    return f"{ext}（{t}）" if t else ext


def readFile(path):
    with open(path, "rb") as f:
        data = f.read()
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise ValueError("该文件不是纯文本文件，无法读取")


def createFile(dir, filename):
    path = os.path.join(dir, filename)
    open(path, "w", encoding="utf-8").close()
    return f"已创建文件：{path}"


def editFile(path, content):
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return f"已写入文件：{path}"


def createDir(path):
    os.makedirs(path, exist_ok=True)
    return f"已创建目录：{path}"


def deleteDir(path):
    _safe(path)
    shutil.rmtree(path)
    return f"已删除目录：{path}"


def deleteFile(path):
    _safe(path)
    os.remove(path)
    return f"已删除文件：{path}"


def rename(old, new):
    _safe(old)
    _safe(new)
    os.rename(old, new)
    return f"已重命名：{old} -> {new}"


# 千帆搜索 API Key 缓存，避免每次调用都读 config.ini
_qianfan_key = None


def searchWeb(query):
    """调用百度千帆联网搜索 API，返回格式化的搜索结果。"""
    global _qianfan_key
    if _qianfan_key is None:
        _qianfan_key = load_config()["search"]["baidu_qianfan_api_key"]
    if not _qianfan_key:
        return "搜索 API 未配置：config.ini [search] 小节缺少 baidu_qianfan_api_key"

    endpoint = "https://qianfan.baidubce.com/v2/ai_search/web_search"
    headers = {
        "Authorization": f"Bearer {_qianfan_key}",
        "Content-Type": "application/json",
    }
    payload = {"messages": [{"role": "user", "content": query}]}

    try:
        resp = requests.post(endpoint, headers=headers, json=payload, timeout=15)
    except requests.RequestException as e:
        return f"搜索网络请求失败：{e}"

    if resp.status_code != 200:
        return f"搜索 API 返回错误（HTTP {resp.status_code}）：{resp.text[:200]}"

    try:
        data = resp.json()
    except json.JSONDecodeError:
        return f"搜索 API 返回非 JSON 内容：{resp.text[:200]}"

    refs = data.get("references", [])
    if not refs:
        return f"未找到与「{query}」相关的搜索结果"

    # 取前 8 条，按 rerank_score / authority_score 排序（千帆返回已排好）
    top = refs[:8]
    lines = [f"搜索「{query}」共找到 {len(refs)} 条结果，以下是前 {len(top)} 条：\n"]
    for i, r in enumerate(top, 1):
        title = r.get("title", "(无标题)")
        url = r.get("url", "")
        date = r.get("date", "")
        snippet = r.get("snippet") or r.get("content", "")
        # snippet 过长截断
        if len(snippet) > 300:
            snippet = snippet[:300] + "..."
        lines.append(f"{i}. {title}\n   来源：{url}\n   日期：{date}\n   摘要：{snippet}\n")
    return "\n".join(lines)


def fetchWeb(url):
    """用 curl 拉取网页 HTML，trafilatura 提取正文转 Markdown。"""
    if not _HAS_TRAFILATURA:
        return "fetchWeb 依赖未安装：请先执行 pip install trafilatura"
    if not url.startswith(("http://", "https://")):
        return f"URL 必须以 http:// 或 https:// 开头：{url}"

    # subprocess 列表参数方式，不使用 shell=True
    curl_exe = "curl.exe" if sys.platform == "win32" else "curl"
    try:
        proc = subprocess.run(
            [
                curl_exe,
                "-L",                     # 跟随重定向
                "--max-time", "30",       # 总超时 30 秒
                "-H", "User-Agent: Mozilla/5.0 (Nagent-FetchWeb)",
                "-H", "Accept: text/html,application/xhtml+xml",
                "-sS",                    # 静默但显示错误
                url,
            ],
            capture_output=True,
            timeout=45,                    # Python 层兜底超时
        )
    except subprocess.TimeoutExpired:
        return f"网页访问超时（> 45s）：{url}"
    except FileNotFoundError:
        return "curl 未找到：请确认系统已安装 curl"
    except Exception as e:
        return f"网页访问失败：{e}"

    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()[:200]
        return f"curl 请求失败（退出码 {proc.returncode}）：{err}"

    html = proc.stdout
    if not html:
        return f"curl 返回空内容：{url}"

    try:
        html_text = html.decode("utf-8", errors="replace")
    except Exception as e:
        return f"HTML 解码失败：{e}"

    try:
        markdown = trafilatura.extract(
            html_text,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            deduplicate=True,
            favor_precision=True,
        )
    except Exception as e:
        return f"网页正文提取失败：{e}"

    if not markdown:
        return f"无法从该网页提取到有效正文：{url}"

    # 限制长度，避免 Token 浪费（LLM 侧再截断也可以）
    MAX_LEN = 12000
    if len(markdown) > MAX_LEN:
        markdown = markdown[:MAX_LEN] + f"\n\n--- 内容过长，已截断（原始 {len(markdown)} 字符）---"

    return f"来源：{url}\n\n{markdown}"


# RunCli：命令执行超时（秒）与单路输出截断上限（字符）
CLI_TIMEOUT = 30
CLI_MAX_OUTPUT = 5000


def _decode_output(data):
    """命令输出字节流解码：utf-8 优先，失败退回 gbk（兼容 Windows 中文控制台）。"""
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def _clip_output(text, label):
    """过长输出截断，并标明截断情况。"""
    if len(text) > CLI_MAX_OUTPUT:
        return (
            text[:CLI_MAX_OUTPUT]
            + f"\n...[{label}过长已截断：显示前 {CLI_MAX_OUTPUT} 字符，实际共 {len(text)} 字符]"
        )
    return text


def runCli(command, args=None):
    """执行本地命令行程序：列表参数 + shell=False，返回 stdout/stderr/退出码。"""
    argv = [command] + [str(a) for a in (args or [])]
    try:
        proc = subprocess.run(
            argv, shell=False, capture_output=True, timeout=CLI_TIMEOUT
        )
    except subprocess.TimeoutExpired:
        return f"命令执行超时（超过 {CLI_TIMEOUT} 秒），已强制终止：{argv}"
    except FileNotFoundError:
        return f"命令未找到：{command}（请确认程序已安装且在 PATH 中）"
    except Exception as e:
        return f"命令执行失败：{e}"

    stdout = _clip_output(_decode_output(proc.stdout or b""), "stdout")
    stderr = _clip_output(_decode_output(proc.stderr or b""), "stderr")
    return f"退出码: {proc.returncode}\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"


def loadSkill(name, filename=None):
    """loadSkill 工具入口 —— 从模块级上下文取 skills 和 project_root，委托给 skills 模块。"""
    return load_skill_file(
        _skills_ctx["project_root"],
        _skills_ctx["skills"],
        name,
        filename,
    )


def createSkill(name, skillContext):
    """createSkill 工具入口 —— 委托给 skills 模块创建 Skill，成功后刷新上下文。"""
    message, skill_dir = create_skill_file(
        _skills_ctx["project_root"], name, skillContext
    )
    # 创建成功 → 重新扫描 skills，让新 Skill 立即可被 loadSkill 发现
    if skill_dir is not None:
        from .skills import scan_skills
        _skills_ctx["skills"] = scan_skills(_skills_ctx["project_root"])
    return message


def recallContext(text, id=None):
    """recallContext 工具入口 —— 在历史归档中全文检索。"""
    return _recall_context_impl(_skills_ctx["project_root"], text, id)


TOOL_MAP = {
    "getDate": getDate,
    "isLeapYear": isLeapYear,
    "getCwd": getCwd,
    "listDir": listDir,
    "getFileType": getFileType,
    "readFile": readFile,
    "createFile": createFile,
    "editFile": editFile,
    "createDir": createDir,
    "deleteDir": deleteDir,
    "deleteFile": deleteFile,
    "rename": rename,
    "searchWeb": searchWeb,
    "fetchWeb": fetchWeb,
    "RunCli": runCli,
    "loadSkill": loadSkill,
    "createSkill": createSkill,
    "recallContext": recallContext,
}


def execute_tool(name, args):
    """统一工具执行入口：任何异常都转为错误信息字符串，保证会话不中断。"""
    try:
        if name in TOOL_MAP:
            return TOOL_MAP[name](**args)
        # 兜底：MCP 工具名形如 "server__tool"，直接转发
        if "__" in name:
            return call_mcp_tool(name, args)
        return f"未知的工具: {name}"
    except Exception as e:
        return f"工具执行失败：{e}"
