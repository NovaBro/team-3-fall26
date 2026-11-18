// Today's mood / energy dropdowns next to the Top picks title.
// Without this script each menu is a visible form that posts and reloads.
(function () {
  "use strict";

  var picker = document.querySelector(".mood-pick");
  if (!picker) return;
  picker.classList.add("is-js");

  var buttons = picker.querySelectorAll(".mood-pick__btn");

  function menuFor(button) {
    return document.getElementById(button.getAttribute("aria-controls"));
  }

  function closeAll(except) {
    buttons.forEach(function (button) {
      if (button === except) return;
      button.setAttribute("aria-expanded", "false");
      menuFor(button).classList.remove("is-open");
    });
  }

  buttons.forEach(function (button) {
    button.addEventListener("click", function (event) {
      event.stopPropagation();
      var open = button.getAttribute("aria-expanded") === "true";
      closeAll(button);
      button.setAttribute("aria-expanded", open ? "false" : "true");
      menuFor(button).classList.toggle("is-open", !open);
      if (!open) {
        var first = menuFor(button).querySelector(".mood-pick__opt");
        if (first) first.focus();
      }
    });
  });

  document.addEventListener("click", function (event) {
    if (!picker.contains(event.target)) closeAll(null);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeAll(null);
  });

  // A small celebration on the banner when today's mood / energy is picked:
  //   5 (Great / Energized)  7 firework bursts all over the banner
  //   4 (Good / Alert)       3 bursts
  //   3 (Okay)               paper confetti
  //   2 (Bad / Tired)        a soft glow behind the headline
  //   1 (Awful / Exhausted)  the glow, twice
  var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)");
  var CONFETTI = ["#c9a64b", "#e8d8a8", "#ffffff", "#9cc3a5", "#e5a27f"];
  var PALETTES = [
    ["#ffd36e", "#fff4cc", "#ffb13b"],
    ["#ff7a8a", "#ffd1d8", "#ff4d6d"],
    ["#7cf0c0", "#dffff0", "#2fd49a"],
    ["#9ec9ff", "#e6f1ff", "#5aa2ff"],
    ["#d59cff", "#f3e3ff", "#b26bff"],
    ["#ffffff", "#fff1c9", "#ffe08a"],
  ];
  // [x, y (share of the banner), size, delay in ms]
  var SHOWS = {
    5: [[0.18, 0.35, 1.15, 0], [0.82, 0.32, 1.15, 220], [0.5, 0.22, 1.35, 440],
        [0.3, 0.62, 0.9, 700], [0.7, 0.6, 0.95, 880], [0.1, 0.2, 0.85, 1100],
        [0.9, 0.2, 0.9, 1250]],
    4: [[0.22, 0.35, 1, 0], [0.78, 0.33, 1, 260], [0.5, 0.25, 1.1, 560]],
  };
  var sky = null; // canvas over the banner, made on first use
  var sparks = [];
  var flashes = [];
  var drawing = false;
  var timers = [];

  function pick(list) {
    return list[Math.floor(Math.random() * list.length)];
  }

  function canvasFor(hero) {
    if (!sky) {
      sky = document.createElement("canvas");
      sky.className = "hero-sky";
      sky.setAttribute("aria-hidden", "true");
      hero.insertBefore(sky, hero.firstChild);
    }
    var box = hero.getBoundingClientRect();
    var ratio = window.devicePixelRatio || 1;
    sky.width = box.width * ratio;
    sky.height = box.height * ratio;
    sky.getContext("2d").setTransform(ratio, 0, 0, ratio, 0, 0);
    return { width: box.width, height: box.height };
  }

  function burst(x, y, size) {
    var main = pick(PALETTES);
    var inner = pick(PALETTES);
    var speed = 3.2 * size + 1;
    var count = Math.round(70 * size);
    var i, angle, v;
    for (i = 0; i < count; i++) {
      angle = (Math.PI * 2 * i) / count + Math.random() * 0.08;
      v = speed * (0.82 + Math.random() * 0.3);
      sparks.push({
        x: x, y: y, trail: [], vx: Math.cos(angle) * v, vy: Math.sin(angle) * v,
        life: 1, decay: 0.011 + Math.random() * 0.006, color: main[i % 3],
        width: 1.8 * size + 0.4, fall: 0.05, glitter: Math.random() < 0.35,
      });
    }
    count = Math.round(32 * size);
    for (i = 0; i < count; i++) {
      angle = (Math.PI * 2 * i) / count;
      sparks.push({
        x: x, y: y, trail: [], vx: Math.cos(angle) * speed * 0.45,
        vy: Math.sin(angle) * speed * 0.45, life: 1, decay: 0.018,
        color: inner[i % 3], width: 1.4 * size + 0.4, fall: 0.04, glitter: false,
      });
    }
    flashes.push({ x: x, y: y, r: 70 * size + 30, a: 0.85 });
    draw();
  }

  function draw() {
    if (drawing || !sky) return;
    drawing = true;
    var ctx = sky.getContext("2d");
    var w = sky.width / (window.devicePixelRatio || 1);
    var h = sky.height / (window.devicePixelRatio || 1);
    (function frame() {
      ctx.globalCompositeOperation = "source-over";
      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = "lighter"; // overlapping light adds up
      flashes = flashes.filter(function (f) {
        var g = ctx.createRadialGradient(f.x, f.y, 0, f.x, f.y, f.r);
        g.addColorStop(0, "rgba(255,240,210," + f.a + ")");
        g.addColorStop(1, "rgba(255,240,210,0)");
        ctx.fillStyle = g;
        ctx.fillRect(f.x - f.r, f.y - f.r, f.r * 2, f.r * 2);
        ctx.fillStyle = "rgba(255,235,200," + f.a * 0.12 + ")";
        ctx.fillRect(0, 0, w, h);
        f.a *= 0.82;
        f.r *= 1.04;
        return f.a > 0.02;
      });
      sparks = sparks.filter(function (s) {
        s.trail.push([s.x, s.y]);
        if (s.trail.length > 6) s.trail.shift();
        s.vx *= 0.965;
        s.vy = s.vy * 0.965 + s.fall;
        s.x += s.vx;
        s.y += s.vy;
        s.life -= s.decay;
        if (s.life <= 0) return false;
        var alpha = s.life;
        if (s.glitter && s.life < 0.6 && Math.random() < 0.5) alpha *= 0.15;
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = s.color;
        ctx.lineWidth = s.width;
        ctx.lineCap = "round";
        ctx.beginPath();
        ctx.moveTo(s.trail[0][0], s.trail[0][1]);
        s.trail.forEach(function (pt) { ctx.lineTo(pt[0], pt[1]); });
        ctx.lineTo(s.x, s.y);
        ctx.stroke();
        if (s.glitter && s.life < 0.6 && Math.random() < 0.5) {
          ctx.fillStyle = "#ffffff";
          ctx.fillRect(s.x - 1, s.y - 1, 2, 2);
        }
        ctx.globalAlpha = 1;
        return true;
      });
      if (sparks.length || flashes.length) {
        window.requestAnimationFrame(frame);
      } else {
        drawing = false;
        ctx.globalCompositeOperation = "source-over";
        ctx.clearRect(0, 0, w, h);
      }
    })();
  }

  function fireworks(hero, show) {
    var area = canvasFor(hero);
    show.forEach(function (shot) {
      timers.push(window.setTimeout(function () {
        var x = (shot[0] + (Math.random() - 0.5) * 0.06) * area.width;
        var y = (shot[1] + (Math.random() - 0.5) * 0.06) * area.height;
        burst(x, y, shot[2]);
      }, shot[3]));
    });
  }

  function confetti(hero, title, count) {
    var heroBox = hero.getBoundingClientRect();
    var titleBox = title.getBoundingClientRect();
    var centerX = titleBox.left - heroBox.left + titleBox.width / 2;
    var centerY = titleBox.top - heroBox.top + titleBox.height / 2;
    for (var i = 0; i < count; i++) {
      var piece = document.createElement("span");
      piece.className = "hero-confetti";
      piece.style.left = centerX + (Math.random() - 0.5) * Math.min(titleBox.width, 320) + "px";
      piece.style.top = centerY + "px";
      piece.style.background = CONFETTI[i % CONFETTI.length];
      hero.appendChild(piece);
      var angle = -Math.PI / 2 + (Math.random() - 0.5) * Math.PI * 1.4;
      var speed = 60 + Math.random() * 90;
      var dx = Math.cos(angle) * speed;
      var dy = Math.sin(angle) * speed;
      var spin = Math.random() * 720 - 360;
      piece.animate(
        [
          { transform: "translate(-50%, -50%) rotate(0deg)", opacity: 1 },
          {
            transform: "translate(calc(-50% + " + dx + "px), calc(-50% + " + dy + "px)) rotate(" + spin / 2 + "deg)",
            opacity: 1,
            offset: 0.45,
          },
          {
            transform: "translate(calc(-50% + " + dx * 1.3 + "px), calc(-50% + " + (dy + 150) + "px)) rotate(" + spin + "deg)",
            opacity: 0,
          },
        ],
        { duration: 1300 + Math.random() * 500, easing: "cubic-bezier(.25,.6,.4,1)" }
      ).onfinish = (function (el) {
        return function () { el.remove(); };
      })(piece);
    }
  }

  function glow(hero, title, times) {
    var heroBox = hero.getBoundingClientRect();
    var titleBox = title.getBoundingClientRect();
    var light = document.createElement("span");
    light.className = "hero-glow";
    light.style.left = titleBox.left - heroBox.left + titleBox.width / 2 + "px";
    light.style.top = titleBox.top - heroBox.top + titleBox.height / 2 + "px";
    hero.appendChild(light);
    // One slow glow, or two (in, out, in, out) taking their time.
    var steps = times === 2
      ? [{ opacity: 0 }, { opacity: 1, offset: 0.22 }, { opacity: 0.15, offset: 0.5 },
         { opacity: 1, offset: 0.72 }, { opacity: 0 }]
      : [{ opacity: 0 }, { opacity: 1, offset: 0.4 }, { opacity: 0 }];
    light.animate(steps, { duration: times === 2 ? 3400 : 1800, easing: "ease-in-out" })
      .onfinish = function () { light.remove(); };
  }

  function celebrate(value) {
    var title = document.getElementById("home-hero-title");
    if (!title || !title.animate || (calm && calm.matches)) return;
    var hero = title.parentNode;
    timers.forEach(window.clearTimeout);
    timers = [];
    if (SHOWS[value]) fireworks(hero, SHOWS[value]);
    else if (value === 3) confetti(hero, title, 24);
    else glow(hero, title, value === 1 ? 2 : 1);
  }

  function setHeadline(title, lede, value) {
    var h1 = document.getElementById("home-hero-title");
    var p = document.getElementById("home-hero-lede");
    if (!h1 || !p) return;
    if (h1.textContent === title) {
      celebrate(value);
      return;
    }
    var hero = h1.parentNode;
    hero.classList.add("is-fading");
    window.setTimeout(function () {
      h1.textContent = title;
      p.textContent = lede;
      hero.classList.remove("is-fading");
      celebrate(value);
    }, 220);
  }

  picker.querySelectorAll(".mood-pick__menu").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      var choice = event.submitter;
      if (!choice || !window.fetch) return; // fall back to a normal post
      event.preventDefault();
      var data = new FormData(form);
      data.set("value", choice.value);
      fetch(form.action, {
        method: "POST",
        body: data,
        headers: { Accept: "application/json" },
        credentials: "same-origin",
      })
        .then(function (response) {
          if (!response.ok) throw new Error("check-in failed");
          return response.json();
        })
        .then(function (result) {
          var button = picker.querySelector('.mood-pick__btn[data-kind="' + result.kind + '"]');
          var caption = result.kind === "mood" ? "Mood" : "Energy";
          button.querySelector(".mood-pick__now").innerHTML = result.icon;
          button.classList.add("is-set");
          button.title = caption + ": " + result.label;
          button.setAttribute("aria-label", "Today's " + caption.toLowerCase() + ": " + result.label);
          form.querySelectorAll(".mood-pick__opt").forEach(function (opt) {
            opt.classList.toggle("is-on", opt === choice);
          });
          closeAll(null);
          button.focus();
          setHeadline(result.title, result.lede, result.value);
        })
        .catch(function () {
          // Let the server handle it the plain way.
          var value = document.createElement("input");
          value.type = "hidden";
          value.name = "value";
          value.value = choice.value;
          form.appendChild(value);
          form.submit();
        });
    });
  });
})();
