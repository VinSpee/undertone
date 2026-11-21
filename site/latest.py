"""The step of site/Dockerfile that resolves site/RELEASE = latest, before release.sh downloads the files.
  latest.py PIN_DIR FEED_URL BASE_URL
When PIN_DIR/RELEASE names a tag or none, it changes nothing: the pin of the repository stands. When it says latest, it
reads the repository's releases feed (FEED_URL, GitHub's releases.atom: the published releases, pre-releases included,
never a draft, newest first; unlike the REST API it has no rate limit for a build without a token) and replaces the two
files of PIN_DIR with the newest release's tag and its checksum list, the release asset site.sha256 read from
BASE_URL/<tag>/site.sha256 (one line per file: its SHA-256, its path on the site, the name of its release asset).
release.sh then downloads each file and checks it against that list. With no published release, RELEASE becomes none
and the site serves the pages only. It fails, and the build with it, when the feed or the list cannot be read after
three tries, and when a path of the list leaves the site's folder.
"""
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

pin, feed, base = sys.argv[1:4]
ATOM = "{http://www.w3.org/2005/Atom}"


def fail(why):
    sys.exit(f"site release: {why}")


def get(url, what):
    for attempt in range(3):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "undertone-site-build"})
            with urllib.request.urlopen(request, timeout=30) as answer:
                return answer.read()
        except Exception as e:
            if attempt == 2:
                fail(f"could not read {what} from {url} after 3 tries: {e}")
            time.sleep(2 * (attempt + 1))


with open(f"{pin}/RELEASE") as f:
    if f.read().strip() != "latest":
        sys.exit(0)

try:
    root = ET.fromstring(get(feed, "the releases feed"))
except ET.ParseError as e:
    fail(f"the releases feed {feed} is not an Atom feed: {e}")
if root.tag != f"{ATOM}feed":
    fail(f"the releases feed {feed} is not an Atom feed: its root is {root.tag}")
entry = root.find(f"{ATOM}entry")
if entry is None:
    tag, sums = "none", "# site/RELEASE says latest, and the repository has no published release yet.\n"
else:
    link = entry.find(f"{ATOM}link")
    href = link.get("href", "") if link is not None else ""
    tag = urllib.parse.unquote(href.rpartition("/releases/tag/")[2]) if "/releases/tag/" in href else ""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+-]*", tag):
        fail(f"the newest entry of the releases feed {feed} names no release tag: {href}")
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
