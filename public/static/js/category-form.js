// Category form: preview a chosen photo and switch the icon type to match what the user picks.
(function () {
  var form = document.getElementById("category-form");
  if (!form) return;

  function selectType(value) {
    var radio = form.querySelector('input[name="icon_type"][value="' + value + '"]');
    if (radio) radio.checked = true;
  }

  var file = form.querySelector('input[type="file"]');
  var preview = form.querySelector("[data-icon-preview]");
  if (file && preview) {
    file.addEventListener("change", function () {
      var chosen = file.files && file.files[0];
      if (!chosen) return;
      preview.src = URL.createObjectURL(chosen);
      preview.hidden = false;
      selectType("image");
    });
  }

  form.querySelectorAll('input[name="emoji"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      selectType("emoji");
    });
  });
})();
