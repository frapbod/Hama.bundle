import copy
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
from test_provider_guards import common, functions
from test_repairs import common_namespace, refresh_scope


class EpisodeSummaryTests(unittest.TestCase):
    def setUp(self):
        self.common = common()
        self.ns = functions('TheMovieDb.py', ['GetEpisodeSummary', 'FillEpisodeSummaries'], {
            'common': self.common, 'Dict': self.common.Dict, 'SaveDict': self.common.SaveDict,
            'Log': Mock(), 'os': __import__('os'), 're': __import__('re'), 'basestring': str,
            'TMDB_FIND_TVDB_EPISODE_URL': 'https://example.test/find/{id}?language={lang}',
            'TMDB_TV_EXTERNAL_IDS_URL': 'https://example.test/tv/{id}/external_ids',
            'TMDB_EPISODE_EXTERNAL_URL': 'https://example.test/tv/{show}/season/{season}/episode/{episode}/external_ids',
            'Prefs': {'summary': 'TheTVDB, AniDB | TheTVDB, AniDB, TheMovieDb'},
        })
        self.find = {'tv_episode_results': [{'id': 1029387, 'show_id': 1429, 'season_number': 0,
                                           'episode_number': 8, 'overview': ' Correct summary. '}]}
        self.series = {'id': 1429, 'tvdb_id': 267440}
        self.episode = {'id': 1029387, 'tvdb_id': 4791625}
        self.common.LoadFile.side_effect = lambda **kw: copy.deepcopy(
            self.find if '/find/' in kw['url'] else self.episode if '/episode/' in kw['url'] else self.series)

    def test_exact_episode_and_parent_series_ids_are_verified(self):
        self.assertEqual(self.ns['GetEpisodeSummary']('267440', 4791625, 'en'), 'Correct summary.')
        self.assertEqual(self.common.LoadFile.call_count, 3)
        self.assertIn('/season/0/episode/8/', self.common.LoadFile.call_args.kwargs['url'])

    def test_wrong_series_or_episode_identity_fails_closed(self):
        for obj, key in [(self.series, 'tvdb_id'), (self.series, 'id'), (self.episode, 'tvdb_id'), (self.episode, 'id')]:
            with self.subTest(object=obj, key=key):
                saved = obj[key]
                obj[key] = 999
                self.assertEqual(self.ns['GetEpisodeSummary']('267440', 4791625, 'en'), '')
                obj[key] = saved

    def test_missing_ambiguous_or_empty_overview_does_not_guess(self):
        for result in [{}, {'tv_episode_results': self.find['tv_episode_results'] * 2},
                       {'tv_episode_results': [dict(self.find['tv_episode_results'][0], overview=None)]}]:
            with self.subTest(result=result):
                self.find = result
                self.assertEqual(self.ns['GetEpisodeSummary']('267440', 4791625, 'en'), '')

    def test_invalid_external_id_does_not_request(self):
        self.assertEqual(self.ns['GetEpisodeSummary']('267440', 'xxxxxxx', 'en'), '')
        self.common.LoadFile.assert_not_called()

    def test_only_mapped_gaps_request_fallback_and_keep_earlier_sources(self):
        media = SimpleNamespace(seasons={'1': SimpleNamespace(episodes={'1': object(), '2': object(), '3': object(), '4': object()})})
        providers = {'TheTVDB': {'seasons': {'1': {'episodes': {
            '1': {'summary': 'TVDB wins', 'tvdb_id': 1}, '2': {'tvdb_id': 2},
            '3': {'tvdb_id': 4791625}, '4': {}}}}},
            'AniDB': {'seasons': {'1': {'episodes': {'2': {'summary': 'AniDB wins'}}}}}, 'TheMovieDb': {}}
        self.ns['FillEpisodeSummaries'](media, 'en', '267440', providers)
        self.assertEqual(providers['TheMovieDb'], {'seasons': {'1': {'episodes': {'3': {'summary': 'Correct summary.'}}}}})
        self.assertEqual(self.common.LoadFile.call_count, 3)
        self.assertEqual(providers['TheTVDB']['seasons']['1']['episodes']['1']['summary'], 'TVDB wins')
        self.assertEqual(providers['AniDB']['seasons']['1']['episodes']['2']['summary'], 'AniDB wins')

    def test_disabled_episode_fallback_does_not_request(self):
        self.ns['Prefs']['summary'] = 'TheMovieDb | TheTVDB, AniDB'
        self.ns['FillEpisodeSummaries'](SimpleNamespace(seasons={}), 'en', '267440', {})
        self.common.LoadFile.assert_not_called()

    def test_episode_preference_does_not_change_show_or_season_precedence(self):
        ns = common_namespace()
        ns.update(Prefs={'summary': 'TheTVDB, AniDB | TheTVDB, AniDB, TheMovieDb', 'EpisodeLanguagePriority': 'en'},
                  FieldListSeries=('summary',), FieldListMovies=('summary',), FieldListSeasons=('summary',),
                  FieldListEpisodes=('summary',), DictString=lambda *args: '', downloaded={})
        metadata = SimpleNamespace(id='tvdb-267440', summary='', seasons={
            '1': SimpleNamespace(summary='', episodes={'1': SimpleNamespace(summary='')})})
        media = SimpleNamespace(seasons={'1': SimpleNamespace(episodes={'1': object()})})
        sources = {'TheTVDB': {}, 'AniDB': {'summary': 'AniDB show', 'seasons': {'1': {'summary': 'AniDB season'}}},
                   'TheMovieDb': {'summary': 'TMDb show', 'seasons': {'1': {'summary': 'TMDb season',
                                  'episodes': {'1': {'summary': 'TMDb episode'}}}}}}
        ns['UpdateMeta'](metadata, media, False, sources, {})
        self.assertEqual(metadata.summary, 'AniDB show')
        self.assertEqual(metadata.seasons['1'].summary, 'AniDB season')
        self.assertEqual(metadata.seasons['1'].episodes['1'].summary, 'TMDb episode')

    def test_forced_fallback_refresh_bypasses_both_caches(self):
        ns = common_namespace()
        ns.update(LoadFileCache=Mock(return_value=({'old': True}, 30)),
                  HTTP=SimpleNamespace(Request=Mock(return_value=SimpleNamespace(content='{"new":true}'))),
                  ObjectFromFile=__import__('json').loads, SaveFile=Mock())
        with refresh_scope(ns, True):
            result = ns['LoadFile']('episode.json', 'TheMovieDb/episodes', 'https://example.test/episode')
        self.assertEqual(result, {'new': True})
        self.assertEqual(ns['HTTP'].Request.call_args.kwargs['cacheTime'], 0)


if __name__ == '__main__':
    unittest.main()
