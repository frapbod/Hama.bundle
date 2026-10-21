#!/usr/bin/env python3
"""Build immutable Hama and ASS artifacts from pinned Git objects."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

ASS_REF = 'b6bfa300332369062b48d17e2277207d1da0a6cd'
ASS_FILE = 'Scanners/Series/Absolute Series Scanner.py'


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root)] + list(args))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--scanner-repo', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if git(root, 'status', '--porcelain').strip():
        raise SystemExit('Build requires a clean committed source checkout')
    commit = git(root, 'rev-parse', 'HEAD').decode().strip()
    files = git(root, 'ls-tree', '-r', '--name-only', commit, 'Contents').decode().splitlines()
    bundle = gzip.compress(git(root, 'archive', '--format=tar', '--prefix=Hama.bundle/', commit), mtime=0)
    scanner = git(args.scanner_repo, 'show', ASS_REF + ':' + ASS_FILE)
    args.output.mkdir(parents=True, exist_ok=True)
    bundle_name = 'Hama.bundle-' + commit[:12] + '.tar.gz'
    (args.output / bundle_name).write_bytes(bundle)
    (args.output / 'Absolute Series Scanner.py').write_bytes(scanner)
    manifest = {
        'hamaCommit': commit,
        'hamaUpstreamBase': 'cfddf8fc5dc37e568aaf004ff36898eb500db40e',
        'scannerCommit': ASS_REF,
        'artifacts': {bundle_name: sha(bundle), 'Absolute Series Scanner.py': sha(scanner)},
        'hamaFiles': {name: sha(git(root, 'show', commit + ':' + name)) for name in files},
    }
    (args.output / 'manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    print(json.dumps({'hamaCommit': commit, 'scannerCommit': ASS_REF, 'artifacts': manifest['artifacts']}, indent=2))


if __name__ == '__main__':
    main()
