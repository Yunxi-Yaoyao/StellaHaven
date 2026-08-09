from uuid import uuid4

import pytest


@pytest.fixture
def workspace_id(client):
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "搜索测试"
    }).json()
    ws = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "搜索测试工作区"
    }).json()
    return ws["id"]


def make_doc(client, workspace_id, title, content):
    return client.post("/documents/", json={
        "title": title,
        "file_path": f"/notes/{uuid4().hex[:8]}.md",
        "workspace_id": workspace_id,
        "content": content,
    })


def test_search_by_title(client, workspace_id):
    """标题命中"""
    doc = make_doc(client, workspace_id, "搬家采买清单", "拖把洗衣液").json()

    r = client.get(f"/documents/search?q=搬家&workspace_id={workspace_id}")
    assert r.status_code == 200
    assert doc["id"] in {d["id"] for d in r.json()}


def test_search_by_content(client, workspace_id):
    """正文命中（标题不含关键词）"""
    doc = make_doc(client, workspace_id, "随便什么标题", "旋转拖把真的好用").json()

    r = client.get(f"/documents/search?q=旋转拖把&workspace_id={workspace_id}")
    assert doc["id"] in {d["id"] for d in r.json()}


def test_search_chinese_substring(client, workspace_id):
    """中文子串：连续中文里的一段也能命中（pg_trgm 三字元的意义）"""
    doc = make_doc(client, workspace_id, "日记", "今天晚饭吃了青椒肉丝面还喝了一杯冰美式").json()

    r = client.get(f"/documents/search?q=青椒肉丝&workspace_id={workspace_id}")
    assert doc["id"] in {d["id"] for d in r.json()}


def test_search_no_match(client, workspace_id):
    """无命中 → 空列表不是报错"""
    make_doc(client, workspace_id, "正常文档", "正常内容")

    r = client.get(f"/documents/search?q=绝不存在的关键词xyz&workspace_id={workspace_id}")
    assert r.status_code == 200
    assert r.json() == []


def test_search_excludes_trash(client, workspace_id):
    """回收站里的不被搜到"""
    doc = make_doc(client, workspace_id, "待删除的秘密", "秘密内容").json()
    client.delete(f"/documents/{doc['id']}")

    r = client.get(f"/documents/search?q=秘密&workspace_id={workspace_id}")
    assert doc["id"] not in {d["id"] for d in r.json()}


def test_search_scoped_to_workspace(client, workspace_id):
    """别的 workspace 的文档不被搜到"""
    # 另一个 workspace 里的文档
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "别人"
    }).json()
    other_ws = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "别人的工作区"
    }).json()
    other_doc = make_doc(client, other_ws["id"], "隔空关键词文档", "隔空内容").json()

    r = client.get(f"/documents/search?q=隔空&workspace_id={workspace_id}")
    assert other_doc["id"] not in {d["id"] for d in r.json()}
