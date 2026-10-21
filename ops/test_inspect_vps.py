"""Synthetic fixtures only. No real service, profile, auth or deployment reads."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from inspect_vps import (
    configured_connection, summarize_config, footprint, classify_argv,
    unit_metadata, package_metadata, helper_metadata, text_file,
)


class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_config_whitelist_keeps_connection_method_not_credentials(self):
        config = {
            'agents': {'defaults': {'model': {'primary': 'openai/test-model'},
                'models': {'openai/test-model': {'agentRuntime': {'id': 'codex'}}},
                'cliBackends': {'codex-cli': {'command': '/opt/bin/codex', 'args': ['SECRET_PROMPT']}}}},
            'auth': {'profiles': {'openai:PRIVATE_EMAIL': {'provider': 'openai', 'mode': 'oauth', 'access': 'SECRET_ACCESS', 'refresh': 'SECRET_REFRESH'}}},
            'plugins': {'entries': {'codex': {'enabled': True, 'config': {'appServer': {'homeScope': 'agent', 'apiKey': 'SECRET_KEY'}}}}},
            'gateway': {'auth': {'token': 'SECRET_GATEWAY'}},
            'env': {'vars': {'OPENAI_API_KEY': 'SECRET_ENV'}},
        }
        summary = configured_connection(config)
        self.assertEqual(summary['primary_model'], 'openai/test-model')
        self.assertEqual(summary['runtime_ids'], ['codex'])
        self.assertEqual(summary['auth_modes'], [{'provider': 'openai', 'mode': 'oauth'}])
        self.assertEqual(summary['cli_backends'][0]['executable'], 'codex')
        rendered = json.dumps(summary)
        self.assertNotIn('SECRET', rendered)
        self.assertNotIn('PRIVATE_EMAIL', rendered)

    def test_unrecognized_model_and_command_are_not_echoed(self):
        result = configured_connection({'agents': {'defaults': {'model': 'SECRET',
            'cliBackends': {'codex-cli': {'command': 'sh -c SECRET'}}}}})
        self.assertIsNone(result['primary_model'])
        self.assertNotIn('SECRET', json.dumps(result))

    def test_agent_overrides_and_provider_runtime_are_reported_without_identifiers(self):
        result = configured_connection({'agents': {'defaults': {}, 'entries': {
            'PRIVATE_OWNER': {'model': 'openai/test-model', 'models': {'openai/test-model': {'agentRuntime': {'id': 'codex'}}}}
        }}, 'models': {'providers': {'openai': {'agentRuntime': {'id': 'codex'}, 'apiKey': 'SECRET'}}}})
        self.assertEqual(result['agent_overrides'][0]['runtime_ids'], ['codex'])
        self.assertEqual(result['provider_runtimes'], [{'provider': 'openai', 'runtime': 'codex'}])
        self.assertNotIn('PRIVATE_OWNER', json.dumps(result))
        self.assertNotIn('SECRET', json.dumps(result))

    def test_invalid_config_errors_do_not_include_source_snippets(self):
        config = self.root / 'openclaw.json'
        config.write_text('SECRET invalid JSON')
        result = summarize_config(config)
        self.assertNotIn('SECRET', json.dumps(result))
        self.assertIn('manual private review', result['format'])

    def test_limits_and_symlinks_prevent_unbounded_or_redirected_reads(self):
        config = self.root / 'config.json'
        config.write_text('x' * 50)
        self.assertIsNone(text_file(config, 10))
        link = self.root / 'linked.json'
        link.symlink_to(config)
        self.assertIsNone(text_file(link))

    def test_credential_footprint_never_opens_credential(self):
        credential = self.root / 'auth.json'
        credential.write_text('SECRET')
        with patch.object(Path, 'open', side_effect=AssertionError('Credentials must not be opened')):
            result = footprint(credential)
        self.assertTrue(result['present'])
        self.assertNotIn('SECRET', json.dumps(result))

    def test_argv_classification_drops_prompts_and_tokens(self):
        result = classify_argv(['node', '/opt/openclaw/index.js', 'gateway', '--config', '/private/openclaw.json', '--token', 'SECRET'])
        self.assertEqual(result, {'role': 'gateway', 'config_candidates': ['/private/openclaw.json']})
        result = classify_argv(['/opt/codex', 'exec', 'PRIVATE_PROMPT'])
        self.assertEqual(result['role'], 'exec')
        self.assertNotIn('PRIVATE_PROMPT', json.dumps(result))
        self.assertIsNone(classify_argv(['/bin/unrelated', 'SECRET']))

    def test_codex_inline_config_is_not_mistaken_for_config_file(self):
        result = classify_argv(['/opt/codex', '--config', 'api_key="SECRET"', 'app-server'])
        self.assertEqual(result['role'], 'app-server')
        self.assertEqual(result['config_candidates'], [])

    def test_systemd_metadata_does_not_collect_environment_files_or_secrets(self):
        text = '\n'.join([
            '[Service]',
            'Environment="OPENAI_API_KEY=SECRET_ENV" "OPENCLAW_CONFIG_PATH=/private/config.json" "CODEX_HOME=/private/codex"',
            'EnvironmentFile=/private/SECRET_FILE',
            'ExecStart=/opt/openclaw gateway --token SECRET_ARG',
        ])
        result = unit_metadata(text)
        self.assertEqual(result['config_candidates'], ['/private/config.json'])
        self.assertTrue(result['environment_files_present'])
        self.assertEqual(result['exec_roles'], ['gateway'])
        self.assertNotIn('SECRET', json.dumps(result))

    def test_package_metadata_reads_version_without_running_binary(self):
        package = self.root / 'node_modules/openclaw'
        (package / 'bin').mkdir(parents=True)
        binary = package / 'bin/openclaw'
        binary.write_text('do not execute')
        (package / 'package.json').write_text(json.dumps({'name': 'openclaw', 'version': '2026.10.4', 'apiKey': 'SECRET'}))
        result = package_metadata(binary)
        self.assertEqual(result['version'], '2026.10.4')
        self.assertNotIn('SECRET', json.dumps(result))

    def test_helper_reports_login_flags_without_copying_script(self):
        helper = self.root / 'codex_helper.sh'
        helper.write_text('export HOME="$workspace_root"\nexport CODEX_HOME="$workspace_root/.codex"\ncodex login --device-auth\n# SECRET\nexec codex exec "$@"\n')
        result = helper_metadata(helper)
        self.assertTrue(result['device_code_flow'])
        self.assertTrue(result['overrides_home'])
        self.assertTrue(result['overrides_codex_home'])
        self.assertNotIn('SECRET', json.dumps(result))


if __name__ == '__main__':
    unittest.main()
