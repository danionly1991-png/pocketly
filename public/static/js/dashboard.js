// Dashboard: auto-submit the month and day filters, and close the profile menu on outside click / Esc.
(function () {
  document.querySelectorAll("form[data-autosubmit]").forEach(function (form) {
    form.addEventListener("change", function () {
      form.requestSubmit();
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
