(() => {
  const CATEGORIES = ["farmers_market", "grocery", "restaurant_dohmh", "restaurant_google"];

  const CATEGORY_LABELS = {
    farmers_market: "Farmers market",
    grocery: "Grocery (Shop Healthy)",
    restaurant_dohmh: "DOHMH restaurant",
    restaurant_google: "Google restaurant",
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
      restaurant_google: false,
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

  function fitVisible() {
    if (!state.map) return;
    const points = visiblePoints();
    if (!points.length) {
      state.map.setCenter([-73.95, 40.72]);
      state.map.setZoom(10);
      return;
    }
    const bounds = new maplibregl.LngLatBounds();
    points.forEach((point) => bounds.extend([point.lng, point.lat]));
    state.map.fitBounds(bounds, { padding: 48, maxZoom: points.length === 1 ? 14 : 13 });
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
      ? "No visitor ratings yet."
      : `Visitors ${payload.average_rating} (${payload.rating_count})`;
    addText(panel, "h3", "", average);

    if (payload.authenticated) {
      const ratingForm = document.createElement("form");
      ratingForm.className = "community-form";
      const select = document.createElement("select");
      select.name = "rating";
      select.setAttribute("aria-label", "Your rating");
      const placeholder = document.createElement("option");
      placeholder.value = "";
      placeholder.textContent = "Your rating";
      select.appendChild(placeholder);
      for (let score = 1; score <= 5; score += 1) {
        const option = document.createElement("option");
        option.value = String(score);
        option.textContent = `${score} star${score === 1 ? "" : "s"}`;
        if (payload.user_rating === score) option.selected = true;
        select.appendChild(option);
      }
      const ratingButton = document.createElement("button");
      ratingButton.type = "submit";
      ratingButton.className = "btn";
      ratingButton.textContent = "Save rating";
      ratingForm.appendChild(select);
      ratingForm.appendChild(ratingButton);
      ratingForm.addEventListener("submit", (event) => {
        event.preventDefault();
        postCommunity(point, "rating", new FormData(ratingForm));
      });
      panel.appendChild(ratingForm);

      const commentForm = document.createElement("form");
      commentForm.className = "community-form";
      const textarea = document.createElement("textarea");
      textarea.name = "text";
      textarea.rows = 3;
      textarea.maxLength = 2000;
      textarea.placeholder = "Add a comment";
      textarea.setAttribute("aria-label", "Comment");
      const commentButton = document.createElement("button");
      commentButton.type = "submit";
      commentButton.className = "btn";
      commentButton.textContent = "Post comment";
      commentForm.appendChild(textarea);
      commentForm.appendChild(commentButton);
      commentForm.addEventListener("submit", (event) => {
        event.preventDefault();
        postCommunity(point, "comment", new FormData(commentForm));
      });
      panel.appendChild(commentForm);

      const photoForm = document.createElement("form");
      photoForm.className = "community-form";
      const file = document.createElement("input");
      file.type = "file";
      file.name = "photo";
      file.accept = "image/*";
      file.setAttribute("aria-label", "Photo");
      const photoButton = document.createElement("button");
      photoButton.type = "submit";
      photoButton.className = "btn";
      photoButton.textContent = "Upload photo";
      photoForm.appendChild(file);
      photoForm.appendChild(photoButton);
      photoForm.addEventListener("submit", (event) => {
        event.preventDefault();
        postCommunity(point, "photo", new FormData(photoForm));
      });
      panel.appendChild(photoForm);
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
      panel.scrollIntoView({ block: "nearest" });
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

  async function postCommunity(point, action, formData) {
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
        return;
      }
      const payload = await response.json();
      if (!response.ok) {
        if (panel) addText(panel, "p", "community-error", payload.error || "Could not save.");
        return;
      }
      renderPanel(point, payload);
    } catch (_error) {
      if (panel) addText(panel, "p", "community-error", "Could not save.");
    }
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
    };
  }

  function openPoint(point) {
    state.openKey = point.key || "";
    loadCommunityPanel(point);
  }

  function setLayerVisible(category, visible) {
    state.visibility[category] = visible;
    if (state.map?.getLayer(category)) {
      state.map.setLayoutProperty(category, "visibility", visible ? "visible" : "none");
    }
    const googleControls = document.getElementById("google-load-controls");
    if (category === "restaurant_google" && googleControls) {
      googleControls.hidden = !visible;
    }
    fitVisible();
    setStatus(`${visiblePoints().length} visible points`);
  }

  async function loadGoogleRestaurants() {
    const config = readJson("combined-map-config");
    if (!config?.googleUrl) return;

    const area = document.getElementById("google-area")?.value || "";
    const diet = document.getElementById("google-diet")?.value || "";
    const prices = Array.from(
      document.querySelectorAll('input[name="google-price"]:checked')
    ).map((input) => input.value);

    const params = new URLSearchParams();
    if (area) params.set("area", area);
    if (diet) params.set("diet", diet);
    prices.forEach((price) => params.append("price", price));

    setStatus("Loading Google restaurants…");
    const button = document.getElementById("load-google-btn");
    if (button) button.disabled = true;

    try {
      const response = await fetch(`${config.googleUrl}?${params.toString()}`, {
        headers: { Accept: "application/json" },
      });
      const payload = await response.json();
      if (!response.ok) {
        setStatus(payload.error || "Could not load Google restaurants.");
        return;
      }
      state.points.restaurant_google = payload.points || [];
      syncSource("restaurant_google");
      state.visibility.restaurant_google = true;
      if (state.map?.getLayer("restaurant_google")) {
        state.map.setLayoutProperty("restaurant_google", "visibility", "visible");
      }
      const checkbox = document.querySelector('input[data-layer="restaurant_google"]');
      if (checkbox) checkbox.checked = true;
      const googleControls = document.getElementById("google-load-controls");
      if (googleControls) googleControls.hidden = false;
      fitVisible();
      setStatus(
        `Loaded ${state.points.restaurant_google.length} Google restaurants · ${visiblePoints().length} visible points`
      );
    } catch (_error) {
      setStatus("Could not load Google restaurants. Try again.");
    } finally {
      if (button) button.disabled = false;
    }
  }

  function bindControls() {
    document.querySelectorAll("input[data-layer]").forEach((input) => {
      const category = input.dataset.layer;
      input.addEventListener("change", () => {
        setLayerVisible(category, input.checked);
      });
    });

    const loadBtn = document.getElementById("load-google-btn");
    if (loadBtn) loadBtn.addEventListener("click", loadGoogleRestaurants);
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

    const opening = visiblePoints();
    const mapOptions = {
      container: mapElement,
      style: "https://tiles.openfreemap.org/styles/dark",
      maxZoom: 18,
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

      setStatus(`${visiblePoints().length} visible points`);
    }

    state.map.on("style.load", () => {
      state.map.resize();
      addPinLayers();
    });
    if (state.map.isStyleLoaded()) addPinLayers();
    bindControls();
  }

  initMap();
})();
