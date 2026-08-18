"""图库（Immich）服务：容器状态探测 + 启停管理。

Immich 由 /opt/immich docker compose 部署（server/postgres/redis/machine_learning 四容器），
Stella 只管理主容器 immich_server 的启停——不负责安装/卸载（compose 部署归宿主管）。
"""
from docker.errors import NotFound

from app.services.drive import detect_docker, _client

IMMICH_CONTAINER = "immich_server"


def get_status() -> dict:
    """docker 环境 + immich_server 容器状态。"""
    docker_info = detect_docker()
    container_exists = False
    container_running = False
    container_status = None
    if docker_info["running"]:
        try:
            ct = _client().containers.get(IMMICH_CONTAINER)
            container_exists = True
            container_status = ct.status
            container_running = ct.status == "running"
        except NotFound:
            pass
        except Exception:
            pass
    return {
        "docker": docker_info,
        "container_exists": container_exists,
        "container_running": container_running,
        "container_status": container_status,
    }


def start_container() -> dict:
    _client().containers.get(IMMICH_CONTAINER).start()
    return get_status()


def stop_container() -> dict:
    _client().containers.get(IMMICH_CONTAINER).stop()
    return get_status()


def restart_container() -> dict:
    _client().containers.get(IMMICH_CONTAINER).restart()
    return get_status()
