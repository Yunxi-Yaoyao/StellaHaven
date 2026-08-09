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
