# Maintained repair build

Kai requested: “do a patched update”.

This branch starts at upstream Hama commit
`cfddf8fc5dc37e568aaf004ff36898eb500db40e` and keeps its AniDB mappings,
metadata preferences, and Absolute Series Scanner integration. Deploy with ASS
commit `b6bfa300332369062b48d17e2277207d1da0a6cd`.

## Patch boundary

- Use the working TVDB legacy API until the v4 module has an actual API key,
  following [upstream PR #611](https://github.com/ZeroQI/Hama.bundle/pull/611).
  The default v4 key shipped upstream is `TODO` and cannot authenticate.
- Honor a forced refresh for TVDB series/episode metadata. Bypass both the
  agent's local `TheTVDB/json` or `TheTVDBv4/json` cache and the Plex HTTP cache.
  The same bypass applies to the new `TheMovieDb/episodes` summary fallback.
  The override is thread-local, nested-safe, and restored after exceptions.
  A failed download retains existing cached metadata and logs the failure.
- Keep AniDB's adaptive cache, six-second delay, and 100-request/hour throttle.
  Shared title databases, Anime-Lists mappings, artwork files, and other
  provider caches are not force-invalidated. This avoids turning a library
  refresh into repeated AniDB or shared mapping downloads.
- Recognize square and curly forced IDs. Resolve TV IMDb IDs using TMDb's
  exact external-ID endpoints, require one TV result, and cross-check its IMDb
  and TMDb IDs before accepting a positive TVDB ID. Missing or ambiguous
  identities produce no match rather than a fuzzy title fallback. Existing
  explicit AniDB and TVDB numbering modes are preserved.
- Restore untagged general-TV searches through TMDb's supported TV search API.
  The shared dispatcher collects legacy anime candidates before publishing any
  result. An anime similarity score, even 100, is not title/year identity proof:
  AniDB ignores the requested premiere year and echoes it in its result.
  Every untagged TV query now checks exact normalized localized/original titles
  and a supplied premiere year or trailing `(YYYY)`, including high-scoring anime
  collisions. A unique candidate must pass the TMDb external-ID lookup and a
  unique reverse TVDB-ID lookup with the same TMDb ID, title and premiere date.
  A verified same-series Anime-Lists mapping keeps the original anime numbering;
  with a requested year, conflicting/unverified legacy identities are discarded.
  Without a year, multiple exact identities or a conflicting strong anime
  candidate are ambiguous: automatic searches return nothing and manual choices
  remain at 79. Failed/incomplete provider or external-ID evidence returns no
  result, not the old anime guess. A complete search with no exact title retains
  the existing anime-only path only when no premiere year was requested.
  Tagged IDs and movie searches bypass this reconciliation entirely. Field-source
  preferences, metadata updates and numbering maps are unchanged. No title-specific
  rules or confidence-threshold bumps are used. Add a premiere year or explicit
  provider tag when evidence is ambiguous or unavailable.
  A complete page is capped at 20 entries: up to 41 provider reads per search
  (normally 3 for one exact candidate). This also applies to automatic ambiguity
  checks. Search results use a one-day cache; identity reads reuse the existing
  cache. New uncached reads use the existing serialized loader with 100 ms spacing;
  no retries or new credentials are added. Untagged anime search now depends on
  this provider being available; tagged anime and metadata updates do not.
- Add artwork without deleting existing URLs first. Provider failures and
  partial image-download failures cannot clear the old show/season artwork.
  Existing artwork keeps its previous ordering; future preference changes
  will not re-rank an already stored URL automatically.
- Skip AniDB and AniList ID lookups for absent or invalid AniDB identifiers.
  Valid mapped installments and the AniList MAL-ID fallback still run. Keep
  voice-actor names and roles when AniDB has no actor photo.
- Fill episode-summary gaps through TMDb only when earlier configured
  providers have no summary. Carry the exact TVDB episode ID through Hama's
  numbering map, find it through TMDb's external-ID endpoint, and cross-check
  both the episode and parent show's external IDs. Do not guess by season
  number or title. Ambiguous IDs or failed checks leave the gap unchanged.

No user preference file is included or replaced. To enable the episode
fallback on an existing installation, preserve the current summary source
order and append `TheMovieDb` only to the episode half after `|`. For example,
`TheTVDB, AniDB` becomes `TheTVDB, AniDB | TheTVDB, AniDB, TheMovieDb`.
All other values in `com.plexapp.agents.hama.xml` stay unchanged. The default
for new installations follows that same split; show and season precedence
remains unchanged.

In Plex's legacy agent settings, put **HamaTV** before **Local Media Assets
(TV)** under **Shows > HamaTV**. Keep Local Media Assets enabled for local
subtitles and artwork. If it comes first, embedded release titles or encoder
comments can replace Hama's episode titles and summaries during Plex's final
metadata combination, even after a successful Hama update. Refresh affected
shows after changing the order and verify the published text. This Plex source
priority is separate from Hama's per-field provider preferences above.

## Validation and build

Run the production-function tests with boundary doubles:

```sh
python3 -W ignore::SyntaxWarning -m unittest discover -s tests -v
```

The tests exercise provider dispatch, forced IDs, cache freshness/failure,
parallel and exceptional refreshes, and artwork preservation. Compile every
production file with the target server's installed RestrictedPython compiler
and Plex Script Host before deploying. Ordinary Python 2 syntax checks do not
catch Plex's prohibition on generators, including `contextmanager` helpers.
The smoke check reads the bundle's existing code policy, rejects a `yield`
negative control, and records compiler and source hashes without importing
the plugin or writing to the server:

```sh
python3 scripts/check_plex_sandbox.py \
  --libraries /path/to/Framework.bundle/Contents/Resources/Platforms/Shared/Libraries \
  --output /path/to/compiler-report.json \
  -- env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/path/to/Resources/Python/python27.zip \
  '/path/to/Plex Script Host' -S
```

Also execute the fallback using the target's actual restricted builtins and
Elevated-policy globals. Compiling alone cannot detect unavailable runtime
names: Plex omits `any()` and `all()` even on its Python 2.7 host. The runtime
check reads the installed environment definitions, executes the production
module against in-memory provider fixtures, checks identity rejection and
source precedence, and proves both unsupported calls fail. It writes no
plugin state and makes no provider requests:

```sh
python3 scripts/check_plex_runtime.py \
  --libraries /path/to/Framework.bundle/Contents/Resources/Platforms/Shared/Libraries \
  --output /path/to/runtime-report.json \
  -- env PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/path/to/Resources/Python/python27.zip \
  '/path/to/Plex Script Host' -S
```

Both runner commands may be prefixed with `kubectl exec -i ... --` for a remote
server. These checks do not replace a live canary that reaches Hama's final
`UpdateMeta` and `end` log entries; Plex can publish old metadata after an
agent exception. The read-only provider check also calls the real resolver:

```sh
python3 scripts/verify_imdb_ids.py --plan /path/to/match-plan.json --output /path/to/results.json
```

Read-only live title-search verification uses a JSON list of cases with `title`,
optional `year`/`manual`/`lang`, and `expected` TVDB GUIDs (for example,
`[{"title":"Breaking Bad","expected":["tvdb-81189"]}]`). Ground expectations in
an independent provider or the already-verified library identity, not in the
new search result itself. Ambiguous/missing cases use an empty expected list.

```sh
python3 scripts/verify_tv_search.py --cases /path/to/cases.json --output /path/to/results.json
```

This probe executes production functions against live TMDb, with no Plex writes.
It is not a deployed-agent canary. The RestrictedPython runner also executes the
shared title-search cases and real agent dispatch for tagged IDs/anime priority.
Integrated cases cover live-action/anime name collisions through the actual Search
function, both explicit/trailing years, single/multi-season numbering, automatic
and manual ambiguity, provider failure, partial pages, mapping conflicts and
missing results. These run with the same source fixtures under Python 3 and the
installed Plex Python 2 RestrictedPython environment; a provider-only pass does
not establish dispatcher correctness.

Build from a clean committed checkout:

```sh
python3 scripts/build_artifacts.py --scanner-repo /path/to/Absolute-Series-Scanner --output dist
```

The manifest pins both Git commits and every deployment file's SHA-256.
Only the Hama bundle and scanner belong in Plex's plugin/scanner directories.
Preserve a database/plugin/scanner backup and verify exact series IDs,
episode keys/order/files, all-account watch state, and representative anime
metadata during a bounded canary before changing the full library.
