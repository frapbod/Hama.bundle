#!/usr/bin/env python3
"""Read-only production title-search probe. No Plex/library/cache writes."""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import re
import types
import unicodedata
import urllib.parse
import urllib.request


def search_namespace():
    code = Path(__file__).resolve().parents[1] / 'Contents/Code'
    ns = dict(os=os, re=re, unicodedata=unicodedata, unicode=str, CACHE_1DAY=86400,
              String=types.SimpleNamespace(Quote=urllib.parse.quote),
              Hash=types.SimpleNamespace(SHA1=lambda s: hashlib.sha1(s.encode()).hexdigest()),
              MetadataSearchResult=lambda **kw: kw)
    helpers = ast.parse((code / 'common.py').read_text())
    exec(compile(ast.Module(body=[n for n in helpers.body if isinstance(n, ast.FunctionDef) and n.name == 'Dict'], type_ignores=[]), '<common>', 'exec'), ns)
    def read(**kwargs):
        # URLs contain the existing provider key. Never print URLs or exceptions.
        try:
            with urllib.request.urlopen(urllib.request.Request(kwargs['url'], headers={'Accept': 'application/json'}), timeout=30) as response:
                return json.load(response)
        except Exception:
            raise RuntimeError('provider request failed') from None
    ns['common'] = types.SimpleNamespace(LoadFile=read)
    tree = ast.parse((code / 'TheMovieDb.py').read_text())
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in ('SearchTV', 'TVTitleKey') or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id.startswith('TMDB_') for t in n.targets)]
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<TheMovieDb>', 'exec'), ns)
    return ns


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases', type=Path, required=True, help='JSON list: title, optional year/manual/lang, expected TVDB IDs')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    ns, report = search_namespace(), []
    for case in json.loads(args.cases.read_text()):
        results = []
        try:
            score = ns['SearchTV'](types.SimpleNamespace(Append=results.append), types.SimpleNamespace(show=case['title'], year=case.get('year')), case.get('lang', 'en'), case.get('manual', False))
            actual = sorted(r['id'] for r in results)
            report.append(dict(case, results=results, score=score, passed=actual == sorted(case['expected'])))
        except RuntimeError as exc:
            report.append(dict(case, error=str(exc), passed=False))
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'tested':len(report), 'passed':sum(r['passed'] for r in report)}))
    return 0 if all(r['passed'] for r in report) else 1


if __name__ == '__main__':
    raise SystemExit(main())
