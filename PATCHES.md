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
- Add artwork without deleting existing URLs first. Provider failures and
  partial image-download failures cannot clear the old show/season artwork.
  Existing artwork keeps its previous ordering; future preference changes
  will not re-rank an already stored URL automatically.

No user preference file is included or replaced. Do not change existing
`com.plexapp.agents.hama.xml` preferences when deploying this build.

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

The runner command may be prefixed with `kubectl exec -i ... --` for a remote
server. This compilation check does not replace a live canary. The read-only
provider check additionally calls the real resolver:

```sh
python3 scripts/verify_imdb_ids.py --plan /path/to/match-plan.json --output /path/to/results.json
```

Build from a clean committed checkout:

```sh
python3 scripts/build_artifacts.py --scanner-repo /path/to/Absolute-Series-Scanner --output dist
```

The manifest pins both Git commits and every deployment file's SHA-256.
Only the Hama bundle and scanner belong in Plex's plugin/scanner directories.
Preserve a database/plugin/scanner backup and verify exact series IDs,
episode keys/order/files, all-account watch state, and representative anime
metadata during a bounded canary before changing the full library.
