// Expense form: show the weekday under the date and a live note character counter.
(function () {
  document.querySelectorAll("[data-day-input]").forEach(function (input) {
    var label = input.parentElement.querySelector("[data-day-name]");
    if (!label) return;
    input.addEventListener("change", function () {
      var date = input.value ? new Date(input.value + "T00:00") : null;
      label.textContent = date && !isNaN(date) ? date.toLocaleDateString("en-GB", { weekday: "long" }) : "";
    });
  });

  document.querySelectorAll("[data-char-input]").forEach(function (input) {
    var counter = input.parentElement.querySelector("[data-char-count]");
    if (!counter) return;
    input.addEventListener("input", function () {
      counter.textContent = String(input.value.length);
    });
  });
})();
