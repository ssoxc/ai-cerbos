"""Run the backend tests in a disposable Postgres database; never touch the demo workspace.

Works both from the host (with `compose.dev.yaml` publishing Postgres and Cerbos) and
inside the compose `tests` container, where settings come from the environment.
"""

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql

root = Path(__file__).resolve().parents[1]
# On the host the backend lives in ./backend; in the test image it is the image root.
backend = root / "backend" if (root / "backend").is_dir() else root


def load_dotenv_values():
    env_file = root / ".env"
    if not env_file.exists():
        return {}
    from dotenv import dotenv_values

    return {k: v for k, v in dotenv_values(env_file).items() if v is not None}


config = {**load_dotenv_values(), **os.environ}
password = config.get("POSTGRES_PASSWORD")
if not password:
    sys.exit("POSTGRES_PASSWORD is not set. Run `python3 scripts/demo.py start` first.")
host = config.get("POSTGRES_HOST", "localhost")
test_db = f"ai_cerbos_test_{uuid4().hex[:12]}"
env = {
    **config,
    "DATABASE_URL": f"postgresql+psycopg://cerbos:{password}@{host}:5432/{test_db}",
    "CERBOS_URL": config.get("CERBOS_URL", "http://localhost:3592"),
    "DEMO_MODE": "true",
}
admin = psycopg.connect(host=host, user="cerbos", password=password, dbname="postgres", autocommit=True)
result = None
try:
    admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(test_db)))
    subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=backend, env=env, check=True)
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", *sys.argv[1:]], cwd=backend, env=env)
finally:
    admin.execute(sql.SQL("DROP DATABASE {} WITH (FORCE)").format(sql.Identifier(test_db)))
    admin.close()
sys.exit(result.returncode if result else 1)
