---
name: officecli
description: 调用本地 officecli-win-x64.exe 读取、创建和修改 Word(.docx)、Excel(.xlsx)、PowerPoint(.pptx) 文档
---

## 定位

officecli-win-x64.exe 是一个 AI 友好的 Office 文档命令行工具，**无依赖、无需安装 Office**。LLM 通过 RunCli 工具调用它，所有操作以 `officecli-win-x64.exe <命令> [参数]` 的形式执行。

exe 位置：**当前项目根目录**下的 `officecli-win-x64.exe`（即 `os.getcwd()\officecli-win-x64.exe`）。
完整参考文档见同目录下的 `references/OfficeCli操作说明.md`（约 400 行，首次使用建议 loadSkill 后再 loadSkill(filename="references/OfficeCli操作说明.md")）。

## 三层操作策略（重要）

**L1 → L2 → L3，优先高层。**

| 层级 | 能力 | 什么时候用 |
|------|------|-----------|
| **L1** | `create` `view` `get` `query` `validate` | 读取、检查结构、创建空白文档 |
| **L2** | `set` `add` `remove` `move` `swap` `batch` | 修改属性、增删元素、批量操作（99% 的场景） |
| **L3** | `raw` `raw-set` | L2 无法表达时的底层 XML 回退 |

所有支持结构化 JSON 输出的命令都可加 `--json`，便于 AI 解析结果。

## Help 系统（不确定时先查）

**永远用 help 代替猜命令和属性名。** 一个 help 查询胜过猜了又试的循环：

```bash
officecli-win-x64.exe help                                    # 全部命令 + 全局选项
officecli-win-x64.exe help docx                               # docx 所有元素类型
officecli-win-x64.exe help docx paragraph                     # paragraph 的完整属性 schema
officecli-win-x64.exe help docx paragraph --json              # 机器可读的 schema
officecli-win-x64.exe help pptx shape                         # PPT shape 元素
officecli-win-x64.exe help xlsx sheet                         # Excel sheet 属性
```

## 命令速查（最常用）

### L1 读取 / 创建

```bash
# 创建空白文档（类型由扩展名推断）
officecli-win-x64.exe create report.docx
officecli-win-x64.exe create slides.pptx
officecli-win-x64.exe create data.xlsx

# 查看文档（多种模式）
officecli-win-x64.exe view report.docx outline            # 文档大纲
officecli-win-x64.exe view report.docx text               # 纯文本
officecli-win-x64.exe view report.docx issues             # 格式/结构问题
officecli-win-x64.exe view slides.pptx html               # HTML 快照（静态）

# 读取节点
officecli-win-x64.exe get report.docx '/body/p[3]' --depth 2 --json
officecli-win-x64.exe get slides.pptx '/slide[1]' --depth 1 --json

# CSS 风格查询
officecli-win-x64.exe query report.docx 'paragraph[style=Heading1]'
```

### L2 修改

```bash
# 设置属性（格式: --prop key=value）
officecli-win-x64.exe set report.docx '/body/p[1]' --prop bold=true --prop color=red

# 查找替换（范围: / = 全文）
officecli-win-x64.exe set report.docx / --find draft --replace final

# 添加元素（parent + type）
officecli-win-x64.exe add report.docx /body --type paragraph --prop text="新段落" --prop style=Heading1
officecli-win-x64.exe add slides.pptx '/slide[1]' --type shape --prop text="标题" --prop x=2cm --prop y=5cm
officecli-win-x64.exe add data.xlsx /Sheet1 --type pivottable --prop source="A1:E100" --prop rows=Region --prop values="Sales:sum"

# 删除 / 移动 / 交换
officecli-win-x64.exe remove report.docx '/body/p[4]'
officecli-win-x64.exe move report.docx '/body/p[3]' --to /body --after '/body/p[1]'
officecli-win-x64.exe swap slides.pptx '/slide[1]' '/slide[2]'
```

### Resident Mode（性能）

officecli 自动为每个文件启动常驻进程（60s 空闲超时），避免重复文件 I/O。建议长会话显式管理：

```bash
officecli-win-x64.exe open report.docx       # 显式打开到内存
# ... 多次 set / add / get ...
officecli-win-x64.exe close report.docx      # 保存并释放
```

## 格式别名

| 用户可能说的 | 实际格式 |
|---|---|
| word / Word / 文档 | `.docx` |
| excel / Excel / 表格 | `.xlsx` |
| ppt / pptx / PowerPoint / 幻灯片 | `.pptx` |

## 关键约束

1. **路径是 1-based（XPath 惯例）**：`'/body/p[3]'` = 第三个段落
2. **`--index` 是 0-based**（数组惯例）：`--index 0` = 第一个位置；但 Excel 的 `add row/col --index` 是 1-based（OOMXL 行号）
3. **Excel 例外**：`add --type row` 和 `add --type col` 的 `--index N` 是 **1-based**
4. **中文路径和参数需要正确引号**，通过 RunCli 调用时用 args 数组传参避免 shell 转义问题
5. **修改 Word/Excel/PPT 之前先 close**：如果文件在 Word/WPS/PowerPoint 中打开，officecli 会因文件锁失败
6. **批量操作用 `batch` 命令**：多个改动想要原子性（全成功或全回滚）时用 `batch --json`

## 工作流建议

```
用户: 帮我创建一份 Q4 业绩报告（Word）
  ↓
1. officecli-win-x64.exe create q4-report.docx
2. officecli-win-x64.exe add q4-report.docx /body --type paragraph --prop text="Q4 业绩报告" --prop style=Heading1
3. officecli-win-x64.exe add q4-report.docx /body --type paragraph --prop text="..."
4. officecli-win-x64.exe view q4-report.docx outline    # 验证结构
5. officecli-win-x64.exe close q4-report.docx           # 保存释放
```

## 常见陷阱

| 错误做法 | 正确做法 |
|---|---|
| `--name "foo"` | `--prop name="foo"`（所有属性都走 `--prop`） |
| 猜属性名如 `fontBold` | 先 `officecli-win-x64.exe help docx paragraph` 查准确名称 |
| 忘记 close 就用 Office 打开 | 先 `close report.docx`，再用 Word 打开 |
| shell 里路径有 `[N]` 不加引号 | RunCli 用 args 数组传参，避免 shell glob 扩展 |
