// Category form: show only the icon picker that matches the chosen type, and preview a chosen photo.
// Without JavaScript both pickers stay visible and the selected icon type decides which one is used.
(function () {
  var form = document.getElementById("category-form");
  if (!form) return;

  var panels = form.querySelectorAll("[data-icon-panel]");
  var typeRadios = form.querySelectorAll('input[name="icon_type"]');

  function currentType() {
    var checked = form.querySelector('input[name="icon_type"]:checked');
    return checked ? checked.value : "emoji";
  }

  function sync() {
    var type = currentType();
    panels.forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-icon-panel") !== type;
    });
  }

  function selectType(value) {
    var radio = form.querySelector('input[name="icon_type"][value="' + value + '"]');
    if (radio) radio.checked = true;
    sync();
  }

  typeRadios.forEach(function (radio) {
    radio.addEventListener("change", sync);
  });

  var file = form.querySelector('input[type="file"]');
  var preview = form.querySelector("[data-icon-preview]");
  if (file) {
    file.addEventListener("change", function () {
      var chosen = file.files && file.files[0];
      if (!chosen) return;
      if (preview) {
        preview.src = URL.createObjectURL(chosen);
        preview.hidden = false;
      }
      selectType("image");
    });
  }

  form.querySelectorAll('input[name="emoji"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      selectType("emoji");
    });
  });

  sync();
})();
