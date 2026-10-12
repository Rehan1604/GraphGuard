def acct(id="A1", **kw):
    return {"id": id, "name": "Alice", "account_type": "individual", **kw}


def test_create_and_get_account(client):
    r = client.post("/api/accounts", json=acct())
    assert r.status_code == 201
    assert client.get("/api/accounts/A1").json()["name"] == "Alice"
    assert len(client.get("/api/accounts").json()) == 1


def test_duplicate_account_conflicts(client):
    client.post("/api/accounts", json=acct())
    assert client.post("/api/accounts", json=acct()).status_code == 409


def test_missing_account_is_404(client):
    assert client.get("/api/accounts/NOPE").status_code == 404


def test_invalid_account_payloads_rejected(client):
    assert client.post("/api/accounts", json=acct(id="bad id!")).status_code == 422
    assert client.post("/api/accounts", json=acct(account_type="alien")).status_code == 422
    assert client.post("/api/accounts", json=acct(name="")).status_code == 422