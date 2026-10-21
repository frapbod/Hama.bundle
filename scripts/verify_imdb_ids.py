#!/usr/bin/env python3
"""Read-only integration check of the production IMDb resolver against a match plan."""
import argparse
import ast
import concurrent.futures
import datetime
import json
import os
from pathlib import Path
import re
import types
import urllib.error
import urllib.request


def resolver():
    code = Path(__file__).resolve().parents[1] / 'Contents' / 'Code'
    ns = {'os': os, 're': re}
    common = ast.parse((code / 'common.py').read_text())
    functions = [node for node in common.body if isinstance(node, ast.FunctionDef) and node.name == 'Dict']
    exec(compile(ast.Module(body=functions, type_ignores=[]), 'common.Dict', 'exec'), ns)

    def read(**kwargs):
        # Never print URLs or exceptions: the existing application key is in the query.
        req = urllib.request.Request(kwargs['url'], headers={'Accept': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            raise RuntimeError('provider HTTP {}'.format(exc.code)) from None
        except Exception:
            raise RuntimeError('provider request failed') from None

    ns['common'] = types.SimpleNamespace(LoadFile=read)
    source = ast.parse((code / 'TheMovieDb.py').read_text())
    selected = []
    for node in source.body:
        if isinstance(node, ast.FunctionDef) and node.name == 'ResolveTVDBID':
            selected.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id in
                {'TMDB_API_KEY', 'TMDB_FIND_IMDB_URL', 'TMDB_TV_EXTERNAL_IDS_URL'} for target in node.targets):
            selected.append(node)
    exec(compile(ast.Module(body=selected, type_ignores=[]), 'TheMovieDb.ResolveTVDBID', 'exec'), ns)
    return ns['ResolveTVDBID']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--limit', type=int, default=0)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    rows = [row for row in plan['shows'] if row['provider'] == 'imdb']
    if args.limit:
        rows = rows[:args.limit]
    resolve = resolver()

    def check(row):
        result = {'ratingKey': row['ratingKey'], 'title': row['expectedTitle'],
                  'imdbId': row['providerId'], 'expectedTvdbId': str(row['expectedTvdbId'])}
        try:
            result['resolvedTvdbId'] = resolve(row['providerId'])
            result['matches'] = result['resolvedTvdbId'] == result['expectedTvdbId']
        except RuntimeError as exc:
            result['error'] = str(exc)
            result['matches'] = False
        return result

    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(check, rows))
    report = {'observedAt': datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'scope': 'Read-only production resolver calls; exact Sonarr TVDB identity comparison',
              'summary': {'tested': len(results), 'matches': sum(r['matches'] for r in results)},
              'results': results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['summary']))
    for result in results:
        if not result['matches']:
            print(json.dumps(result))
    return 0 if all(r['matches'] for r in results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
