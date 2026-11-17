// Show/Hide toggle for password inputs. Buttons are rendered `hidden` so the
// forms still work without JavaScript; this script reveals and wires them up.
document.querySelectorAll("[data-password-toggle]").forEach(function (button) {
  var input = document.getElementById(button.dataset.passwordToggle);
  if (!input) return;
  button.hidden = false;
  button.addEventListener("click", function () {
    var show = input.type === "password";
    input.type = show ? "text" : "password";
    button.textContent = show ? "Hide" : "Show";
  });
});
