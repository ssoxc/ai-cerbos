"""The story playground tells the truth: every capability, what-if and policy change."""

import shutil

import pytest

from app import policy_store, story
from app.config import settings
from app.models import User

WHAT_IFS = [
    pytest.param(persona, item, id=f"{persona}: {item['id']}")
    for persona, items in story.WHAT_IFS.items()
    for item in items
]


def test_every_persona_has_three_what_ifs_with_known_concepts():
    for persona, items in story.WHAT_IFS.items():
        assert len(items) == 3, persona
        for item in items:
            assert item["concept"] in story.CONCEPTS
            assert set(item["flips"]) <= story.CAPABILITY_IDS
            assert item["flips"] or item["spotlight"], f"{persona}/{item['id']} shows nothing"


@pytest.mark.parametrize(("persona", "item"), WHAT_IFS)
def test_what_if_flips_exactly_what_it_declares(db, persona, item):
    user = db.get(User, persona)
    board = story.capability_board(db, user, {item["id"]})
    flipped = sorted(c["id"] for c in board["capabilities"] if c["changed"])
    assert flipped == item["flips"]
    if item["spotlight"]:
        spotlight = next(c for c in board["capabilities"] if c["id"] == item["spotlight"])
        # A spotlight explains a decision that deliberately did NOT change.
        assert not spotlight["changed"]
        assert spotlight["rule"], "a spotlight must name the rule that holds"


def test_separation_of_duties_holds_for_multi_role_people(db):
    for persona in ("avery", "jordan"):
        board = story.capability_board(db, db.get(User, persona), {"developer"})
        edit = next(c for c in board["capabilities"] if c["id"] == "t-edit")
        assert edit["effect"] == "deny" and edit["rule"] == "admins-cannot-change-assets"


def test_self_approval_survives_any_role(db):
    board = story.capability_board(db, db.get(User, "alex"), {"approver"})
    approve = next(c for c in board["capabilities"] if c["id"] == "t-approve-key")
    assert approve["rule"] == "no-self-approval-or-reopening"


def test_every_capability_is_explained_for_every_persona(db):
    for persona in story.WHAT_IFS:
        board = story.capability_board(db, db.get(User, persona), set())
        assert board["total"] == len(story.CAPABILITIES)
        for capability in board["capabilities"]:
            assert capability["reason"]
            assert capability["rule"] or capability["effect"] == "deny"


def test_board_reports_what_cerbos_looked_at(db):
    board = story.capability_board(db, db.get(User, "jordan"), {"cover-hr"})
    assert board["before"]["departments"] == ["Technology"]
    assert board["after"]["departments"] == ["Technology", "Human Resources"]


def test_board_endpoint_accepts_only_that_personas_what_ifs(client, sign_in):
    sign_in("maya")
    ok = client.post("/api/playground/board", json={"persona_id": "maya", "what_ifs": ["delegate"]})
    assert ok.status_code == 200
    assert ok.json()["allowed"] == ok.json()["baseline_allowed"] + 1
    wrong = client.post(
        "/api/playground/board", json={"persona_id": "maya", "what_ifs": ["cover-hr"]}
    )
    assert wrong.status_code == 422


@pytest.mark.parametrize("preset", story.PRESETS, ids=[p["id"] for p in story.PRESETS])
def test_each_policy_change_applies_once_and_compiles(preset, tmp_path, monkeypatch):
    if not shutil.which("cerbos"):
        pytest.skip("Cerbos CLI not installed")
    shipped = policy_store.read_shipped(preset["policy"])
    assert shipped.count(preset["find"]) == 1
    assert preset["replace"] not in shipped
    live = tmp_path / "live"
    shutil.copytree(settings().shipped_policies_dir, live)
    monkeypatch.setattr(settings(), "policies_dir", str(live))
    report = policy_store.validate(
        {f"{preset['policy']}.yaml": shipped.replace(preset["find"], preset["replace"])}
    )
    assert report.compile_errors == []


def test_presets_report_their_state(client, sign_in):
    sign_in("maya")
    states = client.get("/api/playground/presets").json()
    assert {s["id"] for s in states} == {p["id"] for p in story.PRESETS}
    assert all(s["available"] and not s["on"] for s in states)
