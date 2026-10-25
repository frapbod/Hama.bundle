import types
import unicodedata
import unittest
import test_repairs
from test_repairs import common_namespace, load_functions
from tv_search_cases import run_cases


class TVSearchTests(unittest.TestCase):
    def test_shared_cases(self):
        env = common_namespace()
        env.update(common=types.SimpleNamespace(), unicode=str, unicodedata=unicodedata)
        load_functions('TheMovieDb.py', ['TVTitleKey', 'SearchTV'], env)
        self.assertGreaterEqual(len(run_cases(env)), 40)


class TVRoutingTests(test_repairs.AgentRoutingTests):
    def setUp(self):
        super().setUp()
        from unittest.mock import Mock
        self.general_search = Mock(return_value=100)
        self.ns['TheMovieDb'].SearchTV = self.general_search

    def test_weak_multi_season_anime_falls_back_to_tv(self):
        self.tvdb_search.return_value = 71
        self.search('The Pitt')
        self.general_search.assert_called_once()

    def test_weak_single_season_anime_falls_back_to_tv(self):
        self.media.seasons = {'1': types.SimpleNamespace(episodes={})}
        self.tvdb_search.return_value = 0
        self.search('A Teacher')
        self.anidb_search.assert_called_once()
        self.general_search.assert_called_once()

    def test_strong_anime_keeps_numbering_and_no_new_requests(self):
        self.media.seasons = {'1': types.SimpleNamespace(episodes={})}
        self.anidb_search.return_value = (100, 1)
        self.search('Some Anime')
        self.tvdb_search.assert_not_called()
        self.general_search.assert_not_called()

    def test_strong_multi_season_mapping_keeps_tvdb(self):
        self.search('Some Anime')
        self.general_search.assert_not_called()

    def test_forced_tag_does_not_search_title(self):
        self.search('The Pitt {tvdb-411364}')
        self.search('A Teacher {imdb-tt7654321}')
        self.general_search.assert_not_called()
