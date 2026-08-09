from uuid import UUID
import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.document import save_draft

router = APIRouter()

# 连接池：doc_id -> [WebSocket]，只用于 doc_saved 广播
connections: dict = {}

# 通知队列（线程安全——同步路由函数往这里推消息）
_notification_queue: asyncio.Queue = asyncio.Queue()

_worker_started = False


def notify_sync(doc_id: UUID, message: dict):
    """线程安全：从任何地方（同步/异步）推消息到队列"""
    try:
        _notification_queue.put_nowait((doc_id, message))
    except asyncio.QueueFull:
        pass


async def broadcast(doc_id: UUID, message: dict):
    """给这篇文档的所有连接群发消息"""
    if doc_id not in connections:
        return
    dead = []
    for ws in connections[doc_id]:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connections[doc_id] = [w for w in connections[doc_id] if w is not ws]
    if not connections[doc_id]:
        del connections[doc_id]


async def _process_notifications():
    """后台无限循环：处理队列里的通知消息"""
    while True:
        doc_id, message = await _notification_queue.get()
        await broadcast(doc_id, message)


@router.websocket("/ws/{doc_id}")
async def document_ws(
    ws: WebSocket,
    doc_id: UUID,
    device: str = Query("unknown"),
    db: Session = Depends(get_db),
):
    """草稿上行管道：浏览器 debounce 后发 type:"draft" → 覆写草稿槽。

    设计要点：
    - 没有 presence 状态机——「谁在编辑」由草稿槽的 draft_device + draft_updated_at 回答
    - 手动保存后其他设备靠 doc_saved 广播感知（notify_sync → 队列 → broadcast）
    - db 走 get_db 依赖注入：测试能覆写到测试库，不会写穿到开发库
    """
    global _worker_started
    await ws.accept()

    if not _worker_started:
        _worker_started = True
        asyncio.create_task(_process_notifications())

    connections.setdefault(doc_id, []).append(ws)

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if data.get("type") == "draft":
                content = data.get("content")
                if isinstance(content, str):
                    save_draft(db, doc_id, content, device)

    except WebSocketDisconnect:
        pass
    finally:
        if doc_id in connections:
            connections[doc_id] = [w for w in connections[doc_id] if w is not ws]
            if not connections[doc_id]:
                del connections[doc_id]
