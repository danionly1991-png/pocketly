// Native <dialog> helpers: open/close buttons, backdrop click, focus return, auto-open after a form error.
// Everything degrades without JS: the "+" link goes to ?add=1 and delete buttons fall back to <noscript> forms.
(function () {
  if (typeof HTMLDialogElement === "undefined") return;

  document.querySelectorAll("[data-js-only]").forEach(function (el) {
    el.hidden = false;
  });

  var openers = new WeakMap();

  function openDialog(dialog, opener) {
    if (!dialog || dialog.open) return;
    openers.set(dialog, opener || document.activeElement);
    dialog.showModal();
  }

  document.querySelectorAll("[data-open-dialog]").forEach(function (trigger) {
    trigger.addEventListener("click", function (event) {
      var dialog = document.getElementById(trigger.getAttribute("data-open-dialog"));
      if (!dialog) return;
      event.preventDefault();
      openDialog(dialog, trigger);
    });
  });

  document.querySelectorAll("dialog").forEach(function (dialog) {
    dialog.addEventListener("click", function (event) {
      // Clicking the backdrop targets the <dialog> itself (the content sits in an inner padded div).
      if (event.target === dialog) dialog.close();
    });
    dialog.addEventListener("close", function () {
      var opener = openers.get(dialog);
      if (opener && typeof opener.focus === "function") opener.focus();
    });
  });

  document.querySelectorAll("[data-close-dialog]").forEach(function (button) {
    button.addEventListener("click", function () {
      var dialog = button.closest("dialog");
      if (dialog) dialog.close();
    });
  });

  // A dialog rendered open (validation error, or ?add=1) becomes a proper modal.
  document.querySelectorAll("dialog[data-auto-open]").forEach(function (dialog) {
    if (dialog.open) dialog.close();
    dialog.showModal();
    var first = dialog.querySelector('[aria-invalid="true"]') || dialog.querySelector("input, textarea, select");
    if (first) first.focus();
  });
})();
