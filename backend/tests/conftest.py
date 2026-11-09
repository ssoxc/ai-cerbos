import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.db import Base, SessionLocal, engine
from app.main import app
from app.seed import seed


@pytest.fixture(autouse=True)
def workspace():
    assert "ai_cerbos_test_" in str(engine.url), "Tests require a disposable database"
    with engine.begin() as db:
        names = ", ".join(table.name for table in Base.metadata.sorted_tables)
        db.execute(text(f"TRUNCATE {names} CASCADE"))
    seed()


@pytest.fixture
def client():
    with TestClient(app, headers={"X-Requested-With": "ai-cerbos"}) as client:
        yield client


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def sign_in(client):
    def login(user_id):
        assert client.post("/api/session", json={"user_id": user_id}).status_code == 200

    return login
