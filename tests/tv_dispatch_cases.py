# -*- coding: utf-8 -*-
"""Integrated Search -> title/year resolver cases, shared with real Plex runtime.

Legacy provider fixtures reproduce its public candidate fields and score, not a
claim that a similarity score or its echoed media.year verifies identity.
"""
import copy
import hashlib
import xml.etree.ElementTree as ET
try:
    from urllib.parse import quote, urlparse, parse_qs
except ImportError:
    from urllib import quote
    from urlparse import urlparse, parse_qs


class Namespace(object):
    def __init__(self, **values):
        self.__dict__.update(values)


class Result(dict):
    __getattr__ = dict.__getitem__
    __setattr__ = dict.__setitem__


class Results(list):
    def Append(self, result):
        self.append(result)


def run_dispatch_cases(provider, agent, common):
    records, calls = [], []
    state = {}
    def load(**kwargs):
        calls.append(kwargs)
        url = kwargs['url']
        if '/search/' in url:
            if state.get('failure'): return None
            rows = copy.deepcopy(state['rows'])
            year = parse_qs(urlparse(url).query).get('first_air_date_year', [''])[0]
            if year: rows = [r for r in rows if r['first_air_date'].startswith(year)]
            return {'results': rows, 'total_pages': state.get('pages', 1)}
        for row in state['rows']:
            if '/tv/' + str(row['id']) + '/' in url:
                return {'id': row['id'], 'tvdb_id': row['tvdb_id']}
            if '/find/' + str(row['tvdb_id']) + '?' in url:
                return {'tv_results': [] if state.get('bad_reverse') else [copy.deepcopy(row)]}
        raise AssertionError('Unexpected provider request')
    common.LoadFile = load
    provider.update(String=Namespace(Quote=lambda s: quote(s.encode('utf-8'))),
                    Hash=Namespace(SHA1=lambda s: hashlib.sha1(s.encode('utf-8')).hexdigest()),
                    CACHE_1DAY=86400, MetadataSearchResult=Result,
                    TMDB_API_KEY='fixture', TMDB_TV_EXTERNAL_IDS_URL='https://fixture.invalid/tv/{id}/external_ids',
                    TMDB_FIND_TVDB_EPISODE_URL='https://fixture.invalid/find/{id}?language={lang}')
    def legacy(results, media, *args):
        for identifier in state['previous']:
            # AniDB echoes the query year, so this field is deliberately untrusted.
            results.Append(Result(id=identifier, score=state.get('score', 100), name=media.show, year=media.year))
        return state.get('score', 100) if state['previous'] else 0
    agent.update(TheMovieDb=Namespace(TVSearchCandidates=provider['TVSearchCandidates'],
                                      ResolveTVDBID=lambda s: '392276'),
                 AniDB=Namespace(Search=lambda *a: (legacy(*a), 1)),
                 TheTVDB=Namespace(Search=legacy), TheTVDBv2=Namespace(SearchResults=Results),
                 AnimeLists=Namespace(AniDBTVDBMap=None), MetadataSearchResult=Result)
    def run(title, year=None, previous=None, manual=False, single=False, **options):
        calls[:] = []
        state.update(previous=previous or [], score=100, failure=False, pages=1, bad_reverse=False)
        state.update(options)
        results = Results()
        media = Namespace(show=title, name='', filename='', year=year, seasons={'1' if single else '2': None})
        agent['Search'](results, media, 'en', manual, False)
        return results
    def record(name, okay):
        assert okay, name
        records.append({'name': name, 'passed': True})
    def rows(title, old, new, old_year, new_year):
        return [dict(id=1, name=title, original_name=title, first_air_date=str(old_year)+'-01-01', tvdb_id=old),
                dict(id=2, name=title, original_name=title, first_air_date=str(new_year)+'-01-01', tvdb_id=new)]
    for title, old, new, old_year, new_year in [
            ('One Piece', 81797, 392276, 1999, 2023),
            ('Alice in Borderland', 289181, 376472, 2014, 2020),
            ('Death Note', 79481, 296956, 2006, 2015)]:
        state['rows'] = rows(title, old, new, old_year, new_year)
        old_id, new_id = 'tvdb-'+str(old), 'tvdb-'+str(new)
        agent['AnimeLists'].AniDBTVDBMap = ET.fromstring('<animelist><anime anidbid="69" tvdbid="%s"/></animelist>' % old)
        for single in (False, True):
            previous = ['anidb-69' if single else old_id]
            for manual in (False, True):
                for suffix in (False, True):
                    result = run(title+' ('+str(new_year)+')' if suffix else title,
                                 None if suffix else new_year, previous, manual, single)
                    record('collision_%s_%s_%s_%s' % (title, single, manual, suffix),
                           [r.id for r in result] == [new_id] and result[0].score == 100 and len(calls) == 3)
            result = run(title, old_year, previous, single=single)
            record('same_anime_numbering_'+title+str(single), [r.id for r in result] == previous)
            record('ambiguous_no_year_auto_'+title+str(single), run(title, previous=previous, single=single) == [])
            result = run(title, previous=previous, single=single, manual=True)
            record('ambiguous_no_year_manual_'+title+str(single),
                   sorted(r.id for r in result) == sorted([old_id, new_id]) and all(r.score == 79 for r in result))
        record('conflicting_year_forms_'+title, run(title+' ('+str(old_year)+')', new_year, [old_id]) == [] and calls == [])
        record('missing_year_match_'+title, run(title, 1900, [old_id]) == [])
        record('provider_failure_'+title, run(title, new_year, [old_id], failure=True) == [])
        record('partial_page_'+title, run(title, new_year, [old_id], pages=2) == [])
        record('bad_reverse_'+title, run(title, new_year, [old_id], bad_reverse=True) == [])
    # An unresolved provider must never promote the old score-100 guess.
    for year in (None, 2023):
        record('failed_no_guess_'+str(year), run('One Piece', year, ['tvdb-81797'], failure=True) == [])
    state['rows'] = []
    record('anime_only_no_year_preserved', run('Anime-only title', previous=['anidb-69'], single=True)[0].id == 'anidb-69')
    record('anime_only_requested_year_unverified', run('Anime-only title', 2023, ['anidb-69'], single=True) == [])
    for title in ('The Pitt!', u'이태원 클라쓰'):
        normalized = 'The Pitt' if title == 'The Pitt!' else title
        state['rows'] = [dict(id=3, name=normalized, original_name=normalized, first_air_date='2025-01-01', tvdb_id=411364)]
        result = run(title, previous=['tvdb-346945'], score=71)
        record('weak_fallback_'+title, [r.id for r in result] == ['tvdb-411364'] and result[0].score == 100)
        record('no_year_conflicting_identity_'+title, run(title, previous=['tvdb-346945']) == [])
        result = run(title, previous=['tvdb-346945'], manual=True)
        record('no_year_conflicting_manual_'+title, len(result) == 1 and result[0].score == 79)
        result = run(title, previous=['tvdb-411364'])
        record('same_mapped_no_year_'+title, len(result) == 1 and result[0].id == 'tvdb-411364' and result[0].score == 100)
    for title, expected in [('Show {tvdb-81797}', 'tvdb-81797'),
                            ('Show {imdb-tt1234567}', 'tvdb-392276'),
                            ('Show [anidb2-69]', 'anidb2-69')]:
        record('tagged_priority_'+expected, run(title, 2023)[0].id == expected and calls == [])
    # An ambiguous Anime-Lists mapping is not proof of same-series numbering.
    state['rows'] = [dict(id=3, name='Anime', original_name='Anime', first_air_date='2025-01-01', tvdb_id=411364)]
    agent['AnimeLists'].AniDBTVDBMap = ET.fromstring('<animelist><anime anidbid="69" tvdbid="411364"/><anime anidbid="69" tvdbid="123"/></animelist>')
    record('ambiguous_mapping_no_year', run('Anime', previous=['anidb-69'], single=True) == [])
    record('ambiguous_mapping_year_uses_verified', run('Anime', 2025, ['anidb-69'], single=True)[0].id == 'tvdb-411364')
    # Movie searches retain the original route and do not call TV identity search.
    for score in (100, 20):
        calls[:] = []
        state.update(previous=['anidb-69'], score=score)
        agent['TheMovieDb'].Search = legacy
        result = Results()
        movie = Namespace(show='', name='Movie', filename='', year=2023, seasons={})
        agent['Search'](result, movie, 'en', False, True)
        record('movie_route_'+str(score), bool(result) and calls == [] and all(r.id == 'anidb-69' for r in result))
    return records
