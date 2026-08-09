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
