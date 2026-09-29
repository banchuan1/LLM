# AnythingLLM 文档上传与向量化嵌入

一个自包含的 HTML 网页，调用 AnythingLLM 的 `POST /api/v1/document/upload` 接口，向**第一个工作区**上传文档并完成向量化嵌入。单文件交付，内联 CSS + JS，无框架、无构建。

## 功能

1. 页面加载时自动获取工作区列表，展示第一个工作区的名称与 slug。
2. 选择文件 → 点击「上传并嵌入」→ 一次调用完成上传 + 向量化嵌入。
3. 成功后展示文档摘要（标题 / 字数 / 估算 token / 存储位置）。
4. 失败时按状态码或错误字段提示原因。

## 前置条件

| 项 | 值 |
| --- | --- |
| AnythingLLM 服务地址 | `http://localhost:3001/api` |
| API Key | `PMKKAJG-TZ9MCFM-Q028HXJ-806T09R`（内嵌于页面） |
| Python（用于托管页面） | 3.x（内置 `http.server`，零依赖） |

AnythingLLM 服务须在本机 `localhost:3001` 运行，且至少存在一个工作区。

## 为什么需要本地 HTTP 服务器托管

Chromium 禁止 `file://` 页面对 `http://` 发起 fetch（协议层硬阻断）。因此不能直接双击打开 `upload.html`，必须通过本地 HTTP 服务器托管。服务端 CORS 采用 Origin 反射，对 `http://localhost:8080` 放行。

## 启动步骤

### 1. 确认 AnythingLLM 服务已启动

AnythingLLM 须监听 `localhost:3001`，且已创建至少一个工作区。

### 2. 启动本地静态服务器托管页面

```bash
cd D:\llm\AnythingLLMSever
python -m http.server 8080
```

### 3. 浏览器打开页面

```
http://localhost:8080/upload.html
```

## 使用流程

1. 页面顶部显示目标工作区名称与 slug（自动获取第一个工作区）。
2. 点击「选择文件」选择一个文档文件。
3. 点击「上传并嵌入」按钮。
4. 等待处理（解析 + 向量化嵌入，可能需要数秒）。
5. 成功：显示绿色「✅ 上传并完成向量化嵌入」及文档摘要。
6. 失败：显示红色错误信息，根据提示修正。

## API 调用说明

### 列出工作区

```
GET http://localhost:3001/api/v1/workspaces
Authorization: Bearer PMKKAJG-TZ9MCFM-Q028HXJ-806T09R
```

响应：`{ workspaces: [{ id, name, slug, ... }] }`，页面取 `workspaces[0]`。

### 上传并嵌入文档

```
POST http://localhost:3001/api/v1/document/upload
Authorization: Bearer PMKKAJG-TZ9MCFM-Q028HXJ-806T09R
Content-Type: multipart/form-data（浏览器自动带 boundary）

字段：
  file            (binary, 必填)        文件二进制
  addToWorkspaces (string, 必填)        工作区 slug，逗号分隔；传该参数即触发向量化嵌入
  metadata        (object, 可选)        title / docAuthor / description / docSource
```

成功响应 200：
```json
{
  "success": true,
  "error": null,
  "documents": [{
    "location": "...",
    "name": "...",
    "title": "...",
    "wordCount": 123,
    "token_count_estimate": 456
  }]
}
```

错误码：
- `403` — API Key 无效
- `422` — 文件类型/内容不可处理
- `500` — 服务器错误

## 文件清单

```
D:\llm\AnythingLLMSever\
├── upload.html                              # 唯一交付物：自包含网页
├── README.md                                # 本文件
└── .trae\
    └── documents\
        └── anythingllm-upload-page.md       # 开发计划文档
```

## 安全提示

API Key 写在前端 JS 中（`upload.html` 第 37 行），页内可见。本场景为**本地单机演示**，可接受。若需对外暴露，应改为后端代理，由服务端持有 Key 并转发请求，不应将 Key 暴露到浏览器。
