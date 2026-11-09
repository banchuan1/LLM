"""Skill 动态加载机制：扫描 .agents/skills/ 目录，按 LLM 指令按需加载 Skill 内容。

用法：
    skills = scan_skills(project_root)          # 启动时扫描，只读 name/description
    prompt = build_skills_prompt(skills)         # 注入 System Prompt
    content = load_skill_file(project_root, skills, name, filename)  # LLM 调用 loadSkill 工具时
    result  = create_skill_file(project_root, name, skill_context)   # LLM 调用 createSkill 工具时
"""
import os
import re


# ---------- YAML Frontmatter 解析（极简，仅处理字符串字段，避免引入 PyYAML 依赖） ----------

def _parse_frontmatter(text):
    """从 SKILL.md 开头提取 YAML Frontmatter，返回 {name, description} 或 None。

    Frontmatter 以 '---' 行开始和结束，例如：
        ---
        name: mySkill
        description: Does something useful
        ---
    """
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    # 找到第二个 ---
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return None
    body = "\n".join(lines[1:end_idx])
    result = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, val = line.partition(":")
        key = key.strip()
        val = val.strip()
        # 去掉首尾引号
        if len(val) >= 2 and val[0] == val[-1] and val[0] in ('"', "'"):
            val = val[1:-1]
        result[key] = val
    return result


def _extract_body(full_text):
    """去掉 SKILL.md 的 Frontmatter，返回正文部分。"""
    if not full_text.startswith("---"):
        return full_text
    lines = full_text.splitlines()
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return full_text
    start = end_idx + 1
    while start < len(lines) and not lines[start].strip():
        start += 1
    return "\n".join(lines[start:])


def _extract_hint(head_text):
    """从 SKILL.md 前 4KB 里提取规则 hint（最多 3 条，每条截断到 50 字符）。

    用于 System Prompt 的 Level0 摘要，让 LLM 知道这个 skill 里有它不知道的独有规则，
    从而触发 loadSkill。既泄露最小必要信息，又不违反渐进披露原则。
    """
    body = _extract_body(head_text)
    hint_lines = []
    for raw in body.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # 匹配数字列表 (1. xxx / 1、xxx / 1) xxx / 1)xxx) 或短横线列表 (- xxx / * xxx)
        matched = False
        if line.startswith("- ") or line.startswith("* "):
            matched = True
        else:
            # 尝试匹配 "数字.xxx" "数字、xxx" "数字)xxx" "数字) xxx"
            for sep in (". ", "、", ") ", ").", ")"):
                idx = line.find(sep)
                if idx > 0 and line[:idx].isdigit():
                    matched = True
                    break
        if matched:
            # 去掉前缀，截断到 50 字符
            content = line.lstrip("0123456789.、) -*").strip()
            if len(content) > 50:
                content = content[:50] + "…"
            hint_lines.append(content)
        if len(hint_lines) >= 3:
            break
    return hint_lines


# ---------- Skill 扫描 ----------

def scan_skills(project_root):
    """扫描 <project_root>/.agents/skills/，返回有效 Skill 列表。

    每个 Skill 子目录需包含 SKILL.md，且 Frontmatter 声明 name 和 description。
    返回 [{"name": str, "description": str, "skill_dir": str, "skill_md": str}, ...]
    仅加载元信息，不读取 SKILL.md 正文。
    """
    skills_dir = os.path.join(project_root, ".agents", "skills")
    if not os.path.isdir(skills_dir):
        return []

    result = []
    for entry in sorted(os.listdir(skills_dir)):
        skill_dir = os.path.join(skills_dir, entry)
        if not os.path.isdir(skill_dir):
            continue
        skill_md = os.path.join(skill_dir, "SKILL.md")
        if not os.path.isfile(skill_md):
            continue
        try:
            with open(skill_md, "r", encoding="utf-8") as f:
                head = f.read(4096)  # 只读前 4KB，Frontmatter 足够
        except OSError:
            continue
        fm = _parse_frontmatter(head)
        if not fm:
            continue
        name = fm.get("name", "").strip()
        desc = fm.get("description", "").strip()
        if not name or not desc:
            continue
        hint = _extract_hint(head)
        result.append({
            "name": name,
            "description": desc,
            "hint": hint,
            "skill_dir": os.path.abspath(skill_dir),
            "skill_md": os.path.abspath(skill_md),
        })
    return result


def build_skills_prompt(skills):
    """将 Skill 元信息格式化为 System Prompt 片段（强制语气 + hint 规则）。"""
    if not skills:
        return ""
    lines = [
        "【重要】以下 Skill 包含独有的业务规则或步骤。"
        "遇到相关领域的用户请求，**必须先调用 loadSkill 加载对应 Skill 的完整说明**，"
        "再基于 Skill 规则回答。禁止跳过 Skill 直接凭常识回答。"
    ]
    lines.append("")
    for s in skills:
        entry = f"- skill '{s['name']}': {s['description']}"
        if s.get("hint"):
            hints = "；".join(s["hint"])
            entry += f"（含独有规则：{hints}）"
        lines.append(entry)
    lines.append("")
    lines.append("【反循环规则】同一个 Skill 只需 loadSkill **一次**。")
    lines.append("拿到 SKILL.md 全文后，应基于其中的规则直接执行（输出答案或追问用户缺失信息），")
    lines.append("**禁止重复 loadSkill 同一个 Skill**。如果 SKILL.md 中的规则要求你向用户追问（如"
                 "起草人姓名、部门信息），请直接用自然语言追问，不要再次调用 loadSkill。")
    lines.append("")
    lines.append("调用方式: loadSkill({\"name\": \"skill名称\"}) 读取完整 SKILL.md；需要附加文件时加 filename 参数。")
    lines.append("Skill 加载完成后，可结合 RunCli、readFile、searchWeb 等其他工具协同完成任务。")
    lines.append("")
    lines.append("如需创建新 Skill，使用 createSkill 工具（name + skillContext 两个参数）。"
                 "创建后可用 createDir / createFile 等工具补充 references/、scripts/ 等子目录。")
    return "\n".join(lines)


# ---------- Skill 文件加载（loadSkill 工具实现） ----------

def _safe_resolve(base_dir, target_path):
    """将 target_path 解析为 base_dir 内的绝对路径；越界返回 None。"""
    resolved = os.path.normpath(os.path.join(base_dir, target_path))
    base = os.path.abspath(base_dir)
    # 确保 resolved 在 base 目录内（realpath 处理符号链接边界）
    try:
        if not os.path.commonpath([resolved, base]) == base:
            return None
    except ValueError:
        return None
    return resolved


def _recursive_find(skill_dir, filename):
    """在 skill_dir 内递归查找所有名为 filename 的文件，返回绝对路径列表。"""
    matches = []
    for root, _, files in os.walk(skill_dir):
        if filename in files:
            matches.append(os.path.join(root, filename))
    return matches


def load_skill_file(project_root, skills, name, filename=None):
    """loadSkill 工具的核心实现。

    参数:
        project_root: 项目根目录（用于路径解析）
        skills: scan_skills() 返回的 Skill 元信息列表
        name: Skill 名称（必需）
        filename: 可选。None → 返回 SKILL.md 全文；有值 → 加载指定附加文件

    返回: str，成功时是文件内容，失败时是错误/提示信息。
    """
    # 1. 定位 Skill
    skill = next((s for s in skills if s["name"] == name), None)
    if skill is None:
        available = ", ".join(s["name"] for s in skills) or "(none)"
        return f"Skill '{name}' 未找到。可用 skills: {available}"

    skill_dir = skill["skill_dir"]

    # 2. 未指定 filename → 返回 SKILL.md 全文
    if not filename:
        try:
            with open(skill["skill_md"], "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            return f"无法读取 SKILL.md: {e}"

    # 3. 指定了 filename → 尝试多种路径解析方式
    # 3a. 精确路径匹配：相对于 skill_dir
    candidate = _safe_resolve(skill_dir, filename)
    if candidate and os.path.isfile(candidate):
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            return f"无法读取 {filename}: {e}"

    # 3b. 精确路径匹配：相对于 project_root（解析后必须仍在 skill_dir 内）
    candidate = _safe_resolve(skill_dir, os.path.relpath(
        os.path.normpath(os.path.join(project_root, filename)), skill_dir
    ))
    if candidate and os.path.isfile(candidate):
        try:
            with open(candidate, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            return f"无法读取 {filename}: {e}"

    # 3c. 绝对路径（解析后必须仍在 skill_dir 内）
    if os.path.isabs(filename):
        candidate = os.path.normpath(filename)
        base = os.path.abspath(skill_dir)
        try:
            if os.path.commonpath([candidate, base]) == base and os.path.isfile(candidate):
                try:
                    with open(candidate, "r", encoding="utf-8") as f:
                        return f.read()
                except OSError as e:
                    return f"无法读取 {filename}: {e}"
        except ValueError:
            pass

    # 3d. 仅提供文件名 → 递归搜索 skill_dir
    basename = os.path.basename(filename)
    matches = _recursive_find(skill_dir, basename)
    if len(matches) == 1:
        try:
            with open(matches[0], "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            return f"无法读取 {basename}: {e}"
    elif len(matches) > 1:
        return (
            f"在 Skill '{name}' 下找到多个名为 '{basename}' 的文件，请使用更精确的路径：\n"
            + "\n".join(f"  {os.path.relpath(m, skill_dir)}" for m in matches)
        )

    # 兜底：未找到
    all_files = []
    for root, _, files in os.walk(skill_dir):
        for fn in files:
            all_files.append(os.path.relpath(os.path.join(root, fn), skill_dir))
    file_list = "\n".join(f"  {f}" for f in all_files[:50]) or "  (空)"
    if len(all_files) > 50:
        file_list += f"\n  ...（共 {len(all_files)} 个文件）"
    return (
        f"在 Skill '{name}' 下未找到 '{filename}'。\n"
        f"Skill 目录内可用文件：\n{file_list}"
    )


# ---------- Skill 创建（createSkill 工具实现） ----------

_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$|^[a-z0-9]$")


def _validate_skill_name(name):
    """校验 Skill 名称：小写字母、数字、连字符，非空，非首尾连字符。

    返回 (normalized_name, None) 或 (None, error_message)。
    """
    if not name or not name.strip():
        return None, "Skill 名称不能为空"
    # 规范化：trim + 小写
    normalized = name.strip().lower()
    if not _SKILL_NAME_RE.match(normalized):
        return None, (
            f"Skill 名称 '{name}' 不符合规范：只能包含小写字母、数字和连字符（-），"
            f"且不能以连字符开头或结尾。例如：code-review、api-doc、my-skill-1"
        )
    return normalized, None


def _ensure_skill_md_context(name, skill_context):
    """确保 skill_context 包含合法的 YAML Frontmatter（name + description）。

    如果 LLM 提供的 skill_context 没有 frontmatter 或缺少字段，自动补齐。
    返回最终要写入 SKILL.md 的完整文本。
    """
    if not skill_context or not skill_context.strip():
        # 完全没有内容，自动生成最小骨架
        return (
            "---\n"
            f"name: {name}\n"
            "description: 待补充的 Skill 描述\n"
            "---\n\n"
            "# Skill 说明\n\n"
            "请在此处补充 Skill 的完整规则和步骤。\n"
        )

    if skill_context.startswith("---"):
        fm = _parse_frontmatter(skill_context)
        if fm:
            needs_patch = False
            if not fm.get("name"):
                fm["name"] = name
                needs_patch = True
            if not fm.get("description"):
                fm["description"] = "待补充的 Skill 描述"
                needs_patch = True
            if not needs_patch:
                return skill_context
            # 需要补齐 —— 重建 frontmatter + 保留 body
            body = _extract_body(skill_context)
            parts = ["---"]
            for k, v in fm.items():
                parts.append(f"{k}: {v}")
            parts.append("---")
            return "\n".join(parts) + "\n\n" + body.lstrip("\n")

    # 没有 frontmatter —— 自动加
    return (
        "---\n"
        f"name: {name}\n"
        "description: 待补充的 Skill 描述\n"
        "---\n\n"
        + skill_context.lstrip("\n")
    )


def create_skill_file(project_root, name, skill_context):
    """createSkill 工具核心实现。

    在 <project_root>/.agents/skills/<name>/ 下创建 SKILL.md。

    返回: (message, skill_dir_or_None)
        message: str，结果描述（成功/错误）
        skill_dir: str | None，成功时返回新创建的 skill 目录路径，供上层刷新上下文
    """
    normalized, err = _validate_skill_name(name)
    if err:
        return err, None

    skills_dir = os.path.join(project_root, ".agents", "skills")
    skill_dir = os.path.join(skills_dir, normalized)
    skill_md = os.path.join(skill_dir, "SKILL.md")

    # 冲突检测
    if os.path.exists(skill_md):
        return (
            f"Skill '{normalized}' 已存在（{skill_md}）。"
            f"如需覆盖，请先手动删除原目录，或使用不同的名称。"
        ), None

    if os.path.isdir(skill_dir) and not os.path.exists(skill_md):
        # 目录存在但没有 SKILL.md（残留/半成品），允许继续
        pass

    # 准备内容
    content = _ensure_skill_md_context(normalized, skill_context)

    try:
        os.makedirs(skill_dir, exist_ok=True)
        with open(skill_md, "w", encoding="utf-8") as f:
            f.write(content)
    except OSError as e:
        return f"创建 Skill 失败：{e}", None

    return (
        f"✓ Skill '{normalized}' 创建成功：\n"
        f"  目录: {skill_dir}\n"
        f"  文件: {skill_md}\n"
        f"  注意: 如需添加 references/、scripts/ 等子目录或其他辅助文件，"
        f"请继续调用 createDir / createFile / editFile 等文件操作工具完成。"
    ), skill_dir
