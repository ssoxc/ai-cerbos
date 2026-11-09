"""The live Cerbos policies, editable from the dashboard.

Cerbos reads policies from a directory it watches (`POLICIES_DIR`, a volume shared with
this API). The image also carries the shipped policies (`SHIPPED_POLICIES_DIR`), which are
the baseline for diffs and for "reset". Every edit is:

1. checked to still be a resource policy for the same resource kind;
2. compiled, together with every other live policy and the policy unit tests, by the
   bundled Cerbos CLI. Compile errors block the save; failing policy tests are reported
   as information, because changing behaviour is the point of an edit;
3. written atomically, after which a probe policy's revision is bumped and Cerbos is
   polled until it serves that revision, proving the edit is live. If Cerbos does not
   pick it up in time, the previous text is restored.
"""

import difflib
import hashlib
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import yaml
from sqlalchemy import text

from .config import settings
from .db import SessionLocal

log = logging.getLogger("ai_cerbos.policies")
PROBE_FILE = "ai_cerbos_probe.yaml"
PROBE_KIND = "ai_cerbos_probe"
RECORD_FILE = ".shipped.sha256"  # Not a .yaml file, so Cerbos ignores it.
RELOAD_TIMEOUT_SECONDS = 10.0
LOCK_ID = 918272


class PolicyError(Exception):
    def __init__(self, status: int, message: str, payload: dict | None = None):
        super().__init__(message)
        self.status, self.message, self.payload = status, message, payload or {}


@dataclass
class ValidationReport:
    compile_errors: list[dict] = field(default_factory=list)
    tests_passed: int = 0
    tests_failed: int = 0
    failures: list[dict] = field(default_factory=list)

    def as_dict(self):
        return {
            "compile": {"ok": not self.compile_errors, "errors": self.compile_errors},
            "tests": {
                "passed": self.tests_passed,
                "failed": self.tests_failed,
                "failures": self.failures,
            },
        }


def live_dir() -> Path:
    return Path(settings().policies_dir)


def shipped_dir() -> Path:
    return Path(settings().shipped_policies_dir)


def is_policy_file(path: Path) -> bool:
    return (
        path.suffix == ".yaml" and not path.name.endswith("_test.yaml") and path.name != PROBE_FILE
    )


def policy_ids() -> list[str]:
    """Editable policies are exactly the shipped resource policies."""
    return sorted(p.stem for p in shipped_dir().glob("*.yaml") if is_policy_file(p))


def _path(directory: Path, policy_id: str) -> Path:
    if policy_id not in policy_ids():
        raise PolicyError(404, "Unknown policy")
    return directory / f"{policy_id}.yaml"


def sha(text_value: str) -> str:
    return hashlib.sha256(text_value.encode()).hexdigest()


def read_live(policy_id: str) -> str:
    return _path(live_dir(), policy_id).read_text()


def read_shipped(policy_id: str) -> str:
    return _path(shipped_dir(), policy_id).read_text()


def resource_kind(text_value: str) -> str:
    document = yaml.safe_load(text_value)
    if not isinstance(document, dict) or not isinstance(document.get("resourcePolicy"), dict):
        raise ValueError("Not a Cerbos resource policy")
    return str(document["resourcePolicy"].get("resource", ""))


def diff(policy_id: str) -> str:
    return "".join(
        difflib.unified_diff(
            read_shipped(policy_id).splitlines(keepends=True),
            read_live(policy_id).splitlines(keepends=True),
            fromfile=f"shipped/{policy_id}.yaml",
            tofile=f"live/{policy_id}.yaml",
        )
    )


def summary():
    items = []
    for policy_id in policy_ids():
        live, shipped = read_live(policy_id), read_shipped(policy_id)
        items.append(
            {
                "id": policy_id,
                "file": f"{policy_id}.yaml",
                "kind": resource_kind(shipped),
                "modified": live != shipped,
                "sha": sha(live),
            }
        )
    return items


def document(policy_id: str):
    live = read_live(policy_id)
    return {
        "id": policy_id,
        "file": f"{policy_id}.yaml",
        "yaml": live,
        "shipped_yaml": read_shipped(policy_id),
        "diff": diff(policy_id),
        "sha": sha(live),
        "modified": live != read_shipped(policy_id),
    }


# --- Validation -------------------------------------------------------------------------


def _cerbos_binary() -> str:
    binary = shutil.which("cerbos")
    if not binary:
        raise PolicyError(503, "The Cerbos CLI is not available to validate policies")
    return binary


def _parse_compile_output(stdout: str) -> dict:
    stdout = stdout.strip()
    if not stdout:
        return {}
    try:
        return json.loads(stdout[: stdout.rindex("}") + 1])
    except ValueError:
        return {}


def validate(overrides: dict[str, str]) -> ValidationReport:
    """Compile all live policies with `overrides` applied, and run the policy tests."""
    report = ValidationReport()
    with tempfile.TemporaryDirectory(prefix="cerbos-validate-") as workdir:
        target = Path(workdir) / "policies"
        shutil.copytree(live_dir(), target, ignore=shutil.ignore_patterns(".*", "*.tmp"))
        for name, content in overrides.items():
            (target / name).write_text(content)
        completed = subprocess.run(
            [_cerbos_binary(), "compile", "--output=json", str(target)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    result = _parse_compile_output(completed.stdout)
    if completed.returncode == 3 or "compileErrors" in result:
        for error in (result.get("compileErrors") or {}).get("errors", []):
            position = error.get("position") or {}
            report.compile_errors.append(
                {
                    "file": error.get("file", ""),
                    "line": position.get("line"),
                    "column": position.get("column"),
                    "message": error.get("description") or error.get("error", ""),
                    "context": error.get("context", ""),
                }
            )
        if not report.compile_errors:
            report.compile_errors.append({"file": "", "message": completed.stderr.strip()})
        return report
    if completed.returncode not in (0, 4):
        raise PolicyError(500, f"Cerbos CLI failed: {completed.stderr.strip()[:300]}")
    for suite in result.get("suites", []):
        for case in suite.get("testCases", []):
            for principal in case.get("principals", []):
                for resource in principal.get("resources", []):
                    for action in resource.get("actions", []):
                        details = action.get("details", {})
                        if details.get("result") == "RESULT_PASSED":
                            report.tests_passed += 1
                        elif details.get("result") == "RESULT_FAILED":
                            report.tests_failed += 1
                            failure = details.get("failure", {})
                            report.failures.append(
                                {
                                    "suite": suite.get("name", ""),
                                    "test": case.get("name", ""),
                                    "principal": principal.get("name", ""),
                                    "resource": resource.get("name", ""),
                                    "action": action.get("name", ""),
                                    "expected": failure.get("expected", ""),
                                    "actual": failure.get("actual", ""),
                                }
                            )
    return report


# --- Writing and reload confirmation ------------------------------------------------------


def _write_atomic(path: Path, content: str):
    temporary = path.with_name(path.name + ".tmp")  # .tmp is ignored by Cerbos.
    temporary.write_text(content)
    os.replace(temporary, path)


def _probe_policy(revision: str) -> str:
    return (
        "apiVersion: api.cerbos.dev/v1\n"
        "# Written by the API after every policy change. The API polls Cerbos until this\n"
        "# revision is served, which proves the change is live. Not part of the demo.\n"
        "resourcePolicy:\n"
        "  version: default\n"
        f"  resource: {PROBE_KIND}\n"
        "  rules:\n"
        "    - name: revision\n"
        "      actions: [check]\n"
        "      effect: EFFECT_ALLOW\n"
        '      roles: ["*"]\n'
        "      output:\n"
        "        when:\n"
        f"          ruleActivated: '\"{revision}\"'\n"
    )


def _served_revision(client: httpx.Client) -> str | None:
    response = client.post(
        f"{settings().cerbos_url}/api/check/resources",
        json={
            "requestId": str(uuid.uuid4()),
            "principal": {"id": "probe", "roles": ["probe"]},
            "resources": [{"resource": {"kind": PROBE_KIND, "id": "probe"}, "actions": ["check"]}],
        },
    )
    response.raise_for_status()
    outputs = response.json()["results"][0].get("outputs") or []
    return outputs[0].get("val") if outputs else None


def publish_and_confirm() -> float:
    """Bump the probe and wait until Cerbos serves it. Returns the seconds it took."""
    revision = uuid.uuid4().hex
    _write_atomic(live_dir() / PROBE_FILE, _probe_policy(revision))
    started = time.monotonic()
    with httpx.Client(timeout=3) as client:
        while time.monotonic() - started < RELOAD_TIMEOUT_SECONDS:
            try:
                if _served_revision(client) == revision:
                    return time.monotonic() - started
            except (httpx.HTTPError, ValueError, KeyError, IndexError):
                pass
            time.sleep(0.2)
    raise PolicyError(503, "Cerbos did not load the change in time; it was rolled back")


class _lock:
    """Serialise policy writes across API workers with a Postgres advisory lock."""

    def __enter__(self):
        self.session = SessionLocal()
        self.session.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
        return self

    def __exit__(self, *exc):
        self.session.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
        self.session.close()


def save(policy_id: str, content: str, base_sha: str) -> dict:
    path = _path(live_dir(), policy_id)
    try:
        kind = resource_kind(content)
    except (ValueError, yaml.YAMLError) as error:
        raise PolicyError(
            422,
            "The YAML could not be read as a Cerbos resource policy",
            {"compile": {"ok": False, "errors": [{"file": path.name, "message": str(error)}]}},
        ) from None
    if kind != resource_kind(read_shipped(policy_id)):
        raise PolicyError(
            422, f"This file must stay the policy for '{resource_kind(read_shipped(policy_id))}'"
        )
    with _lock():
        previous = path.read_text()
        if sha(previous) != base_sha:
            raise PolicyError(409, "This policy changed since you opened it. Reload and try again.")
        report = validate({path.name: content})
        if report.compile_errors:
            raise PolicyError(422, "Cerbos could not compile this policy", report.as_dict())
        _write_atomic(path, content)
        try:
            seconds = publish_and_confirm()
        except PolicyError:
            _write_atomic(path, previous)
            publish_and_confirm()
            raise
    return {**report.as_dict(), "reload_seconds": round(seconds, 2), "sha": sha(content)}


def _write_shipped_set():
    target = live_dir()
    target.mkdir(parents=True, exist_ok=True)
    source = shipped_dir()
    for path in source.rglob("*.yaml"):
        destination = target / path.relative_to(source)
        destination.parent.mkdir(parents=True, exist_ok=True)
        _write_atomic(destination, path.read_text())
    # Drop live policy files that no longer ship (never the probe or tests).
    shipped_names = {p.name for p in source.glob("*.yaml")}
    for path in target.glob("*.yaml"):
        if is_policy_file(path) and path.name not in shipped_names:
            path.unlink()
    (target / RECORD_FILE).write_text(_policy_set_digest(source))


def _policy_set_digest(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(p for p in directory.glob("*.yaml") if is_policy_file(p)):
        digest.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return digest.hexdigest()


def reset() -> float:
    with _lock():
        _write_shipped_set()
        return publish_and_confirm()


def sync_on_startup() -> str:
    """Make the live directory consistent with this image, without discarding edits."""
    if live_dir().resolve() == shipped_dir().resolve():
        return "live policies are the shipped files"
    with _lock():
        record = live_dir() / RECORD_FILE
        has_policies = any(is_policy_file(p) for p in live_dir().glob("*.yaml"))
        recorded = record.read_text().strip() if record.exists() else None
        if not has_policies or recorded is None or recorded == _policy_set_digest(live_dir()):
            # Never edited through the dashboard: follow the shipped set of this image.
            _write_shipped_set()
            outcome = "installed the shipped policies"
        else:
            # Edited in the dashboard: keep the edits, refresh the read-only tests.
            for path in shipped_dir().rglob("*.yaml"):
                if not is_policy_file(path) or path.parent != shipped_dir():
                    destination = live_dir() / path.relative_to(shipped_dir())
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    _write_atomic(destination, path.read_text())
            outcome = "kept policies edited in the dashboard"
            if _policy_set_digest(shipped_dir()) != recorded:
                outcome += " (this version ships different defaults; use Reset to adopt them)"
        publish_and_confirm()
    return outcome


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    if sys.argv[1:] == ["sync"]:
        print(f"Cerbos policies: {sync_on_startup()}.")
    elif sys.argv[1:] == ["reset"]:
        print(f"Cerbos policies reset in {reset():.1f}s.")
    else:
        sys.exit("usage: python -m app.policy_store sync|reset")
