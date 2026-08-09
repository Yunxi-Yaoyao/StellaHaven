from uuid import uuid4


def test_create_user(client):
    """创建 user → 201 + 字段正确 + 自动生成 UUID"""
    username = f"user_{uuid4().hex[:8]}"  # 唯一，避免跨测试残留撞 unique
    response = client.post("/users/", json={
        "username": username,
        "display_name": "测试用户"
    })
    assert response.status_code == 201
    data = response.json()
    assert data["username"] == username
    assert data["display_name"] == "测试用户"
    assert "id" in data


def test_get_user(client):
    """创建后能按 id 读回来"""
    username = f"user_{uuid4().hex[:8]}"
    created = client.post("/users/", json={
        "username": username, "display_name": "读取测试"
    }).json()

    response = client.get(f"/users/{created['id']}")
    assert response.status_code == 200
    assert response.json()["username"] == username


def test_list_users(client):
    """列表接口能查到刚创建的用户"""
    username = f"user_{uuid4().hex[:8]}"
    client.post("/users/", json={"username": username, "display_name": "列表测试"})

    response = client.get("/users/?limit=100")
    assert response.status_code == 200
    usernames = {u["username"] for u in response.json()}
    assert username in usernames
