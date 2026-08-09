import pytest
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
    """TestClient 用测试 session 替代真实数据库——不启动 uvicorn 也能调 API"""

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()
