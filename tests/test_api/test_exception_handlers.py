"""Error responses are a public contract; these guard both shape and leakage."""

import logging

import pytest
from fastapi import HTTPException

from backend.main import app


@pytest.fixture
def boom_route():
    """Register a route that always explodes, then remove it again."""

    @app.get("/__test__/boom")
    async def _boom():
        raise RuntimeError("secret internal detail: db://user:password@host")

    yield "/__test__/boom"

    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/__test__/boom"]


@pytest.fixture
def teapot_route():
    @app.get("/__test__/teapot")
    async def _teapot():
        raise HTTPException(status_code=418, detail="I am a teapot", headers={"X-Brew": "tea"})

    yield "/__test__/teapot"

    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/__test__/teapot"]


def test_unhandled_error_returns_generic_body(raw_client, boom_route):
    response = raw_client.get(boom_route)

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"


def test_unhandled_error_never_leaks_internals(raw_client, boom_route):
    """Exception text can hold credentials and connection strings."""
    response = raw_client.get(boom_route)

    body = response.text
    assert "secret internal detail" not in body
    assert "password" not in body
    assert "Traceback" not in body


def test_unhandled_error_body_carries_the_request_id(raw_client, boom_route):
    response = raw_client.get(boom_route, headers={"X-Request-ID": "trace-500"})

    assert response.json()["request_id"] == "trace-500"


def test_unhandled_error_is_logged_with_traceback(raw_client, boom_route, caplog):
    with caplog.at_level(logging.ERROR, logger="backend.main"):
        raw_client.get(boom_route)

    record = next(r for r in caplog.records if getattr(r, "event", None) == "http.unhandled_error")
    assert record.exc_info is not None
    assert record.status_code == 500


def test_404_keeps_its_shape(client):
    response = client.get("/api/v1/no-such-route")

    assert response.status_code == 404
    assert response.json() == {"detail": "Not Found"}


def test_http_exception_preserves_custom_headers(client, teapot_route):
    """auth.py relies on WWW-Authenticate surviving; dropping it breaks OAuth2."""
    response = client.get(teapot_route)

    assert response.status_code == 418
    assert response.headers["x-brew"] == "tea"
    assert response.json() == {"detail": "I am a teapot"}


@pytest.fixture
def unauthorized_route():
    """Mirrors the 401 auth.py raises, without needing a live database."""

    @app.get("/__test__/unauthorized")
    async def _unauthorized():
        raise HTTPException(
            status_code=401,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    yield "/__test__/unauthorized"

    app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/__test__/unauthorized"]


def test_401_still_carries_www_authenticate(client, unauthorized_route):
    """Losing this header on 401 breaks the OAuth2 flow the frontend depends on."""
    response = client.get(unauthorized_route)

    assert response.status_code == 401
    assert response.headers.get("www-authenticate") == "Bearer"


def test_validation_error_keeps_fastapi_shape(client):
    response = client.post("/api/v1/auth/login", data={"username": "only-username"})

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert isinstance(detail, list)
    assert detail[0]["loc"]
    assert detail[0]["type"]


def test_validation_log_omits_the_offending_input_value(client, caplog):
    """pydantic v2 puts the bad value in errors(); logging it would leak secrets."""
    with caplog.at_level(logging.WARNING, logger="backend.main"):
        client.post("/api/v1/auth/refresh", json={"wrong_field": "hunter2-secret-value"})

    record = next(r for r in caplog.records if getattr(r, "event", None) == "http.validation_error")
    assert "hunter2-secret-value" not in str(record.errors)
    assert "hunter2-secret-value" not in caplog.text
    assert record.errors[0]["loc"]
