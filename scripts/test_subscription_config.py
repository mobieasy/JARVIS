"""Offline regression tests; no user's profile or model service is accessed."""
import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from subscription_config import ROOT, PROFILE, build_config, environment, initialize, policy_errors
from jarvis import check_private, command_for, main


class SubscriptionSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.target = Path(self.temp.name) / "private"

    def setup(self):
        initialize(self.target, "openai/test-model", 18889)
        return json.loads((self.target / "openclaw.json").read_text())

    def test_preset_has_single_codex_model_and_oauth_profile(self):
        config = self.setup()
        default = config["agents"]["defaults"]
        self.assertEqual(default["model"], {"primary": "openai/test-model", "fallbacks": []})
        self.assertEqual(default["models"], {"openai/test-model": {"agentRuntime": {"id": "codex"}}})
        self.assertEqual(config["auth"]["order"], {"openai": [PROFILE]})
        self.assertEqual(config["auth"]["profiles"][PROFILE]["mode"], "oauth")
        self.assertEqual(config["memory"]["search"]["provider"], "none")
        self.assertEqual(config["tools"]["web"]["search"], {"enabled": False})
        self.assertEqual(config["gateway"]["bind"], "loopback")
        self.assertEqual(default["sandbox"]["mode"], "all")
        self.assertFalse(config["tools"]["elevated"]["enabled"])
        self.assertEqual(policy_errors(config), [])

    def test_rejects_paid_fallback_unknown_provider_and_runtime_override(self):
        baseline = self.setup()
        variants = []
        config = copy.deepcopy(baseline)
        config["agents"]["defaults"]["model"]["fallbacks"] = ["openrouter/paid"]
        variants.append(config)
        config = copy.deepcopy(baseline)
        config["agents"]["defaults"]["models"]["openai/test-model"]["agentRuntime"]["id"] = "openclaw"
        variants.append(config)
        config = copy.deepcopy(baseline)
        config["models"] = {"providers": {"openai": {"apiKey": "synthetic-not-secret"}}}
        variants.append(config)
        for config in variants:
            self.assertTrue(policy_errors(config))

    def test_official_install_and_login_metadata_does_not_weaken_policy(self):
        config = self.setup()
        config['meta'] = {'lastTouchedVersion': '2026.10.4', 'migrations': {'modelPolicyAllowlist': True, 'utilityModelSeparation': True}}
        config['auth']['profiles'][PROFILE]['email'] = 'synthetic@example.test'
        self.assertEqual(policy_errors(config), [])
        config['meta']['arbitrary'] = 'untrusted'
        self.assertTrue(policy_errors(config))
        del config['meta']['arbitrary']
        config['auth']['profiles'][PROFILE]['apiKey'] = 'synthetic'
        self.assertTrue(policy_errors(config))

    def test_rejects_sandbox_elevation_network_and_scheduled_work_changes(self):
        baseline = self.setup()
        mutations = [
            lambda c: c["gateway"].update(bind="lan"),
            lambda c: c["agents"]["defaults"]["sandbox"].update(mode="off"),
            lambda c: c["tools"]["elevated"].update(enabled=True),
            lambda c: c["agents"]["defaults"]["heartbeat"].update(every="5m"),
            lambda c: c["auth"]["order"]["openai"].append("openai:api-backup"),
            lambda c: c.update(env={"vars": {"OPENAI_API_KEY": "synthetic"}}),
            lambda c: c.update(channels={"telegram": {"enabled": True}}),
        ]
        for mutate in mutations:
            config = copy.deepcopy(baseline)
            mutate(config)
            self.assertTrue(policy_errors(config))

    def test_initialization_is_private_unique_and_never_overwrites(self):
        self.setup()
        before = (self.target / "gateway.env").read_bytes()
        for path in self.target.rglob("*"):
            self.assertEqual(path.stat().st_mode & 0o077, 0)
        with self.assertRaises(FileExistsError):
            initialize(self.target, "openai/test-model")
        self.assertEqual((self.target / "gateway.env").read_bytes(), before)
        self.assertEqual(check_private(self.target)["gateway"]["port"], 18889)
        other = self.target.parent / "other"
        initialize(other, "openai/test-model")
        self.assertNotEqual((other / "gateway.env").read_bytes(), before)

    def test_rejects_symlink_and_source_tree_targets(self):
        real = self.target.parent / "real"
        real.mkdir()
        link = self.target.parent / "link"
        link.symlink_to(real, target_is_directory=True)
        with self.assertRaises(ValueError):
            initialize(link / "new", "openai/test-model")
        with self.assertRaises(ValueError):
            initialize(ROOT / "private-do-not-create", "openai/test-model")
        self.assertFalse((real / "new").exists())

    def test_rejects_world_readable_paths_and_redirected_token(self):
        self.setup()
        token = self.target / "gateway.env"
        token.chmod(0o644)
        with self.assertRaises(ValueError):
            check_private(self.target)
        token.chmod(0o600)
        saved = self.target / "saved.env"
        token.rename(saved)
        token.symlink_to(saved)
        with self.assertRaises(ValueError):
            check_private(self.target)

    def test_environment_drops_keys_injection_and_unrelated_secrets(self):
        self.setup()
        env = environment(self.target, {
            "PATH": "/usr/bin", "HOME": "/home/test-user", "LANG": "en_US.UTF-8",
            "OPENAI_API_KEY": "synthetic", "CODEX_API_KEY": "synthetic",
            "OPENROUTER_API_KEY": "synthetic", "DATABASE_URL": "synthetic",
            "NODE_OPTIONS": "--require=/untrusted.js", "HTTP_PROXY": "synthetic",
            "OPENCLAW_CONFIG_PATH": "/wrong", "CODEX_HOME": "/wrong",
        })
        for key in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENROUTER_API_KEY", "DATABASE_URL", "NODE_OPTIONS", "HTTP_PROXY", "CODEX_HOME"):
            self.assertNotIn(key, env)
        self.assertEqual(env["HOME"], "/home/test-user")
        self.assertEqual(env["OPENCLAW_CONFIG_PATH"], str(self.target / "openclaw.json"))
        self.assertEqual(len(env["OPENCLAW_GATEWAY_TOKEN"]), 64)

    def test_env_file_is_data_not_shell_code(self):
        self.setup()
        (self.target / "gateway.env").write_text("OPENCLAW_GATEWAY_TOKEN=$(touch /tmp/never)\n")
        with self.assertRaises(ValueError):
            environment(self.target, {})

    def test_login_command_uses_fixed_profile_and_agent(self):
        command = command_for("login", Path("/opt/openclaw"))
        self.assertIn("--device-code", command)
        self.assertEqual(command[command.index("--profile-id") + 1], PROFILE)
        self.assertEqual(command[command.index("--agent") + 1], "jarvis")
        self.assertNotIn("--force", command)
        with self.assertRaises(ValueError):
            command_for("exec arbitrary", Path("/opt/openclaw"))
        install = command_for("install-codex", Path("/opt/openclaw"))
        self.assertIn("@openclaw/codex@2026.10.4", install)
        self.assertIn("--no-enable", install)
        self.assertNotIn("--force", install)

    def test_check_does_not_run_a_process_or_reveal_gateway_token(self):
        self.setup()
        with patch("jarvis.subprocess.run") as run, patch("builtins.print") as output:
            self.assertEqual(main(["--private-dir", str(self.target), "check"]), 0)
            run.assert_not_called()
            rendered = str(output.call_args_list)
            secret = (self.target / "gateway.env").read_text().strip().split("=")[1]
            self.assertNotIn(secret, rendered)
            self.assertIn('"live_auth_verified": false', rendered)

    def test_nonroot_requirement_blocks_execution(self):
        self.setup()
        with patch("jarvis.os.geteuid", return_value=0), patch("jarvis.subprocess.run") as run, patch("builtins.print"):
            self.assertEqual(main(["--private-dir", str(self.target), "start"]), 1)
            run.assert_not_called()

    def test_rejects_invalid_model_port_and_manifest(self):
        for model in ("openrouter/paid", "openai/a; rm -rf /", "openai/../../x", "openai/"):
            with self.assertRaises(ValueError):
                build_config(self.target, model)
        for port in (0, 22, 65536, True, "18789"):
            with self.assertRaises(ValueError):
                build_config(self.target, "openai/test-model", port)
        self.setup()
        (self.target / "SETUP.json").write_text('{"runtime":"unknown"}')
        with self.assertRaises(ValueError):
            check_private(self.target)

    def test_existing_runtime_database_must_pass_integrity_check(self):
        self.setup()
        database = self.target / 'state/state/openclaw.sqlite'
        database.parent.mkdir(mode=0o700)
        with sqlite3.connect(database) as db:
            db.execute('CREATE TABLE synthetic (id INTEGER)')
        self.assertEqual(check_private(self.target)['gateway']['port'], 18889)
        database.write_bytes(b'not a database')
        with self.assertRaisesRegex(ValueError, 'integrity check'):
            check_private(self.target)


if __name__ == "__main__":
    unittest.main()
