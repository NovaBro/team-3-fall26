(() => {
  const CATEGORY_LABELS = {
    farmers_market: "Farmers market",
    grocery: "Grocery (Shop Healthy)",
    restaurant_dohmh: "DOHMH restaurant",
    restaurant_google: "Google restaurant",
  };

  const PIN_COLORS = {
    farmers_market: { background: "#1f5fbf", borderColor: "#0f3a75", glyphColor: "#ffffff" },
    grocery: { background: "#2e8b57", borderColor: "#1a5c38", glyphColor: "#ffffff" },
    restaurant_dohmh: { background: "#e67e22", borderColor: "#a35410", glyphColor: "#ffffff" },
    restaurant_google: { background: "#9b59b6", borderColor: "#6c3483", glyphColor: "#ffffff" },
  };

  const state = {
    map: null,
    info: null,
    markersByCategory: {
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
    AdvancedMarkerElement: null,
    PinElement: null,
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

  function visiblePointsCount() {
    return Object.entries(state.markersByCategory).reduce((total, [category, markers]) => {
      return total + (state.visibility[category] ? markers.length : 0);
    }, 0);
  }

  function fitVisible() {
    if (!state.map) return;
    const bounds = new google.maps.LatLngBounds();
    let count = 0;
    Object.entries(state.markersByCategory).forEach(([category, markers]) => {
      if (!state.visibility[category]) return;
      markers.forEach((marker) => {
        bounds.extend(marker.position);
        count += 1;
      });
    });
    if (count === 0) {
      state.map.setCenter({ lat: 40.7295, lng: -73.9965 });
      state.map.setZoom(11);
      return;
    }
    if (count === 1) {
      state.map.setCenter(bounds.getCenter());
      state.map.setZoom(14);
      return;
    }
    state.map.fitBounds(bounds, 48);
  }

  function popupContent(point) {
    const root = document.createElement("div");
    root.className = "combined-map-popup";

    const title = document.createElement("strong");
    title.textContent = point.name || "Untitled";
    root.appendChild(title);

    const category = document.createElement("div");
    category.className = "muted";
    category.textContent = CATEGORY_LABELS[point.category] || point.category;
    root.appendChild(category);

    if (point.address) {
      const address = document.createElement("div");
      address.textContent = point.address;
      root.appendChild(address);
    }

    if (point.url) {
      const link = document.createElement("a");
      link.href = point.url;
      link.textContent =
        point.category === "restaurant_google" ? "View on Google Maps" : "View details";
      if (point.category === "restaurant_google") {
        link.rel = "noopener nofollow";
        link.target = "_blank";
      }
      root.appendChild(link);
    }

    return root;
  }

  function clearCategory(category) {
    state.markersByCategory[category].forEach((marker) => {
      marker.map = null;
    });
    state.markersByCategory[category] = [];
  }

  function addPoints(points) {
    points.forEach((point) => {
      if (point.lat == null || point.lng == null) return;
      const colors = PIN_COLORS[point.category] || PIN_COLORS.restaurant_dohmh;
      const pin = new state.PinElement(colors);
      const marker = new state.AdvancedMarkerElement({
        map: state.visibility[point.category] ? state.map : null,
        position: { lat: point.lat, lng: point.lng },
        title: point.name || "",
        content: pin.element,
      });
      marker.addListener("click", () => {
        state.info.setContent(popupContent(point));
        state.info.open({ map: state.map, anchor: marker });
      });
      state.markersByCategory[point.category].push(marker);
    });
  }

  function setLayerVisible(category, visible) {
    state.visibility[category] = visible;
    state.markersByCategory[category].forEach((marker) => {
      marker.map = visible ? state.map : null;
    });
    const googleControls = document.getElementById("google-load-controls");
    if (category === "restaurant_google" && googleControls) {
      googleControls.hidden = !visible;
    }
    fitVisible();
    setStatus(`${visiblePointsCount()} visible points`);
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
      clearCategory("restaurant_google");
      addPoints(payload.points || []);
      state.visibility.restaurant_google = true;
      const checkbox = document.querySelector('input[data-layer="restaurant_google"]');
      if (checkbox) checkbox.checked = true;
      const googleControls = document.getElementById("google-load-controls");
      if (googleControls) googleControls.hidden = false;
      fitVisible();
      setStatus(
        `Loaded ${(payload.points || []).length} Google restaurants · ${visiblePointsCount()} visible points`
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
      setLayerVisible(category, input.checked);
      input.addEventListener("change", () => {
        setLayerVisible(category, input.checked);
      });
    });

    const loadBtn = document.getElementById("load-google-btn");
    if (loadBtn) loadBtn.addEventListener("click", loadGoogleRestaurants);
  }

  window.initCombinedMap = async function initCombinedMap() {
    const mapElement = document.getElementById("combined-map");
    const points = readJson("combined-map-data") || [];
    const config = readJson("combined-map-config");
    if (!mapElement || !config?.hasMapsKey) {
      setStatus("Set GOOGLE_MAPS_JS_KEY in .env to enable the map.");
      return;
    }

    const { Map, InfoWindow } = await google.maps.importLibrary("maps");
    const { AdvancedMarkerElement, PinElement } = await google.maps.importLibrary("marker");
    state.AdvancedMarkerElement = AdvancedMarkerElement;
    state.PinElement = PinElement;
    state.info = new InfoWindow();
    state.map = new Map(mapElement, {
      center: { lat: 40.7295, lng: -73.9965 },
      zoom: 11,
      mapId: "DEMO_MAP_ID",
    });

    addPoints(points);
    bindControls();
    fitVisible();
    setStatus(`${visiblePointsCount()} visible points`);
  };
})();
