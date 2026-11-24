// SPDX-License-Identifier: GPL-3.0-only
// OpenPocket — the files of a release (.github/scripts/assets.mjs) and its draft (.github/scripts/release.mjs --draft),
// from the fixture packages, a catalog and the rescue kit, with no Docker and no GitHub:
//   1. the assets: the catalog, each firmware's manifest and packages, the kit, site.sha256 and SHA256SUMS, nothing else;
//   2. the site's own release steps (site/latest.py, site/release.sh) against a stand-in GitHub that serves those files
//      as a release, into the pages and the kit the site has already: every file of the catalog arrives at its path, the
//      bytes its list names, and none is a page or the kit;
//   3. what the assembler refuses: a folder that is not empty, a package that is not its manifest's, the full kit;
//      and with --program, undertone's programs as assets and on the site at undertone/, with their checksums, and
//      nothing else from that folder;
//   4. the draft, with a stand-in gh: a tag that is not the changelogs' version, a tag with a release already, and the
//      draft itself, pre-release for a beta, with every file and the changelog entries as its notes.
// It needs Node, Python 3, curl or wget, and sha256sum. tests/run_tests.sh runs it.
//   node tests/test_release_files.mjs
import { execFile, execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { chmodSync, cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const TMP = mkdtempSync(join(tmpdir(), "oprelease-"));
let failed = 0;
const ok = (c, what) => { console.log(`${what.padEnd(100)} ${c ? "ok" : "FAIL"}`); if (!c) failed++; };
const sha256 = (file) => createHash("sha256").update(readFileSync(file)).digest("hex");
// not blocking: the stand-in GitHub below is served by this process while the site's steps download from it
const run = (cmd, args, env = {}) => new Promise((done) => {
  execFile(cmd, args, { cwd: ROOT, env: { ...process.env, ...env } }, (error, stdout, stderr) => done({ code: error ? error.code || 1 : 0, out: stdout + stderr }));
});
const assemble = (out, dirs = {}) => run(process.execPath, [join(ROOT, ".github/scripts/assets.mjs"), out,
  "--site", dirs.site || SITE, "--apps", dirs.apps || APPS, "--kit", dirs.kit || KIT,
  ...(dirs.program ? ["--program", dirs.program] : [])]);

// a build's outputs: the fixture packages as OpenPocket's (build/apps/gamut) and as the app starter's (build/apps/starter),
// the catalog of the two, and the rescue kit
const FIX = join(TMP, "fixtures"), SITE = join(TMP, "site-fw"), APPS = join(TMP, "apps"), KIT = join(TMP, "kit");
execFileSync("python3", [join(ROOT, "tests/fixtures.py"), FIX], { stdio: ["ignore", "ignore", "inherit"] });
mkdirSync(SITE);
for (const f of ["manifest.json", "PocketX_924.fwsc", "BlackBox_924.fwsc"]) cpSync(join(FIX, f), join(SITE, f));
cpSync(join(FIX, "alt"), join(APPS, "starter"), { recursive: true });
writeFileSync(join(TMP, "catalog.json"), JSON.stringify({ firmwares: [{ id: "openpocket", name: "OpenPocket", what: "The first." }, { id: "starter", what: "The second." }] }));
execFileSync("python3", [join(ROOT, "tools/catalog.py"), "--source", join(TMP, "catalog.json"), "--site", SITE, "--apps", APPS], { stdio: "ignore" });
execFileSync("python3", [join(ROOT, "rescue/build_kit.py"), KIT], { stdio: "ignore" });
const kitFile = JSON.parse(readFileSync(join(KIT, "manifest.json"), "utf8")).file;
const catalog = JSON.parse(readFileSync(join(SITE, "release.json"), "utf8"));

const server = createServer((req, res) => {
  const answer = github[req.url.split("?")[0]];
  if (answer === undefined) { res.writeHead(404); res.end(); return; }
  res.writeHead(200); res.end(answer);
}).listen(0, "127.0.0.1");
const github = {};
try {
  // 1. the assets
  const OUT = join(TMP, "release");
  const made = await assemble(OUT);
  ok(made.code === 0, `assets.mjs assembles the release's files${made.code ? ":\n" + made.out : ""}`);
  const names = readdirSync(OUT).sort();
  ok(JSON.stringify(names) === JSON.stringify(["BlackBox_924.fwsc", kitFile, "PocketX_924.fwsc", "SHA256SUMS", "manifest.json", "release.json", "site.sha256",
    "starter-BlackBox_901.fwsc", "starter-PocketX_901.fwsc", "starter-manifest.json"].sort()),
  `the assets are the catalog, each firmware's manifest and packages (an app's named after it), the kit and the two lists: ${names.join(" ")}`);
  const sums = readFileSync(join(OUT, "SHA256SUMS"), "utf8").trim().split("\n").map((l) => l.split(/\s+/));
  ok(sums.length === names.length - 1 && sums.every(([s, a]) => existsSync(join(OUT, a)) && sha256(join(OUT, a)) === s) && !sums.some(([, a]) => a === "SHA256SUMS"),
    "SHA256SUMS holds every other asset, site.sha256 too, with its SHA-256");
  ok(execFileSync("sha256sum", ["-c", "SHA256SUMS"], { cwd: OUT, encoding: "utf8" }).trim().split("\n").every((l) => l.endsWith(": OK")), "sha256sum -c SHA256SUMS passes");
  const listed = readFileSync(join(OUT, "site.sha256"), "utf8").split("\n").filter((l) => l && !l.startsWith("#")).map((l) => l.split(/\s+/));
  const served = ["release.json", ...catalog.firmwares.flatMap((f) => [f.manifest, ...f.packages.map((p) => p.file)])].map((p) => `firmware/${p}`);
  ok(listed.every((l) => l.length === 3) && JSON.stringify(listed.map(([, p]) => p).sort()) === JSON.stringify(served.sort()),
    "site.sha256: one line of SHA-256, path and asset for the catalog and every file it names, and no other (the site builds its own kit)");
  ok(listed.every(([s, , a]) => sha256(join(OUT, a)) === s), "site.sha256: each line's SHA-256 is its asset's");

  // 2. the site's own steps: latest.py finds the stand-in release in the feed and reads its site.sha256; release.sh
  // downloads every file and checks it. Without wget (macOS), a stand-in wget that calls curl.
  const TAG = "v0.0.1-test";
  for (const a of names) github[`/${TAG}/${a}`] = readFileSync(join(OUT, a));
  github["/feed.atom"] = `<?xml version="1.0" encoding="UTF-8"?><feed xmlns="http://www.w3.org/2005/Atom"><entry><id>1</id>` +
    `<link rel="alternate" type="text/html" href="https://github.com/VinSpee/undertone/releases/tag/${TAG}"/><title>${TAG}</title></entry></feed>`;
  const base = `http://127.0.0.1:${server.address().port}`;
  const PIN = join(TMP, "pin"), WWW = join(TMP, "www"), BIN = join(TMP, "bin");
  mkdirSync(PIN); mkdirSync(WWW); mkdirSync(BIN);
  writeFileSync(join(PIN, "RELEASE"), "latest\n");
  writeFileSync(join(PIN, "release.sha256"), "");
  // the site as site/Dockerfile makes it before this step: the pages of docs/ without a local build's firmware/ and rescue/
  // (site/Dockerfile.dockerignore), and the kit at rescue/
  cpSync(join(ROOT, "docs"), WWW, { recursive: true, filter: (src) => !["firmware", "rescue"].some((d) => src === join(ROOT, "docs", d)) });
  cpSync(KIT, join(WWW, "rescue"), { recursive: true });
  const hasWget = (await run("sh", ["-c", "command -v wget"])).code === 0;
  if (!hasWget) {
    writeFileSync(join(BIN, "wget"), '#!/bin/sh\n# wget -q -O FILE URL\nexec curl -fsS -o "$3" "$4"\n');
    chmodSync(join(BIN, "wget"), 0o755);
  }
  const env = { PATH: `${BIN}:${process.env.PATH}` };
  const latest = await run("python3", [join(ROOT, "site/latest.py"), PIN, `${base}/feed.atom`, base]);
  ok(latest.code === 0 && readFileSync(join(PIN, "RELEASE"), "utf8").trim() === TAG, `site/latest.py takes the stand-in release from the feed${latest.code ? ":\n" + latest.out : ""}`);
  const fetched = await run("sh", [join(ROOT, "site/release.sh"), PIN, WWW, base], env);
  ok(fetched.code === 0 && fetched.out.includes(`${TAG}, ${served.length} files`), `site/release.sh downloads and checks the ${served.length} files of site.sha256${hasWget ? "" : " (wget through curl)"}${fetched.code ? ":\n" + fetched.out : ""}`);
  ok(served.every((p) => existsSync(join(WWW, p))) && listed.every(([, p, a]) => readFileSync(join(WWW, p)).equals(readFileSync(join(OUT, a)))),
    "every file of the catalog is on the site at its path, the asset's bytes");
  const onSite = JSON.parse(readFileSync(join(WWW, "firmware/release.json"), "utf8"));
  ok(onSite.firmwares.every((f) => existsSync(join(WWW, "firmware", f.manifest)) && f.packages.every((p) => sha256(join(WWW, "firmware", p.file)) === p.sha256)),
    "the site's catalog finds each firmware's manifest and packages beside it, with the catalog's SHA-256");
  github[`/${TAG}/site.sha256`] = readFileSync(join(OUT, "site.sha256"), "utf8").replace(/^([0-9a-f])/m, (c) => (c === "0" ? "1" : "0"));
  writeFileSync(join(PIN, "RELEASE"), "latest\n");
  const changed = await run("python3", [join(ROOT, "site/latest.py"), PIN, `${base}/feed.atom`, base]);
  for (const p of served) rmSync(join(WWW, p));
  const refused = changed.code === 0 && await run("sh", [join(ROOT, "site/release.sh"), PIN, WWW, base], env);
  ok(refused && refused.code !== 0 && /is not the pinned file/.test(refused.out), "a release whose site.sha256 does not match a file stops the site's build");

  // the programs the release workflow's program job built: two systems here, as when the other two could not be built
  const PROG = join(TMP, "program"), OUTP = join(TMP, "release-program");
  mkdirSync(PROG);
  writeFileSync(join(PROG, "undertone-macos"), "a Mac program");
  writeFileSync(join(PROG, "undertone-windows-x86_64.exe"), "a Windows program");
  const withProgram = await assemble(OUTP, { program: PROG });
  ok(withProgram.code === 0, `assets.mjs --program assembles the programs too${withProgram.code ? ":\n" + withProgram.out : ""}`);
  const programAssets = readdirSync(OUTP).filter((a) => a.startsWith("undertone-")).sort();
  ok(JSON.stringify(programAssets) === JSON.stringify(["undertone-SHA256SUMS", "undertone-macos", "undertone-windows-x86_64.exe"]),
    `the programs are assets, with their checksums: ${programAssets.join(" ")}`);
  ok(readFileSync(join(OUTP, "undertone-SHA256SUMS"), "utf8") === `${sha256(join(PROG, "undertone-macos"))}  undertone-macos\n${sha256(join(PROG, "undertone-windows-x86_64.exe"))}  undertone-windows-x86_64.exe\n`,
    "undertone-SHA256SUMS holds each program's SHA-256 under its asset name");
  const programLines = readFileSync(join(OUTP, "site.sha256"), "utf8").split("\n").filter((l) => l.includes("undertone")).map((l) => l.split(/\s+/));
  ok(JSON.stringify(programLines.map(([, p, a]) => `${p} ${a}`).sort()) === JSON.stringify(["undertone/SHA256SUMS undertone-SHA256SUMS",
    "undertone/undertone-macos undertone-macos", "undertone/undertone-windows-x86_64.exe undertone-windows-x86_64.exe"]),
  "site.sha256 puts the programs and their checksums at undertone/ on the site, where the Rescue card reads them");
  ok(execFileSync("sha256sum", ["-c", "SHA256SUMS"], { cwd: OUTP, encoding: "utf8" }).includes("undertone-macos: OK"), "SHA256SUMS covers the programs");
  const PTAG = "v0.0.2-test", PWWW = join(TMP, "www-program"), PPIN = join(TMP, "pin-program");
  mkdirSync(PPIN);
  for (const a of readdirSync(OUTP)) github[`/${PTAG}/${a}`] = readFileSync(join(OUTP, a));
  writeFileSync(join(PPIN, "RELEASE"), `${PTAG}\n`);
  writeFileSync(join(PPIN, "release.sha256"), readFileSync(join(OUTP, "site.sha256")));
  cpSync(join(ROOT, "docs"), PWWW, { recursive: true, filter: (src) => !["firmware", "rescue"].some((d) => src === join(ROOT, "docs", d)) });
  const delivered = await run("sh", [join(ROOT, "site/release.sh"), PPIN, PWWW, base], env);
  ok(delivered.code === 0 && readFileSync(join(PWWW, "undertone/undertone-macos"), "utf8") === "a Mac program" && existsSync(join(PWWW, "undertone/SHA256SUMS")),
    `site/release.sh puts the programs and their checksums at undertone/${delivered.code ? ":\n" + delivered.out : ""}`);

  // 3. what the assembler refuses
  const no = async (what, out, dirs, says) => {
    const r = await assemble(out, dirs);
    ok(r.code !== 0 && says.test(r.out), `assets.mjs refuses ${what}${r.code === 0 ? ": it assembled" : says.test(r.out) ? "" : ":\n" + r.out}`);
  };
  await no("a folder that is not empty", OUT, {}, /is not empty/);
  const BAD = join(TMP, "bad-apps");
  cpSync(APPS, BAD, { recursive: true });
  writeFileSync(join(BAD, "starter", "starter-PocketX_901.fwsc"), "not the package");
  await no("a package that is not its manifest's", join(TMP, "out-bad"), { apps: BAD }, /starter-PocketX_901\.fwsc is not the file its manifest names/);
  const FULL = join(TMP, "full-kit");
  cpSync(KIT, FULL, { recursive: true });
  writeFileSync(join(FULL, "manifest.json"), JSON.stringify({ ...JSON.parse(readFileSync(join(KIT, "manifest.json"), "utf8")), firmware: true }));
  await no("the full kit with M-VAVE's files", join(TMP, "out-full"), { kit: FULL }, /full kit with M-VAVE's files/);
  await no("a build without the kit", join(TMP, "out-nokit"), { kit: join(TMP, "nokit") }, /build the kit first/);
  const ODD = join(TMP, "odd-program");
  cpSync(PROG, ODD, { recursive: true });
  writeFileSync(join(ODD, "undertone-amiga"), "not a program of this repository");
  await no("a file of the program folder that is not one of undertone's programs", join(TMP, "out-odd"), { program: ODD }, /is not one of undertone's programs/);

  // 4. the draft, from a copy of the release step and the changelogs at version 1.0.0-beta.1, with a stand-in gh that
  // records its calls and answers for the releases it was asked to create
  const REPO = join(TMP, "repo");
  cpSync(join(ROOT, ".github/scripts/release.mjs"), join(REPO, ".github/scripts/release.mjs"));
  cpSync(join(ROOT, ".changeset/config.json"), join(REPO, ".changeset/config.json"));
  for (const unit of readdirSync(join(ROOT, "changelog"))) {
    const pkg = JSON.parse(readFileSync(join(ROOT, "changelog", unit, "package.json"), "utf8"));
    mkdirSync(join(REPO, "changelog", unit), { recursive: true });
    writeFileSync(join(REPO, "changelog", unit, "package.json"), JSON.stringify({ ...pkg, version: "1.0.0-beta.1" }));
  }
  writeFileSync(join(REPO, "changelog/tools/CHANGELOG.md"), "# tools\n\n## 1.0.0-beta.1\n\n### Minor Changes\n\n- A line of the notes.\n\n## 1.0.0-beta.0\n\n- An older line.\n");
  const GH = join(TMP, "gh-bin"), STATE = join(TMP, "gh-state");
  mkdirSync(GH); mkdirSync(STATE);
  writeFileSync(join(GH, "gh"), `#!/bin/sh
echo "$*" >> "${STATE}/calls"
case "$1 $2" in
  "api repos/test/undertone/releases") [ -f "${STATE}/release" ] && case "$*" in *assets*) cat "${STATE}/assets" ;; *) echo 1 ;; esac ;;
  "release create")
    cp "$(echo "$*" | sed 's/.*--notes-file \\([^ ]*\\).*/\\1/')" "${STATE}/notes"; touch "${STATE}/release"; shift 3
    for a; do case "$a" in --*) break ;; esac; echo "$(basename "$a") $(wc -c < "$a" | tr -d ' ')" >> "${STATE}/assets"; done
    echo https://github.com/test/undertone/releases/tag/untagged-1 ;;
esac
exit 0
`);
  chmodSync(join(GH, "gh"), 0o755);
  const draft = (tag) => run(process.execPath, [join(REPO, ".github/scripts/release.mjs"), "--draft", tag, OUT],
    { PATH: `${GH}:${process.env.PATH}`, GITHUB_REPOSITORY: "test/undertone", GH_TOKEN: "stand-in" });
  let r = await draft("v1.0.0-beta.2");
  ok(r.code !== 0 && /not the version of changelog\/ at this commit \(v1\.0\.0-beta\.1\)/.test(r.out) && !existsSync(join(STATE, "calls")), "release.mjs --draft refuses a tag that is not the changelogs' version, before it asks GitHub");
  r = await draft("v1.0.0-beta.1");
  const calls = existsSync(join(STATE, "calls")) ? readFileSync(join(STATE, "calls"), "utf8") : "";
  ok(r.code === 0 && /release: the draft holds the 10 files/.test(r.out), `release.mjs --draft creates the draft with the ${names.length} files and finds them on it${r.code ? ":\n" + r.out : ""}`);
  ok(/release create v1\.0\.0-beta\.1 .* --draft --verify-tag --title v1\.0\.0-beta\.1 --notes-file \S+ --prerelease/.test(calls) && !/release (edit|upload|delete)|--latest|publish/.test(calls),
    "the release is a draft, marked as a pre-release for a beta, of the existing tag; nothing is published, edited or replaced");
  ok(readFileSync(join(STATE, "notes"), "utf8") === "## Installer, rescue and tools\n\n### Minor Changes\n\n- A line of the notes.\n", "its notes are the changelog entries of the tag's version, under each unit's title");
  r = await draft("v1.0.0-beta.1");
  ok(r.code !== 0 && /a release for v1\.0\.0-beta\.1 exists already/.test(r.out) && (readFileSync(join(STATE, "calls"), "utf8").match(/release create/g) || []).length === 1,
    "release.mjs --draft refuses a tag that has a release already, and creates nothing");
} finally {
  server.close();
  rmSync(TMP, { recursive: true, force: true });
}
console.log(failed ? `${failed} FAILED` : "release files test passed");
process.exit(failed ? 1 : 0);
