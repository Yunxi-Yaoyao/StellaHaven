from uuid import UUID
import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.editing import editors, join, leave, mark_input, mark_idle, mark_auto_save, get_presence, count_active

router = APIRouter()

# 连接池
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
    for ws, _ in connections[doc_id]:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    for ws in dead:
        connections[doc_id] = [(w, u) for w, u in connections[doc_id] if w is not ws]
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
    user_id: UUID = Query(...),
    device: str = Query("unknown"),
    display_name: str = Query("云曦"),
):
    global _worker_started
    await ws.accept()

    # 启动通知处理器（只启动一次）
    if not _worker_started:
        _worker_started = True
        asyncio.create_task(_process_notifications())

    # 加入编辑 + 登记连接
    join(doc_id, user_id, device, display_name)
    if doc_id not in connections:
        connections[doc_id] = []
    connections[doc_id].append((ws, user_id))

    # 广播给所有人
    await broadcast(doc_id, {"type": "presence", "editors": get_presence(doc_id)})

    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue

            msg_type = data.get("type")

            if msg_type == "input":
                mark_input(doc_id, user_id)
            elif msg_type == "idle":
                mark_idle(doc_id, user_id)
            elif msg_type == "auto_save":
                mark_auto_save(doc_id, user_id)
            elif msg_type == "leave":
                break

            await broadcast(doc_id, {"type": "presence", "editors": get_presence(doc_id)})

    except WebSocketDisconnect:
        pass
    finally:
        if doc_id in connections:
            connections[doc_id] = [(w, u) for w, u in connections[doc_id] if w is not ws]
            if not connections[doc_id]:
                del connections[doc_id]
        leave(doc_id, user_id)
        await broadcast(doc_id, {"type": "presence", "editors": get_presence(doc_id)})
