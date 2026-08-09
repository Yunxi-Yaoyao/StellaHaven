from datetime import datetime
from uuid import UUID

# 内存字典
editors: dict[UUID, dict[UUID, dict]] = {}


def join(doc_id: UUID, user_id: UUID, device: str, display_name: str) -> None:
    """有人打开文档进入编辑"""
    if doc_id not in editors:
        editors[doc_id] = {}

    now = datetime.now()
    editors[doc_id][user_id] = {
        "device": device,
        "display_name": display_name,
        "status": "editing",
        "started_at": now,
        "last_input_at": now,
    }


def leave(doc_id: UUID, user_id: UUID) -> None:
    """有人关闭文档"""
    if doc_id in editors and user_id in editors[doc_id]:
        del editors[doc_id][user_id]
        if not editors[doc_id]:
            del editors[doc_id]


def mark_input(doc_id: UUID, user_id: UUID) -> None:
    """用户有输入 → 重置空闲，状态变回 editing"""
    if doc_id in editors and user_id in editors[doc_id]:
        editors[doc_id][user_id]["last_input_at"] = datetime.now()
        editors[doc_id][user_id]["status"] = "editing"


def mark_idle(doc_id: UUID, user_id: UUID) -> None:
    """前端通知：5 分钟没输入了"""
    if doc_id in editors and user_id in editors[doc_id]:
        editors[doc_id][user_id]["status"] = "idle"


def mark_auto_save(doc_id: UUID, user_id: UUID) -> None:
    """前端通知：自动保存了"""
    if doc_id in editors and user_id in editors[doc_id]:
        editors[doc_id][user_id]["status"] = "idle"


def get_presence(doc_id: UUID) -> list[dict]:
    """返回当前这篇文档的所有活跃用户"""
    if doc_id not in editors:
        return []
    result = []
    for user_id, info in editors[doc_id].items():
        result.append({
            "user_id": str(user_id),
            **{k: v.isoformat() if isinstance(v, datetime) else v for k, v in info.items()},
        })
    return result


def count_active(doc_id: UUID) -> int:
    """有几个用户正在编辑（非 idle）"""
    if doc_id not in editors:
        return 0
    return sum(1 for info in editors[doc_id].values() if info["status"] == "editing")
