import pytest
from fastapi.testclient import TestClient

from org import db
from org.seed.build import load


@pytest.fixture(scope="session")
def client():
    db.reset_engine()
    db.get_engine(memory=True)
    load()
    from org.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def _reset_between_tests(client):
    """Every test starts from the snapshot."""
    yield
    load()
