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
    openPoint: null,
    docked: false,
    popup: null,
    panelHome: null,
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
        panel.appendChild(renderGoogleReview(point, payload, review));
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

    (payload.comments || []).forEach((comment) => {
      panel.appendChild(renderComment(point, payload, comment));
    });

    if ((payload.photos || []).length) {
      addText(panel, "h3", "", "Photos");
      payload.photos.forEach((photo) => {
        panel.appendChild(renderPhoto(photo));
      });
    }

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

  function renderPhoto(photo) {
    const figure = document.createElement("figure");
    figure.className = "community-photo";
    const image = document.createElement("img");
    image.src = photo.url;
    image.alt = photo.author ? `Photo from ${photo.author}` : "Visitor photo";
    figure.appendChild(image);
    if (photo.author) addText(figure, "figcaption", "muted", photo.author);
    return figure;
  }

  function createToggle(label, form) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "community-reply-toggle";
    button.textContent = label;
    form.hidden = true;
    button.addEventListener("click", () => {
      form.hidden = !form.hidden;
      if (!form.hidden) {
        form.querySelector("textarea, input[type='file']")?.focus();
      }
    });
    return button;
  }

  function renderGoogleReview(point, payload, review) {
    const block = document.createElement("div");
    block.className = "community-entry";
    addText(block, "strong", "", review.author_name || "Google reviewer");
    if (review.rating) addText(block, "span", "muted", ` ${review.rating}/5`);
    if (review.relative_time) addText(block, "span", "muted", ` · ${review.relative_time}`);
    if (review.text) addText(block, "p", "", review.text);

    (review.comments || []).forEach((comment) => {
      block.appendChild(
        renderComment(point, payload, comment, { underReview: true }),
      );
    });

    if (payload.authenticated && review.id) {
      const form = createThreadForm(point, {
        placeholder: "Write a comment on this Google review",
        submitLabel: "Post comment",
        googleReviewId: review.id,
        includePhoto: true,
      });
      block.append(createToggle("Comment", form), form);
    } else if (!payload.authenticated && review.id) {
      const login = document.createElement("p");
      login.className = "muted";
      const link = document.createElement("a");
      const config = readJson("combined-map-config");
      link.href = payload.login_url || config?.loginUrl || "/login/";
      link.textContent = "Log in";
      login.appendChild(link);
      login.appendChild(document.createTextNode(" to comment"));
      block.appendChild(login);
    }
    return block;
  }

  function renderComment(point, payload, comment, options = {}) {
    const block = document.createElement("div");
    if (options.isReply || options.underReview) {
      block.className = "community-entry community-entry--reply";
    } else {
      block.className = "community-entry";
    }
    addText(block, "strong", "", comment.author || "User");
    addText(block, "p", "", comment.text || "");
    (comment.photos || []).forEach((photo) => {
      block.appendChild(renderPhoto(photo));
    });

    (comment.replies || []).forEach((reply) => {
      block.appendChild(renderComment(point, payload, reply, { isReply: true }));
    });

    if (!options.isReply && payload.authenticated && comment.id) {
      const actions = document.createElement("div");
      actions.className = "community-comment-actions";

      const replyForm = createThreadForm(point, {
        placeholder: "Write a reply",
        submitLabel: "Post reply",
        parentId: comment.id,
        includePhoto: true,
      });
      const photoForm = createPhotoForm(point, comment.id);
      actions.append(
        createToggle("Reply", replyForm),
        createToggle("Add photo", photoForm),
        replyForm,
        photoForm,
      );
      block.appendChild(actions);
    }
    return block;
  }

  function createAddPhotosControl(fileInput) {
    const wrap = document.createElement("div");
    wrap.className = "community-add-photos-wrap";

    fileInput.hidden = true;
    wrap.appendChild(fileInput);

    const button = document.createElement("button");
    button.type = "button";
    button.className = "community-add-photos-btn";
    button.textContent = "Add photos";
    button.addEventListener("click", () => fileInput.click());

    const status = document.createElement("span");
    status.className = "muted community-add-photos-btn__status";
    fileInput.addEventListener("change", () => {
      status.textContent = fileInput.files?.[0] ? fileInput.files[0].name : "";
    });

    wrap.append(button, status);
    return wrap;
  }

  function createPhotoForm(point, commentId) {
    const form = document.createElement("form");
    form.className = "community-form community-form--reply";

    const file = document.createElement("input");
    file.type = "file";
    file.name = "photo";
    file.accept = "image/*";
    file.required = true;
    file.setAttribute("aria-label", "Photo for this comment");
    form.appendChild(createAddPhotosControl(file));

    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn";
    submit.textContent = "Upload photo";
    form.appendChild(submit);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const photo = file.files?.[0];
      if (!photo) return;
      const photoData = new FormData();
      photoData.set("photo", photo);
      photoData.set("comment_id", String(commentId));
      await postCommunity(point, "photo", photoData);
    });
    return form;
  }

  function createThreadForm(point, options) {
    const form = document.createElement("form");
    form.className = "community-form community-form--reply";

    const textarea = document.createElement("textarea");
    textarea.name = "text";
    textarea.rows = 2;
    textarea.maxLength = 2000;
    textarea.placeholder = options.placeholder || "Write a comment";
    textarea.required = true;
    textarea.setAttribute("aria-label", options.placeholder || "Comment");
    form.appendChild(textarea);

    let file = null;
    if (options.includePhoto) {
      file = document.createElement("input");
      file.type = "file";
      file.name = "photo";
      file.accept = "image/*";
      file.setAttribute("aria-label", "Photo (optional)");
      form.appendChild(createAddPhotosControl(file));
    }

    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn";
    submit.textContent = options.submitLabel || "Post";
    form.appendChild(submit);

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const text = (textarea.value || "").trim();
      if (!text) return;
      const commentData = new FormData();
      commentData.set("text", text);
      if (options.parentId) commentData.set("parent_id", String(options.parentId));
      if (options.googleReviewId) {
        commentData.set("google_review_id", String(options.googleReviewId));
      }
      let payload = await postCommunity(point, "comment", commentData, {
        deferRender: true,
      });
      if (!payload) return;
      const photo = file?.files?.[0];
      if (photo && payload.created_comment_id) {
        const photoData = new FormData();
        photoData.set("photo", photo);
        photoData.set("comment_id", String(payload.created_comment_id));
        const next = await postCommunity(point, "photo", photoData, {
          deferRender: true,
        });
        if (!next) return;
        payload = next;
      }
      renderPanel(point, payload);
    });
    return form;
  }

  function createVisitorForm(point, payload) {
    const wrap = document.createElement("div");
    wrap.className = "community-review-composer";

    const openButton = document.createElement("button");
    openButton.type = "button";
    openButton.className = "btn community-write-review";
    openButton.textContent = "Write a review";
    wrap.appendChild(openButton);

    const form = document.createElement("form");
    form.className = "community-form community-form--visitor";
    form.hidden = true;

    const formId = `community-${(point.key || "pin").replace(/[^a-zA-Z0-9_-]/g, "-")}`;
    const stars = document.createElement("div");
    stars.className = "review-stars review-stars--composer";
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
    textarea.rows = 4;
    textarea.maxLength = 2000;
    textarea.placeholder = "Share details of your own experience at this place";
    textarea.setAttribute("aria-label", "Comment (optional)");
    form.appendChild(textarea);

    const file = document.createElement("input");
    file.type = "file";
    file.name = "photo";
    file.accept = "image/*";
    file.setAttribute("aria-label", "Photo (optional)");
    const photosControl = createAddPhotosControl(file);
    const photoStatus = photosControl.querySelector(".community-add-photos-btn__status");
    form.appendChild(photosControl);

    const actions = document.createElement("div");
    actions.className = "community-review-actions";

    const submit = document.createElement("button");
    submit.type = "submit";
    submit.className = "btn";
    submit.textContent = "Leave review";
    submit.disabled = !payload.user_rating;

    const cancel = document.createElement("button");
    cancel.type = "button";
    cancel.className = "community-review-cancel";
    cancel.textContent = "Cancel";
    cancel.addEventListener("click", () => {
      form.hidden = true;
      openButton.hidden = false;
      form.reset();
      photoStatus.textContent = "";
      submit.disabled = !payload.user_rating;
    });

    actions.append(cancel, submit);
    form.appendChild(actions);

    stars.addEventListener("change", () => {
      submit.disabled = !form.querySelector('input[name="rating"]:checked');
    });

    openButton.addEventListener("click", () => {
      openButton.hidden = true;
      form.hidden = false;
      textarea.focus();
    });

    form.addEventListener("submit", (event) => {
      event.preventDefault();
      submitVisitorContribution(point, form);
    });

    wrap.appendChild(form);
    return wrap;
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
    const photo = form.querySelector('input[name="photo"]')?.files?.[0];
    let createdCommentId = null;
    if (text) {
      const commentData = new FormData();
      commentData.set("text", text);
      const next = await postCommunity(point, "comment", commentData, {
        deferRender: true,
      });
      if (!next) return;
      payload = next;
      createdCommentId = payload.created_comment_id || null;
    }

    if (photo) {
      const photoData = new FormData();
      photoData.set("photo", photo);
      if (createdCommentId) photoData.set("comment_id", String(createdCommentId));
      const next = await postCommunity(point, "photo", photoData, {
        deferRender: true,
      });
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

  function rememberPanelHome(panel) {
    if (!state.panelHome) {
      state.panelHome = panel.parentNode || document.querySelector(".community-panel-slot");
    }
  }

  function restorePanelHome() {
    const panel = panelElement();
    if (!panel) return;
    panel.classList.remove("in-popup");
    rememberPanelHome(panel);
    if (state.panelHome && panel.parentNode !== state.panelHome) {
      state.panelHome.appendChild(panel);
    }
  }

  function resizeMapSoon() {
    if (!state.map) return;
    requestAnimationFrame(() => state.map.resize());
  }

  function showCommunityPanel() {
    const layout = document.querySelector(".combined-map-layout");
    if (!layout || layout.classList.contains("is-panel-open")) {
      resizeMapSoon();
      return;
    }
    layout.classList.add("is-panel-open");
    resizeMapSoon();
  }

  function hideCommunityPanel() {
    const layout = document.querySelector(".combined-map-layout");
    if (!layout || !layout.classList.contains("is-panel-open")) {
      resizeMapSoon();
      return;
    }
    layout.classList.remove("is-panel-open");
    resizeMapSoon();
  }

  function attachExpandTab(popup) {
    const content = popup.getElement()?.querySelector(".maplibregl-popup-content");
    if (!content || content.querySelector(".panel-edge-tab--expand")) return;
    content.classList.add("has-panel-edge-tab");
    popup.getElement()?.classList.add("has-panel-edge-tab");
    const button = document.createElement("button");
    button.type = "button";
    button.className = "panel-edge-tab panel-edge-tab--expand";
    button.setAttribute("aria-label", "Expand details to the side");
    button.innerHTML = '<span aria-hidden="true">›</span>';
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      dockPanel();
    });
    content.appendChild(button);
  }

  function dockPanel() {
    state.docked = true;
    const popup = state.popup;
    state.popup = null;
    restorePanelHome();
    if (popup) popup.remove();
    showCommunityPanel();
    state.reclampPanelWidth?.();
  }

  function collapsePanelToPopup() {
    const point = state.openPoint;
    state.docked = false;
    hideCommunityPanel();
    if (point) showPointPopup(point);
  }

  function showPointPopup(point) {
    const panel = panelElement();
    const gl = window.maplibregl;
    if (!panel || !gl || !state.map || point.lat == null || point.lng == null) {
      state.docked = true;
      restorePanelHome();
      showCommunityPanel();
      return;
    }
    if (state.popup) {
      const previous = state.popup;
      state.popup = null;
      previous.remove();
    }
    rememberPanelHome(panel);
    panel.classList.add("in-popup");
    const popup = new gl.Popup({ maxWidth: "none", closeOnClick: false, offset: 16, anchor: "bottom" })
      .setLngLat([point.lng, point.lat])
      .setDOMContent(panel)
      .addTo(state.map);
    popup.on("close", () => {
      if (state.popup === popup) state.popup = null;
      if (state.docked) return;
      restorePanelHome();
    });
    state.popup = popup;
    attachExpandTab(popup);
    state.map.easeTo({ center: [point.lng, point.lat], offset: [0, 170] });
  }

  function openPoint(point) {
    state.openKey = point.key || "";
    state.openPoint = point;
    highlightCard(state.openKey, true);
    if (state.docked) {
      if (state.popup) {
        const popup = state.popup;
        state.popup = null;
        popup.remove();
      }
      restorePanelHome();
      showCommunityPanel();
    } else {
      showPointPopup(point);
    }
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
    const MIN_PANEL = 200;
    const MAX_PANEL = 420;

    function clampWidth(width) {
      const layoutWidth = layout.getBoundingClientRect().width;
      // Keep at least half the map visible, and never exceed the CSS max.
      const maxForLayout = Math.max(160, Math.min(MAX_PANEL, Math.floor(layoutWidth * 0.48)));
      const minForLayout = Math.min(MIN_PANEL, maxForLayout);
      return Math.round(Math.min(maxForLayout, Math.max(minForLayout, width)));
    }

    function currentWidth() {
      return Number.parseInt(
        getComputedStyle(layout).getPropertyValue("--community-panel-width"),
        10,
      ) || DEFAULT_PANEL_WIDTH;
    }

    function applyWidth(width) {
      const next = clampWidth(width);
      layout.style.setProperty("--community-panel-width", `${next}px`);
      splitter.setAttribute("aria-valuenow", String(next));
      return next;
    }

    function reclamp() {
      applyWidth(currentWidth());
    }

    // Drop any previously saved width so reloads always start at the default.
    localStorage.removeItem("combined-map-panel-width");
    applyWidth(DEFAULT_PANEL_WIDTH);
    state.reclampPanelWidth = reclamp;

    let dragging = false;

    function onPointerMove(event) {
      if (!dragging) return;
      const bounds = layout.getBoundingClientRect();
      const width = bounds.right - event.clientX - 10;
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
      const current = currentWidth();
      if (event.key === "ArrowLeft") {
        event.preventDefault();
        applyWidth(current + 16);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        applyWidth(current - 16);
      }
    });

    window.addEventListener("resize", () => {
      reclamp();
      if (state.map) state.map.resize();
    });
  }

  function bindPanelCollapse() {
    document.getElementById("community-panel-collapse")?.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      collapsePanelToPopup();
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
        openPoint(point);
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
    bindPanelCollapse();

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
