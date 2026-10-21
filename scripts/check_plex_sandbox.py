#!/usr/bin/env python3
"""Compile every production file using Plex's installed compiler and Python 2 host.

The runner receives source on stdin and performs no plugin imports or filesystem writes.
Example: ... -- env PYTHONPATH=/.../python27.zip /.../'Plex Script Host' -S
The command can also be prefixed by kubectl exec -i ... -- for a remote runtime.
"""
import argparse
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess

RUNNER = r'''
import sys
sys.dont_write_bytecode = True
import hashlib, json, os
payload = json.load(sys.stdin)
sys.path.insert(0, payload['libraries'])
import RestrictedPython
compiler_hashes = {}
compiler_dir = os.path.dirname(RestrictedPython.__file__)
for name in sorted(os.listdir(compiler_dir)):
    if name.endswith('.py'):
        with open(os.path.join(compiler_dir, name), 'rb') as source_file:
            compiler_hashes[name] = hashlib.sha256(source_file.read()).hexdigest()
try:
    RestrictedPython.compile_restricted('def probe():\n    yield 1\n', '<negative-control>', 'exec', elevated=payload['elevated'])
except SyntaxError as error:
    negative_control = 'Yield statements are not allowed' in str(error)
else:
    negative_control = False
results = []
for name in sorted(payload['sources']):
    try:
        RestrictedPython.compile_restricted(payload['sources'][name].encode('utf-8'), name.encode('utf-8'), 'exec', elevated=payload['elevated'])
        results.append({'file': name, 'compiled': True})
    except Exception as error:
        results.append({'file': name, 'compiled': False, 'error': str(error)})
print(json.dumps({'python': sys.version, 'compilerPath': compiler_dir, 'compilerSha256': compiler_hashes,
                  'elevatedPolicy': payload['elevated'], 'negativeControlRejectedYield': negative_control, 'files': results}))
sys.exit(0 if negative_control and all(row['compiled'] for row in results) else 1)
'''


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    parser.add_argument('--libraries', required=True, help='Installed Plex Framework Shared/Libraries path on the runtime host')
    parser.add_argument('runner', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    runner = args.runner[1:] if args.runner[:1] == ['--'] else args.runner
    if not runner:
        parser.error('provide the Plex Script Host runner after --')
    root = Path(__file__).resolve().parents[1]
    with (root / 'Contents/Info.plist').open('rb') as info_file:
        elevated = plistlib.load(info_file).get('PlexPluginCodePolicy') == 'Elevated'
    sources = {str(path.relative_to(root)): path.read_text() for path in (root / 'Contents/Code').rglob('*.py')}
    payload = {'libraries': args.libraries, 'sources': sources, 'elevated': elevated}
    result = subprocess.run(runner + ['-c', RUNNER], input=json.dumps(payload), text=True, capture_output=True)
    reports = [line for line in result.stdout.splitlines() if line.startswith('{')]
    if reports:
        report = json.loads(reports[-1])
        report['sourceSha256'] = {name: hashlib.sha256(source.encode()).hexdigest() for name, source in sources.items()}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'files': len(report['files']), 'compiled': sum(row['compiled'] for row in report['files']),
                          'negativeControlRejectedYield': report['negativeControlRejectedYield']}))
        for row in report['files']:
            if not row['compiled']:
                print(json.dumps(row))
    if result.stderr:
        print(result.stderr)
    if not reports:
        print('Compiler runner did not return a report: ' + result.stdout[-2000:])
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
