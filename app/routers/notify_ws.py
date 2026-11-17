"""全局通知 WebSocket：铃铛实时推送（asyncio.Queue 模式，见 references/websocket-notify-pattern）。

- 同步代码（告警评估在同步路由线程池里跑）只管 put_nowait；
- 后台协程从队列取消息广播给所有已登录连接；
- 通知本体已落库（notifications 表），WS 只负责「即时弹出」，断了重连靠未读数接口补齐。
"""
import asyncio

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from starlette.requests import Request
from fastapi import HTTPException

from app.database import get_db
from app.routers.auth import current_user

router = APIRouter()

_clients: set[WebSocket] = set()
_queue: asyncio.Queue = asyncio.Queue(maxsize=1000)
_worker_started = False


def push_notification_sync(payload: dict) -> None:
    """线程安全：同步上下文（告警评估）只管塞队列。"""
    try:
        _queue.put_nowait(payload)
    except asyncio.QueueFull:
        pass


async def _process() -> None:
    while True:
        payload = await _queue.get()
        dead = []
        for ws in list(_clients):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            _clients.discard(ws)


async def _authorize(ws: WebSocket, db: Session) -> bool:
    try:
        db.expire_all()
        # Validation is a read, not activity/refresh: never extend last_seen.
        current_user(Request({**ws.scope, "type": "http"}), db)
        db.rollback()
        return True
    except HTTPException:
        db.rollback()
        await ws.close(code=1008)
        return False


@router.websocket("/ws/notifications")
async def notifications_ws(ws: WebSocket, db: Session = Depends(get_db)):
    global _worker_started
    if not await _authorize(ws, db):
        return
    await ws.accept()
    if not _worker_started:
        _worker_started = True
        asyncio.create_task(_process())
    _clients.add(ws)
    try:
        while True:
            try:
                message = await asyncio.wait_for(ws.receive(), timeout=15)
                if message["type"] == "websocket.disconnect":
                    break
            except asyncio.TimeoutError:
                pass
            if not await _authorize(ws, db):
                break
    except WebSocketDisconnect:
        pass
    finally:
        _clients.discard(ws)
