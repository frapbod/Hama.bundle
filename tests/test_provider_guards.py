"""Exercise complete provider functions at missing-ID and missing-photo boundaries."""
import ast
from collections import defaultdict
import os
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import xml.etree.ElementTree as ET

CODE = Path(__file__).resolve().parents[1] / 'Contents/Code'


def functions(filename, names, namespace):
    tree = ast.parse((CODE / filename).read_text())
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    # Python 2 permits the upstream nested global declaration after reads;
    # Python 3 requires the same declaration before reads. Its semantics are unchanged.
    class GlobalsFirst(ast.NodeTransformer):
        def visit_Global(self, node):
            declarations.extend(node.names)
            return None
    for function in selected:
        declarations = []
        GlobalsFirst().visit(function)
        if declarations:
            function.body.insert(0, ast.Global(names=sorted(set(declarations))))
    module = ast.fix_missing_locations(ast.Module(body=selected, type_ignores=[]))
    exec(compile(module, filename, 'exec'), namespace)
    return namespace


def common():
    ns = functions('common.py', ['Dict', 'SaveDict', 'natural_sort_key'], {'re': re})
    ns.update(LoadFile=Mock(return_value=None), LoadFileCache=Mock(return_value=(None, 0)),
              WEB_LINK='%s %s', ANIDB_SERIE_URL='https://example.test/anime/', poster_rank=Mock(return_value=1))
    return SimpleNamespace(**ns)


class AniDBTests(unittest.TestCase):
    def setUp(self):
        self.common = common()
        self.ns = functions('AniDB.py', ['GetMetadata'], {
            'common': self.common, 'Dict': self.common.Dict, 'SaveDict': self.common.SaveDict,
            'DictString': lambda value, depth: str(value), 'Log': Mock(), 'os': os, 'basestring': str,
            'AniDBBan': False, 'CACHE_1DAY': 86400, 'CACHE_1HOUR': 3600,
            'ANIDB_HTTP_API_URL': 'https://example.test/anidb?id=', 'ANIDB_PIC_BASE_URL': 'https://example.test/photo/',
            'AnimeLists': SimpleNamespace(anidb_ep=Mock(return_value=('1', '1', 'xxxxxxx'))),
            'GetAniDBTitle': Mock(return_value=('Mapped title', 'Original title', 0)),
            'AniDBTitlesDB': SimpleNamespace(xpath=Mock(return_value=[])),
            'GetXml': lambda xml, path: (xml.find(path).text or '') if isinstance(xml, ET.Element) and xml.find(path) is not None else '',
            'Prefs': {'MinimumWeight': '200', 'AnidbGenresAddWeights': False},
            'summary_sanitizer': lambda value: value,
        })
        self.media = SimpleNamespace(seasons={'1': SimpleNamespace(episodes={'1': object()})})
        self.sets = SimpleNamespace(xpath=Mock(return_value=[]))

    def metadata(self, primary='', mapping=None, movie=False, source='tvdb'):
        return self.ns['GetMetadata'](self.media, movie, defaultdict(list), source, primary, '418424',
                                      self.sets, mapping or {'defaulttvdbseason': '1'})

    def test_unmapped_sentinel_and_invalid_primary_do_not_fetch_anidb(self):
        for primary in (None, '', 'xxxxxxx', '0', '-1'):
            with self.subTest(primary=primary):
                self.assertEqual(self.metadata(primary), ({}, '', {}))
        self.common.LoadFile.assert_not_called()
        self.common.LoadFileCache.assert_not_called()

    def test_missing_primary_keeps_valid_mapped_installment_and_throttle(self):
        self.ns['AnimeLists'].anidb_ep.return_value = ('1', '1', '3433')
        result, _, _ = self.metadata(None, {'defaulttvdbseason': '1', 'TVDB': {'s1': {'3433': '0'}}})
        self.assertEqual(result['title'], 'Mapped title')
        self.common.LoadFile.assert_called_once()
        request = self.common.LoadFile.call_args.kwargs
        self.assertEqual(request['filename'], '3433.xml')
        self.assertEqual(request['sleep'], 6)
        self.assertEqual(request['throttle'], ['AniDB', 3600, 100])

    def test_missing_actor_photo_keeps_name_and_role(self):
        for picture, expected in [('', None), (' picture=""', None), (' picture="actor.jpg"', 'https://example.test/photo/actor.jpg')]:
            with self.subTest(picture=picture):
                role = ET.fromstring('<character><name>Ginko</name><seiyuu' + picture + '>Yuto Nakano</seiyuu></character>')
                xml = SimpleNamespace(xpath=lambda path: [role] if path.startswith('characters/character') else [])
                self.common.LoadFile.return_value = xml
                result, _, _ = self.metadata('3433', movie=True, source='anidb')
                self.assertEqual(result['roles'], [{'name': 'Yuto Nakano', 'role': 'Ginko', 'photo': expected}])
                self.assertFalse(any('Seyiuu error' in str(call) for call in self.ns['Log'].Info.call_args_list))


class AniListTests(unittest.TestCase):
    def setUp(self):
        self.common = common()
        self.query = Mock(return_value=None)
        self.ns = functions('AniList.py', ['GetMetadata'], {
            'common': self.common, 'Dict': self.common.Dict, 'SaveDict': self.common.SaveDict,
            'DictString': lambda value, depth: str(value), 'Log': Mock(), 'os': os, 'basestring': str,
            'MakeGraphqlQuery': self.query, 'ANIME_DATA_DOCUMENT': 'query',
            'ARM_SERVER_URL': 'https://example.test/ids?id={id}',
        })

    def test_invalid_anidb_without_mal_performs_no_requests(self):
        for aid in (None, '', 'xxxxxxx', '0', '-1'):
            self.assertEqual(self.ns['GetMetadata'](aid, None), {})
        self.common.LoadFile.assert_not_called()
        self.query.assert_not_called()

    def test_invalid_anidb_preserves_valid_mal_fallback(self):
        self.assertEqual(self.ns['GetMetadata']('', '457'), {})
        self.common.LoadFile.assert_not_called()
        self.query.assert_called_once_with('query', {'malId': 457})

    def test_valid_anidb_still_uses_arm(self):
        self.common.LoadFile.return_value = {'anilist': 457}
        self.ns['GetMetadata']('3433', None)
        self.common.LoadFile.assert_called_once()
        self.query.assert_called_once_with('query', {'id': 457})


if __name__ == '__main__':
    unittest.main()
