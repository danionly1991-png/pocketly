// Dashboard: auto-submit the month filter, open the calendar day picker, and close the profile menu on outside click / Esc.
(function () {
  document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
    form.addEventListener("change", function () {
      form.requestSubmit();
    });
  });

  // Calendar button: open the hidden native date input, then load the picked day (Spec 03 §7.1).
  document.querySelectorAll("form[data-day-picker]").forEach(function (form) {
    var input = form.querySelector('input[type="date"]');
    var button = form.querySelector("[data-day-button]");
    if (!input || !button) return;

    button.addEventListener("click", function () {
      if (typeof input.showPicker === "function") {
        try {
          input.showPicker();
          return;
        } catch (error) {
          // Not allowed here (e.g. some iframes): fall through to focus/click.
        }
      }
      input.focus();
      input.click();
    });

    input.addEventListener("change", function () {
      if (input.value) {
        form.requestSubmit();
      } else if (form.dataset.clearUrl) {
        window.location.href = form.dataset.clearUrl; // the picker's own "Clear" = back to the month
      }
    });
  });

  var menus = document.querySelectorAll("details[data-profile-menu]");

  document.addEventListener("click", function (event) {
    menus.forEach(function (menu) {
      if (menu.open && !menu.contains(event.target)) menu.open = false;
    });
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "Escape") return;
    menus.forEach(function (menu) {
      if (!menu.open) return;
      menu.open = false;
      var summary = menu.querySelector("summary");
      if (summary) summary.focus();
    });
  });
})();
