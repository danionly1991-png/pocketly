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

  // Gallery photos are often several MB. Shrink them in the browser first (longest side 1024px, WEBP or JPEG),
  // so the upload stays well under the 2 MB limit. The server still checks and crops to 128x128.
  var MAX_SIDE = 1024;

  function toBlob(canvas, type, quality) {
    return new Promise(function (resolve) {
      canvas.toBlob(resolve, type, quality);
    });
  }

  function loadBitmap(chosen) {
    if (window.createImageBitmap) {
      return createImageBitmap(chosen, { imageOrientation: "from-image" });
    }
    return new Promise(function (resolve, reject) {
      var img = new Image();
      img.onload = function () {
        resolve(img);
      };
      img.onerror = reject;
      img.src = URL.createObjectURL(chosen);
    });
  }

  async function shrink(chosen) {
    var bitmap = await loadBitmap(chosen);
    var width = bitmap.width || bitmap.naturalWidth;
    var height = bitmap.height || bitmap.naturalHeight;
    var scale = Math.min(1, MAX_SIDE / Math.max(width, height));
    var canvas = document.createElement("canvas");
    canvas.width = Math.max(1, Math.round(width * scale));
    canvas.height = Math.max(1, Math.round(height * scale));
    canvas.getContext("2d").drawImage(bitmap, 0, 0, canvas.width, canvas.height);

    var blob = await toBlob(canvas, "image/webp", 0.85);
    var type = "image/webp";
    if (!blob || blob.type !== "image/webp") {
      blob = await toBlob(canvas, "image/jpeg", 0.85);
      type = "image/jpeg";
    }
    if (!blob) return chosen;
    return new File([blob], "icon." + (type === "image/webp" ? "webp" : "jpg"), { type: type });
  }

  var file = form.querySelector('input[type="file"]');
  var preview = form.querySelector("[data-icon-preview]");
  if (file) {
    file.addEventListener("change", async function () {
      var chosen = file.files && file.files[0];
      if (!chosen) return;
      selectType("image");

      try {
        var smaller = await shrink(chosen);
        if (smaller !== chosen && window.DataTransfer) {
          var transfer = new DataTransfer();
          transfer.items.add(smaller);
          file.files = transfer.files;
          chosen = smaller;
        }
      } catch (error) {
        // Can't decode it here (e.g. HEIC): send the original and let the server decide.
      }

      if (preview) {
        preview.src = URL.createObjectURL(chosen);
        preview.hidden = false;
      }
    });
  }

  form.querySelectorAll('input[name="emoji"]').forEach(function (radio) {
    radio.addEventListener("change", function () {
      selectType("emoji");
    });
  });

  sync();
})();
