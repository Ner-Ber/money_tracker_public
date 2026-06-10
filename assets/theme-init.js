// Apply the persisted theme to <html> as early as possible so the first paint
// already uses the correct palette (avoids a flash of the default theme).
// dcc.Store(storage_type="local") persists under the key "theme-store" as a
// JSON-encoded string, e.g. '"dark"'.
(function () {
  "use strict";
  var theme = "teal";
  try {
    var raw = window.localStorage.getItem("theme-store");
    if (raw) {
      var parsed = JSON.parse(raw);
      if (parsed === "dark" || parsed === "teal") {
        theme = parsed;
      }
    }
  } catch (e) {
    /* ignore storage/parse errors and fall back to the default */
  }
  document.documentElement.setAttribute("data-theme", theme);
})();
