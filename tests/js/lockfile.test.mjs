// package-lock.json must resolve every package from the public npm registry.
//
// npm records the URL each tarball was fetched from. Run `npm install` on a
// machine whose npm is configured with a private mirror and the lockfile fills
// with that mirror's URLs, which CI (and anyone else) can't reach. This catches
// it before it is pushed: re-point the URLs at registry.npmjs.org (the tarballs,
// and so the integrity hashes, are the same), or regenerate the lockfile with
// `npm install --registry=https://registry.npmjs.org/`.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const PUBLIC = "https://registry.npmjs.org/";
const lock = JSON.parse(readFileSync(new URL("../../package-lock.json", import.meta.url)));

test("every locked package resolves from the public npm registry", () => {
  const off = Object.entries(lock.packages)
    .filter(([path, pkg]) => path && !pkg.link && !String(pkg.resolved).startsWith(PUBLIC))
    .map(([path, pkg]) => `${path}: ${pkg.resolved}`);
  assert.deepEqual(off, [], `not from ${PUBLIC}:\n${off.join("\n")}`);
});

test("every locked package is pinned by an integrity hash", () => {
  const loose = Object.entries(lock.packages)
    .filter(([path, pkg]) => path && !pkg.link && !pkg.integrity)
    .map(([path]) => path);
  assert.deepEqual(loose, []);
});
