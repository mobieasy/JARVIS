#!/usr/bin/env python3
"""Single entry point for a private subscription-backed JARVIS installation."""
from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from subscription_config import (
    ROOT, PROFILE, RUNTIME_VERSION, environment, initialize, policy_errors,
)


def check_private(target: Path) -> dict:
    paths = [target, target / "state", target / "workspace", target / "gateway.env", target / "openclaw.json", target / "SETUP.json"]
    for path in paths:
        if any(p.is_symlink() for p in (path, *path.parents)):
            raise ValueError("Private setup paths must not contain symlinks")
        info = path.stat()
        if info.st_mode & 0o077 or info.st_uid != os.getuid():
            raise ValueError("Private paths must be owned by the current user and inaccessible to group/other users")
    manifest = json.loads((target / "SETUP.json").read_text())
    if manifest.get("runtime") != RUNTIME_VERSION:
        raise ValueError("Setup runtime differs from the pinned source runtime")
    config = json.loads((target / "openclaw.json").read_text())
    errors = policy_errors(config)
    if errors:
        raise ValueError(errors[0])
    if manifest.get("model") != config["agents"]["defaults"]["model"]["primary"]:
        raise ValueError("Selected model differs from this setup manifest")
    if Path(config["agents"]["defaults"]["workspace"]) != target / "workspace":
        raise ValueError("Workspace must belong to this private setup")
    environment(target, {})  # Validate token without printing it.
    database = target / "state/state/openclaw.sqlite"
    if database.exists() or database.is_symlink():
        if any(p.is_symlink() for p in (database, *database.parents)):
            raise ValueError("Runtime database must not be a symlink")
        try:
            with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=2)) as db:
                if db.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise ValueError("Runtime database integrity check failed; preserve state and investigate before continuing")
        except sqlite3.Error:
            raise ValueError("Runtime database could not pass a read-only integrity check; preserve state and investigate before continuing") from None
    return config


def command_for(action: str, binary: Path, message: str | None = None) -> list[str]:
    commands = {
        "login": ["models", "auth", "login", "--provider", "openai", "--profile-id", PROFILE, "--agent", "jarvis", "--device-code"],
        "validate": ["config", "validate"],
        "install-codex": ["plugins", "install", "@openclaw/codex@" + RUNTIME_VERSION, "--pin", "--no-enable"],
        "status": ["models", "status", "--agent", "jarvis", "--check"],
        "models": ["models", "list", "--agent", "jarvis", "--provider", "openai"],
        "start": ["gateway", "--bind", "loopback"],
        "dashboard": ["dashboard"],
        "smoke": ["agent", "--agent", "jarvis", "--message", message or "Reply exactly JARVIS_READY. Do not call any tools.", "--json"],
    }
    if action not in commands:
        raise ValueError("Unsupported action")
    return [str(binary), *commands[action]]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private-dir", required=True, type=Path, help="Existing dedicated setup path, or new target for init")
    sub = parser.add_subparsers(dest="action", required=True)
    init = sub.add_parser("init", help="Create new private setup; never overwrites")
    init.add_argument("--model", required=True, help="Exact openai/<model> available to your Plus account")
    init.add_argument("--port", type=int, default=18789)
    for name in ("check", "validate", "install-codex", "login", "status", "models", "start", "dashboard", "smoke"):
        sub.add_parser(name)
    args = parser.parse_args(argv)
    target = Path(os.path.abspath(args.private_dir.expanduser()))
    try:
        if args.action == "init":
            initialize(target, args.model, args.port)
            print("Private setup created. Next: check, install-codex, validate, login, models, status, start, smoke.")
            return 0
        config = check_private(target)
        if args.action == "check":
            print(json.dumps({
                "preset": "subscription", "runtime": RUNTIME_VERSION,
                "model": config["agents"]["defaults"]["model"]["primary"],
                "api_fallback": False, "scheduled_ai_jobs_enabled": False,
                "gateway_exposure": "loopback", "source_policy": "passed",
                "live_auth_verified": False,
            }, indent=2))
            return 0
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            raise ValueError("Run JARVIS as a dedicated non-root operating-system user")
        binary = ROOT / "node_modules/.bin/openclaw"
        if not binary.is_file():
            raise ValueError("Install the pinned runtime with npm ci before running OpenClaw")
        installed = json.loads((ROOT / "node_modules/openclaw/package.json").read_text())
        if installed.get("version") != RUNTIME_VERSION:
            raise ValueError("Installed OpenClaw version differs from the pinned runtime")
        child_env = environment(target, os.environ)
        # No shell, arbitrary extra arguments, root elevation, or auto-retry.
        return subprocess.run(command_for(args.action, binary), env=child_env, cwd=target / "workspace", check=False).returncode
    except json.JSONDecodeError:
        print("JARVIS preflight failed: setup JSON is invalid. Inspect it privately.", file=sys.stderr)
        return 1
    except ValueError as error:
        print("JARVIS preflight failed: " + str(error), file=sys.stderr)
        return 1
    except OSError:
        # Do not echo exception strings that could contain a secret/config value.
        print("JARVIS preflight failed. Check path ownership/permissions, the reviewed preset, pinned runtime, and non-root user. No runtime command was executed.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
