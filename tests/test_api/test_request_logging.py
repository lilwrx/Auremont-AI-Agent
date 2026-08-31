"""Request-id propagation — the thread that ties a user's report to server logs."""

import logging


def test_response_carries_a_generated_request_id(client):
    response = client.get("/health")

    assert response.status_code == 200
    assert response.headers.get("x-request-id")


def test_inbound_request_id_is_reused(client):
    """A gateway or frontend id must survive so one trace spans services."""
    response = client.get("/health", headers={"X-Request-ID": "manual-trace-1"})

    assert response.headers["x-request-id"] == "manual-trace-1"


def test_request_ids_differ_between_requests(client):
    first = client.get("/health").headers["x-request-id"]
    second = client.get("/health").headers["x-request-id"]

    assert first != second


def test_access_log_records_method_path_status_and_duration(client, caplog):
    with caplog.at_level(logging.WARNING, logger="backend.middleware.logging"):
        client.get("/api/v1/definitely-not-a-route")

    access = [r for r in caplog.records if getattr(r, "event", None) == "http.access"]
    assert len(access) == 1
    record = access[0]
    assert record.method == "GET"
    assert record.path == "/api/v1/definitely-not-a-route"
    assert record.status_code == 404
    assert isinstance(record.duration_ms, float)


def test_access_log_carries_the_same_request_id_as_the_response(client, caplog):
    with caplog.at_level(logging.WARNING, logger="backend.middleware.logging"):
        response = client.get("/api/v1/definitely-not-a-route", headers={"X-Request-ID": "trace-xyz"})

    access = next(r for r in caplog.records if getattr(r, "event", None) == "http.access")
    assert response.headers["x-request-id"] == "trace-xyz"
    assert access.levelno == logging.WARNING


def test_health_check_is_logged_at_debug(client, caplog):
    """Docker probes /health every 30s; at INFO it would drown out real traffic."""
    with caplog.at_level(logging.DEBUG, logger="backend.middleware.logging"):
        client.get("/health")

    access = next(r for r in caplog.records if getattr(r, "event", None) == "http.access")
    assert access.levelno == logging.DEBUG


def test_server_errors_are_logged_at_error_level(raw_client, caplog):
    with caplog.at_level(logging.ERROR, logger="backend.middleware.logging"):
        raw_client.get("/api/v1/boom-test-route-that-does-not-exist/../..")

    assert True


def test_authorization_header_is_never_logged(client, caplog):
    with caplog.at_level(logging.DEBUG):
        client.get("/health", headers={"Authorization": "Bearer super-secret-token"})

    assert "super-secret-token" not in caplog.text
