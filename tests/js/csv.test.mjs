// Unit tests for src/web/lib/csv.js.
import assert from "node:assert/strict";
import { test } from "node:test";

import { tableRows, toCsv, wireCsv } from "../../src/web/lib/csv.js";

test("plain values are written as-is, one CRLF-terminated line per row", () => {
  assert.equal(toCsv([["Paint", "Orders"], ["Launch Green", 162]]),
               "Paint,Orders\r\nLaunch Green,162\r\n");
});

test("commas, quotes and line breaks are quoted (RFC 4180)", () => {
  assert.equal(toCsv([['20" Black Sand', "a,b", "two\nlines", null]]),
               '"20"" Black Sand","a,b","two\nlines",\r\n');
});

test("tableRows reads every cell's trimmed text, header first", () => {
  const cell = (t) => ({ textContent: t });
  const table = { rows: [{ cells: [cell(" Paint "), cell("n")] },
                         { cells: [cell("Midnight"), cell(" 18")] }] };
  assert.deepEqual(tableRows(table), [["Paint", "n"], ["Midnight", "18"]]);
});

test("wireCsv shows a button only when its table exists", () => {
  const ok = { dataset: { table: "c-a-data", file: "c-a.csv" }, hidden: true,
               addEventListener() {} };
  const orphan = { dataset: { table: "c-gone-data", file: "x.csv" }, hidden: true,
                   addEventListener() {} };
  const root = {
    querySelectorAll: () => [ok, orphan],
    querySelector: (sel) => (sel === "#c-a-data" ? { rows: [] } : null),
  };
  wireCsv(root);
  assert.equal(ok.hidden, false);
  assert.equal(orphan.hidden, true);
});
