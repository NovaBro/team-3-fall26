// Profile food picker: popular chips plus a search box.
// The real form value stays in the text input (hidden here), as
// comma-separated labels from accounts/forms.FoodPickerWidget.
(function () {
  var pickers = document.querySelectorAll("[data-food-picker]");
  if (!pickers.length) return;

  function readList(input) {
    return (input.value || "")
      .split(",")
      .map(function (item) { return item.trim(); })
      .filter(Boolean);
  }

  function chip(label, className, iconText, onClick) {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "food-chip " + className;
    button.textContent = label;
    var icon = document.createElement("span");
    icon.className = "food-chip__icon";
    icon.setAttribute("aria-hidden", "true");
    icon.textContent = iconText;
    if (iconText === "+") button.insertBefore(icon, button.firstChild);
    else button.appendChild(icon);
    button.addEventListener("click", onClick);
    return button;
  }

  pickers.forEach(function (box) {
    var input = box.querySelector("input");
    var other = document.getElementById(box.dataset.other);
    var options = JSON.parse(box.dataset.options || "[]");
    var popular = JSON.parse(box.dataset.popular || "[]");
    var kind = input.name === "disliked_foods" ? "is-disliked" : "is-favorite";
    var byKey = {};
    options.forEach(function (label) { byKey[label.toLowerCase()] = label; });

    input.type = "hidden";
    var picked = document.createElement("div");
    picked.className = "food-picker__picked";
    var popularLabel = document.createElement("p");
    popularLabel.className = "muted field-help";
    popularLabel.textContent = "Popular";
    var popularBox = document.createElement("div");
    popularBox.className = "food-picker__popular";
    var search = document.createElement("input");
    search.type = "text";
    search.className = "food-picker__search";
    search.placeholder = box.dataset.placeholder || "Search";
    search.setAttribute("aria-label", "Search foods to add");
    search.autocomplete = "off";
    var suggest = document.createElement("div");
    suggest.className = "food-picker__suggest";
    suggest.hidden = true;
    [picked, popularLabel, popularBox, search, suggest].forEach(function (el) {
      box.insertBefore(el, input);
    });

    function taken() {
      var mine = readList(input);
      var theirs = other ? readList(other) : [];
      return mine.concat(theirs).map(function (l) { return l.toLowerCase(); });
    }

    function save(list) {
      input.value = list.join(", ");
      document.dispatchEvent(new CustomEvent("foods-change"));
    }

    function add(label) {
      var list = readList(input);
      if (list.indexOf(label) === -1) list.push(label);
      save(list);
    }

    function remove(label) {
      save(readList(input).filter(function (item) { return item !== label; }));
    }

    function renderSuggest() {
      var text = search.value.trim().toLowerCase();
      suggest.innerHTML = "";
      if (!text) { suggest.hidden = true; return; }
      var used = taken();
      var matches = options.filter(function (label) {
        return label.toLowerCase().indexOf(text) !== -1 &&
          used.indexOf(label.toLowerCase()) === -1;
      }).slice(0, 6);
      if (!matches.length) {
        var none = document.createElement("p");
        none.className = "food-picker__none muted";
        none.textContent = "No match";
        suggest.appendChild(none);
      }
      matches.forEach(function (label) {
        var item = document.createElement("button");
        item.type = "button";
        item.className = "food-picker__option";
        item.textContent = label;
        item.addEventListener("click", function () {
          add(label);
          search.value = "";
          suggest.hidden = true;
          search.focus();
        });
        suggest.appendChild(item);
      });
      suggest.hidden = false;
    }

    function render() {
      picked.innerHTML = "";
      readList(input).forEach(function (label) {
        var shown = byKey[label.toLowerCase()] || label;
        var button = chip(shown, kind, "×", function () { remove(label); });
        button.setAttribute("aria-label", "Remove " + shown);
        picked.appendChild(button);
      });
      popularBox.innerHTML = "";
      var used = taken();
      popular.forEach(function (label) {
        if (used.indexOf(label.toLowerCase()) !== -1) return;
        popularBox.appendChild(chip(label, "", "+", function () { add(label); }));
      });
      popularLabel.hidden = !popularBox.children.length;
    }

    search.addEventListener("input", renderSuggest);
    search.addEventListener("keydown", function (event) {
      if (event.key !== "Enter") return;
      event.preventDefault();  // don't submit the whole form
      var first = suggest.querySelector(".food-picker__option");
      if (first) first.click();
    });
    document.addEventListener("foods-change", function () {
      render();
      if (!suggest.hidden) renderSuggest();
    });
    render();
  });
})();
