import configparser
import time
import json
import requests
import sys

sys.stdout.reconfigure(encoding="utf-8")

config = configparser.ConfigParser()
config.read("config.ini", encoding="utf-8")

url = config["llm"]["url"]
api_key = config["llm"]["api_key"]
model = config["llm"]["model"]

print("按 Ctrl+C 退出程序")

messages = []

while True:
    prompt = input("\n请输入你的问题：")
    messages.append({"role": "user", "content": prompt})

    resp = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": model, "messages": messages, "stream": True},
        stream=True,
    )

    reply = ""
    resp.encoding = "utf-8"
    for line in resp.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        data = line[5:].strip()
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        delta = chunk["choices"][0]["delta"].get("content", "")
        reply += delta
        for ch in delta:
            sys.stdout.write(ch)
            sys.stdout.flush()
            time.sleep(0.03)
    print()
    messages.append({"role": "assistant", "content": reply})
