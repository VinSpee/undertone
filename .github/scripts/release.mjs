#!/usr/bin/env node
// The release steps of .github/workflows/release.yml (docs/RELEASING.md). The release units of changelog/ share one
// version: the "fixed" group of .changeset/config.json. `changeset version` writes that version and one CHANGELOG.md
// per unit; this script turns them into the tag v<version> and a draft GitHub release whose notes are those entries.
//   node .github/scripts/release.mjs                 print the tag and the release notes of the current version; changes nothing
//   node .github/scripts/release.mjs --tag           create the tag v<version> when it is missing, and, when no release
//                                                     exists for it, name it in the step output `tag` (the build follows)
//   node .github/scripts/release.mjs --draft TAG DIR create the draft release of TAG with every file of DIR as an asset;
//                                                     TAG must be v<version>, and it refuses when TAG has a release already
// --tag and --draft need the gh CLI with GH_TOKEN, and GITHUB_REPOSITORY, as a workflow step has them. It never publishes.
import { execFileSync } from "node:child_process";
import { appendFileSync, existsSync, mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const read = (p) => readFileSync(resolve(root, p), "utf8");
const fail = (m) => { console.error(`release: ${m}`); process.exit(1); };

// the units, in the order of the notes: the fixed group names them, each folder of changelog/ holds one
const units = JSON.parse(read(".changeset/config.json")).fixed[0].map((name) => {
  const pkg = JSON.parse(read(`changelog/${name}/package.json`));
  if (pkg.name !== name) fail(`changelog/${name}/package.json is named ${pkg.name}.`);
  return { name, title: pkg.description, version: pkg.version, dir: `changelog/${name}` };
});
const version = units[0].version;
const odd = units.filter((u) => u.version !== version);
if (odd.length) fail(`the units must share one version, but ${units[0].name} is ${version} and ${odd.map((u) => `${u.name} is ${u.version}`).join(", ")}.`);
const tag = `v${version}`;

// a unit's entry for this version: the lines under "## <version>" up to the next "## "
function entry(unit) {
  const file = `${unit.dir}/CHANGELOG.md`;
  if (!existsSync(resolve(root, file))) return "";
  const lines = read(file).split("\n");
  const from = lines.indexOf(`## ${version}`);
  if (from < 0) return "";
  const rest = lines.slice(from + 1);
  const to = rest.findIndex((l) => l.startsWith("## "));
  const text = rest.slice(0, to < 0 ? rest.length : to).join("\n").trim();
  return text === "No changes in this release." ? "" : text;
}
const notes = units.map((u) => [u, entry(u)]).filter(([, e]) => e).map(([u, e]) => `## ${u.title}\n\n${e}\n`).join("\n");
const [mode, draftTag, dir] = process.argv.slice(2);
if (!["--tag", "--draft", undefined].includes(mode) || (mode === "--draft" && !dir)) fail("usage: release.mjs [--tag | --draft TAG DIR]");
// a draft is made from a checkout of its tag, whose changelogs hold the entries of the tag's version
if (mode === "--draft" && draftTag !== tag) fail(`the tag ${draftTag} is not the version of changelog/ at this commit (${tag}). Tag the merge of the Version Packages pull request.`);
if (!notes) {
  if (mode === "--draft") fail(`no unit has a changelog entry for ${version}: the draft would have no notes.`);
  console.log(`release: no unit has a changelog entry for ${version}. Nothing to release.`);
  process.exit(0);
}
if (!mode) { console.log(`tag: ${tag}\n\n${notes}`); process.exit(0); }

const repo = process.env.GITHUB_REPOSITORY || fail("GITHUB_REPOSITORY is not set.");
const gh = (...args) => execFileSync("gh", args, { cwd: root, encoding: "utf8", stdio: ["ignore", "pipe", "inherit"] }).trim();
// drafts are in this list too
const released = () => gh("api", `repos/${repo}/releases`, "--paginate", "--jq", `.[] | select(.tag_name == "${tag}") | .id`) !== "";

if (mode === "--tag") {
  // the commit that set this version: the merge of the Version Packages pull request
  const commit = execFileSync("git", ["log", "-1", "--format=%H", "--", `${units[0].dir}/package.json`], { cwd: root, encoding: "utf8" }).trim();
  if (gh("api", `repos/${repo}/git/matching-refs/tags/${tag}`, "--jq", `[.[] | select(.ref == "refs/tags/${tag}")] | length`) === "0") {
    gh("api", `repos/${repo}/git/refs`, "-f", `ref=refs/tags/${tag}`, "-f", `sha=${commit}`, "--silent");
    console.log(`release: created the tag ${tag} at ${commit}`);
  } else console.log(`release: the tag ${tag} exists`);
  if (released()) { console.log(`release: a release for ${tag} exists. Nothing to do.`); process.exit(0); }
  console.log(`release: ${tag} has no release yet: the build of its files and the draft follow`);
  if (process.env.GITHUB_OUTPUT) appendFileSync(process.env.GITHUB_OUTPUT, `tag=${tag}\n`);
  process.exit(0);
}

if (released()) fail(`a release for ${tag} exists already. It is never replaced: delete it on GitHub first to make it again.`);
const assets = readdirSync(dir).sort().map((name) => join(dir, name));
if (!assets.length) fail(`${dir} holds no file to attach.`);
const file = join(mkdtempSync(join(tmpdir(), "release-")), "notes.md");
writeFileSync(file, notes);
const url = gh("release", "create", tag, ...assets, "--repo", repo, "--draft", "--verify-tag", "--title", tag, "--notes-file", file, ...(version.includes("-") ? ["--prerelease"] : []));
console.log(`release: created the draft release ${url}`);
// what GitHub holds: every file, at its size
const held = gh("api", `repos/${repo}/releases`, "--paginate", "--jq", `.[] | select(.tag_name == "${tag}") | .assets[] | "\\(.name) \\(.size)"`).split("\n").filter(Boolean).sort();
const sent = assets.map((a) => `${basename(a)} ${statSync(a).size}`).sort();
if (held.join("\n") !== sent.join("\n")) fail(`the draft's files are not the ones sent:\n  sent: ${sent.join(", ")}\n  held: ${held.join(", ")}`);
console.log(`release: the draft holds the ${held.length} files`);
