// Builds the info-window content for a pin on the Find restaurants map.
// p: one item of map_points (every field except name is optional).
window.rfPopupContent = function (p) {
  const root = document.createElement("div");
  root.className = "pin-popup";
  const row = (text, cls) => {
    const el = document.createElement("div");
    el.className = cls || "row";
    el.textContent = text;
    root.appendChild(el);
    return el;
  };
  if (p.photo_url) {
    const img = document.createElement("img");
    img.src = p.photo_url;
    img.alt = "";
    img.onerror = () => img.remove();
    root.appendChild(img);
  }
  row(p.name, "name");
  if (p.rating) row("\u2605 " + p.rating + (p.rating_count ? " (" + p.rating_count + " reviews)" : ""));
  const line = [p.price, p.address].filter(Boolean).join(" \u00b7 ");
  if (line) row(line);
  if (p.has_inspection) {
    const a = document.createElement("a");
    a.href = p.detail_url;
    a.className = "badge grade-" + (p.grade || "na").toLowerCase();
    a.textContent = p.grade ? "Grade " + p.grade : "Grade pending";
    root.appendChild(a);
  } else {
    row("No grade", "row muted");
  }
  if (p.maps_url) {
    const a = document.createElement("a");
    a.href = p.maps_url;
    a.target = "_blank";
    a.rel = "noopener";
    a.className = "gmaps";
    a.textContent = "View on Google Maps";
    root.appendChild(a);
  }
  return root;
};
