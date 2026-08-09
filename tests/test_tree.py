"""层级树相关：循环防护 / 级联删除 / 级联还原 / 最近查看"""
from uuid import uuid4

import pytest


@pytest.fixture
def ws(client):
    user = client.post("/users/", json={
        "username": f"user_{uuid4().hex[:8]}", "display_name": "树测试"
    }).json()
    w = client.post("/workspaces/", json={
        "user_id": user["id"], "name": "树测试工作区"
    }).json()
    return w["id"]


def make_doc(client, ws, title, parent_id=None):
    payload = {
        "title": title,
        "file_path": f"/notes/{uuid4().hex[:8]}.md",
        "workspace_id": ws,
        "content": title,
    }
    if parent_id:
        payload["parent_id"] = parent_id
    return client.post("/documents/", json=payload).json()


def test_circular_parent_rejected(client, ws):
    """A 挂到 B 下面，B 再想挂到 A 下面 → 409（循环防护）"""
    a = make_doc(client, ws, "页面A")
    b = make_doc(client, ws, "页面B", parent_id=a["id"])

    r = client.put(f"/documents/{a['id']}", json={
        "updated_at": a["updated_at"],
        "parent_id": b["id"],
    })
    assert r.status_code == 409
    assert "自己或它的子页面" in str(r.json()["detail"])


def test_cascade_delete_takes_children(client, ws):
    """级联删除：父进回收站，下挂一起进"""
    parent = make_doc(client, ws, "父页面")
    child = make_doc(client, ws, "子页面", parent_id=parent["id"])
    grandchild = make_doc(client, ws, "孙页面", parent_id=child["id"])

    client.delete(f"/documents/{parent['id']}?cascade=true")

    assert client.get(f"/documents/{parent['id']}").status_code == 404
    assert client.get(f"/documents/{child['id']}").status_code == 404
    assert client.get(f"/documents/{grandchild['id']}").status_code == 404


def test_non_cascade_delete_promotes_children(client, ws):
    """仅删此篇：子页上移一级（挂到爷爷下）"""
    grandpa = make_doc(client, ws, "爷爷")
    parent = make_doc(client, ws, "父页面", parent_id=grandpa["id"])
    child = make_doc(client, ws, "子页面", parent_id=parent["id"])

    client.delete(f"/documents/{parent['id']}?cascade=false")

    assert client.get(f"/documents/{parent['id']}").status_code == 404
    c = client.get(f"/documents/{child['id']}").json()
    assert c["parent_id"] == grandpa["id"]  # 上移成功


def test_restore_reattaches_to_root(client, ws):
    """还原时父页面还在回收站 → 挂回根级 + reattached 标记"""
    parent = make_doc(client, ws, "父页面")
    child = make_doc(client, ws, "子页面", parent_id=parent["id"])

    # 只删父（子页上移根级），再单独把子页也删了，然后还原子页…
    # 直接构造：级联删除父子，然后单独还原子页（父还在回收站）
    client.delete(f"/documents/{parent['id']}?cascade=true")
    r = client.post(f"/documents/{child['id']}/restore")
    body = r.json()
    assert body["reattached"] is True
    assert body["doc"]["parent_id"] is None  # 挂回根级


def test_restore_cascade_brings_family_back(client, ws):
    """级联还原：父页面回来，下挂全部回来"""
    parent = make_doc(client, ws, "父页面")
    child = make_doc(client, ws, "子页面", parent_id=parent["id"])
    grandchild = make_doc(client, ws, "孙页面", parent_id=child["id"])

    client.delete(f"/documents/{parent['id']}?cascade=true")
    r = client.post(f"/documents/{parent['id']}/restore?cascade=true")
    body = r.json()
    assert body["restored"] == 3

    assert client.get(f"/documents/{child['id']}").status_code == 200
    assert client.get(f"/documents/{grandchild['id']}").status_code == 200
    # 家族结构还在
    assert client.get(f"/documents/{child['id']}").json()["parent_id"] == parent["id"]


def test_recent_view(client, ws):
    """最近查看：打开过的页面出现在 /recent，按查看时间倒序"""
    a = make_doc(client, ws, "先看的")
    b = make_doc(client, ws, "后看的")

    client.get(f"/documents/{a['id']}")
    client.get(f"/documents/{b['id']}")

    recent = client.get(f"/documents/recent?workspace_id={ws}").json()
    ids = [d["id"] for d in recent]
    assert ids[0] == b["id"]  # 后看的排第一
    assert a["id"] in ids


def test_wikilink_sync_and_backlinks(client, ws):
    """双链：保存带 [[标题]] 的正文 → 自动建链；目标页能查到反链"""
    target = make_doc(client, ws, "瓷砖选购")
    source = make_doc(client, ws, "装修日志")

    r = client.put(f"/documents/{source['id']}", json={
        "updated_at": source["updated_at"],
        "content": "今天定了 [[瓷砖选购]] 的方案，还提了 [[不存在的页面]]",
    })
    assert r.status_code == 200

    # 出链：只有解析成功的一条
    links = client.get(f"/document-links/?doc_id={source['id']}").json()
    outgoing = [l for l in links if l["source_id"] == source["id"]]
    assert len(outgoing) == 1
    assert outgoing[0]["target_id"] == target["id"]
    assert outgoing[0]["link_type"] == "wiki"

    # 反链
    backlinks = client.get(f"/documents/{target['id']}/backlinks").json()
    assert [b["id"] for b in backlinks] == [source["id"]]

    # 改掉正文去掉链接 → 出链清空
    src = client.get(f"/documents/{source['id']}").json()
    client.put(f"/documents/{source['id']}", json={
        "updated_at": src["updated_at"], "content": "没链接了",
    })
    links2 = client.get(f"/document-links/?doc_id={source['id']}").json()
    assert [l for l in links2 if l["source_id"] == source["id"]] == []
