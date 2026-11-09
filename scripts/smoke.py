"""Exercise real Cerbos + LiteLLM through the public API. Uses disposable POC records.

No key or cookie is printed. Created assets are archived and keys revoked on completion.
"""
import os
from uuid import uuid4

import httpx

BASE_URL = os.environ.get("BASE_URL", "http://localhost:5173")
client = httpx.Client(base_url=BASE_URL, headers={"X-Requested-With": "ai-cerbos"}, timeout=60)
suffix = uuid4().hex[:6]
asset_id = key_id = None
key_ids = []


def call(method, path, body=None, expected=200, **kwargs):
    result = client.request(method, path, json=body, **kwargs)
    if result.status_code != expected:
        raise RuntimeError(f"{method} {path}: expected {expected}, received {result.status_code}: {result.text[:400]}")
    return result.json()


def login(user):
    call("POST", "/api/session", {"user_id": user})


try:
    login("alex")
    asset = call("POST", "/api/assets", {"name": f"Gateway verification {suffix}", "description": "Disposable end-to-end governance verification agent.", "kind": "agent", "department_id": "technology", "visibility": "private", "budget": "1"}, expected=201)
    asset_id = asset["id"]
    registration = next(a for a in call("GET", "/api/state")["approvals"] if a["resource_id"] == asset_id)
    login("jordan")
    call("POST", f"/api/approvals/{registration['id']}/decision", {"decision": "approve", "note": "Approve disposable integration verification"})
    login("alex")
    call("POST", "/api/key-requests", {"asset_id": asset_id, "name": f"Verification key {suffix}", "budget": "0.001", "rpm": 30, "tpm": 20000, "days": 1, "reason": "Verify hard budget enforcement without paid AI calls."}, expected=201)
    request = next(a for a in call("GET", "/api/state")["approvals"] if a["resource_id"] == asset_id and a["kind"] == "key")
    login("sam")
    call("POST", f"/api/approvals/{request['id']}/decision", {"decision": "approve", "note": "Approve tightly bounded demonstration key"})
    login("alex")
    key = next(k for k in call("GET", "/api/state")["keys"] if k["asset_id"] == asset_id)
    key_id = key["id"]
    key_ids.append(key_id)
    # Display names may repeat; LiteLLM's internal aliases must not collide.
    call("POST", "/api/key-requests", {"asset_id": asset_id, "name": key["name"], "budget": "0.001", "rpm": 30, "tpm": 20000, "days": 1, "reason": "Verify duplicate display names use distinct upstream aliases."}, expected=201)
    duplicate_request = next(a for a in call("GET", "/api/state")["approvals"] if a["resource_id"] == asset_id and a["kind"] == "key" and a["status"] == "pending")
    login("sam")
    call("POST", f"/api/approvals/{duplicate_request['id']}/decision", {"decision": "approve", "note": "Approve a second key with the same display name"})
    login("alex")
    duplicate_key = next(k for k in call("GET", "/api/state")["keys"] if k["asset_id"] == asset_id and k["id"] != key_id)
    key_ids.append(duplicate_key["id"])
    assert duplicate_key["name"] == key["name"]
    token = call("POST", f"/api/keys/{key_id}/claim")["key"]
    call("POST", f"/api/keys/{key_id}/claim", expected=409)
    body = {"model": "governed-demo", "messages": [{"role": "user", "content": "Hello"}], "max_tokens": 10}
    headers = {"Authorization": f"Bearer {token}", "Idempotency-Key": str(uuid4())}
    result = call("POST", "/v1/chat/completions", body, headers=headers)
    repeated = call("POST", "/v1/chat/completions", body, headers=headers)
    assert result == repeated
    call("POST", "/v1/chat/completions", body, headers={**headers, "Idempotency-Key": str(uuid4())}, expected=429)
    call("POST", f"/api/keys/{key_id}/revoke")
    call("POST", "/v1/chat/completions", body, headers={**headers, "Idempotency-Key": str(uuid4())}, expected=401)
    # Cerbos inside LiteLLM (cerbos/policies/model.yaml and mcp_tool.yaml): the AI traffic
    # board sends every situation for every demo key as real calls through LiteLLM.
    expected = {
        "standard": {"alex": "answered", "sam": "answered", "riley": "answered"},
        "premium": {"alex": "downgraded", "sam": "answered", "riley": "downgraded"},
        "premium-long": {"alex": "downgraded", "sam": "capped", "riley": "downgraded"},
        "confidential": {"alex": "refused", "sam": "answered", "riley": "refused"},
        "bypass": {"alex": "refused", "sam": "refused", "riley": "refused"},
        "bypass-billed": {"alex": "answered", "sam": "answered", "riley": "answered"},
        "streamed": {"alex": "answered", "sam": "answered", "riley": "answered"},
        "catalog": {"alex": "hidden", "sam": "listed", "riley": "hidden"},
        "mcp-read": {"alex": "called", "sam": "called", "riley": "called"},
        "mcp-write": {"alex": "refused", "sam": "called", "riley": "refused"},
        "mcp-destructive": {"alex": "refused", "sam": "refused", "riley": "refused"},
    }

    def outcomes(board):
        return {
            situation: {owner: board["cells"][f"{situation}:{owner}"]["outcome"] for owner in owners}
            for situation, owners in expected.items()
        }

    # Start from the shipped budgets, whatever was switched in the playground before.
    call("PUT", "/api/playground/team-budget", {"on": False})
    board = call("POST", "/api/playground/traffic")
    assert outcomes(board) == expected, outcomes(board)
    downgraded = board["cells"]["premium:alex"]
    assert downgraded["answered_model"] == "governed-demo", downgraded
    assert downgraded["obligations"] == {"model": "governed-demo"}, downgraded
    assert board["cells"]["premium-long:sam"]["obligations"] == {"max_tokens": 512}
    # A streamed answer is billed by the ledger inside LiteLLM when the stream ends.
    streamed = board["cells"]["streamed:sam"]
    assert streamed["streamed"], streamed
    settle = next(s for s in streamed["steps"] if s["name"] == "Settle actual cost")
    assert settle["status"] == "ok", streamed["steps"]
    # A one-click policy change is live within seconds and flips exactly the expected cell.
    call("PUT", "/api/playground/presets/hr-confidential", {"on": True})
    changed = outcomes(call("POST", "/api/playground/traffic"))
    assert changed["confidential"]["riley"] == "answered", changed
    call("PUT", "/api/playground/presets/hr-confidential", {"on": False})
    assert outcomes(call("POST", "/api/playground/traffic")) == expected
    # Budgets are enforced inside LiteLLM: once People Operations has spent its team cap,
    # Riley's model calls are refused, through the gateway and straight to LiteLLM alike.
    call("PUT", "/api/playground/team-budget", {"on": True})
    try:
        spent = outcomes(call("POST", "/api/playground/traffic"))
        for situation in ("standard", "premium", "premium-long", "bypass-billed", "streamed"):
            assert spent[situation]["riley"] == "over_budget", spent
            assert spent[situation]["alex"] == expected[situation]["alex"], spent
        assert spent["confidential"]["riley"] == "refused", spent  # Cerbos decides first.
    finally:
        call("PUT", "/api/playground/team-budget", {"on": False})
    # The ledger API is internal: the public web server does not expose it.
    exposed = client.post("/internal/ledger/reserve", json={})
    assert "reservation_id" not in exposed.text and exposed.status_code != 200, exposed.status_code
    # Metrics read Cerbos's own decision log: LiteLLM's checks arrive tagged by source.
    login("morgan")
    metrics = call("GET", "/api/metrics?window=1h")
    cerbos = metrics["cerbos"]
    assert cerbos["available"], cerbos
    litellm = next(s for s in cerbos["sources"] if s["source"] == "litellm")
    assert litellm["decisions"] > 0, cerbos["sources"]
    assert cerbos["litellm"]["outcomes"]["downgraded"] > 0, cerbos["litellm"]
    ledger = metrics["ledger"]["summary"]
    assert ledger["saved_micros"] > 0, ledger
    # Calls sent straight to LiteLLM are billed by the ledger inside LiteLLM.
    assert ledger["direct_requests"] > 0, ledger
    print("PASS: registration → scoped approval → two real LiteLLM keys with the same display name → one-time reveal → completion → idempotent replay → hard budget rejection → revocation → Cerbos inside LiteLLM: 33-call traffic board, with a streamed answer (obligations, data classification with gateway bypass, filtered model catalog, MCP tool authorization), a live policy change, budgets enforced inside LiteLLM even when the gateway is skipped, and metrics read from Cerbos's own decision log.")
finally:
    login("alex")
    for issued_key_id in key_ids:
        call("POST", f"/api/keys/{issued_key_id}/revoke")
    if asset_id:
        call("DELETE", f"/api/assets/{asset_id}")
    client.close()
