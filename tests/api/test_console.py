from brain_api.main import create_app
from fastapi.testclient import TestClient


def test_console_static_mount_serves_app() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/console/")

    assert response.status_code == 200
    assert "Juno Brain Console" in response.text


def test_root_redirects_to_console() -> None:
    app = create_app()

    with TestClient(app) as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/console/"
