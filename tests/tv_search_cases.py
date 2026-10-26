# -*- coding: utf-8 -*-
"""Shared assertions for source tests and the real Plex Python 2 sandbox."""
import copy
import hashlib
try:
    from urllib.parse import quote
except ImportError:
    from urllib import quote


class Result(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class Namespace(object):
    def __init__(self, **values):
        self.__dict__.update(values)


def run_cases(env):
    records, calls = [], []
    row = {'id': 100, 'name': 'The Pitt', 'original_name': 'The Pitt',
           'first_air_date': '2025-01-09'}
    fixture = {}
    def reset(rows=None):
        fixture.clear()
        fixture.update(search={'results': copy.deepcopy(rows if rows is not None else [row]), 'total_pages': 1},
                       external={'id': 100, 'tvdb_id': 411364}, reverse={'tv_results': [copy.deepcopy(row)]})
        calls[:] = []
    def load(**kwargs):
        calls.append(kwargs)
        if '/tv/101/' in kwargs['url']:
            return {'id': 101, 'tvdb_id': 411365}
        if '/find/411365?' in kwargs['url']:
            return {'tv_results': [dict(row, id=101, first_air_date='2020-01-01')]}
        return copy.deepcopy(fixture['search'] if '/search/' in kwargs['url'] else fixture['reverse'] if '/find/' in kwargs['url'] else fixture['external'])
    env['common'].LoadFile = load
    env.update(String=Namespace(Quote=lambda x: quote(x.encode('utf-8'))),
               Hash=Namespace(SHA1=lambda x: hashlib.sha1(x.encode('utf-8')).hexdigest()),
               CACHE_1DAY=86400, MetadataSearchResult=Result,
               TMDB_API_KEY='fixture', TMDB_TV_EXTERNAL_IDS_URL='https://fixture.invalid/tv/{id}/external_ids',
               TMDB_FIND_TVDB_EPISODE_URL='https://fixture.invalid/find/{id}?language={lang}')
    def search(title='The Pitt', year=None, manual=False, lang='en'):
        results = []
        score = env['SearchTV'](Namespace(Append=results.append), Namespace(show=title, year=year), lang, manual)
        return score, results
    def record(name, okay):
        assert okay, name
        records.append({'name': name, 'passed': True})
    reset()
    score, results = search()
    record('tv_exact_unique_crosschecked', score == 100 and results[0]['id'] == 'tvdb-411364' and results[0]['year'] == 2025 and len(calls) == 3)
    record('tv_cache_and_bounded_query', calls[0]['cache'] == 86400 and 'page=1' in calls[0]['url'] and all(c['sleep'] == 0.1 for c in calls))
    reset()
    record('tv_suffix_year', search('The Pitt (2025)')[0] == 100 and 'first_air_date_year=2025' in calls[0]['url'])
    reset()
    record('tv_conflicting_years_no_request', search('The Pitt (2025)', 2024) == (0, []) and not calls)
    reset()
    record('tv_wrong_premiere_rejected', search(year=2024) == (0, []) and len(calls) == 1)
    reset()
    record('tv_fuzzy_not_forced', search('The Pits') == (0, []))
    for title in ['The Pitt!', 'The-Pitt', 'The_Pitt', '  The  Pitt  ']:
        reset()
        record('tv_punctuation_' + title, search(title)[0] == 100)
    for title in [u'이태원 클라쓰', u'進撃の巨人', u'La casa de papel', u'Marvel’s Show']:
        reset()
        fixture['search']['results'][0]['original_name'] = title
        fixture['reverse']['tv_results'][0]['original_name'] = title
        record('tv_original_name_' + title, search(title)[0] == 100)
        fixture['search']['results'][0]['name'] = title
        fixture['reverse']['tv_results'][0]['name'] = title
        record('tv_unicode_result_' + title, search(title)[1][0]['name'].startswith(title))
    other = dict(row, id=101, first_air_date='2020-01-01')
    reset([row, other])
    record('tv_ambiguous_automatic_rejected', search() == (0, []) and len(calls) == 5)
    reset([row, other])
    record('tv_ambiguous_manual_never_auto_score', search(manual=True)[0] == 79)
    reset([row, other])
    record('tv_year_disambiguates', search(year=2025)[0] == 100)
    reset([row, row])
    record('tv_duplicate_id_is_one_candidate', search()[0] == 100)
    for response in [None, {}, {'results': [], 'total_pages': 0}, {'results': {}, 'total_pages': 1},
                     {'results': [row], 'total_pages': 2}, {'results': [row] * 21, 'total_pages': 1}]:
        reset()
        fixture['search'] = response
        record('tv_missing_failed_or_partial_' + str(len(records)), search() == (0, []) and len(calls) == 1)
    for external in [{'id': 999, 'tvdb_id': 411364}, {'id': 100, 'tvdb_id': 0},
                     {'id': 100, 'tvdb_id': None}, {'id': 100, 'tvdb_id': '12/3'}]:
        reset()
        fixture['external'] = external
        record('tv_bad_external_' + str(len(records)), search() == (0, []))
    for reverse in [None, {'tv_results': []}, {'tv_results': [row, other]},
                    {'tv_results': [dict(row, id=999)]},
                    {'tv_results': [dict(row, first_air_date='2020-01-01')]},
                    {'tv_results': [dict(row, name='Wrong', original_name='Wrong')]}]:
        reset()
        fixture['reverse'] = reverse
        record('tv_bad_reverse_' + str(len(records)), search() == (0, []))
    reset()
    record('tv_bad_year_no_request', search(year='2025&x=1') == (0, []) and not calls)
    reset()
    record('tv_language_guard', search(lang='en&x=1')[0] == 100 and '&language=en&' in calls[0]['url'])
    return records
