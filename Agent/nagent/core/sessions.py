"""会话保存/加载/列表。

会话以 JSON 格式保存到 <project_root>/<sessions_dir>/<id>.json，
包含 messages 历史 + agent 元信息（mode, context_window, created_at, compact_history）。
"""
import json
import os
import glob
import shutil
from datetime import datetime
from typing import List, Optional, Tuple


def sessions_dir(project_root: str, sessions_dir_rel: str) -> str:
    d = os.path.join(project_root, sessions_dir_rel)
    os.makedirs(d, exist_ok=True)
    return d


def _session_path(project_root: str, sessions_dir_rel: str, session_id: str) -> str:
    return os.path.join(sessions_dir(project_root, sessions_dir_rel), f"{session_id}.json")


def save_session(project_root: str, sessions_dir_rel: str, session_id: str,
                 messages: list, agent_meta: dict) -> str:
    """保存会话。session_id 不存在则自动生成。返回实际 ID。"""
    if not session_id:
        session_id = datetime.now().strftime("%Y%m%d-%H%M%S")
    data = {
        "session_id": session_id,
        "saved_at": datetime.now().isoformat(timespec="seconds"),
        "messages": messages,
        "agent": agent_meta,
    }
    path = _session_path(project_root, sessions_dir_rel, session_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return session_id


def load_session(project_root: str, sessions_dir_rel: str, session_id: str) -> Optional[dict]:
    """加载会话，返回完整 dict（含 messages + agent meta）。失败返回 None。"""
    path = _session_path(project_root, sessions_dir_rel, session_id)
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def list_sessions(project_root: str, sessions_dir_rel: str) -> List[Tuple[str, dict]]:
    """列出所有会话。返回 [(session_id, meta_dict), ...]，按 saved_at 倒序。"""
    d = sessions_dir(project_root, sessions_dir_rel)
    files = glob.glob(os.path.join(d, "*.json"))
    results = []
    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            sid = data.get("session_id") or os.path.splitext(os.path.basename(fpath))[0]
            meta = {
                "saved_at": data.get("saved_at", "?"),
                "message_count": len(data.get("messages", [])),
                "agent_mode": (data.get("agent") or {}).get("mode", "?"),
                "first_user": _first_user_text(data.get("messages", [])),
            }
            results.append((sid, meta))
        except (OSError, json.JSONDecodeError):
            # 损坏的文件跳过
            pass
    results.sort(key=lambda x: x[1].get("saved_at", ""), reverse=True)
    return results


def delete_session(project_root: str, sessions_dir_rel: str, session_id: str) -> bool:
    path = _session_path(project_root, sessions_dir_rel, session_id)
    if os.path.isfile(path):
        try:
            os.remove(path)
            return True
        except OSError:
            pass
    return False


def _first_user_text(messages: list) -> str:
    for m in messages:
        if m.get("role") == "user":
            c = m.get("content", "")
            if isinstance(c, str):
                return c[:40].replace("\n", " ")
    return "(无用户消息)"
