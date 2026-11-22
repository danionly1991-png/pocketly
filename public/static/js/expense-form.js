// Expense form: Today / Yesterday quick date buttons, the weekday under the date, and a live note character counter.
// Without JS the quick buttons stay hidden and the plain date input still works.
(function () {
  function isoOffset(todayIso, daysBack) {
    var d = new Date(todayIso + "T00:00");
    d.setDate(d.getDate() - daysBack);
    var month = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + month + "-" + day;
  }

  function weekday(value) {
    var date = value ? new Date(value + "T00:00") : null;
    return date && !isNaN(date) ? date.toLocaleDateString("en-GB", { weekday: "long" }) : "";
  }

  document.querySelectorAll("[data-day-input]").forEach(function (input) {
    var group = input.closest("[data-day-quick-group]");
    var field = group ? group.parentElement : input.parentElement;
    var label = field.querySelector("[data-day-name]");
    var buttons = group ? group.querySelectorAll("[data-day-quick]") : [];
    var todayIso = group ? group.getAttribute("data-today") : "";

    function sync() {
      if (label) label.textContent = weekday(input.value);
      buttons.forEach(function (button) {
        var target = isoOffset(todayIso, Number(button.getAttribute("data-day-quick")));
        button.setAttribute("aria-pressed", String(input.value === target));
      });
    }

    buttons.forEach(function (button) {
      button.hidden = false;
      button.addEventListener("click", function () {
        input.value = isoOffset(todayIso, Number(button.getAttribute("data-day-quick")));
        input.dispatchEvent(new Event("change", { bubbles: true }));
      });
    });

    input.addEventListener("change", sync);
    input.addEventListener("input", sync);
    if (todayIso) sync();
  });

  document.querySelectorAll("[data-char-input]").forEach(function (input) {
    var counter = input.parentElement.querySelector("[data-char-count]");
    if (!counter) return;
    input.addEventListener("input", function () {
      counter.textContent = String(input.value.length);
    });
  });
})();
