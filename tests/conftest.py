"""全局测试 fixtures"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from platform_mcp.auth.session import SessionManager
from platform_mcp.common.crypto import CryptoUtils


@pytest.fixture
def test_key():
    return CryptoUtils.generate_key()


@pytest.fixture
def crypto(test_key):
    return CryptoUtils(test_key)


@pytest.fixture
def session_manager():
    return SessionManager(ttl=1800)


@pytest.fixture
def admin_user():
    return {"id": 1, "username": "admin", "nickname": "管理员", "role_code": "admin", "status": 1}


@pytest.fixture
def developer_user():
    return {"id": 2, "username": "dev01", "nickname": "开发者", "role_code": "developer", "status": 1}


@pytest.fixture
def admin_session_id(session_manager, admin_user):
    return session_manager.create(
        user_id=admin_user["id"],
        username=admin_user["username"],
        nickname=admin_user["nickname"],
        role_code=admin_user["role_code"],
    )


@pytest.fixture
def developer_session_id(session_manager, developer_user):
    return session_manager.create(
        user_id=developer_user["id"],
        username=developer_user["username"],
        nickname=developer_user["nickname"],
        role_code=developer_user["role_code"],
    )


@pytest.fixture
def mock_db_session():
    session = AsyncMock()
    session.execute = AsyncMock()
    session.get = AsyncMock()
    session.add = MagicMock()
    session.commit = AsyncMock()
    session.flush = AsyncMock()
    session.rollback = AsyncMock()
    return session


@pytest.fixture
def mock_request():
    request = MagicMock()
    request.cookies = {}
    return request


# --- Integration test fixtures (shared across integration/security/performance) ---

@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()
    db.get = AsyncMock(return_value=None)
    db.execute = AsyncMock()
    db.rollback = AsyncMock()

    # Default mock results for execute queries
    mock_scalar_result = MagicMock()
    mock_scalar_result.scalar.return_value = 0
    mock_scalar_result.scalar_one_or_none.return_value = None
    mock_scalar_result.scalars.return_value.all.return_value = []
    db.execute = AsyncMock(return_value=mock_scalar_result)

    return db


@pytest.fixture
async def admin_client(mock_db, admin_user):
    from platform_mcp.main import app
    from platform_mcp.common.database import get_db
    from platform_mcp.auth.middleware import get_current_user

    async def override_db():
        yield mock_db

    async def override_user():
        return admin_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


@pytest.fixture
async def dev_client(mock_db, developer_user):
    from platform_mcp.main import app
    from platform_mcp.common.database import get_db
    from platform_mcp.auth.middleware import get_current_user

    async def override_db():
        yield mock_db

    async def override_user():
        return developer_user

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_current_user] = override_user
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
