# Releasing

Release notes are generated with [changesets](https://github.com/changesets/changesets). Each pull request adds a
changeset ([CONTRIBUTING.md](../CONTRIBUTING.md)); a workflow collects them into a version, one changelog per release
unit, a tag, and a draft GitHub release that carries every firmware, the rescue kit and the checksum list of the site.
Nothing is published to npm, and nothing is published without a person.

## The parts

| Part | What it is |
| --- | --- |
| `package.json`, `package-lock.json` | The two pinned npm packages of the release tooling. The build and the tests do not use them. The lock file also records the units' version as it was when the lock was written; npm does not compare it, so a release does not have to touch the lock |
| `changelog/<unit>/package.json` | One private stub per release unit: its name, the release version, and the title of its section in the notes. `changeset version` writes `CHANGELOG.md` beside it |
| `.changeset/config.json` | The settings: the base branch `main`, the changelog generator that links pull requests and authors, and the `fixed` group that gives every unit the same version |
| `.changeset/pre.json` | Pre-release mode with the tag `beta` |
| `.github/workflows/changeset.yml` | The `changeset` check on pull requests. Advisory, not required |
| `.github/workflows/release.yml` | The release flow below |
| `.github/scripts/release.mjs` | The steps that create the tag (`--tag`) and the draft release (`--draft TAG DIR`). Without an option it prints the tag and the notes and changes nothing |
| `.github/scripts/assets.mjs` | The step that assembles the release's files from a build ([The release's files](#the-releases-files)) |

The stubs live in `changelog/` and not beside the sources for three reasons. OpenPocket's sources have no folder of
their own. `tools/` has its own `package.json` and lock file, installed with `npm ci --prefix tools`, which an npm
workspace would change. And a `package.json` in a firmware folder would sit among files the build reads.

## The numbers

Three numbers exist. Changesets own the first one and never touch the other two.

| Number | Example | Where | Who changes it |
| --- | --- | --- | --- |
| The release | `v1.0.0-beta.1` | `changelog/*/package.json`, the tag, the GitHub release | Changesets, in the Version Packages pull request |
| A firmware's version | `v43` for OpenPocket, `v01` for PALETTE | `OP_VERSION_NUM` in `firmware/openpocket.c` and `firmware/apps/palette/palette.c`; on the boot screen | A person, in the pull request that changes that firmware |
| The package identity | `BlackBox_943`, `PocketX_901` | Derived: 900 plus the firmware's version (`tools/pxpkg.py`). The installer tells builds apart by it | It follows the firmware's version |

One release carries several firmwares, and each keeps its own version and identity inside it. The release therefore
needs a number of its own. It is a semantic version, so `v1.0.0-beta.1` cannot be mistaken for a firmware version
such as `v42`, and it cannot collide with upstream's tags `v24` to `v42`.

The first release is a 1.0 beta. The units start at `1.0.0-beta.0`, which is never released. In pre-release mode the
first Version Packages pull request moves them to `1.0.0-beta.1`, the next one to `1.0.0-beta.2`, and so on, whatever
the categories of the changesets are. Leaving pre-release mode gives `1.0.0`. After that the highest category among
the waiting changesets decides the next number, as semantic versioning says.

A changeset does not change a firmware. A pull request that changes a firmware's bytes still moves that firmware's
version and its release pin by hand, as before (`tests/release_pin.sh`).

## Cutting a release

1. Pull requests with changesets merge into `main`. On each push the `release` workflow opens or updates the pull
   request **Version Packages (beta)** from the branch `changeset-release/main`. It holds the new version in every
   `changelog/*/package.json`, the new entries in every `CHANGELOG.md`, and the used changesets moved to
   `.changeset/pre/`. Its description shows the notes as they will be.
2. When the release is wanted, start the checks on that pull request: close it and reopen it. GitHub does not start
   workflows for a pull request that a workflow opened with its own token, so the required `build-and-test` check
   does not appear by itself. A later update of the pull request by the workflow needs the same again.
3. Merge it. The `release` workflow then creates the tag `v<version>` at the merge commit, builds the release's files
   at that tag, and creates a **draft** GitHub release with them, marked as a pre-release while the version has a
   suffix. Its text is the entry of each unit for that version, under the unit's title. A unit without changes is left
   out. The build takes about as long as the `build` workflow.
4. Read the draft, add what only a person can say (what was checked on a pedal, the warnings), and publish it. The
   workflow never publishes a release. Publishing it puts it on the site ([below](#putting-a-release-on-the-site)).

The tag step runs on every push to `main` that has no changeset waiting. It creates the tag only when it is missing,
and the build and the draft follow only while the tag has no release, draft or published. When the build fails, the
next push to `main` tries again. To see the tag and the notes it would use: `node .github/scripts/release.mjs`.

A person can also push a tag such as `v1.0.0-beta.1` (`git tag v1.0.0-beta.1 <commit> && git push origin
v1.0.0-beta.1`). Any tag of the form `v*.*.*` starts the same build and draft. The tag must be on a commit whose
`changelog/*/package.json` hold that version, which is the merge of a Version Packages pull request; the draft step
refuses any other tag, because its notes are that version's changelog entries.

To leave the beta: run `npx changeset pre exit` on a branch, merge it, and the next Version Packages pull request
carries `1.0.0`. To use another tag such as `rc`, change `"tag"` in `.changeset/pre.json`.

## The release's files

The jobs `files` and `release` of `.github/workflows/release.yml` make the draft's files. They run after the tag step
found a tag without a release, and for a pushed tag.

1. `files`, with read access only: it checks out the tag and builds as the `build` workflow does. `node tools/op.mjs
   all` builds OpenPocket, which fails when its packages are not the pinned release's bytes, and every app of
   `firmware/apps`, then runs the host tests with the packages built. `node tools/op.mjs kit` builds the rescue kit.
   The job then compares the files on disk with their pins: OpenPocket's image and packages with
   `tests/release.sha256`, the kit with `rescue/kit.sha256`. The apps have no pin. Then
   `node .github/scripts/assets.mjs` assembles the files, and the job keeps them as the workflow artifact
   `release-files`.
2. `release`, the only job of these two that can write: it creates the draft release with those files
   (`node .github/scripts/release.mjs --draft TAG DIR`). It refuses a tag that has a release already, draft or
   published, and never replaces or edits one. After the upload it checks that the draft holds every file at its size.

The files of a release:

| Asset | What it is | On the site at |
| --- | --- | --- |
| `release.json` | The firmware catalog (`tools/catalog.py`): one card per firmware on the installer page | `firmware/release.json` |
| `manifest.json`, `PocketX_9NN.fwsc`, `BlackBox_9NN.fwsc` | OpenPocket's manifest and its package for each pedal | `firmware/` |
| `<app>-manifest.json`, `<app>-PocketX_9NN.fwsc`, `<app>-BlackBox_9NN.fwsc` | The same for each other firmware of the catalog, such as PALETTE | `firmware/apps/<app>/` |
| `OpenPocket-rescue-kit-<N>.zip` | The rescue kit without M-VAVE's files ([rescue/README.md](../rescue/README.md)) | Not from the release: the site builds its own kit |
| `site.sha256` | The checksum list the site serves the release from: one line per file, its SHA-256, its path on the site and its asset name ([site/README.md](../site/README.md)) | |
| `SHA256SUMS` | The SHA-256 of every other asset, for `sha256sum -c SHA256SUMS` | |

The catalog decides which firmwares a release carries: those of `firmware/catalog.json` that the build made. The
starter app and the MIDI test channel are built but not released. A release's assets have no folders, so an app's
files carry the app's name. Each SHA-256 comes from the build, not from a download of the release.

To make the files without a release, run the workflow by hand from the Actions tab, on any branch or tag. It runs the
`files` job only and keeps the files as the artifact `release-files`; it creates no tag and no release. Locally, after
`node tools/op.mjs all` and `node tools/op.mjs kit`:

```
node .github/scripts/assets.mjs OUT_DIR
```

When a draft is wrong, delete it on GitHub (Releases, the draft, Delete) and push to `main` again, or delete and push
the tag again. The workflow never deletes a release itself.

## Putting a release on the site

Publishing a release puts it on the site. The `deploy-site` workflow (`.github/workflows/deploy-site.yml`) starts
when a release is published, never for a draft, and asks Coolify to rebuild the site container. `site/RELEASE` says
`latest`, so the build serves the newest published release: it downloads the release's `site.sha256` and each file
that list names, and stops when a file is not the bytes its list names. Pinning one release instead, and the rest of
the site, are in [site/README.md](../site/README.md).

The workflow can also run by hand from the Actions tab, to deploy again; with `dry_run` it prints the request and
sends nothing.

## Repository settings

- **Settings, Actions, General: "Allow GitHub Actions to create and approve pull requests"** must be on. Without it
  the workflow cannot open the Version Packages pull request. It was off when this was written.
- The release workflows use only the token GitHub gives each run. In `release.yml` only two jobs can write: the
  version job (the Version Packages pull request and the tag) and the `release` job (the draft release). The build
  of the files can only read. The `deploy-site` workflow needs one secret and
  one variable, under Settings, Secrets and variables, Actions:
  - `COOLIFY_DEPLOY_TOKEN`, a secret: a Coolify API token that can start a deployment and nothing more.
  - `COOLIFY_APP_UUID`, a variable: the uuid of the site's application in Coolify.

  It sends `POST https://deploy.vinspee.me/api/v1/deploy?uuid=<COOLIFY_APP_UUID>&force=true` with the token, and
  fails with a message when either one is missing or Coolify does not answer with a 2xx status.
- The `changeset` check is not a required check. To make it one, add it to the branch protection of `main`.
- `.changeset/config.json` names the repository (`VinSpee/undertone`) for the links in the changelogs. Change it
  when the repository is renamed again.

## Adding a unit

Create `changelog/<name>/package.json` like the others, with the current version, and add `<name>` to the `fixed`
group in `.changeset/config.json`. The order of that group is the order of the sections in the notes.

## What was tested

Tested locally, in a copy of the repository: `changeset version` gives `1.0.0-beta.1`, then `1.0.0-beta.2`, then
`1.0.0` after `pre exit`; the changelog generator returns the pull request and the author for a real commit of this
repository; the release step prints the right notes, and with a stand-in for `gh` it creates the tag and the draft
only when they are missing. The `changeset` check ran on its own pull request.

The release's files: `tests/test_release_files.mjs` (part of the host tests) assembles a release from the fixture
packages, serves it as a stand-in GitHub release with a releases feed, and runs `site/latest.py` and `site/release.sh`
against it; it also runs `release.mjs --draft` with a stand-in `gh`. The workflow ran by hand on its pull request's
branch: the `files` job built, tested and assembled the ten files in 11 minutes, the `release` job was skipped, and the
files were the same bytes as a local build's.

Not tested: the `release` workflow has not run on `main` or for a pushed tag. No Version Packages pull request, tag or
release has been created. On the day this was written, every run on `main` failed at the Version Packages pull
request, because the setting below that lets GitHub Actions create pull requests was off.
