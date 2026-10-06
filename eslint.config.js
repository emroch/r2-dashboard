// ESLint for the browser code under src/web/, the JS tests, and the Worker.
// Lint only (correctness rules from @eslint/js), with no formatter, matching
// how ruff is used for the Python.
import js from "@eslint/js";
import globals from "globals";

export default [
  {
    ignores: ["node_modules/", "output/", "dist/", "data/", ".venv*/",
              "src/web/vendor/"],
  },
  js.configs.recommended,
  {
    // ES modules that run in the page: the boot module and everything it imports.
    files: ["src/web/**/*.js"],
    languageOptions: { sourceType: "module", globals: globals.browser },
  },
  {
    // Classic page scripts, loaded with a plain <script> (not type="module"),
    // in the order page.html lists them. head.js is inlined into <head>.
    files: ["src/web/theme.js", "src/web/nav.js", "src/web/scrollzoom.js",
            "src/templates/*.js"],
    languageOptions: { sourceType: "script", globals: globals.browser },
  },
  {
    // The chart-library spike (#107): classic scripts using each library's
    // global. Temporary, removed with tools/spike/.
    files: ["tools/spike/*.js"],
    languageOptions: {
      sourceType: "script",
      globals: { ...globals.browser, Plot: "readonly", echarts: "readonly",
                 Plotly: "readonly", topojson: "readonly" },
    },
  },
  {
    files: ["tests/js/**/*.mjs", "eslint.config.js"],
    languageOptions: { sourceType: "module", globals: globals.node },
  },
  {
    files: ["worker/**/*.js"],
    languageOptions: { sourceType: "module", globals: globals.serviceworker },
  },
];
