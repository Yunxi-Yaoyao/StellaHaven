"""Doc-tag HTTP contracts on real ORM/business code, memory-only SQLite.

Run alone with --noconftest and PYTEST_DISABLE_PLUGIN_AUTOLOAD=1. Package
initializers and authentication transport are replaced; ownership helpers are
AST-loaded unchanged. Never import production main/database/config.
"""
import ast
import importlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import JSON, create_engine, event, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def env():
    saved = {k: v for k, v in sys.modules.items() if k == "app" or k.startswith("app.")}
    saved_attrs = {k: dict(vars(v)) for k, v in saved.items()}
    for name in saved:
        sys.modules.pop(name)
    engine = None
    try:
        # Empty package shells avoid eager imports of unrelated application code.
        for name in ("app", "app.models", "app.schemas", "app.repositories", "app.services", "app.routers"):
            module = ModuleType(name)
            module.__path__ = [str(ROOT / name.replace(".", "/"))]
            sys.modules[name] = module
            if "." in name:
                parent, child = name.rsplit(".", 1)
                setattr(sys.modules[parent], child, module)

        class Base(DeclarativeBase):
            pass

        models = sys.modules["app.models"]
        for name, value in dict(Base=Base, Mapped=Mapped, mapped_column=mapped_column, UUID=UUID, uuid4=uuid4).items():
            setattr(models, name, value)
        database = ModuleType("app.database")
        database.Base = Base
        sys.modules["app.database"] = database
        sys.modules["app"].database = database

        User = importlib.import_module("app.models.user").User
        Workspace = importlib.import_module("app.models.workspace").Workspace
        Document = importlib.import_module("app.models.document").Document
        Tag = importlib.import_module("app.models.tag").Tag
        DocTag = importlib.import_module("app.models.doc_tag").DocTag
        Document.__table__.c.frontmatter.type = JSON()
        engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(engine)
        with Session(engine) as db:
            own, foreign = uuid4(), uuid4()
            ws, other_ws = uuid4(), uuid4()
            doc, other_doc, tag, other_tag = (uuid4() for _ in range(4))
            db.add_all([User(id=own, username="owner", display_name="owner"), User(id=foreign, username="foreign", display_name="foreign")])
            db.commit()
            db.add_all([Workspace(id=ws, user_id=own, name="own"), Workspace(id=other_ws, user_id=foreign, name="foreign")])
            db.commit()
            db.add_all([Document(id=doc, workspace_id=ws, title="own", file_path="own", content_hash="x"), Document(id=other_doc, workspace_id=other_ws, title="foreign", file_path="foreign", content_hash="y"), Tag(id=tag, user_id=own, name="own"), Tag(id=other_tag, user_id=foreign, name="foreign")])
            db.commit()
            principal = db.get(User, own)

            def get_db():
                yield db

            def current_user():
                return principal

            database.get_db = get_db
            auth = ModuleType("app.routers.auth")
            auth.__dict__.update(Session=Session, UUID=UUID, User=User, HTTPException=HTTPException, current_user=current_user)
            tree = ast.parse((ROOT / "app/routers/auth.py").read_text())
            helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in {"require_doc_owner", "require_ws_owner"}]
            assert len(helpers) == 2
            exec(compile(ast.Module(body=helpers, type_ignores=[]), "auth-owner-helpers", "exec"), auth.__dict__)
            sys.modules[auth.__name__] = auth
            sys.modules["app.routers"].auth = auth
            router = importlib.import_module("app.routers.doc_tag")
            app = FastAPI()
            app.include_router(router.router)
            statements = []
            pg_inserts = []

            @event.listens_for(engine, "before_execute")
            def compile_postgres(_connection, clause, _multiparams, _params, _options):
                if getattr(clause, "is_insert", False):
                    pg_inserts.append(str(clause.compile(dialect=postgresql.dialect())))

            @event.listens_for(engine, "before_cursor_execute")
            def record_sql(_connection, _cursor, statement, _parameters, _context, _many):
                statements.append(statement)

            def snapshot():
                return (
                    tuple(sorted((str(row.doc_id), str(row.tag_id)) for row in db.scalars(select(DocTag)))),
                    tuple(sorted(str(row.id) for row in db.scalars(select(Tag)))),
                )

            with TestClient(app, raise_server_exceptions=False) as client:
                yield SimpleNamespace(db=db, client=client, doc=doc, other_doc=other_doc, tag=tag, other_tag=other_tag, own=own, foreign=foreign, DocTag=DocTag, Tag=Tag, Document=Document, statements=statements, pg_inserts=pg_inserts, snapshot=snapshot)
    finally:
        if engine is not None:
            engine.dispose()
        for name in list(sys.modules):
            if name == "app" or name.startswith("app."):
                sys.modules.pop(name)
        sys.modules.update(saved)
        for name, attrs in saved_attrs.items():
            vars(saved[name]).clear()
            vars(saved[name]).update(attrs)


def request(env, method, doc_id, tag_id):
    values = {"doc_id": str(doc_id), "tag_id": str(tag_id)}
    if method == "post":
        return env.client.post("/doc-tags/", json=values)
    return env.client.delete("/doc-tags/", params=values)


@pytest.mark.parametrize("method", ["post", "delete"])
@pytest.mark.parametrize("target", ["foreign_tag", "missing_tag", "foreign_doc", "missing_doc"])
def test_mutations_reject_unowned_or_missing_targets_without_writes(env, method, target):
    doc_id = env.other_doc if target == "foreign_doc" else uuid4() if target == "missing_doc" else env.doc
    tag_id = env.other_tag if target == "foreign_tag" else uuid4() if target == "missing_tag" else env.tag
    before = env.snapshot()
    env.statements.clear()
    response = request(env, method, doc_id, tag_id)
    assert response.status_code == 404, response.text
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in env.statements)
    assert env.snapshot() == before


def test_repeated_binding_is_successful_and_has_one_row(env):
    expected = {"doc_id": str(env.doc), "tag_id": str(env.tag)}
    for _ in range(3):
        response = request(env, "post", env.doc, env.tag)
        assert response.status_code == 201, response.text
        assert response.json() == expected
        assert env.snapshot()[0] == ((str(env.doc), str(env.tag)),)


def test_binding_uses_targeted_database_conflict_handling(env):
    # Require atomic conflict handling, not SELECT-then-INSERT or broad error swallowing.
    response = request(env, "post", env.doc, env.tag)
    assert response.status_code == 201, response.text
    insert_index = next(i for i, sql in enumerate(env.statements) if sql.startswith("INSERT INTO doc_tags"))
    insert_sql = env.statements[insert_index]
    assert "ON CONFLICT (doc_id, tag_id) DO NOTHING" in insert_sql
    assert "ON CONFLICT (doc_id, tag_id) DO NOTHING" in env.pg_inserts[-1]
    assert not any("FROM doc_tags" in sql for sql in env.statements[:insert_index])


def test_non_duplicate_integrity_errors_are_not_swallowed(env):
    repo = importlib.import_module("app.repositories.doc_tag")
    schema = importlib.import_module("app.schemas.doc_tag")
    with pytest.raises(IntegrityError):
        repo.add(env.db, schema.DocTagCreate(doc_id=env.doc, tag_id=uuid4()))
    env.db.rollback()
    assert env.snapshot()[0] == ()


@pytest.mark.parametrize("method", ["post", "delete"])
def test_legacy_foreign_binding_cannot_be_mutated(env, method):
    env.db.add(env.DocTag(doc_id=env.doc, tag_id=env.other_tag))
    env.db.commit()
    before = env.snapshot()
    env.statements.clear()
    response = request(env, method, env.doc, env.other_tag)
    assert response.status_code == 404, response.text
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in env.statements)
    assert env.snapshot() == before


@pytest.mark.parametrize("target", ["foreign", "missing"])
def test_scoped_listing_rejects_unowned_document(env, target):
    response = env.client.get("/doc-tags/", params={"doc_id": str(env.other_doc if target == "foreign" else uuid4())})
    assert response.status_code == 404, response.text


@pytest.mark.parametrize("method", ["post", "delete"])
@pytest.mark.parametrize("field", ["doc_id", "tag_id"])
def test_invalid_uuid_is_422_without_writes(env, method, field):
    values = {"doc_id": str(env.doc), "tag_id": str(env.tag)}
    values[field] = "not-a-uuid"
    before = env.snapshot()
    env.statements.clear()
    if method == "post":
        response = env.client.post("/doc-tags/", json=values)
    else:
        response = env.client.delete("/doc-tags/", params=values)
    assert response.status_code == 422, response.text
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in env.statements)
    assert env.snapshot() == before


def test_retry_after_last_reference_purge_is_404_without_writes(env):
    assert request(env, "post", env.doc, env.tag).status_code == 201
    assert request(env, "delete", env.doc, env.tag).status_code == 204
    before = env.snapshot()
    env.statements.clear()
    response = request(env, "delete", env.doc, env.tag)
    assert response.status_code == 404, response.text
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in env.statements)
    assert env.snapshot() == before


def test_removing_absent_association_preserves_unbound_tag(env):
    before = env.snapshot()
    for _ in range(2):
        response = request(env, "delete", env.doc, env.tag)
        assert response.status_code == 204, response.text
        assert response.content == b""
        assert env.snapshot() == before


@pytest.mark.parametrize("remaining_reference", [False, True])
def test_removing_real_association_only_purges_orphans(env, remaining_reference):
    env.db.add(env.DocTag(doc_id=env.doc, tag_id=env.tag))
    if remaining_reference:
        env.db.add(env.DocTag(doc_id=env.other_doc, tag_id=env.tag))
    env.db.commit()
    response = request(env, "delete", env.doc, env.tag)
    assert response.status_code == 204, response.text
    env.db.expire_all()
    assert env.db.get(env.DocTag, (env.doc, env.tag)) is None
    assert (env.db.get(env.Tag, env.tag) is not None) == remaining_reference
    assert env.db.get(env.Tag, env.other_tag) is not None


def test_deleted_document_cannot_gain_tags(env):
    from datetime import datetime
    env.db.get(env.Document, env.doc).deleted_at = datetime(2026, 1, 1)
    env.db.commit()
    before = env.snapshot()
    env.statements.clear()
    response = request(env, "post", env.doc, env.tag)
    assert response.status_code == 404, response.text
    assert not any(sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for sql in env.statements)
    assert env.snapshot() == before


@pytest.mark.parametrize("scoped", [False, True])
def test_listing_hides_legacy_cross_owner_tags(env, scoped):
    env.db.add_all([
        env.DocTag(doc_id=env.doc, tag_id=env.tag),
        env.DocTag(doc_id=env.doc, tag_id=env.other_tag),
        env.DocTag(doc_id=env.other_doc, tag_id=env.tag),
        env.DocTag(doc_id=env.other_doc, tag_id=env.other_tag),
    ])
    env.db.commit()
    before = env.snapshot()
    response = env.client.get("/doc-tags/", params={"doc_id": str(env.doc)} if scoped else {})
    assert response.status_code == 200, response.text
    assert response.json() == [{"doc_id": str(env.doc), "tag_id": str(env.tag)}]
    assert env.snapshot() == before
