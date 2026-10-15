from fastapi.testclient import TestClient

from backend.app.main import app


def test_health() -> None:
    client = TestClient(app)
    response = client.get("/health").json()
    assert response["status"] == "ok"
    assert response["service"] == "cola-ai-backend"


def test_websocket_streams_simulation(monkeypatch) -> None:
    monkeypatch.setenv("COLA_SIMULATION_DELAY_MS", "0")
    client = TestClient(app)
    with client.websocket_connect("/ws") as websocket:
        websocket.send_json({"type": "session.start"})
        websocket.send_json({"type": "simulation.start"})
        events = [websocket.receive_json() for _ in range(5)]
    assert [event["type"] for event in events] == [
        "session.started", "question.detected", "answer.started", "answer.delta", "answer.delta"
    ]
    assert events[1]["simulated"] is True
