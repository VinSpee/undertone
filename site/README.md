# The site container

`site/Dockerfile` builds the site of `undertone.vinspee.me`: a small container with a static file server. It serves
three things.

- **The pages of this commit.** Everything in `docs/`: the home page (`index.html`), the installer (`install.html`), the editor (`editor.html`) and
  the documents. A correction to a page reaches the site through an ordinary pull request, without a release.
- **The rescue kit of this commit.** The build makes it with `rescue/build_kit.py` and stops when it is not the kit
  pinned in `rescue/kit.sha256`. The installer's Rescue card offers it at `rescue/`.
- **The files of one release.** The packages and whatever else that release publishes for the site: the newest
  published release, or one pinned here. The build downloads them from the GitHub release and checks each one against
  a SHA-256, from the checksum list the release publishes or from this folder.

The packages must come from the site's own address. The installer reads them with `fetch`, and GitHub does not allow
a page of another site to read its release downloads.

The firmware is never built here. The toolchain runs on x86-64 only, and the server that runs the site is arm64.

## The parts

| File | What it is |
| --- | --- |
| `Dockerfile` | The build: the pages and the rescue kit, then the release's files, then the file server. The build context is the top of the repository |
| `Dockerfile.dockerignore` | Keeps everything but `docs/`, `site/` and the kit's sources out of the build, and `docs/firmware/` and `docs/rescue/` too, where a local build leaves its packages and its kit |
| `Caddyfile` | The file server, on port 80 without HTTPS. The proxy in front of the container provides HTTPS |
| `RELEASE` | One line: `latest`, the tag of a pinned release, or `none` |
| `release.sha256` | For a pinned release, one line per file: its SHA-256, its path on the site, the name of its release asset |
| `latest.py` | The step that resolves `latest`: the newest published release and its checksum list |
| `release.sh` | The step that downloads the files and checks them |

The container also serves `RELEASE` and `release.sha256` themselves, at `/RELEASE` and `/release.sha256`, so that
anyone can see which release a running site holds.

## Which release the site serves

`RELEASE` says which release the site serves. It says `latest`.

- **`latest`**: the newest published release of `VinSpee/undertone`, pre-releases included, never a draft. The build
  reads the repository's releases feed, `https://github.com/VinSpee/undertone/releases.atom`, which lists the
  published releases newest first. Unlike the GitHub REST API, the feed has no rate limit for a build without a token.
  The build then downloads the newest release's asset `site.sha256` and serves the files that list names. Each read is
  tried three times.
  Publishing a release therefore reaches the site without a commit: the `deploy-site` workflow asks Coolify to
  rebuild ([Deploying](#deploying)). While the repository has no published release, the site serves the pages only.
- **A tag**, for example `v1.0.0-beta.1`: that release, with the files that `release.sha256` in this folder lists. Use
  it to hold the site at one release, or to go back to one.
- **`none`**: the pages only, without any package. The installer then has nothing to install.

A checksum list has one line for each file the site should serve. `site.sha256` in a release and `release.sha256`
here use the same form:

```
<SHA-256>  <path on the site>  <name of the release asset>
```

The path says where the page will ask for the file, for example `firmware/manifest.json`. The asset name is the
file's name in the GitHub release. The two are separate because a release's assets have no folders. The SHA-256 comes
from the build that made the release, not from a download of the release.

The installer offers one card per firmware of the release's catalog, `firmware/release.json` (`tools/catalog.py`).
List that file and each package it lists, at its path under `firmware/`, for example
`firmware/apps/palette/palette-PocketX_9NN.fwsc`. Without a catalog, the installer offers only the firmware of
`firmware/manifest.json`.

The build stops, and nothing is deployed, when a download fails, when a file is not the bytes its list names, when a
path is already a page of the site or leaves the site's folder, and when `RELEASE` and `release.sha256` disagree about
whether a release is pinned. With `latest`, it also stops when the releases feed cannot be read and when the newest
published release has no `site.sha256`. A release published without that list therefore stops every build of the
site, including those of the pages, until a newer release carries one or `RELEASE` pins a tag.

To pin a release, open a pull request that writes its tag in `RELEASE` and its files in `release.sha256`. Going back
to `latest` is reverting that pull request.

## Building and checking

```
docker build -f site/Dockerfile -t openpocket-site .          # from the top of the repository
docker run --rm -p 8080:80 openpocket-site                    # http://localhost:8080/
sh .claude/skills/verify/scripts/pages.sh site                # the check
```

The check is `tests/test_site.mjs`, and the `site` job of `.github/workflows/build.yml` runs it on every pull request.
It needs Docker and Playwright. It does three things:

1. It builds the image as it will be deployed and reads the pages, the release's files and the rescue kit back from a
   running container. With `latest`, this build reads a stand-in feed without a release, so it serves the pages only.
2. It builds the image again against a stand-in GitHub, which is the test's fixture packages and a releases feed on a
   local server, given to the build with `--build-arg RELEASE_URL=...` and `--build-arg RELEASE_FEED=...`. A pinned
   release and the newest release of a feed must arrive as their lists name them, `none` and a feed without a release
   must give the pages only, and six wrong pins and five broken cases of `latest` must stop the build.

No build of the check reads the real GitHub, so the check does not depend on its rate limits or on which releases are
published.
3. It runs the installer and editor page tests against the container. The installer test needs packages that fit its
   simulated pedal, so the container's `firmware/` folder is the test's own folder for that run. The checks that
   change the kit's manifest run only against the test's own server.

## Deploying

Coolify builds the container from the public repository. It needs these settings and no secret:

| Setting | Value |
| --- | --- |
| Repository | `https://github.com/VinSpee/undertone`, branch `main` |
| Build pack | Dockerfile |
| Base directory | `/` |
| Dockerfile location | `/site/Dockerfile` |
| Port | 80 |

The build needs to reach Docker Hub for the base image, and `github.com` for the releases feed and the release's
files.

The workflow `.github/workflows/deploy-site.yml` deploys the site each time a release is published, and when it is
run by hand from the Actions tab. It sends one request to Coolify's deploy endpoint:

```
POST https://deploy.vinspee.me/api/v1/deploy?uuid=<COOLIFY_APP_UUID>&force=true
Authorization: Bearer <COOLIFY_DEPLOY_TOKEN>
```

`force=true` makes Coolify build without its cache, so that the build asks GitHub again for the newest release. The
workflow fails with a message when the secret or the variable is missing and when Coolify does not answer with a 2xx
status. The token can start a deployment and cannot read one, so the workflow does not wait for the build: its result
is in Coolify, and the running site's `/RELEASE` names the release it serves. Run by hand with `dry_run`, the workflow
prints the request and sends nothing.

| Repository setting | Kind | Value |
| --- | --- | --- |
| `COOLIFY_DEPLOY_TOKEN` | Actions secret | A Coolify API token with the deploy permission only |
| `COOLIFY_APP_UUID` | Actions variable | The uuid of the site's application in Coolify |

## What was tested

Tested on an arm64 Mac: the check above passes; and a build with upstream's `v42` release pinned downloaded
`BlackBox_942.fwsc` from GitHub and served the same bytes.

Tested for `latest`: the check above, against the stand-in GitHub. `latest.py` also read the real feeds: this
repository's feed, which has no release yet, gave `none`, and upstream's feed gave `v42`. The step of the deploy
workflow was run locally against a stand-in endpoint (a 2xx answer, a 401, a 500, no answer), with the secret or the
variable missing, with `dry_run`, and once against the real endpoint with a wrong token, which answered 401.

Not tested: the build on Coolify, the site behind its proxy and Cloudflare, and the workflow on GitHub with the real
token. The download from a release of this repository is not tested either, because the repository has no release
yet.
