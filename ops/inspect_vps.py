#!/usr/bin/env python3
"""Read-only OpenClaw/Codex metadata inventory. Never reads credential contents.

Output is private deployment metadata. Encrypt it before storage or logging.
Does not execute OpenClaw/Codex, authenticate, query models, or change services.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
from pathlib import Path

LIMIT = 262144
MODEL = re.compile(r"(?:openai|openai-codex|codex-cli|openrouter|anthropic|ollama)/[a-zA-Z0-9._:/-]{1,160}")
VERSION = re.compile(r"[0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4}(?:[-+][a-zA-Z0-9._-]{1,60})?")
TOOL = re.compile(r"openclaw|codex|jarvis", re.I)


def text_file(path: Path, limit: int = LIMIT) -> str | None:
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
            return None
        with path.open("r", encoding="utf-8") as stream:
            text = stream.read(limit + 1)
        return text if len(text.encode("utf-8")) <= limit else None
    except (OSError, UnicodeError):
        return None


def footprint(path: Path) -> dict:
    """Metadata only: never open the credential/database file."""
    result = {"path": str(path), "present": False}
    try:
        info = path.lstat()
        result.update(present=True, mode=oct(stat.S_IMODE(info.st_mode)),
                      owner_uid=info.st_uid, symlink=stat.S_ISLNK(info.st_mode))
    except OSError:
        pass
    return result


def model_ref(value):
    return value if isinstance(value, str) and MODEL.fullmatch(value) else None


def configured_connection(config: dict) -> dict:
    """Whitelist structural facts, not arbitrary keys, profile IDs or values."""
    agents = config.get("agents", {})
    defaults = agents.get("defaults", {})
    model = defaults.get("model", {})
    primary = model if isinstance(model, str) else model.get("primary") if isinstance(model, dict) else None
    result = {"primary_model": model_ref(primary), "runtime_ids": [], "cli_backends": [], "auth_modes": []}
    models = defaults.get("models", {})
    for entry in models.values() if isinstance(models, dict) else []:
        runtime = entry.get("agentRuntime", {}).get("id") if isinstance(entry, dict) else None
        if runtime in {"codex", "openclaw", "codex-cli", "claude-cli"}:
            result["runtime_ids"].append(runtime)
    for key, entry in defaults.get("cliBackends", {}).items() if isinstance(defaults.get("cliBackends"), dict) else []:
        if key not in {"codex-cli", "codex", "claude-cli"} or not isinstance(entry, dict):
            continue
        command = entry.get("command", "")
        # A command could contain inline secrets. Report only recognized executable names.
        name = Path(command).name if isinstance(command, str) else ""
        result["cli_backends"].append({"backend": key, "executable": name if name in {"codex", "codex_helper.sh", "claude", "node"} else "custom (not collected)"})
    profiles = config.get("auth", {}).get("profiles", {})
    for entry in profiles.values() if isinstance(profiles, dict) else []:
        if not isinstance(entry, dict):
            continue
        provider, mode = entry.get("provider"), entry.get("mode")
        if provider in {"openai", "openai-codex", "openrouter", "anthropic"} and mode in {"oauth", "api_key", "token"}:
            result["auth_modes"].append({"provider": provider, "mode": mode})
    codex = config.get("plugins", {}).get("entries", {}).get("codex", {})
    result["codex_plugin_enabled"] = codex.get("enabled") is True if isinstance(codex, dict) else False
    app = codex.get("config", {}).get("appServer", {}) if isinstance(codex, dict) else {}
    result["codex_home_scope"] = app.get("homeScope") if app.get("homeScope") in {"agent", "user"} else "not explicit"
    result["runtime_ids"] = sorted(set(result["runtime_ids"]))
    result["agent_overrides"] = []
    entries = agents.get("entries", {})
    entries = list(entries.values()) if isinstance(entries, dict) else entries if isinstance(entries, list) else []
    for index, entry in enumerate(entries[:32]):
        if not isinstance(entry, dict):
            continue
        selected = entry.get("model", {})
        selected = selected if isinstance(selected, str) else selected.get("primary") if isinstance(selected, dict) else None
        runtimes = []
        scoped_models = entry.get("models", {})
        for settings in scoped_models.values() if isinstance(scoped_models, dict) else []:
            runtime = settings.get("agentRuntime", {}).get("id") if isinstance(settings, dict) else None
            if runtime in {"codex", "openclaw", "codex-cli", "claude-cli"}:
                runtimes.append(runtime)
        if model_ref(selected) or runtimes:
            result["agent_overrides"].append({"entry_index": index, "primary_model": model_ref(selected), "runtime_ids": sorted(set(runtimes))})
    providers = config.get("models", {}).get("providers", {})
    result["provider_runtimes"] = []
    for name, entry in providers.items() if isinstance(providers, dict) else []:
        if name not in {"openai", "openai-codex", "codex-cli", "openrouter", "anthropic"} or not isinstance(entry, dict):
            continue
        runtime = entry.get("agentRuntime", {}).get("id")
        if runtime in {"codex", "openclaw", "codex-cli", "claude-cli"}:
            result["provider_runtimes"].append({"provider": name, "runtime": runtime})
    return result


def summarize_config(path: Path) -> dict:
    result = {"path": str(path), "format": "unreadable, linked, or over limit"}
    text = text_file(path)
    if text is None:
        return result
    try:
        config = json.loads(text)
        if not isinstance(config, dict):
            raise ValueError()
        result.update(format="json", connection=configured_connection(config))
    except (ValueError, AttributeError, TypeError):
        # Do not include parse exceptions: those can carry source text.
        result["format"] = "JSON5/invalid/unsupported structure; manual private review needed"
    return result


def classify_argv(argv: list[str]) -> dict | None:
    # Raw argv is never returned: flags may contain tokens or user prompts.
    if not any(TOOL.search(Path(part).name) for part in argv[:5]):
        return None
    role = "unknown"
    for candidate in ("app-server", "gateway", "exec", "review", "login"):
        if candidate in argv[:12]:
            role = candidate
            break
    configs = []
    for i, part in enumerate(argv[:-1]):
        next_part = argv[i + 1]
        if part in {"--config", "--config-path"} and next_part.startswith("/") and next_part.endswith((".json", ".json5")) and len(next_part) < 512:
            configs.append(next_part)
    return {"role": role, "config_candidates": configs}


def process_metadata(proc_root=Path("/proc")) -> list[dict]:
    results = []
    for directory in sorted(proc_root.glob("[0-9]*"))[:65536]:
        try:
            with (directory / "cmdline").open("rb") as stream:
                argv = stream.read(16384).decode("utf-8", errors="replace").split("\0")
            item = classify_argv(argv)
            if item is None:
                continue
            item["pid"] = int(directory.name)
            try:
                item["cwd"] = os.readlink(directory / "cwd")
            except OSError:
                item["cwd"] = None
            results.append(item)
            if len(results) >= 64:
                break
        except OSError:
            continue
    return results


def read_command(argv: list[str]) -> str:
    try:
        done = subprocess.run(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                              stderr=subprocess.DEVNULL, timeout=5, check=False,
                              env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C"})
        return done.stdout[:LIMIT].decode("utf-8", errors="replace") if done.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def unit_metadata(text: str) -> dict:
    result = {"config_candidates": [], "state_candidates": [], "environment_files_present": False, "exec_roles": []}
    for raw in text.splitlines():
        key, _, value = raw.strip().partition("=")
        if key == "EnvironmentFile":
            result["environment_files_present"] = True  # Do not read the file.
        if key == "Environment":
            try:
                for assignment in shlex.split(value):
                    name, _, path = assignment.partition("=")
                    if not path.startswith("/") or len(path) > 512:
                        continue
                    if name == "OPENCLAW_CONFIG_PATH" and path.endswith((".json", ".json5")):
                        result["config_candidates"].append(path)
                    if name in {"OPENCLAW_STATE_DIR", "CODEX_HOME"}:
                        result["state_candidates"].append({"kind": name, "path": path})
            except ValueError:
                pass
        if key == "ExecStart":
            try:
                classified = classify_argv(shlex.split(value))
                if classified:
                    result["exec_roles"].append(classified["role"])
                    result["config_candidates"].extend(classified["config_candidates"])
            except ValueError:
                pass
    return result


def service_metadata() -> list[dict]:
    units = read_command(["systemctl", "list-units", "--type=service", "--all", "--no-pager", "--no-legend"])
    names = []
    for line in units.splitlines():
        for word in line.split()[:2]:
            if re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9@_.-]{0,120}\.service", word) and TOOL.search(word):
                names.append(word)
    result = []
    for name in sorted(set(names))[:16]:
        shown = read_command(["systemctl", "show", name, "--no-pager", "--property=Id,ActiveState,SubState,MainPID,FragmentPath,WorkingDirectory"])
        values = dict(line.partition("=")[::2] for line in shown.splitlines() if "=" in line)
        entry = {k: v for k, v in values.items() if k in {"Id", "ActiveState", "SubState", "MainPID", "FragmentPath", "WorkingDirectory"}}
        unit = text_file(Path(entry.get("FragmentPath", "/nonexistent")), 131072)
        entry["unit_hints"] = unit_metadata(unit) if unit is not None else {"not_read": True}
        result.append(entry)
    return result


def package_metadata(binary: Path) -> dict:
    result = {"binary_path": str(binary), "package": None, "version": None}
    try:
        resolved = binary.resolve(strict=True)
        for parent in list(resolved.parents)[:6]:
            text = text_file(parent / "package.json", 131072)
            if text is None:
                continue
            data = json.loads(text)
            if data.get("name") in {"openclaw", "@openai/codex", "@openclaw/codex"}:
                version = data.get("version")
                result.update(package=data["name"], version=version if isinstance(version, str) and VERSION.fullmatch(version) else "unrecognized")
                break
    except (OSError, ValueError, AttributeError):
        pass
    return result


def helper_metadata(path: Path) -> dict:
    text = text_file(path, 65536)
    result = {"path": str(path), "readable_script": text is not None}
    if text is not None:
        result.update(sha256=hashlib.sha256(text.encode()).hexdigest(),
                      device_code_flow="--device-auth" in text or "--device-code" in text,
                      invokes_exec=bool(re.search(r"\bexec\b", text)),
                      overrides_home=bool(re.search(r"(?:^|\n)(?:export\s+)?HOME=", text)),
                      overrides_codex_home=bool(re.search(r"(?:^|\n)(?:export\s+)?CODEX_HOME=", text)))
    return result


def collect() -> dict:
    services, processes = service_metadata(), process_metadata()
    homes = [Path("/root"), *sorted(Path("/home").glob("*"))[:20]]
    workdirs = {Path(p["cwd"]) for p in processes if (p.get("cwd") or "").startswith("/")}
    workdirs.update(Path(s["WorkingDirectory"]) for s in services if s.get("WorkingDirectory", "").startswith("/"))
    workdirs = sorted(workdirs)[:32]
    candidates = {h / ".openclaw/openclaw.json" for h in homes}
    candidates.update(w / ".openclaw/openclaw.json" for w in workdirs)
    candidates.update(w / "config/openclaw.local.json" for w in workdirs)
    for entry in processes:
        candidates.update(Path(p) for p in entry["config_candidates"])
    for entry in services:
        candidates.update(Path(p) for p in entry["unit_hints"].get("config_candidates", []))
    configurations = [summarize_config(p) for p in sorted(candidates)[:128] if p.is_file()]
    binaries = set()
    for name in ("openclaw", "codex"):
        path = shutil.which(name)
        if path:
            binaries.add(Path(path))
    for base in [*homes, *workdirs]:
        for relative in (".local/node_modules/.bin/codex", "node_modules/.bin/openclaw", "node_modules/.bin/codex"):
            path = base / relative
            if path.is_file():
                binaries.add(path)
    credentials = []
    for base in [*homes, *workdirs]:
        credentials.extend(footprint(base / relative) for relative in (".codex/auth.json", ".openclaw/auth-profiles.json", ".openclaw/openclaw-agent.sqlite"))
    for service in services:
        for hint in service["unit_hints"].get("state_candidates", []):
            root = Path(hint["path"])
            credentials.append(footprint(root / "auth.json" if hint["kind"] == "CODEX_HOME" else root / "state/openclaw.sqlite"))
    helpers = [helper_metadata(w / "tools/codex_helper.sh") for w in workdirs if (w / "tools/codex_helper.sh").is_file()]
    return {"schema": 1, "collected_at": dt.datetime.now(dt.timezone.utc).isoformat(),
            "services": services, "processes": processes, "configurations": configurations,
            "binaries": [package_metadata(p) for p in sorted(binaries)[:32]],
            "credential_footprints": credentials[:128], "cli_helpers": helpers,
            "limits": ["Credential/auth files, chat history, backups and environment files were not opened; secret values and raw configuration text were not collected.",
                       "No login, refresh, probe, migration, restart, model call or write was requested.",
                       "Configured auth metadata is not proof of current credential validity.",
                       "Bounded discovery may miss custom locations, containers or user-level services."]}


if __name__ == "__main__":
    try:
        output = json.dumps(collect(), indent=2)
        if len(output.encode()) > LIMIT:
            raise ValueError()
        print(output)
    except Exception:
        # A generic error only: never echo an exception containing host/config data.
        raise SystemExit("Inspection could not produce a bounded report; no service changes were requested.")
