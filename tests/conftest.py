import pytest
from uuid import uuid4
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from main import app

# ============================================================
# 1. 测试数据库引擎（SQLite 内存模式——飞快 + 自动隔离）
# ============================================================

from app.config import settings
from urllib.parse import quote_plus

TEST_DATABASE_URL = settings.database_url.replace(
    "/stella", "/stella_test"
)

engine = create_engine(TEST_DATABASE_URL)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False)


@pytest.fixture(scope="session")
def test_db():
    """整个测试会话共享：建一次表，后面所有测试复用结构"""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


# ============================================================
# 2. 每个测试独立的数据库 session（自动回滚）
# ============================================================

@pytest.fixture
def db_session(test_db):
    """每个测试函数一个独立 session，测完自动回滚——不互相污染"""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


# ============================================================
# 3. FastAPI TestClient（注入测试 session）
# ============================================================

@pytest.fixture
def client(db_session):
    """TestClient 用测试 session 替代真实数据库——不启动 uvicorn 也能调 API。
    路由已接入登录保护：每个测试的 client 自动注册一个随机用户（登录态）"""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        # 直接 ORM 建号（注册通道初始化后就关了，不能走 /auth/register）+ 登录拿 cookie
        from app.models.user import User
        from app.security import hash_password

        username = f"test_{uuid4().hex[:10]}"
        u = User(username=username, display_name=username,
                 password_hash=hash_password("testpass123"), is_admin=True)
        db_session.add(u)
        db_session.flush()
        c.post("/auth/login", json={"username": username, "password": "testpass123"})
        yield c

    app.dependency_overrides.clear()
