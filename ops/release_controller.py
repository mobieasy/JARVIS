#!/usr/bin/env python3
"""Host-owned, single-writer activation with bounded rollback.

Admin provisions a private policy and fixed executable hooks. A request supplies
only a release ID and expected current ID, never commands, paths or unit names.
No migrations: every accepted manifest must explicitly declare rollback safety.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

REV = re.compile(r"[0-9a-f]{40}")


def atomic_json(path, value):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.record-')
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        dfd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def tree_digest(root):
    """Hash regular files and paths; reject links and special files."""
    if root.is_symlink() or not root.is_dir():
        raise ValueError("payload must be an existing directory")
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('symlinks are forbidden in release payload')
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError('special files are forbidden')
        relative = path.relative_to(root).as_posix().encode()
        digest.update(len(relative).to_bytes(8, 'big'))
        digest.update(relative)
        digest.update(path.stat().st_mode.to_bytes(8, 'big'))
        digest.update(path.stat().st_size.to_bytes(8, 'big'))
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
    return digest.hexdigest()


class Controller:
    def __init__(self, policy):
        self.policy = policy
        self.root = Path(policy['root']).resolve(strict=True)
        self.timeout = policy.get('hook_timeout_seconds', 30)
        if not 1 <= self.timeout <= 120:
            raise ValueError('invalid timeout')

    def hook(self, name):
        # Hooks are fixed host-owned argv lists, not supplied by release manifests.
        subprocess.run(self.policy['hooks'][name], check=True, timeout=self.timeout,
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL, env={'PATH': '/usr/bin:/bin'})

    def candidate(self, revision):
        if not REV.fullmatch(revision):
            raise ValueError('expected full commit SHA')
        release = self.root / 'releases' / revision
        if release.is_symlink() or release.resolve(strict=True) != release:
            raise ValueError('release path is not canonical')
        manifest = json.loads((release / 'manifest.json').read_text())
        if manifest.get('revision') != revision or manifest.get('rollback_safe') is not True:
            raise ValueError('invalid or migration-unsafe manifest')
        if manifest.get('payload_sha256') != tree_digest(release / 'payload'):
            raise ValueError('release digest mismatch')
        return release

    def current(self):
        path = self.root / 'current'
        if not path.is_symlink():
            raise ValueError('current must be an existing release symlink')
        resolved = path.resolve(strict=True)
        if resolved.parent != self.root / 'releases':
            raise ValueError('current escapes releases')
        self.candidate(resolved.name)
        return resolved.name

    def select(self, revision):
        temporary = self.root / '.current-next'
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        temporary.symlink_to(Path('releases') / revision)
        os.replace(temporary, self.root / 'current')

    def run(self, revision, expected):
        with (self.root / 'deploy.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            previous = self.current()
            if previous != expected:
                raise ValueError('current release changed; refusing stale request')
            self.candidate(revision)
            if revision == previous:
                return {'status': 'unchanged', 'revision': revision}
            record = {'revision': revision, 'previous': previous, 'started': time.time(),
                      'status': 'preparing'}
            state = self.root / 'deployment.json'
            if state.exists() and json.loads(state.read_text()).get('status') in {
                    'preparing', 'draining', 'drain_failed', 'activating', 'rolling_back', 'rollback_failed'}:
                raise ValueError('unresolved transaction requires host-admin recovery')
            atomic_json(state, record)
            try:
                self.hook('preflight')
            except Exception:
                record['status'] = 'preflight_failed'
                atomic_json(state, record)
                raise
            record['status'] = 'draining'
            atomic_json(state, record)
            try:
                self.hook('drain')
            except Exception:
                # Drain may have partially paused dispatch; never blindly retry.
                record['status'] = 'drain_failed'
                atomic_json(state, record)
                raise
            record['status'] = 'activating'
            atomic_json(state, record)
            try:
                # Stop then back up: never start a second writer on shared state.
                self.hook('stop')
                self.hook('backup')
                self.select(revision)
                self.hook('start')
                self.hook('ready')
                self.hook('resume')
                record['status'] = 'succeeded'
            except Exception:
                record['status'] = 'rolling_back'
                atomic_json(state, record)
                try:
                    self.hook('stop')
                    self.select(previous)
                    self.hook('start')
                    self.hook('ready')
                    self.hook('resume')
                    record['status'] = 'rolled_back'
                except Exception:
                    record['status'] = 'rollback_failed'
                atomic_json(state, record)
                raise
            record['finished'] = time.time()
            atomic_json(state, record)
            return record


def trusted(path):
    path = Path(path)
    if not path.is_absolute():
        raise ValueError('host policy paths must be absolute')
    for part in [path, *path.parents]:
        stat = part.stat()
        if part.is_symlink() or stat.st_uid != 0 or stat.st_mode & 0o022:
            raise ValueError('host policy, hooks and release paths must be root-owned and not group/world-writable')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--policy', required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--expected-current', required=True)
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run via host-owned root service, not inside agent sandbox')
    trusted(args.policy)
    policy = json.loads(Path(args.policy).read_text())
    trusted(policy['root'])
    for command in policy['hooks'].values():
        if not isinstance(command, list) or not command or not all(isinstance(x, str) for x in command):
            raise ValueError('hooks must be fixed argv lists')
        trusted(command[0])
    for revision in (args.revision, args.expected_current):
        if not REV.fullmatch(revision):
            raise ValueError('invalid revision')
        release = Path(policy['root']) / 'releases' / revision
        for path in [release, *release.rglob('*')]:
            trusted(path)
    print(json.dumps(Controller(policy).run(args.revision, args.expected_current)))


if __name__ == '__main__':
    main()
