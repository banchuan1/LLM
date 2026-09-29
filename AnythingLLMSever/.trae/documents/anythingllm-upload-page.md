# AnythingLLM 文档上传 + 向量化嵌入 网页 开发计划

## Context（背景与目标）

用户需要一个网页，调用 AnythingLLM 的 `POST /api/v1/document/upload` 接口，向**第一个工作区**上传文档，并**完成向量化嵌入**。要求尽量简单、不冗余、不过度设计、节约 token。开发完成后在浏览器打开该网页。

开发前已通过实测确认了所有关键事实（见下），无需再试探。

## 实测确认的关键事实

- **API 基址**：`http://localhost:3001/api`（Swagger `servers` 为 `/api`）。
- **鉴权**：`Authorization: Bearer PMKKAJG-TZ9MCFM-Q028HXJ-806T09R`（已用该 key 成功调用接口）。
- **列出工作区**：`GET /api/v1/workspaces` → `{ workspaces: [{ id, name, slug, ... }] }`。
  - 第一个工作区：name=`我的工作区`，slug=`41d5dcc6-5dd7-4138-a7e7-4c694343df90`（页面运行时动态获取 [0] 更稳健）。
- **上传+嵌入（单次调用即可完成）**：`POST /api/v1/document/upload`，`multipart/form-data`：
  - `file`（binary，必填）
  - `addToWorkspaces`（string，**逗号分隔的工作区 slug**）——Swagger 描述明确写明：用于"post-upload 将文档 embed 进指定工作区"。即传该参数即触发向量化嵌入，无需再调别的接口。
  - `metadata`（object，可选：title/docAuthor/description/docSource）
  - 成功响应 200：`{ success: true, error: null, documents: [{ location, name, title, docAuthor, description, docSource, chunkSource, published, wordCount, token_count_estimate }] }`
  - 403=key 无效，422=不可处理，500=服务器错误
- **CORS**：服务端采用 Origin 反射（返回请求方 Origin）。实测对 `http://localhost:8080` 与 `null` 都反射成功。但 **Chromium 禁止 `file://` 页面对 `http://` 发起 fetch**（协议层硬阻断），故必须用本地 HTTP 服务器托管页面。
- **可用环境**：Python 3.13（`D:\anaconda3\python.exe`），用其内置 `http.server` 托管，零依赖。

## 实现方案（推荐方案）

交付物：**一个自包含 HTML 文件** `d:\llm\AnythingLLMSever\upload.html`（内联 CSS + JS，无框架、无构建）。

### 页面行为
1. 顶部常量：`API_BASE='http://localhost:3001/api'`、`API_KEY='PMKKAJG-TZ9MCFM-Q028HXJ-806T09R'`。
2. 页面加载时：`fetch GET /api/v1/workspaces`（带 Authorization 头）→ 取 `workspaces[0]`，展示工作区名称与 slug；失败则提示错误。
3. `<input type="file">` 选择文件 + 「上传并嵌入」按钮。
4. 点击上传：构造 `FormData`，含 `file` 与 `addToWorkspaces=<第一个工作区slug>`；`fetch POST /api/v1/document/upload`，带 `Authorization` 头（不手动设 Content-Type，让浏览器自动带 boundary）。按钮置为「处理中…」。
5. 成功：展示 `documents` 摘要（name / title / wordCount / token_count_estimate）+ 明确提示「✅ 上传并完成向量化嵌入到工作区：xxx」。
6. 失败：按状态码/`error` 字段展示错误信息。
7. 极简样式（内联 `<style>`），中文界面，无多余设计。

### 安全权衡
API key 写在前端 JS 中（页内可见）。本场景为本地单机演示，可接受；若需对外暴露应改为后端代理。计划中默认内嵌以保持简单。

## 关键文件
- `d:\llm\AnythingLLMSever\upload.html`（新建，唯一交付物）

## 启动与打开步骤
1. 在工作目录后台启动本地静态服务器：`python -m http.server 8080`（后台运行）。
2. 用默认浏览器打开：`Start-Process "http://localhost:8080/upload.html"`（若沙箱阻止拉起浏览器，则以 `dangerouslyDisableSandbox` 重试并说明原因）。

## 验证（端到端）
1. 浏览器打开页面 → 顶部显示工作区「我的工作区」及其 slug。
2. 选一个小文本文件 → 点「上传并嵌入」→ 出现成功提示与文档信息（name / token_count_estimate 等）。
3. （可选）在 AnythingLLM 界面确认该文档已出现在工作区且可被检索（证明嵌入生效）。
4. 若 403 → key 问题；若 422 → 文件类型/内容问题；据提示修正。
