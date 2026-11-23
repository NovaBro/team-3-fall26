// 47c: measure where the page starts (below the site header) before the map
// loads, so the fixed layout lines up exactly with the header.
(() => {
  const sp = document.querySelector(".sp");
  if (!sp) return;
  const top = Math.max(0, Math.round(sp.getBoundingClientRect().top + window.scrollY));
  document.documentElement.style.setProperty("--sp-top", `${top}px`);
})();

// Search page: filter chips live over the map, outside the <form>, so link
// their controls to the form with the `form` attribute. Then: one chip open
// at a time, show chosen values on the chip, hide chips for unchecked types,
// and search right away when a filter changes.
(() => {
  const form = document.getElementById("filter-form");
  const bar = document.getElementById("sp-chips");
  if (!form || !bar) return;

  const controls = bar.querySelectorAll("input, select, textarea");
  controls.forEach((el) => el.setAttribute("form", "filter-form"));
  const chips = Array.from(bar.querySelectorAll(".sp-chip"));

  function submit() {
    if (form.requestSubmit) form.requestSubmit();
    else form.submit();
  }

  function summarize(chip) {
    const parts = [];
    chip.querySelectorAll("select").forEach((s) => {
      if (s.value) parts.push(s.options[s.selectedIndex].text);
    });
    const zip = chip.querySelector('input[name="zip"]');
    if (zip && zip.value) parts.push(zip.value);
    const ticks = chip.querySelectorAll('input[type="checkbox"]:checked').length;
    if (ticks) parts.push(`${ticks} selected`);
    if (chip.querySelector('input[name="source"][value="google"]:checked')) parts.unshift("Live Google");
    const label = chip.dataset.label || "";
    chip.querySelector("summary").textContent = parts.length ? `${label} · ${parts.join(", ")}` : label;
    chip.classList.toggle("is-active", parts.length > 0 || label === "Near me");
  }

  function syncTypes() {
    const checked = Array.from(form.querySelectorAll('input[name="types"]:checked')).map((i) => i.value);
    bar.querySelectorAll("[data-for-type]").forEach((chip) => {
      const show = !checked.length || checked.includes(chip.dataset.forType);
      chip.hidden = !show;
      chip.querySelectorAll("input, select").forEach((el) => { el.disabled = !show; });
    });
    const google = bar.querySelector('input[name="source"][value="google"]');
    const googleFilters = document.getElementById("google-filters");
    if (google && googleFilters) {
      googleFilters.hidden = !google.checked;
      googleFilters.querySelectorAll("input, select").forEach((el) => { el.disabled = !google.checked; });
    }
  }

  chips.forEach((chip) => {
    summarize(chip);
    chip.addEventListener("toggle", () => {
      if (chip.open) chips.forEach((other) => { if (other !== chip) other.open = false; });
    });
  });
  syncTypes();

  // Selects and radios apply at once; checkboxes and ZIP wait for Enter or close.
  bar.querySelectorAll("select, input[type=radio]").forEach((el) => el.addEventListener("change", submit));
  bar.querySelectorAll('input[type="checkbox"], input[name="zip"]').forEach((el) => {
    el.addEventListener("change", () => { chips.forEach(summarize); syncTypes(); });
  });
  bar.querySelectorAll('input[name="zip"]').forEach((el) => {
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
  });
  form.querySelectorAll('input[name="types"]').forEach((el) => el.addEventListener("change", submit));

  document.addEventListener("click", (e) => {
    if (!e.target.closest(".sp-chip")) chips.forEach((c) => { c.open = false; });
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    const open = chips.find((c) => c.open);
    if (open) { open.open = false; open.querySelector("summary").focus(); }
  });
})();

// 47f: the location button in the search bar uses the same handler as
// "Use my location" in the Location chip.
(() => {
  const btn = document.getElementById("sp-locate");
  const use = document.getElementById("use-location");
  const status = document.getElementById("loc-status");
  if (!btn || !use) return;
  btn.addEventListener("click", () => {
    btn.classList.add("is-busy");
    use.click();
    if (status) {
      const stop = new MutationObserver(() => {
        if (/Could not|does not support/.test(status.textContent)) {
          btn.classList.remove("is-busy");
          btn.title = status.textContent;
          stop.disconnect();
        }
      });
      stop.observe(status, { childList: true, characterData: true, subtree: true });
    }
  });
})();

// 47g: no type chosen means "show everything", so show all three as on.
// Keep at least one on: turning off the last one would show nothing.
(() => {
  const boxes = Array.from(document.querySelectorAll('#filter-form input[name="types"]'));
  if (!boxes.length) return;
  if (!boxes.some((b) => b.checked)) boxes.forEach((b) => { b.checked = true; });
  boxes.forEach((b) => {
    b.addEventListener("change", (e) => {
      if (!boxes.some((x) => x.checked)) {
        b.checked = true;
        e.stopImmediatePropagation();
      }
    }, true);
  });
})();

// 48: "Back to results" closes the details and shows the list again.
(() => {
  const back = document.getElementById("sp-back");
  const detail = document.getElementById("sp-detail");
  if (!back || !detail) return;
  back.addEventListener("click", () => {
    window.__spClearSel?.();
    document.querySelector(".combined-map-layout")?.classList.remove("is-panel-open");
    document.querySelectorAll(".result.active").forEach((r) => r.classList.remove("active"));
  });
  // Start each place at the top of its details.
  const layout = document.querySelector(".combined-map-layout");
  if (layout) {
    new MutationObserver(() => {
      if (layout.classList.contains("is-panel-open")) detail.scrollTop = 0;
    }).observe(layout, { attributes: true, attributeFilter: ["class"] });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && layout?.classList.contains("is-panel-open") && !document.querySelector(".sp-chip[open]")) back.click();
  });
})();

// 57: chips v2: names on the chips, tap again to unselect, clear with x.
(() => {
  const form = document.getElementById("filter-form");
  const bar = document.getElementById("sp-chips");
  if (!form || !bar) return;
  const chips = Array.from(bar.querySelectorAll(".sp-chip2"));
  const go = () => (form.requestSubmit ? form.requestSubmit() : form.submit());
  const text = (el) => el.closest("label")?.querySelector("span")?.textContent.trim() || "";

  function label(chip) {
    const on = (sel) => Array.from(chip.querySelectorAll(sel + ":checked")).filter((i) => i.value);
    const kind = chip.dataset.kind;
    if (kind === "cuisine") { const c = on('input[type="checkbox"]').map(text); return c.length > 2 ? `${c[0]}, ${c[1]} +${c.length - 2}` : c.join(", "); }
    if (kind === "dietall") return [...on('input[type="radio"]'), ...on('input[type="checkbox"]')].map(text).join(", ");
    if (kind === "allergies") return on('input[type="checkbox"]').map(text).join(", ");
    if (kind === "day") return on('input[type="radio"]').map(text).join(" · ");
    if (kind === "filters") {
      const parts = [];
      const areas = on('input[name="area"]').map(text);
      if (areas.length) parts.push(areas.join(", "));
      const price = on('input[name="price"]').map((i) => i.value);
      if (price.length) parts.push(price.join(" "));
      const r = on('input[name="min_rating"]')[0];
      if (r) parts.push(text(r) + " ★");
      const h = on('input[name="min_health"]')[0];
      if (h) parts.push("Health score " + text(h));
      return parts.join(" · ");
    }
    const r = on('input[type="radio"]')[0];
    return r ? text(r) : "";
  }

  function paint(chip) {
    const value = label(chip);
    const s = chip.querySelector("summary");
    s.textContent = value || chip.dataset.label;
    chip.classList.toggle("is-on", !!value);
    chip.classList.remove("is-active");
    if (value) {
      const x = document.createElement("span");
      x.className = "sp-x";
      x.setAttribute("role", "button");
      x.setAttribute("aria-label", "Clear " + chip.dataset.label);
      x.textContent = "×";
      x.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        chip.querySelectorAll("input:checked").forEach((i) => { if (i.value) i.checked = false; });
        go();
      });
      s.appendChild(x);
    }
  }

  chips.forEach((chip) => {
    paint(chip);
    chip.querySelectorAll('input[type="radio"]').forEach((i) => {
      i.addEventListener("pointerdown", () => { i.dataset.was = i.checked ? "1" : ""; });
      i.closest("label")?.addEventListener("pointerdown", () => { i.dataset.was = i.checked ? "1" : ""; });
      i.closest("label")?.addEventListener("click", (e) => {
        if (i.dataset.was === "1") { e.preventDefault(); i.checked = false; i.dataset.was = ""; if (chip.dataset.defer) { paint(chip); form.dispatchEvent(new Event("sp-dirty")); } else go(); }
      });
    });
    chip.querySelectorAll('input[type="checkbox"]').forEach((i) => i.addEventListener("change", go));
    chip.querySelectorAll("input").forEach((i) => i.addEventListener("change", () => paint(chip)));
    const find = chip.querySelector(".sp-find");
    if (find) {
      find.removeAttribute("form");
      find.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
      find.addEventListener("input", () => {
        const q = find.value.trim().toLowerCase();
        chip.querySelectorAll(".sp-opt").forEach((o) => { o.hidden = q && !o.textContent.toLowerCase().includes(q); });
      });
      chip.addEventListener("toggle", () => { if (chip.open) setTimeout(() => find.focus(), 0); });
    }
  });
})();

// 61: a click on a result's name opens the side panel (like a map dot),
// not the restaurant page. Cmd/Ctrl-click still opens the page in a new tab.
document.addEventListener("click", (e) => {
  const link = e.target.closest(".sp-row h2 a");
  if (!link || e.metaKey || e.ctrlKey || e.shiftKey || e.button !== 0) return;
  e.preventDefault();
  e.stopPropagation();
  link.closest("h2").click();
}, true);

// 71: panel tabs switch content (Overview / Reviews). Review button opens Reviews.
(() => {
  const panelOf = (el) => el.closest(".community-panel");
  const setTab = (panel, tab) => {
    panel.dataset.tab = tab;
    panel.querySelectorAll(".pp-tabs a").forEach((a) => a.classList.toggle("is-on", a.dataset.tab === tab));
    panel.closest(".sp-detail")?.scrollTo({ top: 0 });
  };
  document.addEventListener("click", (e) => {
    const tab = e.target.closest(".pp-tabs a[data-tab]");
    if (tab) {
      e.preventDefault();
      e.stopPropagation();
      setTab(panelOf(tab), tab.dataset.tab);
      return;
    }
    const write = e.target.closest(".pp-write");
    if (write) setTab(panelOf(write), "reviews");
  }, true);
  const panel = document.getElementById("community-panel");
  if (panel) {
    let last = "";
    new MutationObserver(() => {
      const name = panel.querySelector(".pp-name")?.textContent || "";
      if (name !== last) { last = name; panel.dataset.tab = "overview"; }
    }).observe(panel, { childList: true });
  }
})();

// 89: favorite hearts (list rows and panel): same Like as Explore more.
(() => {
  const cookie = (n) => (document.cookie.match("(^|; )" + n + "=([^;]*)") || [])[2] || "";
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".sp-fav, .pp-fav");
    if (!btn) return;
    e.preventDefault();
    e.stopPropagation();
    const id = btn.dataset.place;
    const body = new FormData();
    body.append("value", "like");
    fetch(`/restaurant/${encodeURIComponent(id)}/feedback/`, {
      method: "POST", body, credentials: "same-origin",
      headers: { "X-CSRFToken": cookie("csrftoken"), Accept: "application/json" },
    })
      .then((r) => {
        const json = (r.headers.get("content-type") || "").includes("application/json");
        if (!r.ok || !json) { window.location.href = "/login/?next=" + encodeURIComponent(location.pathname + location.search); return null; }
        return r.json();
      })
      .then((data) => {
        if (!data) return;
        document.querySelectorAll(`.sp-fav[data-place="${CSS.escape(id)}"], .pp-fav[data-place="${CSS.escape(id)}"]`).forEach((b) => {
          b.classList.toggle("is-on", !!data.liked);
          b.setAttribute("aria-pressed", data.liked ? "true" : "false");
        });
      })
      .catch(() => {});
  }, true);
})();

// 101: Cuisine: tick several, search when the chip closes.
(() => {
  const chip = document.querySelector('.sp-chip2[data-kind="cuisine"]');
  const form = document.getElementById("filter-form");
  if (!chip || !form) return;
  let dirty = false;
  const label = () => {
    const names = Array.from(chip.querySelectorAll('input[type="checkbox"]:checked')).map((i) => i.closest("label")?.querySelector("span")?.textContent.trim() || "");
    const s = chip.querySelector("summary");
    const x = s.querySelector(".sp-x");
    s.firstChild && s.firstChild.nodeType === 3 ? (s.firstChild.textContent = names.length ? (names.length > 2 ? `${names[0]}, ${names[1]} +${names.length - 2}` : names.join(", ")) : chip.dataset.label) : null;
    chip.classList.toggle("is-on", names.length > 0);
    if (x && !names.length) x.remove();
  };
  chip.addEventListener("change", (e) => {
    if (!e.target.matches('input[name="cuisine"]')) return;
    e.stopPropagation();
    dirty = true;
    label();
  }, true);
  chip.addEventListener("toggle", () => {
    if (!chip.open && dirty) { dirty = false; form.requestSubmit ? form.requestSubmit() : form.submit(); }
  });
})();

// 108: keep filter pop-ups inside the map.
(() => {
  const bar = document.getElementById("sp-chips");
  if (!bar) return;
  const fit = (chip) => {
    const pop = chip.querySelector(".sp-pop");
    const area = chip.closest(".sp-map") || document.body;
    if (!pop) return;
    pop.style.left = ""; pop.style.right = ""; pop.style.transform = "";
    requestAnimationFrame(() => {
      const p = pop.getBoundingClientRect(), a = area.getBoundingClientRect(), c = chip.getBoundingClientRect();
      const pad = 12;
      if (p.right > a.right - pad) {
        const shift = p.right - (a.right - pad);
        const room = p.left - (a.left + pad);
        pop.style.transform = `translateX(${-Math.min(shift, Math.max(0, room))}px)`;
      }
    });
  };
  bar.querySelectorAll(".sp-chip").forEach((chip) => chip.addEventListener("toggle", () => { if (chip.open) fit(chip); }));
  window.addEventListener("resize", () => bar.querySelectorAll(".sp-chip[open]").forEach(fit));
})();

// 168: keep these pop-ups open while setting several things; search on close.
(() => {
  const form = document.getElementById("filter-form");
  const bar = document.getElementById("sp-chips");
  if (!form || !bar) return;
  const keep = bar.querySelectorAll('.sp-chip2[data-kind="filters"], .sp-chip2[data-kind="dietall"], .sp-chip2[data-kind="day"]');
  keep.forEach((c) => { c.dataset.defer = "1"; });
  let dirty = false, allow = false;
  form.addEventListener("sp-dirty", () => { dirty = true; });
  form.addEventListener("submit", (e) => {
    if (allow) { allow = false; return; }
    if (bar.querySelector('.sp-chip2[data-defer][open]')) { e.preventDefault(); dirty = true; }
  });
  keep.forEach((c) => c.addEventListener("toggle", () => {
    if (!c.open && dirty) { dirty = false; allow = true; form.requestSubmit ? form.requestSubmit() : form.submit(); }
  }));
})();

// 168: score pages remember this search, so "Back to search" keeps the filters.
document.addEventListener("pointerdown", (e) => {
  const a = e.target.closest('a[href^="/restaurant/"]');
  if (!a || a.href.includes("back=")) return;
  const u = new URL(a.href, location.origin);
  u.searchParams.set("back", location.pathname + location.search);
  a.href = u.pathname + u.search;
}, true);
