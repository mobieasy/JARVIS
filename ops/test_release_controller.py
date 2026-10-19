import json
from pathlib import Path
import tempfile
import unittest
from release_controller import Controller, tree_digest


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.old, self.new = 'a' * 40, 'b' * 40
        for revision in (self.old, self.new):
            release = self.root / 'releases' / revision
            (release / 'payload').mkdir(parents=True)
            (release / 'payload' / 'app').write_text(revision)
            (release / 'manifest.json').write_text(json.dumps({
                'revision': revision, 'rollback_safe': True,
                'payload_sha256': tree_digest(release / 'payload')}))
        (self.root / 'current').symlink_to('releases/' + self.old)
        self.controller = Controller({'root': str(self.root)})
        self.actions = []
        self.controller.hook = self.hook
        self.fail_new = False

    def hook(self, name):
        self.actions.append((name, self.controller.current()))
        if name == 'ready' and self.fail_new and self.controller.current() == self.new:
            raise RuntimeError('synthetic readiness failure')

    def test_success_single_writer_order(self):
        result = self.controller.run(self.new, self.old)
        self.assertEqual(result['status'], 'succeeded')
        self.assertEqual([a[0] for a in self.actions],
                         ['preflight', 'drain', 'stop', 'backup', 'start', 'ready', 'resume'])
        self.assertEqual(self.actions[2][1], self.old)
        self.assertEqual(self.actions[4][1], self.new)
        self.assertEqual(json.loads((self.root / 'deployment.json').read_text())['previous'], self.old)

    def test_failed_candidate_restores_previous(self):
        self.fail_new = True
        with self.assertRaises(RuntimeError):
            self.controller.run(self.new, self.old)
        self.assertEqual(self.controller.current(), self.old)
        self.assertEqual(json.loads((self.root / 'deployment.json').read_text())['status'], 'rolled_back')
        self.assertEqual(self.actions[-1], ('resume', self.old))

    def test_rollback_failure_is_durable_and_blocks_next(self):
        self.controller.hook = lambda name: (_ for _ in ()).throw(RuntimeError()) if name == 'start' else None
        with self.assertRaises(RuntimeError):
            self.controller.run(self.new, self.old)
        self.assertEqual(json.loads((self.root / 'deployment.json').read_text())['status'], 'rollback_failed')
        with self.assertRaises(ValueError):
            self.controller.run(self.new, self.old)

    def test_stale_request_has_no_side_effect(self):
        with self.assertRaises(ValueError):
            self.controller.run(self.new, 'c' * 40)
        self.assertEqual(self.actions, [])

    def test_tamper_rejected_before_stop(self):
        (self.root / 'releases' / self.new / 'payload' / 'app').write_text('tampered')
        with self.assertRaises(ValueError):
            self.controller.run(self.new, self.old)
        self.assertEqual(self.actions, [])

    def test_symlink_payload_rejected(self):
        (self.root / 'releases' / self.new / 'payload' / 'link').symlink_to('/etc/passwd')
        with self.assertRaises(ValueError):
            self.controller.run(self.new, self.old)

    def test_unsafe_migration_rejected(self):
        manifest = self.root / 'releases' / self.new / 'manifest.json'
        value = json.loads(manifest.read_text()); value['rollback_safe'] = False
        manifest.write_text(json.dumps(value))
        with self.assertRaises(ValueError):
            self.controller.run(self.new, self.old)

    def test_invalid_revision_rejected(self):
        with self.assertRaises(ValueError):
            self.controller.run('../escape', self.old)

    def test_unfinished_transaction_blocks_new_deploy(self):
        (self.root / 'deployment.json').write_text('{"status":"activating"}')
        with self.assertRaises(ValueError):
            self.controller.run(self.new, self.old)
        self.assertEqual(self.actions, [])

    def test_missing_payload_rejected(self):
        import shutil
        shutil.rmtree(self.root / 'releases' / self.new / 'payload')
        with self.assertRaises(ValueError):
            self.controller.run(self.new, self.old)
        self.assertEqual(self.actions, [])

    def test_partial_drain_blocks_retry(self):
        self.controller.hook = lambda name: (_ for _ in ()).throw(RuntimeError()) if name == 'drain' else None
        with self.assertRaises(RuntimeError):
            self.controller.run(self.new, self.old)
        self.assertEqual(self.controller.current(), self.old)
        self.assertEqual(json.loads((self.root / 'deployment.json').read_text())['status'], 'drain_failed')
        with self.assertRaises(ValueError):
            self.controller.run(self.new, self.old)

    def test_lock_blocks_parallel_controller(self):
        import fcntl
        with (self.root / 'deploy.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):
                self.controller.run(self.new, self.old)


if __name__ == '__main__':
    unittest.main()
