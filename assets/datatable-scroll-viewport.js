(function () {
  "use strict";

  function sortedUnique(values) {
    return values.filter(function (v, i, arr) {
      return v && arr.indexOf(v) === i;
    }).sort();
  }

  function sortedNumeric(values) {
    return values
      .map(function (v) {
        return parseInt(String(v), 10);
      })
      .filter(function (n) {
        return !isNaN(n);
      })
      .sort(function (a, b) {
        return a - b;
      });
  }

  function formatRange(label, values, numeric) {
    var sorted = numeric ? sortedNumeric(values) : sortedUnique(values);
    if (!sorted.length) {
      return "";
    }
    if (sorted.length === 1) {
      return label + ": " + sorted[0];
    }
    return label + ": " + sorted[0] + " – " + sorted[sorted.length - 1];
  }

  function formatViewportInfo(dateValues, indexValues) {
    var parts = [];
    var datePart = formatRange("Dates in view", dateValues, false);
    var indexPart = formatRange("Indexes in view", indexValues, true);
    if (datePart) {
      parts.push(datePart);
    }
    if (indexPart) {
      parts.push(indexPart);
    }
    return parts.join(" · ");
  }

  function visibleColumnValues(viewport, columnId) {
    if (!columnId) {
      return [];
    }
    var containerRect = viewport.getBoundingClientRect();
    var cells = viewport.querySelectorAll('td[data-dash-column="' + columnId + '"]');
    var values = [];
    cells.forEach(function (cell) {
      var row = cell.closest("tr");
      if (!row) {
        return;
      }
      var rowRect = row.getBoundingClientRect();
      if (rowRect.bottom <= containerRect.top || rowRect.top >= containerRect.bottom) {
        return;
      }
      var text = (cell.textContent || "").trim();
      if (text) {
        values.push(text);
      }
    });
    return values;
  }

  function updateViewportInfo(viewport, infoEl, config) {
    if (!viewport || !infoEl) {
      return;
    }
    var dates = visibleColumnValues(viewport, config.dateColumn);
    var indices = visibleColumnValues(viewport, config.indexColumn);
    infoEl.textContent = formatViewportInfo(dates, indices);
  }

  function attachViewport(viewportId, infoId, config) {
    var viewport = document.getElementById(viewportId);
    var infoEl = document.getElementById(infoId);
    if (!viewport || !infoEl) {
      return;
    }
    if (viewport.dataset.scrollViewportBound === "1") {
      updateViewportInfo(viewport, infoEl, config);
      return;
    }
    viewport.dataset.scrollViewportBound = "1";
    var onChange = function () {
      updateViewportInfo(viewport, infoEl, config);
    };
    viewport.addEventListener("scroll", onChange, { passive: true });
    window.addEventListener("resize", onChange);
    var observer = new MutationObserver(onChange);
    observer.observe(viewport, { childList: true, subtree: true, characterData: true });
    onChange();
  }

  function attachAll() {
    attachViewport("expenses-table-scroll", "expenses-table-viewport-info", {
      dateColumn: "Booking Date",
      indexColumn: null,
    });
    attachViewport("seq-expenses-table-scroll", "seq-expenses-table-viewport-info", {
      dateColumn: "Booking Date",
      indexColumn: "Index",
    });
  }

  window.MoneyTrackerScrollViewport = {
    attachAll: attachAll,
    formatViewportInfo: formatViewportInfo,
  };

  var attachTimer = null;
  function scheduleAttachAll() {
    clearTimeout(attachTimer);
    attachTimer = setTimeout(attachAll, 250);
  }

  document.addEventListener("DOMContentLoaded", scheduleAttachAll);

  // Re-attach after Dash replaces table DOM; scope observer to the app root only.
  document.addEventListener("DOMContentLoaded", function () {
    var entry = document.getElementById("react-entry-point");
    if (!entry) {
      return;
    }
    var observer = new MutationObserver(function () {
      if (!entry.querySelector("._dash-loading")) {
        scheduleAttachAll();
      }
    });
    observer.observe(entry, { childList: true, subtree: true });
  });
})();
