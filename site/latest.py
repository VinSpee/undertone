"""The step of site/Dockerfile that resolves site/RELEASE = latest, before release.sh downloads the files.
  latest.py PIN_DIR API_URL BASE_URL
When PIN_DIR/RELEASE names a tag or none, it changes nothing: the pin of the repository stands. When it says latest, it
asks the GitHub releases API (API_URL) for the newest published release, pre-releases included, and replaces the two
files of PIN_DIR with that release's tag and its checksum list, the release asset site.sha256 read from
BASE_URL/<tag>/site.sha256 (one line per file: its SHA-256, its path on the site, the name of its release asset).
release.sh then downloads each file and checks it against that list. With no published release, RELEASE becomes none
and the site serves the pages only. It fails, and the build with it, when the API does not answer, when the newest
release has no site.sha256, and when a path of the list leaves the site's folder.
"""
import json
import sys
import urllib.request

pin, api, base = sys.argv[1:4]


def fail(why):
    sys.exit(f"site release: {why}")


def get(url, what):
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "undertone-site-build"}
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=60) as answer:
            return answer.read()
    except Exception as e:
        fail(f"could not read {what} from {url}: {e}")


with open(f"{pin}/RELEASE") as f:
    if f.read().strip() != "latest":
        sys.exit(0)

releases = json.loads(get(f"{api}?per_page=100", "the list of releases"))
published = [r for r in releases if not r["draft"] and r["published_at"]]
if not published:
    tag, sums = "none", "# site/RELEASE says latest, and the repository has no published release yet.\n"
else:
    tag = max(published, key=lambda r: r["published_at"])["tag_name"]
    sums = get(f"{base}/{tag}/site.sha256", f"the checksum list site.sha256 of {tag}").decode()
    for line in sums.splitlines():
        fields = line.split()
        if len(fields) > 1 and not fields[0].startswith("#"):
            path = fields[1]
            if path.startswith("/") or ".." in path.split("/"):
                fail(f"site.sha256 of {tag} names a path outside the site: {path}")

with open(f"{pin}/RELEASE", "w") as f:
    f.write(tag + "\n")
with open(f"{pin}/release.sha256", "w") as f:
    f.write(sums)
print(f"site release: latest is {tag}")
