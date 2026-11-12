# Fork notes (h0nz1k/homeassistant_philips_homeid)

This is a fork of
[renaudallard/homeassistant_philips_homeid](https://github.com/renaudallard/homeassistant_philips_homeid)
(BSD-2-Clause). It carries the experimental FUSION AutoCook start over the
`acp_c` port (see "Experimental: built-in AutoCook programs on FUSION Venus air
fryers" in the README) until it is tested on hardware and offered upstream.

Bugs in the fork's own changes go to this repository's issues. Everything else
belongs upstream.

## Layout

`main` is always `upstream/main` plus a short stack of fork commits:

1. the feature commits, written so they apply to upstream unchanged
   (these are what an upstream PR is made from);
2. one last commit, "Fork metadata", that only touches `manifest.json`
   (version, `issue_tracker`), `hacs.json` (name) and this file.

Keep it that way: no local paths, no unrelated changes, one topic per commit.

## Versions and tags

- Version: `<upstream version>-h0nz1k.<n>`, e.g. `3.9.15-h0nz1k.1`; `<n>`
  restarts at 1 for every new upstream version.
- Tag and release: `v<version>`, e.g. **`v3.9.15-h0nz1k.1`**. The manifest
  version is the tag without the `v`.
- HACS installs from GitHub releases. `hacs.json` has `zip_release: true` and
  `filename: philips_homeid.zip` (inherited from upstream), so every release
  **must carry the asset `philips_homeid.zip`** holding the files of
  `custom_components/philips_homeid/` at the zip's root, exactly as the
  inherited `Release` workflow builds it. A release without the asset cannot
  be installed. Do not mark the release as a pre-release, or HACS hides it
  unless "Show beta versions" is on.
- The version is valid SemVer, as hassfest and HACS require. As a SemVer
  pre-release it sorts below the plain upstream version, which does not matter
  here: HACS only compares this repository's own releases.

## Remotes (once)

```sh
git remote add upstream https://github.com/renaudallard/homeassistant_philips_homeid.git
git remote -v   # origin = h0nz1k fork, upstream = renaudallard
```

## Sync with upstream

```sh
git fetch upstream
git checkout main
git rebase upstream/main
# On a conflict in manifest.json keep upstream's version, then re-apply the
# fork suffix below. Anything else: resolve, git add, git rebase --continue.

python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/ruff check custom_components tests
.venv/bin/ruff format --check custom_components tests
.venv/bin/mypy --ignore-missing-imports custom_components/philips_homeid
PYTHONPATH=. .venv/bin/pytest tests/ -q
```

Then retag and release:

```sh
# Set "version" in custom_components/philips_homeid/manifest.json to the new
# <upstream version>-h0nz1k.<n> and amend it into the "Fork metadata" commit.
git commit --amend --no-edit custom_components/philips_homeid/manifest.json
VERSION=$(jq -r .version custom_components/philips_homeid/manifest.json)
git push --force-with-lease origin main      # the rebase rewrote main
git tag -a "v$VERSION" -m "v$VERSION"
git push origin "v$VERSION"
# Same zip layout as .github/workflows/release.yml: files at the root.
(cd custom_components/philips_homeid && rm -f ../../philips_homeid.zip && \
  zip -qr ../../philips_homeid.zip . -x '*.pyc' '__pycache__/*' '*/__pycache__/*')
unzip -l philips_homeid.zip | grep -q ' manifest.json$'
gh release create "v$VERSION" philips_homeid.zip \
  --repo h0nz1k/homeassistant_philips_homeid --title "v$VERSION" \
  --notes "Rebased on upstream $(git describe --tags --abbrev=0 upstream/main)"
```

The inherited `Release` workflow does the same when a manifest change lands on
`main` and Actions are enabled on the fork (GitHub leaves them off in a fresh
fork). Create the release one way or the other, not both. The scheduled
`Stale Issues` workflow comments on issues; keep it disabled on the fork
unless wanted.

Force-pushing `main` is fine for HACS users: HACS follows releases, not
branch history. Tags already released are never moved.

## Offering it upstream

```sh
git checkout -b pr/fusion-autocook upstream/main
git cherry-pick upstream/main..main~1   # every fork commit except "Fork metadata"
```

Upstream's version, codeowners and issue tracker stay untouched that way.
