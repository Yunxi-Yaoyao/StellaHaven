from uuid import uuid4

from app.models.user import User


def _name() -> str:
    return f"u_{uuid4().hex[:8]}"


def test_create_workspace(client, db_session):
    """创建 workspace → 验证返回 201 和字段正确"""

    # 先手动建一个 user（workspace 需要 FK 指向它）
    user = User(id=uuid4(), username="testuser", display_name="测试用户")
    db_session.add(user)
    db_session.commit()

    # POST 创建 workspace
    response = client.post("/workspaces/", json={
        "user_id": str(user.id),
        "name": "我的工作区",
        "description": "测试用"
    })

    # 断言
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "我的工作区"
    assert data["description"] == "测试用"
    # 数据隔离后：workspace 永远归属当前登录用户（忽略传入的 user_id）
    me = client.get("/auth/me").json()
    assert data["user_id"] == me["id"]
    assert "id" in data  # 后端自动生成 UUID


def test_showcase_seeded_on_create(client):
    """新工作区自动种「样式展示厅」示例笔记"""
    client.post("/workspaces/", json={"user_id": str(uuid4()), "name": "种籽测试区"})
    me = client.get("/auth/me").json()
    wss = client.get("/workspaces/").json()
    ws = next(w for w in wss if w["name"] == "种籽测试区")
    docs = client.get(f"/documents/?workspace_id={ws['id']}").json()
    assert any(d["title"] == "🎨 Stella 样式展示厅" for d in docs)


def test_cross_user_isolation(client, db_session):
    """数据隔离：别人的工作区 404（不暴露存在性）、列表只出自己的"""
    from app.models.workspace import Workspace

    # 造一个别人的工作区（直接 ORM，归属别的用户）
    other = User(id=uuid4(), username=_name(), display_name="别人", password_hash="x")
    db_session.add(other)
    db_session.flush()
    ws = Workspace(user_id=other.id, name="别人的区", description="")
    db_session.add(ws)
    db_session.flush()

    # 直接访问别人的区 → 404
    r = client.get(f"/workspaces/{ws.id}")
    assert r.status_code == 404
    # 列表里不出现
    rows = client.get("/workspaces/").json()
    assert all(row["id"] != str(ws.id) for row in rows)


def test_list_workspaces(client, db_session):
    """列出当前用户的所有 workspace → 验证能查到刚创建的"""
    user = User(id=uuid4(), username="testuser2", display_name="测试用户2")
    db_session.add(user)
    db_session.commit()

    # 先创建两个 workspace
    client.post("/workspaces/", json={"user_id": str(user.id), "name": "工作区A"})
    client.post("/workspaces/", json={"user_id": str(user.id), "name": "工作区B"})

    # 列出来
    response = client.get(f"/workspaces/?user_id={user.id}")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    names = {ws["name"] for ws in data}
    assert names == {"工作区A", "工作区B"}


def test_rename_workspace(client, db_session):
    """重命名工作区"""
    user = User(id=uuid4(), username=f"u{uuid4().hex[:6]}", display_name="改名测试")
    db_session.add(user)
    db_session.commit()
    ws = client.post("/workspaces/", json={"user_id": str(user.id), "name": "旧名字"}).json()

    r = client.put(f"/workspaces/{ws['id']}?name=新名字")
    assert r.status_code == 200
    assert r.json()["name"] == "新名字"


def _purge_seed(client, ws_id):
    """测试助手：清掉自动种的展示厅笔记（软删+清回收站），让工作区回到真空"""
    docs = client.get(f"/documents/?workspace_id={ws_id}").json()
    for d in docs:
        if d["title"] == "🎨 Stella 样式展示厅":
            client.delete(f"/documents/{d['id']}")
    client.post("/documents/trash/empty", params={"workspace_id": ws_id})


def test_delete_workspace_empty_ok(client, db_session):
    """空工作区可删"""
    user = User(id=uuid4(), username=f"u{uuid4().hex[:6]}", display_name="删区测试")
    db_session.add(user)
    db_session.commit()
    ws = client.post("/workspaces/", json={"user_id": str(user.id), "name": "空区"}).json()
    _purge_seed(client, ws["id"])  # 自动种的展示厅先清掉，才是真空区

    assert client.delete(f"/workspaces/{ws['id']}").status_code == 204


def test_delete_workspace_not_empty_blocked(client, db_session):
    """有笔记的工作区 → 409 不给删"""
    user = User(id=uuid4(), username=f"u{uuid4().hex[:6]}", display_name="非空测试")
    db_session.add(user)
    db_session.commit()
    ws = client.post("/workspaces/", json={"user_id": str(user.id), "name": "有货的区"}).json()
    client.post("/documents/", json={
        "title": "一篇", "file_path": "/x.md", "workspace_id": ws["id"], "content": "",
    })

    r = client.delete(f"/workspaces/{ws['id']}")
    assert r.status_code == 409


def test_delete_workspace_with_notes_force(client, db_session):
    """老婆 8.10 定稿：有笔记的工作区，force=true 连笔记一起永久删"""
    user = User(id=uuid4(), username=f"u{uuid4().hex[:6]}", display_name="强删测试")
    db_session.add(user)
    db_session.commit()
    ws = client.post("/workspaces/", json={"user_id": str(user.id), "name": "有货硬删区"}).json()
    doc = client.post("/documents/", json={
        "title": "陪葬笔记", "file_path": "/x.md", "workspace_id": ws["id"], "content": "",
    }).json()

    assert client.delete(f"/workspaces/{ws['id']}").status_code == 409  # 不 force → 拦
    assert client.delete(f"/workspaces/{ws['id']}?force=true").status_code == 204  # force → 连锅端
    assert client.get(f"/documents/{doc['id']}").status_code == 404


def test_delete_workspace_trash_only(client, db_session):
    """只有回收站有货：不 force → 409 has_trash；force=true → 连回收站一起永久删"""
    user = User(id=uuid4(), username=f"u{uuid4().hex[:6]}", display_name="回收站区测试")
    db_session.add(user)
    db_session.commit()
    ws = client.post("/workspaces/", json={"user_id": str(user.id), "name": "只有回收站的区"}).json()
    _purge_seed(client, ws["id"])
    doc = client.post("/documents/", json={
        "title": "垃圾", "file_path": "/t.md", "workspace_id": ws["id"], "content": "",
    }).json()
    client.delete(f"/documents/{doc['id']}")  # 进回收站

    r = client.delete(f"/workspaces/{ws['id']}")
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "has_trash"

    r2 = client.delete(f"/workspaces/{ws['id']}?force=true")
    assert r2.status_code == 204
    # 回收站内容也物理清了
    assert client.get(f"/documents/{doc['id']}").status_code == 404


def test_empty_trash(client, db_session):
    """一键清空回收站：全部物理删除，返回清了几篇"""
    user = User(id=uuid4(), username=f"u{uuid4().hex[:6]}", display_name="清空测试")
    db_session.add(user)
    db_session.commit()
    ws = client.post("/workspaces/", json={"user_id": str(user.id), "name": "清空区"}).json()

    ids = []
    for i in range(3):
        d = client.post("/documents/", json={
            "title": f"垃圾{i}", "file_path": f"/t{i}.md", "workspace_id": ws["id"], "content": "",
        }).json()
        client.delete(f"/documents/{d['id']}")
        ids.append(d["id"])
    # 留一篇正常的，不能被误伤
    keep = client.post("/documents/", json={
        "title": "正常的", "file_path": "/keep.md", "workspace_id": ws["id"], "content": "",
    }).json()

    r = client.post(f"/documents/trash/empty?workspace_id={ws['id']}")
    assert r.status_code == 200
    assert r.json()["purged"] == 3

    assert client.get(f"/documents/trash?workspace_id={ws['id']}").json() == []
    for i in ids:
        assert client.get(f"/documents/{i}").status_code == 404
    assert client.get(f"/documents/{keep['id']}").status_code == 200  # 正常的还在


def test_clear_all_docs(client, db_session):
    """清空笔记：全部进回收站（可还原），层级保留，返回篇数"""
    user = User(id=uuid4(), username=f"u{uuid4().hex[:6]}", display_name="清空笔记测试")
    db_session.add(user)
    db_session.commit()
    ws = client.post("/workspaces/", json={"user_id": str(user.id), "name": "待清区"}).json()
    _purge_seed(client, ws["id"])  # 清掉自动种的展示厅

    parent = client.post("/documents/", json={
        "title": "父", "file_path": "/p.md", "workspace_id": ws["id"], "content": "",
    }).json()
    child = client.post("/documents/", json={
        "title": "子", "file_path": "/c.md", "workspace_id": ws["id"], "content": "",
        "parent_id": parent["id"],
    }).json()

    r = client.post(f"/documents/clear-all?workspace_id={ws['id']}")
    assert r.status_code == 200
    assert r.json()["trashed"] == 2

    # 都进回收站了，层级还在
    assert client.get(f"/documents/?workspace_id={ws['id']}").json() == []
    trash = client.get(f"/documents/trash?workspace_id={ws['id']}").json()
    assert len(trash) == 2
    # 级联还原能整体回来
    rr = client.post(f"/documents/{parent['id']}/restore?cascade=true")
    assert rr.json()["restored"] == 2
    assert client.get(f"/documents/{child['id']}").json()["parent_id"] == parent["id"]
