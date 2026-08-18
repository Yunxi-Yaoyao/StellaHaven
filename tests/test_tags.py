from uuid import uuid4


def test_create_tag(client):
    """创建 tag → 201 + 字段正确"""
    name = f"tag_{uuid4().hex[:8]}"  # name 有 unique 约束，每次生成新的
    response = client.post("/tags/", json={"name": name, "color": "#ff0000"})
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == name
    assert data["color"] == "#ff0000"
    assert "id" in data
    assert "user_id" in data  # 归属当前用户


def test_create_tag_color_optional(client):
    """color 可选，不传应为 null"""
    name = f"tag_{uuid4().hex[:8]}"
    response = client.post("/tags/", json={"name": name})
    assert response.status_code == 201
    assert response.json()["color"] is None


def test_get_tag(client):
    """创建后能按 id 读回来"""
    name = f"tag_{uuid4().hex[:8]}"
    created = client.post("/tags/", json={"name": name}).json()

    response = client.get(f"/tags/{created['id']}")
    assert response.status_code == 200
    assert response.json()["name"] == name


def test_list_tags(client):
    """列表接口能查到刚创建的标签"""
    name = f"tag_{uuid4().hex[:8]}"
    client.post("/tags/", json={"name": name})

    response = client.get("/tags/?limit=200")
    assert response.status_code == 200
    names = {t["name"] for t in response.json()}
    assert name in names


def test_list_tags_scoped_to_user(client, db_session):
    """列表只出当前用户的标签，不泄露别人的"""
    from app.models.user import User
    from app.security import hash_password
    from app.services.tag import create_tag
    from app.schemas.tag import TagCreate

    # 当前 client 登录的是 conftest 随机用户 A；A 建一个标签
    mine = client.post("/tags/", json={"name": f"mine_{uuid4().hex[:8]}"}).json()

    # 另一个用户 B（直接 ORM 造，不进注册通道）
    b = User(username=f"b_{uuid4().hex[:8]}", display_name="隔离测试B",
             password_hash=hash_password("x"), is_admin=False)
    db_session.add(b)
    db_session.flush()
    # B 也有自己的标签（归属 B）
    btag = create_tag(db_session, TagCreate(name=f"b_{uuid4().hex[:8]}", user_id=b.id))

    # A 的列表里应该有自己的标签，但没有 B 的
    listed = client.get("/tags/?limit=200").json()
    ids = {t["id"] for t in listed}
    assert mine["id"] in ids
    assert str(btag.id) not in ids


def test_get_tag_scoped_to_user(client, db_session):
    """读别人的标签 → 404（不暴露存在性）"""
    from app.models.user import User
    from app.security import hash_password
    from app.services.tag import create_tag
    from app.schemas.tag import TagCreate

    b = User(username=f"b_{uuid4().hex[:8]}", display_name="隔离测试B",
             password_hash=hash_password("x"), is_admin=False)
    db_session.add(b)
    db_session.flush()
    btag = create_tag(db_session, TagCreate(name=f"b_{uuid4().hex[:8]}", user_id=b.id))

    r = client.get(f"/tags/{btag.id}")
    assert r.status_code == 404
