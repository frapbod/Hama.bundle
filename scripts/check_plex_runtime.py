#!/usr/bin/env python3
"""Execute repaired metadata functions with Plex's installed restricted globals.

The target host supplies Sandbox's environment expression, ElevatedPolicy, and
safe_builtins. Provider responses are in-memory fixtures: no plugin, database,
cache, or network writes. Sources and fixtures arrive only on stdin.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import subprocess

RUNNER = r'''
import sys
sys.dont_write_bytecode = True
import ast, binascii, copy, hashlib, json, os, re, types, __builtin__
payload = json.load(sys.stdin)
sys.path.insert(0, payload['libraries'])
import RestrictedPython
from RestrictedPython.Guards import safe_builtins
framework = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(payload['libraries']))), 'Versions', '2', 'Python', 'Framework')
paths = {'sandbox': os.path.join(framework, 'code', 'sandbox.py'),
         'policy': os.path.join(framework, 'policies', 'elevatedpolicy.py'),
         'guards': os.path.join(os.path.dirname(RestrictedPython.__file__), 'Guards.py')}
installed = dict((key, open(path, 'rb').read()) for key, path in paths.items())
class Namespace(object):
    def __init__(self, **values): self.__dict__.update(values)
Framework = Namespace(exceptions=Namespace(FrameworkException=Exception), Object=object)
outer = dict(globals(), __builtins__=__builtin__.__dict__)
trees = dict((name, ast.parse(installed[name])) for name in ('sandbox', 'policy'))
for name in ('sandbox', 'policy'):
    nodes = [n for n in trees[name].body if isinstance(n, ast.FunctionDef) and n.name in ('_apply', '_inplacevar', '_super') or isinstance(n, ast.ClassDef) and n.name == 'PrintHandler']
    exec(compile(ast.Module(body=nodes), '<installed-support>', 'exec'), outer)
standard_builtins = dict(safe_builtins)
outer['standard_builtins'] = standard_builtins
sandbox_class = next(n for n in trees['sandbox'].body if isinstance(n, ast.ClassDef) and n.name == 'Sandbox')
initializer = next(n for n in sandbox_class.body if isinstance(n, ast.FunctionDef) and n.name == '__init__')
environment = next(n.value for n in initializer.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Attribute) and t.attr == 'environment' for t in n.targets))
env = eval(compile(ast.Expression(environment), '<installed-sandbox-environment>', 'eval'), outer)
policy_class = next(n for n in trees['policy'].body if isinstance(n, ast.ClassDef) and n.name == 'ElevatedPolicy')
policy_environment = next(n.value for n in policy_class.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'environment' for t in n.targets))
env.update(eval(compile(ast.Expression(policy_environment), '<installed-elevated-environment>', 'eval'), outer))
available_globals = set(env) | set(standard_builtins)
unsupported = {}
for name, source in payload['addedCode'].items():
    calls = set(n.func.id for n in ast.walk(ast.parse(source.encode('utf-8'))) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name))
    missing = sorted((calls & set(dir(__builtin__))) - available_globals)
    if missing: unsupported[name] = missing
assert not unsupported, unsupported
negative = {}
for name in ('any', 'all'):
    try:
        exec(RestrictedPython.compile_restricted('result = ' + name + '([True])', '<negative-control>', 'exec', elevated=True), dict(env))
    except NameError as error:
        negative[name] = name in str(error)
    else:
        negative[name] = False
assert all(negative.values())
common = types.ModuleType('common')
helper_env = dict(env)
exec(RestrictedPython.compile_restricted(payload['commonHelpers'].encode('utf-8'), '<production-common>', 'exec', elevated=True), helper_env)
common.Dict = helper_env['Dict']
common.SaveDict = helper_env['SaveDict']
common.DictString = lambda *args: ''
common.Log = Namespace(Info=lambda *args: None)
requests = []
fixture = {'find': {'tv_episode_results': [{'id': 1029387, 'show_id': 1429, 'season_number': 0,
            'episode_number': 8, 'overview': ' Correct summary. '}]},
           'series': {'id': 1429, 'tvdb_id': 267440},
           'episode': {'id': 1029387, 'tvdb_id': 4791625}}
def load(**kwargs):
    url = kwargs['url']
    requests.append(url)
    return copy.deepcopy(fixture['find'] if '/find/' in url else fixture['episode'] if '/episode/' in url else fixture['series'])
common.LoadFile = load
def import_fixture(name, *args):
    if name == 'common': return common
    if name == 'os': return os
    if name == 're': return re
    raise ImportError('Unexpected production import: ' + name)
standard_builtins['__import__'] = import_fixture
env.update(Prefs={'summary': 'TheTVDB, AniDB | TheTVDB, AniDB, TheMovieDb'})
exec(RestrictedPython.compile_restricted(payload['source'].encode('utf-8'), 'Contents/Code/TheMovieDb.py', 'exec', elevated=True), env)
env.update(TMDB_FIND_TVDB_EPISODE_URL='https://fixture.invalid/find/{id}?language={lang}',
           TMDB_TV_EXTERNAL_IDS_URL='https://fixture.invalid/tv/{id}/external_ids',
           TMDB_EPISODE_EXTERNAL_URL='https://fixture.invalid/tv/{show}/season/{season}/episode/{episode}/external_ids')
tests = []
def record(name, okay):
    tests.append({'name': name, 'passed': bool(okay)})
    assert okay, name
record('exact_episode_summary', env['GetEpisodeSummary']('267440', '4791625', 'en') == 'Correct summary.' and len(requests) == 3)
for object_name, field in (('series', 'tvdb_id'), ('series', 'id'), ('episode', 'tvdb_id'), ('episode', 'id')):
    old = fixture[object_name][field]
    fixture[object_name][field] = 999
    record('reject_' + object_name + '_' + field, env['GetEpisodeSummary']('267440', '4791625', 'en') == '')
    fixture[object_name][field] = old
saved_find = copy.deepcopy(fixture['find'])
fixture['find']['tv_episode_results'][0]['season_number'] = 'invalid'
record('reject_invalid_episode_number', env['GetEpisodeSummary']('267440', '4791625', 'en') == '')
fixture['find'] = saved_find
media = Namespace(seasons={'1': Namespace(episodes={'1': object(), '2': object(), '3': object()})})
providers = {'TheTVDB': {'seasons': {'1': {'episodes': {'1': {'summary': 'TVDB wins', 'tvdb_id': 1},
             '2': {'tvdb_id': 2}, '3': {'tvdb_id': 4791625}}}}},
             'AniDB': {'seasons': {'1': {'episodes': {'2': {'summary': 'AniDB wins'}}}}}, 'TheMovieDb': {}}
requests[:] = []
env['FillEpisodeSummaries'](media, 'en', '267440', providers)
record('fills_only_gap_and_preserves_priority', providers['TheMovieDb'] == {'seasons': {'1': {'episodes': {'3': {'summary': 'Correct summary.'}}}}} and len(requests) == 3)
record('preferred_sources_unchanged', common.Dict(providers, 'TheTVDB', 'seasons', '1', 'episodes', '1', 'summary') == 'TVDB wins' and common.Dict(providers, 'AniDB', 'seasons', '1', 'episodes', '2', 'summary') == 'AniDB wins')
env['Prefs']['summary'] = 'TheTVDB, AniDB'
requests[:] = []
env['FillEpisodeSummaries'](media, 'en', '267440', providers)
record('disabled_fallback_no_requests', requests == [])
print(json.dumps({'python': sys.version, 'installedPaths': paths,
                  'installedSha256': dict((name, hashlib.sha256(value).hexdigest()) for name, value in installed.items()),
                  'environmentNames': sorted(available_globals), 'unsupportedAddedBuiltins': unsupported,
                  'negativeControls': negative, 'tests': tests}))
'''


def selected_functions(source, names):
    tree = ast.parse(source)
    return '\n\n'.join(ast.get_source_segment(source, node) for node in tree.body
                       if isinstance(node, ast.FunctionDef) and node.name in names)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--libraries', required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('runner', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    runner = args.runner[1:] if args.runner[:1] == ['--'] else args.runner
    if not runner:
        parser.error('provide the Plex Script Host runner after --')
    root = Path(__file__).resolve().parents[1]
    source = (root / 'Contents/Code/TheMovieDb.py').read_text()
    helpers = selected_functions((root / 'Contents/Code/common.py').read_text(), ('Dict', 'SaveDict'))
    changed_modules = ('AniDB.py', 'AniList.py', 'TheMovieDb.py', 'TheTVDBv2.py',
                       'TheTVDBv4.py', '__init__.py', 'common.py')
    added = {name: (root / 'Contents/Code' / name).read_text() for name in changed_modules}
    payload = {'libraries': args.libraries, 'source': source, 'commonHelpers': helpers, 'addedCode': added}
    result = subprocess.run(runner + ['-c', RUNNER], input=json.dumps(payload), text=True, capture_output=True)
    reports = [line for line in result.stdout.splitlines() if line.startswith('{')]
    okay = False
    if reports:
        report = json.loads(reports[-1])
        report['sourceSha256'] = hashlib.sha256(source.encode()).hexdigest()
        okay = (len(report.get('tests', [])) == 9 and all(t['passed'] for t in report['tests'])
                and report['negativeControls'] == {'any': True, 'all': True}
                and not report['unsupportedAddedBuiltins'])
        if args.output:
            args.output.write_text(json.dumps(report, indent=2) + '\n')
        print(json.dumps({'runtimeCases': len(report['tests']), 'passed': okay,
                          'negativeControls': report['negativeControls']}))
    else:
        print('Runtime runner did not return a report')
    if result.stderr:
        print(result.stderr)
    return result.returncode or (0 if okay else 1)


if __name__ == '__main__':
    raise SystemExit(main())
