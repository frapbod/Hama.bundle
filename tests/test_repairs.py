"""Execute production functions with small Plex boundary doubles; no network required."""
import ast
import datetime
import json
import os
import re
import threading
import types
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import Mock

CODE = Path(__file__).resolve().parents[1] / 'Contents' / 'Code'


def load_functions(filename, names, namespace):
    tree = ast.parse((CODE / filename).read_text())
    selected = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names]
    assert {n.name for n in selected} == set(names)
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(CODE / filename), 'exec'), namespace)
    return namespace


def common_namespace():
    ns = {'re': re, 'os': os, 'threading': threading, 'tlocal': threading.local(),
          'contextmanager': contextmanager, 'Log': Mock(), 'CACHE_1DAY': 86400,
          'COMMON_HEADERS': {}, 'netLock': threading.Lock(), 'netLocked': {},
          'time': types.SimpleNamespace(time=lambda: 1, sleep=Mock()), 'basestring': str}
    return load_functions('common.py', ['Dict', 'UpdateDict', 'ForceTVDBRefresh', 'LoadFile',
                                       'natural_sort_key', 'UpdateMeta', 'UpdateMetaField'], ns)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.ns = common_namespace()
        self.stale = {'title': 'TBA'}
        self.request = Mock(return_value=types.SimpleNamespace(content='{"title":"Correct title"}'))
        self.saved = Mock()
        self.ns.update(LoadFileCache=Mock(return_value=(self.stale, 30)),
                       HTTP=types.SimpleNamespace(Request=self.request),
                       ObjectFromFile=json.loads, SaveFile=self.saved)

    def read(self, directory='TheTVDB/json/384541'):
        return self.ns['LoadFile'](filename='episodes.json', relativeDirectory=directory,
                                   url='https://example.test/episodes')

    def test_ordinary_refresh_uses_fresh_disk_cache(self):
        self.assertIs(self.read(), self.stale)
        self.request.assert_not_called()

    def test_forced_refresh_bypasses_disk_and_http_cache_and_saves_result(self):
        with self.ns['ForceTVDBRefresh'](True):
            self.assertEqual(self.read(), {'title': 'Correct title'})
        self.assertEqual(self.request.call_args.kwargs['cacheTime'], 0)
        self.saved.assert_called_once()

    def test_v4_and_windows_cache_paths_are_also_bypassed(self):
        with self.ns['ForceTVDBRefresh'](True):
            self.assertEqual(self.read('TheTVDBv4\\json\\384541'), {'title': 'Correct title'})
        self.assertEqual(self.request.call_args.kwargs['cacheTime'], 0)

    def test_anidb_and_shared_mapping_caches_are_not_bypassed(self):
        with self.ns['ForceTVDBRefresh'](True):
            for directory in ['AniDB/xml', 'AniDB', 'AnimeLists', '', 'TheMovieDb/identity']:
                self.assertIs(self.read(directory), self.stale)
        self.request.assert_not_called()

    def test_failed_forced_fetch_keeps_old_data_and_does_not_save(self):
        self.request.side_effect = IOError('provider unavailable')
        with self.ns['ForceTVDBRefresh'](True):
            self.assertIs(self.read(), self.stale)
        self.saved.assert_not_called()
        self.assertFalse(self.ns['netLocked']['LoadFile'][0])

    def test_context_cleans_up_after_exception_and_nested_context(self):
        with self.assertRaises(RuntimeError):
            with self.ns['ForceTVDBRefresh'](True):
                with self.ns['ForceTVDBRefresh'](False):
                    self.assertTrue(self.ns['tlocal'].force_tvdb_refresh)
                raise RuntimeError('update failed')
        self.assertFalse(self.ns['tlocal'].force_tvdb_refresh)
        self.assertIs(self.read(), self.stale)

    def test_parallel_normal_update_is_not_forced(self):
        observations = []
        with self.ns['ForceTVDBRefresh'](True):
            thread = threading.Thread(target=lambda: observations.append(self.read()))
            thread.start()
            thread.join()
        self.assertEqual(observations, [self.stale])
        self.request.assert_not_called()

    def test_expired_nonforced_cache_retains_standard_http_policy(self):
        self.ns['LoadFileCache'].return_value = (self.stale, 7 * 86400)
        self.assertEqual(self.read(), {'title': 'Correct title'})
        self.assertEqual(self.request.call_args.kwargs['cacheTime'], 86400)


class IdentityTests(unittest.TestCase):
    def setUp(self):
        self.loader = Mock(side_effect=[{'tv_results': [{'id': 123}]},
                                       {'id': 123, 'imdb_id': 'tt7654321', 'tvdb_id': 456}])
        self.ns = common_namespace()
        self.ns.update(common=types.SimpleNamespace(LoadFile=self.loader),
                       TMDB_FIND_IMDB_URL='https://example.test/find/{id}',
                       TMDB_TV_EXTERNAL_IDS_URL='https://example.test/tv/{id}/external_ids')
        load_functions('TheMovieDb.py', ['ResolveTVDBID'], self.ns)

    def resolve(self, imdb='tt7654321'):
        return self.ns['ResolveTVDBID'](imdb)

    def test_exact_external_identity_returns_tvdb(self):
        self.assertEqual(self.resolve(), '456')
        self.assertEqual(self.loader.call_count, 2)

    def test_invalid_id_never_contacts_provider(self):
        self.assertEqual(self.resolve('tt123/../../other'), '')
        self.loader.assert_not_called()

    def test_movie_only_or_ambiguous_results_do_not_fall_back_to_title(self):
        for response in [{'movie_results': [{'id': 123}]}, {'tv_results': []},
                         {'tv_results': [{'id': 123}, {'id': 124}]}, {'tv_results': {'id': 123}}, None]:
            self.loader.side_effect = [response]
            self.assertEqual(self.resolve(), '')

    def test_external_id_conflicts_and_missing_tvdb_are_rejected(self):
        for external in [{'id': 123, 'imdb_id': 'tt0000001', 'tvdb_id': 456},
                         {'id': 999, 'imdb_id': 'tt7654321', 'tvdb_id': 456},
                         {'id': 123, 'imdb_id': 'tt7654321', 'tvdb_id': None},
                         {'id': 123, 'imdb_id': 'tt7654321', 'tvdb_id': 0}]:
            self.loader.side_effect = [{'tv_results': [{'id': 123}]}, external]
            self.assertEqual(self.resolve(), '')


class AgentRoutingTests(unittest.TestCase):
    def setUp(self):
        self.ns = common_namespace()
        self.log = self.ns['Log']
        self.common = types.SimpleNamespace(Log=self.log, ForceTVDBRefresh=self.ns['ForceTVDBRefresh'])
        self.resolver = Mock(return_value='456')
        self.anidb_search = Mock(return_value=(0, 0))
        self.tvdb_search = Mock(return_value=100)
        self.ns.update(common=self.common, datetime=datetime,
                       TheMovieDb=types.SimpleNamespace(ResolveTVDBID=self.resolver),
                       AniDB=types.SimpleNamespace(Search=self.anidb_search),
                       TheTVDB=types.SimpleNamespace(Search=self.tvdb_search),
                       MetadataSearchResult=lambda **kwargs: kwargs)
        load_functions('__init__.py', ['Search', 'Update'], self.ns)
        self.media = types.SimpleNamespace(show='', name='', filename='', year=2024,
                                           seasons={'2': types.SimpleNamespace(episodes={})})
        # Search imports common.Log inside the function, just as Plex does.
        self.module_patch = unittest.mock.patch.dict('sys.modules', {'common': self.common})
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)

    def search(self, title):
        self.media.show = title
        results = []
        collection = types.SimpleNamespace(Append=results.append)
        self.ns['Search'](collection, self.media, 'en', False, False)
        return results

    def test_curly_imdb_folder_resolves_exact_tvdb_guid_without_name_search(self):
        result = self.search('A Teacher (2020) {imdb-tt7654321}')
        self.assertEqual(result[0]['id'], 'tvdb-456')
        self.resolver.assert_called_once_with('tt7654321')
        self.anidb_search.assert_not_called()
        self.tvdb_search.assert_not_called()

    def test_square_and_curly_tvdb_and_anime_modes_keep_identity(self):
        for title, guid in [('Show [tvdb-123]', 'tvdb-123'), ('Show {tvdb-123}', 'tvdb-123'),
                            ('Show [tvdb4-123]', 'tvdb4-123'), ('Show [anidb2-123]', 'anidb2-123')]:
            self.assertEqual(self.search(title)[0]['id'], guid)

    def test_unresolvable_forced_id_never_fuzzy_matches(self):
        self.resolver.return_value = ''
        self.assertEqual(self.search('A Teacher {imdb-tt7654321}'), [])
        self.assertEqual(self.search('Show [tvdb-not-a-number]'), [])
        self.assertEqual(self.search('Show {tvdb-0}'), [])
        self.anidb_search.assert_not_called()
        self.tvdb_search.assert_not_called()

    def test_unforced_later_season_uses_selected_tvdb_provider(self):
        self.search('Some Anime')
        self.tvdb_search.assert_called_once()

    def test_provider_dispatch_uses_legacy_until_real_v4_key_exists(self):
        tree = ast.parse((CODE / '__init__.py').read_text())
        assignment = next(n for n in tree.body if isinstance(n, ast.Assign) and
                          any(isinstance(t, ast.Name) and t.id == 'TheTVDB' for t in n.targets))
        v2 = object()
        for key in ['', 'TODO', 'configured-key']:
            v4 = types.SimpleNamespace(TVDB_API_KEY=key)
            ns = {'TheTVDBv2': v2, 'TheTVDBv4': v4}
            exec(compile(ast.Module(body=[assignment], type_ignores=[]), '<provider dispatch>', 'exec'), ns)
            self.assertIs(ns['TheTVDB'], v4 if key == 'configured-key' else v2)

    def test_update_exception_restores_refresh_context_and_closes_log(self):
        self.ns['UpdateMetadata'] = Mock(side_effect=RuntimeError('provider failed'))
        with self.assertRaises(RuntimeError):
            self.ns['Update'](object(), self.media, 'en', True, False)
        self.assertFalse(self.ns['tlocal'].force_tvdb_refresh)
        self.log.Close.assert_called_once()


class ArtworkTests(unittest.TestCase):
    class Artwork(dict):
        def validate_keys(self, keys):
            for key in list(self):
                if key not in keys:
                    del self[key]

    def setUp(self):
        self.ns = common_namespace()
        self.ns.update(Prefs={'posters': 'TheTVDB', 'EpisodeLanguagePriority': 'en'},
                       FieldListSeries=('posters',), FieldListMovies=('posters',),
                       FieldListSeasons=('posters',), FieldListEpisodes=(),
                       DictString=lambda *args: '', metadata_download=Mock(), downloaded={})
        self.metadata = types.SimpleNamespace(id='tvdb-123', posters=self.Artwork({'old-show': 'selected'}),
                                             seasons={})
        for number in ['1', '2']:
            self.metadata.seasons[number] = types.SimpleNamespace(
                posters=self.Artwork({'old-season-' + number: 'selected'}), episodes={})
        self.media = types.SimpleNamespace(seasons={number: types.SimpleNamespace(episodes={}) for number in ['1', '2']})

    def update(self, data):
        self.ns['UpdateMeta'](self.metadata, self.media, False, {'TheTVDB': data}, {})

    def test_provider_failure_preserves_show_and_every_season_artwork(self):
        self.update({})
        self.assertEqual(dict(self.metadata.posters), {'old-show': 'selected'})
        for number in ['1', '2']:
            self.assertEqual(dict(self.metadata.seasons[number].posters), {'old-season-' + number: 'selected'})

    def test_failed_image_downloads_preserve_existing_artwork(self):
        self.update({'posters': {'new-show': ('image.jpg', 1, None)},
                     'seasons': {'2': {'posters': {'new-season': ('season.jpg', 1, None)}}}})
        self.assertEqual(dict(self.metadata.posters), {'old-show': 'selected'})
        self.assertEqual(dict(self.metadata.seasons['2'].posters), {'old-season-2': 'selected'})

    def test_partial_success_adds_valid_image_without_pruning_other_seasons(self):
        def download(root, artwork, url, *args):
            if url == 'good-image':
                artwork[url] = 'downloaded'
        self.ns['metadata_download'] = download
        self.update({'seasons': {'1': {'posters': {'good-image': ('a.jpg', 1, None), 'bad-image': ('b.jpg', 2, None)}}}})
        self.assertEqual(dict(self.metadata.seasons['1'].posters),
                         {'old-season-1': 'selected', 'good-image': 'downloaded'})
        self.assertEqual(dict(self.metadata.seasons['2'].posters), {'old-season-2': 'selected'})


if __name__ == '__main__':
    unittest.main()
