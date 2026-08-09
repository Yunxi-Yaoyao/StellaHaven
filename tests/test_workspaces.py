from uuid import uuid4

from app.models.user import User


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
    assert data["user_id"] == str(user.id)
    assert "id" in data  # 后端自动生成 UUID


def test_list_workspaces(client, db_session):
    """列出 user 的所有 workspace → 验证能查到刚创建的"""

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


def test_delete_workspace_empty_ok(client, db_session):
    """空工作区可删"""
    user = User(id=uuid4(), username=f"u{uuid4().hex[:6]}", display_name="删区测试")
    db_session.add(user)
    db_session.commit()
    ws = client.post("/workspaces/", json={"user_id": str(user.id), "name": "空区"}).json()

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
