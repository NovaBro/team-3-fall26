/**
 * Home minimap: drag/click a pin and POST it to search:save_location.
 * Expects #location-minimap and #location-pin-config (JSON bootstrap).
 */
(function () {
  var mapEl = document.getElementById("location-minimap");
  var configEl = document.getElementById("location-pin-config");
  if (!mapEl || !configEl || typeof maplibregl === "undefined") return;

  var cfg;
  try {
    cfg = JSON.parse(configEl.textContent);
  } catch (err) {
    return;
  }

  var saveUrl = mapEl.getAttribute("data-save-url");
  var csrf = mapEl.getAttribute("data-csrf");
  var statusEl = document.getElementById("location-pin-status");
  var useBtn = document.getElementById("location-use-geo");
  var clearBtn = document.getElementById("location-clear-pin");

  function inNyc(lat, lng) {
    return (
      lat >= cfg.nyc_lat_min &&
      lat <= cfg.nyc_lat_max &&
      lng >= cfg.nyc_lng_min &&
      lng <= cfg.nyc_lng_max
    );
  }

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text || "";
  }

  function postLocation(body) {
    return fetch(saveUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "X-CSRFToken": csrf,
      },
      body: body,
      credentials: "same-origin",
    }).then(function (res) {
      return res.json().then(function (data) {
        if (!res.ok || !data.ok) {
          throw new Error((data && data.error) || "Could not save location");
        }
        return data;
      });
    });
  }

  var map = new maplibregl.Map({
    container: mapEl,
    style: "https://tiles.openfreemap.org/styles/liberty",
    center: [cfg.lng, cfg.lat],
    zoom: cfg.zoom,
    attributionControl: false,
  });
  map.addControl(new maplibregl.AttributionControl({ compact: true }));
  map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

  var marker = null;

  function placeMarker(lat, lng, save) {
    if (!inNyc(lat, lng)) {
      setStatus("Pick a spot inside New York City.");
      return;
    }
    if (!marker) {
      marker = new maplibregl.Marker({ draggable: true, color: "#5aa9ff" })
        .setLngLat([lng, lat])
        .addTo(map);
      marker.on("dragend", function () {
        var ll = marker.getLngLat();
        placeMarker(ll.lat, ll.lng, true);
      });
    } else {
      marker.setLngLat([lng, lat]);
    }
    if (save) {
      setStatus("Saving…");
      postLocation(
        "lat=" + encodeURIComponent(lat) + "&lng=" + encodeURIComponent(lng)
      )
        .then(function () {
          setStatus("Pin saved for closer picks when energy is low.");
        })
        .catch(function (err) {
          setStatus(err.message || "Could not save location.");
        });
    }
  }

  map.on("click", function (e) {
    placeMarker(e.lngLat.lat, e.lngLat.lng, true);
  });

  if (cfg.has_pin) {
    placeMarker(cfg.lat, cfg.lng, false);
    setStatus("Pin saved. Drag or tap to move it.");
  } else {
    setStatus("Tap the map or use your location to drop a pin.");
  }

  if (useBtn) {
    useBtn.addEventListener("click", function () {
      if (!navigator.geolocation) {
        setStatus("Geolocation is not available in this browser.");
        return;
      }
      setStatus("Finding you…");
      navigator.geolocation.getCurrentPosition(
        function (pos) {
          var lat = pos.coords.latitude;
          var lng = pos.coords.longitude;
          if (!inNyc(lat, lng)) {
            setStatus("Your GPS looks outside NYC — drop a pin on the map instead.");
            return;
          }
          map.flyTo({ center: [lng, lat], zoom: 13 });
          placeMarker(lat, lng, true);
        },
        function () {
          setStatus("Could not read your location. Drop a pin on the map instead.");
        },
        { enableHighAccuracy: true, timeout: 10000 }
      );
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      postLocation("clear=1")
        .then(function () {
          if (marker) {
            marker.remove();
            marker = null;
          }
          setStatus("Pin cleared.");
        })
        .catch(function (err) {
          setStatus(err.message || "Could not clear pin.");
        });
    });
  }
})();
