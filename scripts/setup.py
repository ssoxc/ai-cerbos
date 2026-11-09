"""Create local-only secrets without printing them or overwriting existing configuration.

`python3 scripts/demo.py start` calls this for you; running it directly is optional.
"""

import base64
import os
import secrets
from pathlib import Path

ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def fresh_values() -> dict[str, str]:
    return {
        "POSTGRES_PASSWORD": secrets.token_hex(24),
        "SESSION_SECRET": secrets.token_hex(48),
        "ENCRYPTION_KEY": base64.urlsafe_b64encode(os.urandom(32)).decode(),
        "LITELLM_MASTER_KEY": "sk-" + secrets.token_hex(32),
        "MOCK_PROVIDER_KEY": secrets.token_hex(32),
        # Shared by the API and LiteLLM's Cerbos guard for the internal budget ledger.
        "LEDGER_TOKEN": secrets.token_hex(32),
        "DEMO_MODE": "true",
        "DEMO_PORT": "5173",
    }


def ensure_env(target: Path = ENV_FILE) -> bool:
    """Write a fresh `.env` if none exists. Returns True when one was created.

    An existing `.env` is kept; secrets added by a newer version are appended to it.
    """
    values = fresh_values()
    if target.exists():
        present = {line.split("=", 1)[0] for line in target.read_text().splitlines() if "=" in line}
        missing = {k: v for k, v in values.items() if k not in present}
        if missing:
            text = target.read_text()
            prefix = "" if text.endswith("\n") or not text else "\n"
            target.write_text(text + prefix + "".join(f"{k}={v}\n" for k, v in missing.items()))
        return False
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as output:
        output.write("".join(f"{key}={value}\n" for key, value in values.items()))
    return True


if __name__ == "__main__":
    if ensure_env():
        print("Created .env with fresh local secrets. Demo sign-in is enabled.")
    else:
        print(".env already exists; preserving it.")
