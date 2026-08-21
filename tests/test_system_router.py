from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.routers import system


def _client_with_state(**state) -> TestClient:
    app = FastAPI()
    app.include_router(system.router)

    @app.middleware("http")
    async def inject_state(request: Request, call_next):
        for key, value in state.items():
            setattr(request.state, key, value)
        return await call_next(request)

    return TestClient(app)


def test_get_modules_manifest_returns_the_registered_modules():
    manifest = [
        {"name": "bluetooth", "capabilities": ["pairing"], "endpoints": {"devices": "/bluetooth/devices"}},
        {"name": "network", "capabilities": [], "endpoints": {}},
    ]
    client = _client_with_state(modules_manifest=manifest)

    response = client.get("/system/modules")

    assert response.status_code == 200
    assert response.json() == {"modules": manifest}


def test_get_modules_manifest_empty_when_nothing_registered():
    client = _client_with_state(modules_manifest=[])

    response = client.get("/system/modules")

    assert response.status_code == 200
    assert response.json() == {"modules": []}
