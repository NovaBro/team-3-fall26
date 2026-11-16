// Top picks title: the borough menu becomes a "slot reel". The name rolls up
// or down (arrows, click, mouse wheel or the keyboard), and 0.8 s after the
// last change the page loads that borough. The real <select> stays in the
// form (hidden) so the borough is still sent the normal way.
(function () {
  var select = document.getElementById("restaurant-boro");
  if (!select || !select.classList.contains("top-picks__boro")) return;
  var options = Array.prototype.slice.call(select.options);
  var index = select.selectedIndex;
  var timer = null;

  function svg(path) {
    return '<svg viewBox="0 0 20 20" width="24" height="24" fill="none" ' +
      'stroke="currentColor" stroke-width="2.2" stroke-linecap="round" ' +
      'stroke-linejoin="round" aria-hidden="true"><path d="' + path + '"/></svg>';
  }

  var wrap = document.createElement("span");
  wrap.className = "boro-reel";
  var reel = document.createElement("span");
  reel.className = "boro-reel__window";
  reel.tabIndex = 0;
  reel.setAttribute("role", "spinbutton");
  reel.setAttribute("aria-label", "Borough. Use the up and down arrow keys to change it.");
  var list = document.createElement("span");
  list.className = "boro-reel__list";
  options.forEach(function (option) {
    var item = document.createElement("span");
    item.className = "boro-reel__item";
    item.textContent = option.text;
    list.appendChild(item);
  });
  reel.appendChild(list);
  var arrows = document.createElement("span");
  arrows.className = "boro-reel__arrows";
  var up = document.createElement("button");
  up.type = "button";
  up.className = "boro-reel__arrow";
  up.setAttribute("aria-label", "Previous borough");
  up.innerHTML = svg("m5 12 5-5 5 5");
  var down = document.createElement("button");
  down.type = "button";
  down.className = "boro-reel__arrow boro-reel__arrow--down";
  down.setAttribute("aria-label", "Next borough");
  down.innerHTML = svg("m5 8 5 5 5-5");
  arrows.appendChild(up);
  arrows.appendChild(down);
  wrap.appendChild(reel);
  wrap.appendChild(arrows);
  select.parentNode.insertBefore(wrap, select);
  select.classList.add("is-replaced");

  // The window is as wide as the longest name, so the arrows stay in one
  // place while the name changes.
  var widest = 0;
  Array.prototype.forEach.call(list.children, function (item) {
    widest = Math.max(widest, item.scrollWidth);
  });
  var style = getComputedStyle(reel);
  var padding = parseFloat(style.paddingLeft) + parseFloat(style.paddingRight);
  reel.style.width = widest + 2 + padding + "px";

  function draw() {
    list.style.transform = "translateY(" + (-index * 100) / options.length + "%)";
    reel.setAttribute("aria-valuetext", options[index].text);
  }

  function move(step) {
    index = (index + step + options.length) % options.length;
    draw();
    clearTimeout(timer);
    timer = setTimeout(function () {
      if (select.selectedIndex === index) return;
      select.selectedIndex = index;
      select.form.submit();
    }, 800);
  }

  up.addEventListener("click", function () { move(-1); });
  down.addEventListener("click", function () { move(1); });
  reel.addEventListener("click", function () { move(1); });
  reel.addEventListener("keydown", function (event) {
    if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      move(1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      move(-1);
    }
  });
  var wheelLock = false;
  wrap.addEventListener("wheel", function (event) {
    event.preventDefault();
    if (wheelLock) return;
    wheelLock = true;
    move(event.deltaY > 0 ? 1 : -1);
    setTimeout(function () { wheelLock = false; }, 250);
  }, { passive: false });

  list.style.transition = reel.style.transition = "none";
  draw();
  void list.offsetHeight;
  list.style.transition = reel.style.transition = "";
})();
