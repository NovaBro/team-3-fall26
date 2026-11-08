(function () {
  const panel = document.getElementById("assistant-panel");
  const toggle = document.getElementById("assistant-toggle");
  if (!panel || !toggle) return;

  const form = document.getElementById("assistant-form");
  const input = document.getElementById("assistant-input");
  const send = document.getElementById("assistant-send");
  const messages = document.getElementById("assistant-messages");
  const locationButton = document.getElementById("assistant-location");
  const locationStatus = document.getElementById("assistant-location-status");
  const LOCATION_FLAG = "assistant-use-location";
  const hint = document.getElementById("assistant-hint");
  const csrf = form.querySelector("[name=csrfmiddlewaretoken]").value;
  let loaded = false;
  let coords = null;

  function rememberLocationChoice(on) {
    try {
      if (on) localStorage.setItem(LOCATION_FLAG, "1");
      else localStorage.removeItem(LOCATION_FLAG);
    } catch (_error) {
      // The choice just won't survive a reload.
    }
  }

  function locationWasOn() {
    try {
      return localStorage.getItem(LOCATION_FLAG) === "1";
    } catch (_error) {
      return false;
    }
  }

  function showLocationState(on, text) {
    locationButton.textContent = on ? "Stop using location" : "Use my location";
    locationButton.setAttribute("aria-pressed", String(on));
    locationStatus.textContent = text;
  }

  function requestLocation() {
    if (!navigator.geolocation) {
      showLocationState(false, "Your browser doesn't support location. Mention a ZIP code or borough instead.");
      return;
    }
    locationStatus.textContent = "Getting your location…";
    navigator.geolocation.getCurrentPosition(
      (position) => {
        coords = { lat: position.coords.latitude, lng: position.coords.longitude };
        rememberLocationChoice(true);
        showLocationState(true, "Using your location to search nearby, through Google Places.");
      },
      () => {
        coords = null;
        rememberLocationChoice(false);
        showLocationState(false, "Couldn't get your location. Mention a ZIP code or borough instead.");
      }
    );
  }

  function setOpen(open) {
    panel.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
    if (!open) {
      toggle.focus();
      return;
    }
    if (!loaded) {
      loadHistory();
      if (locationWasOn()) requestLocation();
    }
    input.focus();
  }

  function scrollToEnd() {
    messages.scrollTop = messages.scrollHeight;
  }

  // Everything from the server goes through textContent, so it can't inject HTML.
  function addMessage(kind, text) {
    const bubble = document.createElement("div");
    bubble.className = `assistant-message assistant-message--${kind}`;
    bubble.textContent = text;
    messages.appendChild(bubble);
    hint.hidden = true;
    scrollToEnd();
    return bubble;
  }

  function addCards(places) {
    (places || []).forEach((place) => {
      const card = document.createElement("a");
      card.className = "assistant-card";
      card.href = place.url;
      const name = document.createElement("strong");
      name.textContent = place.name;
      const meta = document.createElement("span");
      if (place.external) {
        card.target = "_blank";
        card.rel = "noopener";
      }
      const distance = place.distance_miles == null ? "" : `${place.distance_miles} mi`;
      meta.textContent = [place.type, distance, place.grade && `Grade ${place.grade}`, place.address]
        .filter(Boolean)
        .join(" · ");
      card.append(name, meta);
      messages.appendChild(card);
    });
    scrollToEnd();
  }

  async function readJson(response) {
    try {
      return await response.json();
    } catch (_error) {
      return {};
    }
  }

  async function loadHistory() {
    loaded = true;
    try {
      const response = await fetch(panel.dataset.historyUrl, {
        headers: { Accept: "application/json" },
      });
      const payload = await readJson(response);
      (payload.messages || []).forEach((turn) => {
        addMessage(turn.role, turn.text);
        addCards(turn.places);
      });
    } catch (_error) {
      loaded = false;
    }
  }

  async function postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
        "X-CSRFToken": csrf,
      },
      body: JSON.stringify(body),
    });
  }

  async function submit() {
    const text = input.value.trim();
    if (!text || send.disabled) return;
    input.value = "";
    send.disabled = true;
    addMessage("user", text);
    const pending = addMessage("assistant", "Looking that up…");
    pending.classList.add("assistant-message--pending");
    try {
      const response = await postJson(panel.dataset.chatUrl, { message: text, ...(coords || {}) });
      const payload = await readJson(response);
      pending.remove();
      if (!response.ok) {
        addMessage("error", payload.error || "Something went wrong. Please try again.");
        input.value = input.value || text;
        return;
      }
      const reply = addMessage("assistant", payload.reply);
      addCards(payload.places);
      // Show the start of the answer, not the end of its last card.
      messages.scrollTop = reply.offsetTop - messages.offsetTop;
    } catch (_error) {
      pending.remove();
      addMessage("error", "Couldn't reach the server. Please try again.");
      input.value = input.value || text;
    } finally {
      send.disabled = false;
      input.focus();
    }
  }

  locationButton.addEventListener("click", () => {
    if (coords) {
      coords = null;
      rememberLocationChoice(false);
      showLocationState(false, "Location off. Mention a ZIP code or borough to search an area.");
    } else {
      requestLocation();
    }
  });
  toggle.addEventListener("click", () => setOpen(panel.hidden));
  document.getElementById("assistant-close").addEventListener("click", () => setOpen(false));
  panel.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setOpen(false);
  });
  document.getElementById("assistant-reset").addEventListener("click", async () => {
    const response = await postJson(panel.dataset.resetUrl, {});
    if (!response.ok) return;
    messages.querySelectorAll(":scope > :not(#assistant-hint)").forEach((node) => node.remove());
    hint.hidden = false;
    input.focus();
  });
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    submit();
  });
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      submit();
    }
  });
})();
