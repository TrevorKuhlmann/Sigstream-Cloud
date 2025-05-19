import json
from fastapi import status

def test_register_and_login(client):
    # 1) register
    resp = client.post("/register", json={
        "email": "alice@example.com",
        "password": "supersecret",
        "customer_name": "Alice Co."
    })
    assert resp.status_code == 200
    assert "user_id" in resp.json()

    # 2) login
    resp = client.post(
        "/token",
        data={"username": "alice@example.com", "password": "supersecret"},
        headers={"Content-Type": "application/x-www-form-urlencoded"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert "access_token" in body

    # Save token for later
    token = body["access_token"]
    return token

def test_data_and_summary_and_claim(client):
    token = test_register_and_login(client)

    headers = {"Authorization": f"Bearer {token}"}

    # 3) POST /data for device "dev1"
    payload = {"device_id": "dev1", "data": "42", "timestamp": 1}
    resp = client.post("/data", json=payload, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"status": "success"}

    # 4) summary should now include our record
    resp = client.get("/summary", headers=headers)
    assert resp.status_code == 200
    html = resp.text
    assert "dev1" in html and "42" in html

    # 5) /claim-device JSON claim
    resp = client.post("/claim-device", json={"device_id": "dev1"}, headers=headers)
    assert resp.status_code == 200
    assert "claimed by user" in resp.json()["message"]

    # 6) summary with filter
    resp = client.get("/summary?device_id=dev1", headers=headers)
    assert resp.status_code == 200
    assert "dev1" in resp.text

def test_dashboard_and_export(client):
    token = test_register_and_login(client)
    headers = {"Authorization": f"Bearer {token}"}

    # dashboard (HTML)
    resp = client.get("/dashboard", headers=headers)
    assert resp.status_code == 200
    assert "<table" in resp.text

    # export CSV for all devices
    resp = client.get("/export", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    text = resp.text.splitlines()
    # first line is header
    assert text[0] == "ID,Device ID,Data,Timestamp"
