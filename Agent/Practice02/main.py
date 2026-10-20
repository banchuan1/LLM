import configparser
import time
import json
import requests
import sys
import subprocess
import os
import shutil
import mimetypes

sys.stdout.reconfigure(encoding="utf-8")

config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

url = config["llm"]["url"]
api_key = config["llm"]["api_key"]
model = config["llm"]["model"]

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
    }
]

def getDate():
    if sys.platform == "win32":
        d = subprocess.run("date /t", shell=True, capture_output=True, text=True).stdout.strip()
        t = subprocess.run("time /t", shell=True, capture_output=True, text=True).stdout.strip()
        return f"{d} {t}"
    else:
        return subprocess.run(["date"], capture_output=True, text=True).stdout.strip()

def isLeapYear(year):
    if year % 4 == 0 and year % 100 != 0 or year % 400 == 0:
        return f"{year} 是闰年"
    return f"{year} 不是闰年"

def _safe(path):
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
}

print("按 Ctrl+C 退出程序")

messages = []

while True:
    prompt = input("\n请输入你的问题：")
    messages.append({"role": "user", "content": prompt})

    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "tools": TOOLS},
    )
    msg = resp.json()["choices"][0]["message"]

    if msg.get("tool_calls"):
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": msg["tool_calls"]})
        for tc in msg["tool_calls"]:
            args = json.loads(tc["function"]["arguments"]) if tc["function"]["arguments"] else {}
            try:
                result = TOOL_MAP[tc["function"]["name"]](**args)
            except Exception as e:
                result = f"工具执行失败：{e}"
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

        resp2 = requests.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={"model": model, "messages": messages, "stream": True},
            stream=True,
        )
        resp2.encoding = "utf-8"
        reply = ""
        for line in resp2.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            delta = json.loads(data)["choices"][0]["delta"].get("content", "")
            reply += delta
            for ch in delta:
                sys.stdout.write(ch)
                sys.stdout.flush()
                time.sleep(0.03)
        print()
        messages.append({"role": "assistant", "content": reply})
    else:
        reply = msg.get("content", "")
        for ch in reply:
            sys.stdout.write(ch)
            sys.stdout.flush()
            time.sleep(0.03)
        print()
        messages.append({"role": "assistant", "content": reply})
