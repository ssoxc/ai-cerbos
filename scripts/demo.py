#!/usr/bin/env python3
"""One command to run, reset and test the ai-cerbos demo.

Needs only Docker (Docker Desktop, or any Docker engine with Compose v2) and Python 3.

    python3 scripts/demo.py start    # build, start, wait until healthy, open the browser
    python3 scripts/demo.py reset    # sample data and shipped Cerbos policies, as on first start
    python3 scripts/demo.py test     # Cerbos policy tests, backend tests and an end-to-end run
    python3 scripts/demo.py logs     # follow the logs (Ctrl+C to stop following)
    python3 scripts/demo.py stop     # stop everything; your data is kept

To use a Docker context other than the current one, set DOCKER_CONTEXT for the command.
To use another port than 5173, set DEMO_PORT in .env.
"""

import argparse
import shutil
import socket
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from setup import ENV_FILE, ensure_env  # noqa: E402


def say(message: str):
    print(f"\n==> {message}", flush=True)


def fail(message: str):
    sys.exit(f"\n[ai-cerbos] {message}")


def compose(*args: str, check: bool = True, capture: bool = False) -> subprocess.CompletedProcess:
    command = ["docker", "compose", *args]
    try:
        return subprocess.run(
            command, cwd=ROOT, check=check, text=True, capture_output=capture
        )
    except subprocess.CalledProcessError as error:
        fail(f"`{' '.join(command)}` failed (exit code {error.returncode}). See the output above.")
    except KeyboardInterrupt:
        sys.exit(130)


def preflight():
    if not shutil.which("docker"):
        fail("Docker is not installed. Install Docker Desktop: https://docs.docker.com/get-docker/")
    if subprocess.run(["docker", "info"], capture_output=True).returncode != 0:
        fail("Docker is installed but not running. Start Docker Desktop and try again.")
    if subprocess.run(["docker", "compose", "version"], capture_output=True).returncode != 0:
        fail("Docker Compose v2 is required. Update Docker Desktop.")


def env_value(name: str, default: str) -> str:
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.startswith(f"{name}="):
                return line.split("=", 1)[1].strip() or default
    return default


def url() -> str:
    return f"http://localhost:{env_value('DEMO_PORT', '5173')}"


def port_in_use(port: int) -> bool:
    """Whether something already listens on the port. Connecting, rather than binding,
    ignores closed connections lingering in TIME_WAIT and behaves the same on Windows."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def dashboard_running_here() -> bool:
    """True when this Docker engine already runs the demo's dashboard (a restart is fine)."""
    result = compose("ps", "--status", "running", "--services", check=False, capture=True)
    return "frontend" in result.stdout.split()


def check_port():
    port = int(env_value("DEMO_PORT", "5173"))
    if port_in_use(port) and not dashboard_running_here():
        engine = subprocess.run(
            ["docker", "context", "show"], capture_output=True, text=True
        ).stdout.strip()
        fail(
            f"Port {port} is already in use, so the dashboard cannot start.\n"
            f"  - Another copy of this demo may be running, possibly on a different Docker\n"
            f"    engine or context than the current one ({engine or 'default'}). Stop it there\n"
            f"    with `python3 scripts/demo.py stop`.\n"
            f"  - Or another app (such as a development server) uses the port.\n"
            f"  - Or choose another port: set DEMO_PORT=5180 in .env and run start again."
        )


def start(open_browser: bool = True):
    preflight()
    if ensure_env():
        say("Created .env with fresh local secrets")
    check_port()
    say("Building and starting the demo. The first run downloads images and takes a few minutes")
    compose("up", "-d", "--build", "--wait")
    say(f"Ready: {url()}")
    print("    Start with Governance > Cerbos playground.")
    print("    Switch persona with the selector in the top right.")
    if open_browser:
        webbrowser.open(f"{url()}/playground")


def stop():
    preflight()
    compose("down")
    say("Stopped. Your data is kept; `start` brings it back.")


def reset():
    preflight()
    say("Restoring the sample workspace and the shipped Cerbos policies")
    compose("exec", "-T", "api", "python", "-m", "app.demo", "reset")


def edited_policies() -> int:
    result = compose(
        "exec",
        "-T",
        "api",
        "python",
        "-c",
        "from app import policy_store; print(sum(p['modified'] for p in policy_store.summary()))",
        check=False,
        capture=True,
    )
    try:
        return int(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return 0


def test():
    preflight()
    ensure_env()
    say("1/3 Cerbos policy unit tests (shipped policies)")
    compose(
        "--profile", "test", "run", "--rm", "--build", "--no-deps",
        "tests", "cerbos", "compile", "/app/shipped-policies",
    )
    say("2/3 Backend tests against a disposable database and a separate test Cerbos")
    # Always a fresh test Cerbos with the policies of this checkout, never a leftover one.
    compose("--profile", "test", "up", "-d", "--build", "--force-recreate", "--wait", "cerbos-test")
    compose("--profile", "test", "run", "--rm", "tests")
    say("3/3 End-to-end run through the dashboard, Cerbos and LiteLLM")
    compose("up", "-d", "--build", "--wait")
    if edited_policies():
        print(
            "    Note: some live policies were edited in the playground. The end-to-end run checks\n"
            "    the shipped behaviour and may fail; run `python3 scripts/demo.py reset` first."
        )
    compose("--profile", "test", "run", "--rm", "--no-deps", "tests", "python", "scripts/smoke.py")
    compose("--profile", "test", "rm", "--stop", "--force", "cerbos-test", check=False, capture=True)
    say("All tests passed")


def logs(services: list[str]):
    preflight()
    compose("logs", "-f", "--tail", "100", *services, check=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    start_parser = commands.add_parser("start", help="build, start and open the demo")
    start_parser.add_argument("--no-browser", action="store_true", help="do not open a browser")
    commands.add_parser("stop", help="stop the demo, keeping its data")
    commands.add_parser("reset", help="restore sample data and the shipped policies")
    commands.add_parser("test", help="run every test")
    logs_parser = commands.add_parser("logs", help="follow service logs")
    logs_parser.add_argument("services", nargs="*", help="for example: api litellm cerbos")
    args = parser.parse_args()
    if args.command == "start":
        start(open_browser=not args.no_browser)
    elif args.command == "stop":
        stop()
    elif args.command == "reset":
        reset()
    elif args.command == "test":
        test()
    elif args.command == "logs":
        logs(args.services)


if __name__ == "__main__":
    main()
