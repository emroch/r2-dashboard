// CSV for a component's data table (the "Download CSV" button, #29).
//
// The numbers come from the table Python rendered into the page, so the file is
// exactly what the reader sees: no second copy of the data, and nothing to keep
// in sync. Pure functions, apart from download(), which needs a document.

// One CSV field: quoted only when it has to be (RFC 4180).
function field(v) {
  const s = String(v ?? "");
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

// rows: arrays of cell values, the header row first.
export function toCsv(rows) {
  return rows.map((r) => r.map(field).join(",")).join("\r\n") + "\r\n";
}

// The text of every cell of a <table>, header row included.
export function tableRows(table) {
  return [...table.rows].map((tr) => [...tr.cells].map((td) => td.textContent.trim()));
}

// Show each component's CSV button and wire it to its table.
export function wireCsv(root) {
  for (const btn of root.querySelectorAll("button.r2c-csv[data-table]")) {
    // Ids are built by components.py from component ids: [a-z0-9-] only.
    const table = root.querySelector(`#${btn.dataset.table}`);
    if (!table) continue;
    btn.hidden = false;
    btn.addEventListener("click", () => download(btn.dataset.file, toCsv(tableRows(table))));
  }
}

function download(name, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
