#!/usr/bin/env node
// The files of a release (.github/workflows/release.yml, docs/RELEASING.md), assembled from what `node tools/op.mjs all`
// and `node tools/op.mjs kit` built:
//   - the firmware catalog release.json and every firmware it names: each one's manifest.json and its packages;
//   - the rescue kit zip of this repository, without M-VAVE's files (rescue/README.md);
//   - site.sha256, the checksum list the site serves the release from (site/README.md, site/latest.py, site/release.sh):
//     one line per file of the catalog, its SHA-256, its path on the site and its asset name. The kit is not on it,
//     because the site builds its own kit from the same sources;
//   - SHA256SUMS, the SHA-256 of every other file, for `sha256sum -c`.
//   node .github/scripts/assets.mjs OUT_DIR [--site docs/firmware] [--apps build/apps] [--kit docs/rescue]
// OUT_DIR must be empty or missing. A release's assets have no folders, so an app's files are named after the app:
// apps/palette/manifest.json is the asset palette-manifest.json. It fails when a file is not the bytes the catalog or the
// kit's manifest names, and when two files would get the same asset name.
import { createHash } from "node:crypto";
import { copyFileSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "../..");
const fail = (m) => { console.error(`release assets: ${m}`); process.exit(1); };
const sha256 = (file) => createHash("sha256").update(readFileSync(file)).digest("hex");

const args = process.argv.slice(2);
const option = (name, fallback) => {
  const i = args.indexOf(name);
  return resolve(root, i < 0 ? fallback : args.splice(i, 2)[1] ?? fail(`${name} needs a folder`));
};
const site = option("--site", "docs/firmware"), apps = option("--apps", "build/apps"), kit = option("--kit", "docs/rescue");
if (args.length !== 1) fail("usage: node .github/scripts/assets.mjs OUT_DIR [--site DIR] [--apps DIR] [--kit DIR]");
const out = resolve(args[0]);
if (existsSync(out) && readdirSync(out).length) fail(`${out} is not empty`);

const files = [];   // { path on the site, or null for a file the site does not serve; asset name; source file }
const add = (path, asset, source, sum) => {
  if (!existsSync(source)) fail(`${source} is missing: build it first (node tools/op.mjs all, node tools/op.mjs kit)`);
  if (sum && sha256(source) !== sum) fail(`${source} is not the file its manifest names (SHA-256 differs): build it again`);
  if (!/^[A-Za-z0-9][A-Za-z0-9._+-]*$/.test(asset) || ["site.sha256", "SHA256SUMS"].includes(asset)) fail(`${asset} cannot be an asset name`);
  if (files.some((f) => f.asset === asset)) fail(`two files would be the asset ${asset}`);
  files.push({ path, asset, source });
};

// the catalog's paths are relative to it: the first firmware's files beside it, an app's under apps/<id>/, which the
// build keeps in build/apps/<id>/ (tools/catalog.py)
const where = (rel) => {
  const app = rel.match(/^apps\/([a-z0-9-]+)\/([^/]+)$/);
  if (app) return { source: join(apps, app[1], app[2]), asset: app[2].startsWith(`${app[1]}-`) ? app[2] : `${app[1]}-${app[2]}` };
  if (!/^[^/]+$/.test(rel)) fail(`release.json names a path the site cannot serve: ${rel}`);
  return { source: join(site, rel), asset: rel };
};
const catalogFile = join(site, "release.json");
if (!existsSync(catalogFile)) fail(`${catalogFile} is missing: build it first (node tools/op.mjs all)`);
const catalog = JSON.parse(readFileSync(catalogFile, "utf8"));
if (!catalog.firmwares?.length) fail(`${catalogFile} names no firmware`);
add("firmware/release.json", "release.json", catalogFile);
for (const fw of catalog.firmwares) {
  const man = where(fw.manifest);
  add(`firmware/${fw.manifest}`, man.asset, man.source);
  for (const p of fw.packages) {
    const pkg = where(p.file);
    add(`firmware/${p.file}`, pkg.asset, pkg.source, p.sha256);
  }
}
const kitFile = join(kit, "manifest.json");
if (!existsSync(kitFile)) fail(`${kitFile} is missing: build the kit first (node tools/op.mjs kit)`);
const kitManifest = JSON.parse(readFileSync(kitFile, "utf8"));
if (kitManifest.firmware) fail(`${kitFile} is the full kit with M-VAVE's files, which no release of this repository carries`);
add(null, kitManifest.file, join(kit, kitManifest.file), kitManifest.sha256);

mkdirSync(out, { recursive: true });
for (const f of files) copyFileSync(f.source, join(out, f.asset));
const served = files.filter((f) => f.path);
writeFileSync(join(out, "site.sha256"), "# The files the site serves from this release (site/README.md): SHA-256, path on the site, release asset\n" +
  served.map((f) => `${sha256(join(out, f.asset))}  ${f.path}  ${f.asset}\n`).join(""));
const all = [...files.map((f) => f.asset), "site.sha256"].sort();
writeFileSync(join(out, "SHA256SUMS"), all.map((a) => `${sha256(join(out, a))}  ${a}\n`).join(""));
for (const a of [...all, "SHA256SUMS"]) {
  const path = files.find((f) => f.asset === a)?.path;
  console.log(path ? `${a}  (the site's ${path})` : a);
}
console.log(`release assets: ${all.length + 1} files in ${out}, ${served.length} of them on the site`);
