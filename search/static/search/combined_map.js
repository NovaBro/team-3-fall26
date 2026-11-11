(() => {
  const CATEGORIES = ["farmers_market", "grocery", "restaurant_dohmh", "restaurant_google"];

  const CATEGORY_LABELS = {
    farmers_market: "Farmers market",
    grocery: "Grocery (Shop Healthy)",
    restaurant_dohmh: "Restaurant (NYC inspection records)",
    restaurant_google: "Restaurant (Google Places)",
  };

  const PIN_COLORS = {
    farmers_market: "#1f5fbf",
    grocery: "#2e8b57",
    restaurant_dohmh: "#e67e22",
    restaurant_google: "#9b59b6",
  };

  const state = {
    map: null,
    points: {
      farmers_market: [],
      grocery: [],
      restaurant_dohmh: [],
      restaurant_google: [],
    },
    visibility: {
      farmers_market: true,
      grocery: true,
      restaurant_dohmh: true,
      restaurant_google: true,
    },
    openKey: "",
  };

  function readJson(id) {
    const el = document.getElementById(id);
    if (!el) return null;
    return JSON.parse(el.textContent);
  }

  function setStatus(text) {
    const status = document.getElementById("map-status");
    if (status) status.textContent = text;
  }

  function located(points) {
    return points.filter((point) => point.lat != null && point.lng != null);
  }

  function visiblePoints() {
    return CATEGORIES.flatMap((category) => (
      state.visibility[category] ? located(state.points[category]) : []
    ));
  }

  function featureCollection(category) {
    return {
      type: "FeatureCollection",
      features: located(state.points[category]).map((point) => ({
        type: "Feature",
        geometry: { type: "Point", coordinates: [point.lng, point.lat] },
        properties: {
          name: point.name || "",
          address: point.address || "",
          category: point.category || category,
          kind: point.kind || point.category || category,
          key: point.key || "",
          url: point.url || "",
        },
      })),
    };
  }

  function visibleLayerIds() {
    if (!state.map) return [];
    return CATEGORIES.filter((category) => state.visibility[category] && state.map.getLayer(category));
  }

  function syncSource(category) {
    const source = state.map?.getSource(category);
    if (source) source.setData(featureCollection(category));
  }

  function csrfToken() {
    return document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  }

  function panelElement() {
    return document.getElementById("community-panel");
  }

  function clearNode(node) {
    while (node.firstChild) node.removeChild(node.firstChild);
  }

  function addText(parent, tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    el.textContent = text;
    parent.appendChild(el);
    return el;
  }

  function communityUrl(point, action) {
    const kind = encodeURIComponent(point.kind || point.category);
    const key = encodeURIComponent(point.key || "");
    const suffix = action ? `${action}/` : "";
    return `/community/${kind}/${key}/${suffix}`;
  }

  function renderPanel(point, payload) {
    const panel = panelElement();
    if (!panel) return;
    const token = csrfToken();
    clearNode(panel);
    addText(panel, "h2", "", payload.name || point.name || "Reviews");
    const category = CATEGORY_LABELS[point.category] || point.category;
    if (category) addText(panel, "p", "muted", category);
    if (payload.address) addText(panel, "p", "", payload.address);
    if (point.url) {
      const link = document.createElement("a");
      link.href = point.url;
      link.textContent = point.category === "restaurant_google" ? "View on Google Maps" : "View details";
      if (point.category === "restaurant_google") {
        link.rel = "noopener nofollow";
        link.target = "_blank";
      }
      panel.appendChild(link);
    }

    if (payload.google) {
      const google = payload.google;
      const heading = google.rating
        ? `Google ${Number(google.rating).toFixed(1)}`
        : "Google reviews";
      addText(panel, "h3", "", heading);
      (google.reviews || []).forEach((review) => {
        const block = document.createElement("div");
        block.className = "community-entry";
        addText(block, "strong", "", review.author_name || "Google reviewer");
        if (review.rating) addText(block, "span", "muted", ` ${review.rating}/5`);
        if (review.relative_time) addText(block, "span", "muted", ` · ${review.relative_time}`);
        if (review.text) addText(block, "p", "", review.text);
        panel.appendChild(block);
      });
      if (!(google.reviews || []).length) {
        addText(panel, "p", "muted", "No Google review text stored.");
      }
    }

    const average = payload.average_rating == null
      ? "Be the first to review!"
      : `Visitors ${payload.average_rating} (${payload.rating_count})`;
    addText(panel, "h3", "", average);

    if (payload.authenticated) {
      panel.appendChild(createVisitorForm(point, payload));
    } else {
      const login = document.createElement("p");
      const link = document.createElement("a");
      const config = readJson("combined-map-config");
      link.href = payload.login_url || config?.loginUrl || "/login/";
      link.textContent = "Log in";
      login.appendChild(link);
      login.appendChild(document.createTextNode(" to add a rating, comment, or photo."));
      panel.appendChild(login);
    }

    addText(panel, "h3", "", "Comments");
    if (!(payload.comments || []).length) addText(panel, "p", "muted", "No comments yet.");
    (payload.comments || []).forEach((comment) => {
      const block = document.createElement("div");
      block.className = "community-entry";
      addText(block, "strong", "", comment.author || "User");
      addText(block, "p", "", comment.text || "");
      panel.appendChild(block);
    });

    addText(panel, "h3", "", "Photos");
    if (!(payload.photos || []).length) addText(panel, "p", "muted", "No photos yet.");
    (payload.photos || []).forEach((photo) => {
      const figure = document.createElement("figure");
      figure.className = "community-photo";
      const image = document.createElement("img");
      image.src = photo.url;
      image.alt = photo.author ? `Photo from ${photo.author}` : "Visitor photo";
      figure.appendChild(image);
      if (photo.author) addText(figure, "figcaption", "muted", photo.author);
      panel.appendChild(figure);
    });

    const hidden = document.createElement("input");
    hidden.type = "hidden";
    hidden.name = "csrfmiddlewaretoken";
    hidden.value = token;
    panel.appendChild(hidden);
  }

  function showCommunityMessage(text) {
    const panel = panelElement();
    if (!panel) return;
    clearNode(panel);
    addText(panel, "p", "muted", text);
  }

  async function loadCommunityPanel(point) {
    const panel = panelElement();
    if (!point.key) {
      showCommunityMessage("This point has no saved identity, so reviews cannot be loaded.");
      return;
    }
    if (panel) {
      clearNode(panel);
      addText(panel, "h2", "", point.name || "Reviews");
      addText(panel, "p", "muted", "Loading reviews…");
      if (!panel.classList.contains("in-popup")) panel.scrollIntoView({ block: "nearest" });
    }
    const params = new URLSearchParams({
      name: point.name || "",
      address: point.address || "",
    });
    const requestKey = point.key;
    try {
      const response = await fetch(`${communityUrl(point)}?${params.toString()}`, {
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (state.openKey !== requestKey) return;
      if (!response.ok) {
        showCommunityMessage(payload.error || "Could not load reviews.");
        return;
      }
      renderPanel(point, payload);
    } catch (_error) {
      if (state.openKey === requestKey) showCommunityMessage("Could not load reviews.");
    }
  }

  function createVisitorForm(point, payload) {
    const form = document.createElement("form");
    form.className = "community-form community-form--visitor";

    const formId = `community-${(point.key || "pin").replace(/[^a-zA-Z0-9_-]/g, "-")}`;
    const stars = document.createElement("div");
    stars.className = "review-stars";
    stars.setAttribute("role", "radiogroup");
    stars.setAttribute("aria-label", "Your rating");
    for (let value = 5; value >= 1; value -= 1) {
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "rating";
      input.id = `${formId}-star-${value}`;
      input.value = String(value);
      input.required = true;
      if (payload.user_rating === value) input.checked = true;
      const label = document.createElement("label");
      label.htmlFor = input.id;
      label.textContent = `${value} ${value === 1 ? "star" : "stars"}`;
      stars.append(input, label);
    }
    form.appendChild(stars);

    const textarea = document.createElement("textarea");
    textarea.name = "text";
    textarea.rows = 3;
    textarea.maxLength = 2000;
    textarea.placeholder = "Leave a review (optional)";
    textarea.setAttribute("aria-label", "Comment");
    form.appendChild(textarea);

    const file = document.createElement("input");
    file.type = "file";
    file.name = "photo";
    file.accept = "image/*";
    file.setAttribute("aria-label", "Photo");
    form.appendChild(file);

    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn";
    submit.textContent = "Submit";
    submit.disabled = !payload.user_rating;
    form.appendChild(submit);

    stars.addEventListener("change", () => {
      submit.disabled = !form.querySelector('input[name="rating"]:checked');
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitVisitorContribution(point, form);
    });
    return form;
  }

  async function postCommunity(point, action, formData, options = {}) {
    formData.set("name", point.name || "");
    formData.set("address", point.address || "");
    const panel = panelElement();
    try {
      const response = await fetch(communityUrl(point, action), {
        method: "POST",
        body: formData,
        headers: {
          Accept: "application/json",
          "X-CSRFToken": csrfToken(),
        },
        redirect: "manual",
      });
      if (response.type === "opaqueredirect" || response.status === 302 || response.status === 0) {
        showCommunityMessage("Log in to post.");
        return null;
      }
      const payload = await response.json();
      if (!response.ok) {
        if (panel) addText(panel, "p", "community-error", payload.error || "Could not save.");
        return null;
      }
      if (!options.deferRender) renderPanel(point, payload);
      return payload;
    } catch (_error) {
      if (panel) addText(panel, "p", "community-error", "Could not save.");
      return null;
    }
  }

  async function submitVisitorContribution(point, form) {
    const ratingInput = form.querySelector('input[name="rating"]:checked');
    if (!ratingInput) return;

    const panel = panelElement();
    const ratingData = new FormData();
    ratingData.set("rating", ratingInput.value);
    let payload = await postCommunity(point, "rating", ratingData, { deferRender: true });
    if (!payload) return;

    const text = (form.querySelector('textarea[name="text"]')?.value || "").trim();
    if (text) {
      const commentData = new FormData();
      commentData.set("text", text);
      const next = await postCommunity(point, "comment", commentData, { deferRender: true });
      if (!next) return;
      payload = next;
    }

    const photoInput = form.querySelector('input[name="photo"]');
    const photo = photoInput?.files?.[0];
    if (photo) {
      const photoData = new FormData();
      photoData.set("photo", photo);
      const next = await postCommunity(point, "photo", photoData, { deferRender: true });
      if (!next) return;
      payload = next;
    }

    renderPanel(point, payload);
    if (panel) panel.scrollIntoView({ block: "nearest" });
  }

  function pointFromFeature(feature) {
    const properties = feature.properties || {};
    return {
      name: properties.name || "",
      address: properties.address || "",
      category: properties.category || "",
      kind: properties.kind || properties.category || "",
      key: properties.key || "",
      url: properties.url || "",
      lng: feature.geometry && feature.geometry.coordinates ? feature.geometry.coordinates[0] : null,
      lat: feature.geometry && feature.geometry.coordinates ? feature.geometry.coordinates[1] : null,
    };
  }

  function cardFor(key) {
    return Array.from(document.querySelectorAll(".result[data-key]")).find(
      (card) => card.dataset.key === key
    );
  }

  function highlightCard(key, scroll) {
    document.querySelectorAll(".result[data-key]").forEach((card) => {
      card.classList.toggle("active", card.dataset.key === key);
    });
    const card = cardFor(key);
    if (card && scroll) card.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  function showCommunityPanel() {
    const layout = document.querySelector(".combined-map-layout");
    if (!layout || layout.classList.contains("is-panel-open")) {
      if (state.map) state.map.resize();
      return;
    }
    layout.classList.add("is-panel-open");
    if (state.map) {
      // Let the grid reflow before MapLibre measures the new width.
      requestAnimationFrame(() => state.map.resize());
    }
  }

  function showPointPopup(point) {
    const panel = panelElement();
    const gl = window.maplibregl;
    if (!panel || !gl || !state.map || point.lat == null || point.lng == null) {
      showCommunityPanel();
      return;
    }
    if (state.popup) state.popup.remove();
    if (!state.panelHome) state.panelHome = panel.parentNode;
    panel.classList.add("in-popup");
    const popup = new gl.Popup({ maxWidth: "none", closeOnClick: false, offset: 16, anchor: "bottom" })
      .setLngLat([point.lng, point.lat])
      .setDOMContent(panel)
      .addTo(state.map);
    popup.on("close", () => {
      if (state.popup === popup) state.popup = null;
      panel.classList.remove("in-popup");
      if (state.panelHome) state.panelHome.appendChild(panel);
    });
    state.popup = popup;
    state.map.easeTo({ center: [point.lng, point.lat], offset: [0, 170] });
  }

  function openPoint(point) {
    state.openKey = point.key || "";
    highlightCard(state.openKey, true);
    showPointPopup(point);
    loadCommunityPanel(point);
  }

  function pointByKey(key) {
    return CATEGORIES.flatMap((category) => state.points[category]).find(
      (point) => point.key === key
    );
  }

  function bindSplitter() {
    const layout = document.querySelector(".combined-map-layout");
    const splitter = document.getElementById("combined-map-splitter");
    if (!layout || !splitter) return;

    // Change this number to set the default reviews-panel width when it opens.
    // Width stays while you click other pins; a full page reload resets to this.
    const DEFAULT_PANEL_WIDTH = 300;
    const MIN_PANEL = 240;
    const MAX_PANEL = 800;

    function clampWidth(width) {
      const layoutWidth = layout.getBoundingClientRect().width;
      const maxForLayout = Math.max(MIN_PANEL, layoutWidth - 280);
      return Math.round(Math.min(MAX_PANEL, maxForLayout, Math.max(MIN_PANEL, width)));
    }

    function applyWidth(width) {
      const next = clampWidth(width);
      layout.style.setProperty("--community-panel-width", `${next}px`);
      splitter.setAttribute("aria-valuenow", String(next));
      if (state.map) state.map.resize();
      return next;
    }

    // Drop any previously saved width so reloads always start at the default.
    localStorage.removeItem("combined-map-panel-width");
    applyWidth(DEFAULT_PANEL_WIDTH);

    let dragging = false;

    function onPointerMove(event) {
      if (!dragging) return;
      const bounds = layout.getBoundingClientRect();
      const width = bounds.right - event.clientX - 8;
      applyWidth(width);
    }

    function stopDragging() {
      if (!dragging) return;
      dragging = false;
      layout.classList.remove("is-resizing");
      window.removeEventListener("pointermove", onPointerMove);
      window.removeEventListener("pointerup", stopDragging);
    }

    splitter.addEventListener("pointerdown", (event) => {
      if (window.matchMedia("(max-width: 900px)").matches) return;
      event.preventDefault();
      dragging = true;
      layout.classList.add("is-resizing");
      splitter.setPointerCapture?.(event.pointerId);
      window.addEventListener("pointermove", onPointerMove);
      window.addEventListener("pointerup", stopDragging);
    });

    splitter.addEventListener("keydown", (event) => {
      const current = Number.parseInt(
        getComputedStyle(layout).getPropertyValue("--community-panel-width"),
        10,
      ) || DEFAULT_PANEL_WIDTH;
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        applyWidth(current + 16);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        applyWidth(current - 16);
      }
    });
  }

  function bindCards() {
    document.querySelectorAll(".result[data-key]").forEach((card) => {
      card.addEventListener("click", (event) => {
        if (event.target.closest("a")) return;
        const point = pointByKey(card.dataset.key);
        if (!point) return;
        if (state.map && point.lat != null && point.lng != null) {
          state.map.flyTo({ center: [point.lng, point.lat], zoom: Math.max(state.map.getZoom(), 15) });
        }
        state.openKey = point.key || "";
        highlightCard(state.openKey, false);
        showPointPopup(point);
        loadCommunityPanel(point);
      });
    });
  }

  function addUserMarker() {
    const userPos = readJson("user-location");
    if (!userPos || !state.map) return;
    const dot = document.createElement("div");
    dot.className = "user-location-dot";
    dot.title = "You are here";
    new maplibregl.Marker({ element: dot }).setLngLat([userPos.lng, userPos.lat]).addTo(state.map);
  }

  function initMap() {
    const mapElement = document.getElementById("combined-map");
    const points = readJson("combined-map-data") || [];
    if (!mapElement) return;
    if (!window.maplibregl) {
      setStatus("The map library could not be loaded. Check your internet connection and refresh.");
      return;
    }

    points.forEach((point) => {
      const category = point.category;
      if (state.points[category]) state.points[category].push(point);
    });
    readJson("result-points")?.forEach((point) => {
      if (!pointByKey(point.key) && state.points[point.category]) {
        state.points[point.category].push(point);
      }
    });
    bindCards();
    bindSplitter();

    const opening = visiblePoints();
    const userPos = readJson("user-location");
    if (userPos) opening.push(userPos);
    const mapOptions = {
      container: mapElement,
      style: "https://tiles.openfreemap.org/styles/" + ((window.__theme && window.__theme() === "dark") ? "dark" : "positron"),
      maxZoom: 18,
      attributionControl: false,
      customAttribution:
        '&copy; <a href="https://openfreemap.org/">OpenFreeMap</a> contributors &middot; ' +
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    };
    if (opening.length) {
      const bounds = new maplibregl.LngLatBounds();
      opening.forEach((point) => bounds.extend([point.lng, point.lat]));
      mapOptions.bounds = bounds;
      mapOptions.fitBoundsOptions = { padding: 48, maxZoom: 13 };
    } else {
      mapOptions.center = [-73.95, 40.72];
      mapOptions.zoom = 10;
    }

    state.map = new maplibregl.Map(mapOptions);
    state.map.addControl(new maplibregl.NavigationControl(), "top-left");
    state.map.addControl(
      new maplibregl.AttributionControl({ compact: true }),
      "bottom-right",
    );

    state.map.on("error", (event) => {
      if (!state.map.isStyleLoaded() || event.sourceId === "openmaptiles") {
        setStatus("The map could not load. Check your internet connection and refresh.");
      }
    });

    function addPinLayers() {
      if (state.map.getSource(CATEGORIES[0])) return;
      CATEGORIES.forEach((category) => {
        state.map.addSource(category, { type: "geojson", data: featureCollection(category) });
        state.map.addLayer({
          id: category,
          type: "circle",
          source: category,
          layout: { visibility: state.visibility[category] ? "visible" : "none" },
          paint: {
            "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 5, 14, 9],
            "circle-color": PIN_COLORS[category],
            "circle-stroke-color": "#0e1116",
            "circle-stroke-width": 2,
          },
        });
        state.map.on("mouseenter", category, () => {
          state.map.getCanvas().style.cursor = "pointer";
        });
        state.map.on("mouseleave", category, () => {
          state.map.getCanvas().style.cursor = "";
        });
      });

      state.map.on("click", (event) => {
        const layers = visibleLayerIds();
        if (!layers.length) return;
        const feature = state.map.queryRenderedFeatures(event.point, { layers })[0];
        if (!feature) return;
        openPoint(pointFromFeature(feature));
      });

      setStatus(`${visiblePoints().length} places on the map`);
    }

    state.map.on("style.load", () => {
      state.map.resize();
      addPinLayers();
    });
    if (state.map.isStyleLoaded()) addPinLayers();
    addUserMarker();
  }

  // Sidebar: hide filters that don't apply, and "Use my location".
  function bindFilterForm() {
    const form = document.getElementById("filter-form");
    if (!form) return;

    function sync() {
      const types = Array.from(form.querySelectorAll('input[name="types"]'));
      const checked = types.filter((input) => input.checked).map((input) => input.value);
      form.querySelectorAll("[data-for-type]").forEach((section) => {
        const show = !checked.length || checked.includes(section.dataset.forType);
        section.hidden = !show;
        section.disabled = !show;
      });
      const google = form.querySelector('input[name="source"][value="google"]');
      const googleFilters = document.getElementById("google-filters");
      if (googleFilters && google) {
        googleFilters.hidden = !google.checked;
        googleFilters.disabled = !google.checked;
      }
    }
    form.addEventListener("change", sync);
    sync();

    const status = document.getElementById("loc-status");
    document.getElementById("use-location")?.addEventListener("click", () => {
      if (!navigator.geolocation) {
        status.textContent = "Your browser does not support location.";
        return;
      }
      status.textContent = "Getting your location...";
      navigator.geolocation.getCurrentPosition(
        (pos) => {
          form.elements.lat.value = pos.coords.latitude;
          form.elements.lng.value = pos.coords.longitude;
          form.submit();
        },
        () => {
          status.textContent = "Could not get your location. Allow location access in the browser and try again.";
        }
      );
    });
    document.getElementById("clear-location")?.addEventListener("click", () => {
      form.elements.lat.value = "";
      form.elements.lng.value = "";
      form.elements.distance.value = "";
      form.submit();
    });
  }

  bindFilterForm();
  initMap();
})();
