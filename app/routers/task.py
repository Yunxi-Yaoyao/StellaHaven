"""任务域路由：打流/MTR/命令 发起（前端，登录）+ agent 轮询领取/回传（token）。"""
import os

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.routers.auth import current_user
from app.repositories import node as node_repo
from app.schemas.monitor import (
    IperfTaskCreate, IperfTaskRead, MtrTaskCreate, MtrTaskRead, CommandCreate, CommandRead,
    ComponentInstallCreate, ComponentTaskRead,
)
from app.services import task as task_svc
from app.services import node as node_svc

# 前端发起：登录鉴权
router = APIRouter(dependencies=[Depends(current_user)], tags=["tasks"])


@router.get("/iperf-tasks", response_model=list[IperfTaskRead])
def list_iperf(user: User = Depends(current_user), db: Session = Depends(get_db)):
    tasks = task_svc.list_iperf(db)
    # 列表不扛实时进度数组（每秒一个点、最多 100 条任务，5s 轮询扛全量是浪费）；
    # 实时曲线走单任务详情的 ?progress_after= 增量拉取
    for t in tasks:
        t.progress_json = None
    return tasks


@router.get("/iperf-tasks/{task_id}", response_model=IperfTaskRead)
def get_iperf(task_id: int, progress_after: int | None = None,
              user: User = Depends(current_user), db: Session = Depends(get_db)):
    """单任务详情。progress_after=N 时 progress_json 只返回第 N 点之后的增量
    （append-only，按下标切片稳定），前端实时曲线 1s 轮询不用每次扛全量。"""
    t = task_svc.get_iperf(db, task_id)
    if t is None:
        raise HTTPException(404, "任务不存在")
    if progress_after is not None and t.progress_json:
        t.progress_json = t.progress_json[progress_after:]
    return t


@router.post("/iperf-tasks/{task_id}/cancel")
def cancel_iperf(task_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """中止打流任务（前端中止按钮）。agent 检测到 cancelled 后 terminate iperf3 进程。"""
    t = task_svc.cancel_iperf(db, task_id)
    if t is None:
        raise HTTPException(404, "任务不存在")
    return {"ok": True}


@router.post("/iperf-tasks", response_model=IperfTaskRead, status_code=201)
def create_iperf(data: IperfTaskCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return task_svc.create_iperf(db, data.server_node_id, data.client_node_id,
                                     data.mode, data.direction, data.duration, data.parallel,
                                     data.udp, data.bitrate, data.port, data.window,
                                     data.length, data.omit, data.zerocopy, data.bytes,
                                     data.speedtest_server)
    except ValueError as e:
        raise HTTPException(409, str(e))


@router.get("/mtr-tasks", response_model=list[MtrTaskRead])
def list_mtr(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return task_svc.list_mtr(db)


@router.post("/mtr-tasks", response_model=MtrTaskRead, status_code=201)
def create_mtr(data: MtrTaskCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return task_svc.create_mtr(db, data.node_id, data.target, data.protocol)


@router.get("/commands", response_model=list[CommandRead])
def list_commands(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return task_svc.list_commands(db)


@router.post("/commands", response_model=CommandRead, status_code=201)
def create_command(data: CommandCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return task_svc.create_command(db, data.node_id, data.command)


@router.get("/component-installs", response_model=list[ComponentTaskRead])
def list_components(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return task_svc.list_components(db)


@router.post("/component-installs", response_model=ComponentTaskRead, status_code=201)
def install_component(data: ComponentInstallCreate, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        return task_svc.install_component(db, data.node_id, data.component)
    except ValueError as e:
        raise HTTPException(400, str(e))


# agent 轮询/回传：token 鉴权
agent_task_router = APIRouter(prefix="/agent", tags=["agent"])


@agent_task_router.get("/tasks")
def poll_tasks(token: str, db: Session = Depends(get_db)):
    """agent 拉待办任务（领取 pending → running）。"""
    try:
        return task_svc.poll_tasks(db, token)
    except ValueError:
        raise HTTPException(401, "无效的 agent token")


@agent_task_router.get("/iperf-tasks/{task_id}/status")
def get_iperf_status(task_id: int, token: str, db: Session = Depends(get_db)):
    """agent 查询打流任务状态（用于检测是否被中止，cancelled 则 terminate iperf3 进程）。"""
    node = node_repo.get_by_token(db, token)
    if node is None:
        raise HTTPException(401, "无效的 agent token")
    t = task_svc.get_iperf(db, task_id)
    if t is None:
        raise HTTPException(404, "任务不存在")
    return {"status": t.status}


@agent_task_router.post("/iperf-tasks/{task_id}/result")
def finish_iperf(task_id: int, token: str, status: str, result_json: dict, db: Session = Depends(get_db)):
    """agent 回传打流结果。status: done / failed"""
    task_svc.finish_iperf(db, task_id, status, result_json)
    return {"ok": True}


@agent_task_router.post("/iperf-tasks/{task_id}/progress")
def iperf_progress(task_id: int, token: str, ts: str, bitrate: float = 0,
                   lost_pct: float | None = None, jitter_ms: float | None = None,
                   role: str = "client",
                   retry: bool = False, attempt: int = 0, reason: str = "",
                   note: str | None = None,
                   db: Session = Depends(get_db)):
    """agent 回传实时打流进度点（每秒一个）。role=client 是发送端（吞吐），
    role=server 是接收端（UDP 正向时带真实丢包/抖动）。
    retry=True 是重试事件（前端显示「xx原因，重试第x次」，不画进吞吐曲线）。
    note 是阶段提示点（speedtest 选服务器/测速阶段等，bitrate=0 占位，前端只显示文字不画图）。"""
    point = {"ts": ts, "bitrate": bitrate, "role": role}
    if note:
        point["note"] = note
    if lost_pct is not None:
        point["lost_pct"] = lost_pct
    if jitter_ms is not None:
        point["jitter_ms"] = jitter_ms
    if retry:
        point["retry"] = True
        point["attempt"] = attempt
        point["reason"] = reason
    task_svc.append_iperf_progress(db, task_id, point)
    return {"ok": True}


@agent_task_router.post("/component-installs/{task_id}/result")
def finish_component(task_id: int, token: str, status: str, error: str = "", db: Session = Depends(get_db)):
    """agent 回传组件安装结果。status: done / failed"""
    task_svc.finish_component(db, task_id, status, error)
    return {"ok": True}


@agent_task_router.post("/net-tasks/{task_id}/result")
def finish_net_task(task_id: int, token: str, status: str, result_json: dict | None = None,
                    db: Session = Depends(get_db)):
    """agent 回传网络操作任务结果（改 IP 回退 / 防火墙修改）。status: done / failed"""
    task_svc.finish_net_task(db, task_id, status, result_json)
    return {"ok": True}


@agent_task_router.get("/component/speedtest-go")
def download_speedtest_go(token: str, db: Session = Depends(get_db)):
    """agent 代装 speedtest-go 时，GitHub 直链被限流（404）则从后端下载预置二进制兜底。"""
    node = node_repo.get_by_token(db, token)
    if node is None:
        raise HTTPException(401, "无效的 agent token")
    path = "/opt/stella-agent/bin/speedtest-go"
    if not os.path.exists(path):
        raise HTTPException(404, "后端未预置 speedtest-go")
    return FileResponse(path, filename="speedtest-go")


@agent_task_router.post("/mtr-tasks/{task_id}/result")
def finish_mtr(task_id: int, token: str, status: str, result_json: dict, db: Session = Depends(get_db)):
    task_svc.finish_mtr(db, task_id, status, result_json)
    return {"ok": True}


@agent_task_router.post("/commands/{cmd_id}/result")
def finish_command(cmd_id: int, token: str, status: str, stdout: str = "", stderr: str = "",
                   exit_code: int = 0, db: Session = Depends(get_db)):
    task_svc.finish_command(db, cmd_id, status, stdout, stderr, exit_code)
    return {"ok": True}


@agent_task_router.post("/uninstall/result")
def finish_uninstall(token: str, status: str, error: str = "", db: Session = Depends(get_db)):
    """agent 回传卸载结果。status: done / failed"""
    node_svc.finish_uninstall(db, token, status, error)
    return {"ok": True}
