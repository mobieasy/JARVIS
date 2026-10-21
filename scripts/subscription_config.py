"""Build a fresh, private OpenClaw/Codex subscription setup without live secrets."""
from __future__ import annotations

import copy
import json
import os
import re
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNTIME_VERSION = "2026.10.4"
PROFILE = "openai:jarvis"
API_ENV = (
    "OPENAI_API_KEY", "CODEX_API_KEY", "OPENROUTER_API_KEY", "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY", "GOOGLE_API_KEY", "XAI_API_KEY", "OPENAI_BASE_URL",
    "OPENAI_API_BASE", "OPENCLAW_CODEX_APP_SERVER_BIN", "NODE_OPTIONS", "NODE_PATH",
    "OPENCLAW_CONFIG_PATH", "OPENCLAW_STATE_DIR", "CODEX_HOME",
)
DENIED = (
    "gateway", "nodes", "computer", "terminal", "plugins", "openclaw",
    "sessions_spawn", "subagents", "image_generate", "video_generate",
    "music_generate", "tts", "message", "workboard_dispatch",
)


def validate_model(model: str) -> str:
    if not re.fullmatch(r"openai/[a-z0-9][a-z0-9._-]{0,100}", model):
        raise ValueError("Select an exact openai/<model> from your signed-in Codex catalog")
    return model


def build_config(workspace: Path, model: str, port: int = 18789) -> dict:
    model = validate_model(model)
    if type(port) is not int or not 1024 <= port <= 65535:
        raise ValueError("Gateway port must be an integer from 1024 to 65535")
    config = json.loads((ROOT / "config/openclaw.example.json").read_text())
    gateway = config["gateway"]
    origin = f"http://127.0.0.1:{port}"
    gateway.update(port=port, publicOrigin=origin)
    gateway["controlUi"]["allowedOrigins"] = [origin]
    # The optional operator HTTP API is deliberately NOT enabled.
    defaults = config["agents"]["defaults"]
    defaults.update(
        workspace=str(workspace.resolve()), userTimezone="Asia/Kolkata",
        model={"primary": model, "fallbacks": []}, utilityModel=model,
        models={model: {"agentRuntime": {"id": "codex"}}},
        modelPolicy={"allow": [model]},
    )
    config["auth"] = {
        "profiles": {PROFILE: {"provider": "openai", "mode": "oauth"}},
        "order": {"openai": [PROFILE]},
    }
    config["plugins"]["entries"]["codex"] = {
        "enabled": True,
        "config": {"appServer": {"homeScope": "agent", "clearEnv": list(API_ENV)}},
    }
    config["memory"] = {"search": {"provider": "none"}}
    config["tools"]["deny"] = list(DENIED)
    # A disabled, unavailable provider still fails upstream schema validation.
    config["tools"]["web"]["search"] = {"enabled": False}
    return config


def policy_errors(config: dict) -> list[str]:
    """Strict compare: an unknown configuration change requires operator review."""
    try:
        config = copy.deepcopy(config)
        # Official install/login may stamp bookkeeping; permit only these
        # non-routing fields. Never ignore arbitrary meta or auth additions.
        meta = config.pop("meta", {})
        if not isinstance(meta, dict) or set(meta) - {"lastTouchedVersion", "lastTouchedAt", "migrations"}:
            return ["Unrecognized runtime metadata"]
        if "lastTouchedVersion" in meta and meta["lastTouchedVersion"] != RUNTIME_VERSION:
            return ["Configuration was written by a different runtime"]
        if "lastTouchedAt" in meta and (not isinstance(meta["lastTouchedAt"], str) or not re.fullmatch(r"[0-9TZ:.+\-]{10,40}", meta["lastTouchedAt"])):
            return ["Invalid runtime timestamp metadata"]
        migrations = meta.get("migrations", {})
        if not isinstance(migrations, dict) or set(migrations) - {"modelPolicyAllowlist", "utilityModelSeparation"} or any(v is not True for v in migrations.values()):
            return ["Unrecognized runtime migration metadata"]
        profile = config.get("auth", {}).get("profiles", {}).get(PROFILE, {})
        if "email" in profile:
            email = profile.pop("email")
            if not isinstance(email, str) or not re.fullmatch(r"[^\s@]{1,160}@[^\s@]{1,160}", email):
                return ["Invalid account metadata"]
        defaults = config["agents"]["defaults"]
        expected = build_config(Path(defaults["workspace"]), defaults["model"]["primary"], config["gateway"]["port"])
        if config == expected:
            return []
        return ["Configuration differs from the reviewed subscription preset; generate a new staging setup or review the change"]
    except (KeyError, TypeError, ValueError, AttributeError):
        return ["Configuration does not match the subscription preset"]


def private_write(path: Path, content: str) -> None:
    """Exclusive creation: never replace a live config or follow an existing file link."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as output:
        output.write(content)


def initialize(target: Path, model: str, port: int = 18789) -> Path:
    # Check symlinks before resolve so a symlinked target cannot redirect writes.
    target = Path(os.path.abspath(target.expanduser()))
    if any(p.is_symlink() for p in (target, *target.parents)):
        raise ValueError("Choose a directory without symlink components")
    if target == ROOT or ROOT in target.parents:
        raise ValueError("Private state must be outside the source repository")
    config = build_config(target / "workspace", model, port)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.mkdir(mode=0o700)  # Reject ALL existing targets, including partial setups.
    for name in ("workspace", "state"):
        (target / name).mkdir(mode=0o700)
    private_write(target / "openclaw.json", json.dumps(config, indent=2) + "\n")
    private_write(target / "gateway.env", "OPENCLAW_GATEWAY_TOKEN=" + secrets.token_hex(32) + "\n")
    private_write(target / "SETUP.json", json.dumps({"schema": 1, "runtime": RUNTIME_VERSION, "model": model}, indent=2) + "\n")
    for source in sorted((ROOT / "templates/private-workspace").glob("*.md")):
        private_write(target / "workspace" / source.name, source.read_text(encoding="utf-8"))
    return target


def environment(target: Path, ambient: dict[str, str]) -> dict[str, str]:
    # Allowlists prevent ambient model keys, node injection, proxy overrides, and
    # unrelated service secrets from leaking into the trusted runtime. HOME and
    # CODEX_HOME are never reassigned here. Use a dedicated operating-system user.
    allowed = ("PATH", "HOME", "USER", "LOGNAME", "LANG", "LC_ALL", "TERM", "TMPDIR", "XDG_RUNTIME_DIR")
    env = {key: ambient[key] for key in allowed if key in ambient}
    token_file = target / "gateway.env"
    line = token_file.read_text(encoding="utf-8").strip()
    if not re.fullmatch(r"OPENCLAW_GATEWAY_TOKEN=[0-9a-f]{64}", line):
        raise ValueError("Invalid gateway secret file; inspect privately")
    env["OPENCLAW_GATEWAY_TOKEN"] = line.partition("=")[2]
    env["OPENCLAW_CONFIG_PATH"] = str(target / "openclaw.json")
    env["OPENCLAW_STATE_DIR"] = str(target / "state")
    return env
