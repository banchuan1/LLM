# Practice02 — LLM Function Calling 工具调用示例

一个极简的 Python 命令行程序，演示如何通过 OpenAI 兼容的 **function calling** 接口，让大模型自主调用本机工具（日期时间、闰年计算、文件操作），并支持流式打字机输出与多轮上下文。

## 功能

1. 读取 `config.ini` 中的 LLM 配置（接口地址 / api_key / 模型名）。
2. 一次性把用户输入与全部历史消息发送给 LLM。
3. 第一轮**非流式**请求携带工具定义，检测模型是否要求调用工具（`tool_calls`）。
4. 需要调用时执行本地工具，把结果以 `tool` 角色回传给模型；第二轮**流式**请求获取最终回复。
5. 回复逐字符打印，带 0.03s 延时模拟打字机效果。
6. 无限循环对话，按 `Ctrl+C` 退出。

## 前置条件

| 项 | 说明 |
| --- | --- |
| Python | 3.x |
| requests | `pip install requests` |
| LLM 服务 | 本示例指向本地 AnythingLLM（`http://localhost:3001`），任意支持 function calling 的 OpenAI 兼容接口均可 |

## config.ini 格式

```ini
[llm]
url = http://localhost:3001/api/v1/openai/chat/completions
api_key = your-api-key
model = your-workspace-slug
```

> 注意：AnythingLLM 的 OpenAI 兼容端点中，`model` 字段填写的是**工作区 slug**，而非模型名称。

`config.ini` 含密钥，已通过 `.gitignore` 排除，不会提交到仓库。

## 运行

```bash
python main.py
```

启动后按提示输入问题，例如：

- `现在几点了？` → 调用 `getDate`
- `2024 年是闰年吗？` → 调用 `isLeapYear`
- `列出当前目录的文件` → 调用 `listDir`
- `在 D:\test 下创建 a.txt，写入 hello` → 调用 `createFile` / `editFile`
- `删除 D:\test 目录` → 调用 `deleteDir`

## 内置工具

| 工具 | 功能 | 实现方式 |
| --- | --- | --- |
| `getDate` | 获取当前电脑日期和时间 | 调用本地 `date` / `time` 命令 |
| `isLeapYear` | 判断指定年份是否闰年 | Python 计算（四年一闰、百年不闰、四百年再闰） |
| `getCwd` | 获取当前工作目录 | `os.getcwd()` |
| `listDir` | 列出目录下所有文件和子目录 | `os.listdir()` |
| `getFileType` | 获取文件类型 | `mimetypes` + 扩展名 |
| `readFile` | 读取纯文本文件内容 | 二进制读取后 utf-8 解码，非文本文件报错 |
| `createFile` | 按目录 + 文件名创建文件 | `open(..., "w")` |
| `editFile` | 编辑文本文件内容（覆盖写） | `open(..., "w").write()` |
| `createDir` | 创建新目录 | `os.makedirs(exist_ok=True)` |
| `deleteDir` | 删除目录（含非空） | `shutil.rmtree()` |
| `deleteFile` | 删除文件 | `os.remove()` |
| `rename` | 重命名文件或目录 | `os.rename()` |

> 破坏性操作（删除 / 重命名）内置了路径安全校验，禁止作用于根路径或空路径。工具执行异常会被捕获并以错误信息字符串回传模型，不会导致程序崩溃。

## 架构图

代码架构见 [`architecture.mmd`](./architecture.mmd)（Mermaid 格式纯文本）。核心流程：

```
config.ini → 配置加载 → 主循环
   → 阶段1 非流式请求(带 tools)
      → 有 tool_calls → 执行工具 → 阶段2 流式请求 → 打字机输出
      → 无 tool_calls → 直接输出 content
```

## 文件清单

```
Practice02/
├── main.py              # 主程序（配置加载 + 对话循环 + 12 个工具）
├── config.ini           # LLM 配置（已被 .gitignore 排除）
├── architecture.mmd     # Mermaid 代码架构图
├── README.md            # 本文件
└── .gitignore
```
