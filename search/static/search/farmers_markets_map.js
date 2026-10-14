(() => {
  const mapElement = document.getElementById("farmers-market-map");
  const dataElement = document.getElementById("farmers-market-data");
  const statusElement = document.getElementById("map-status");
  if (!mapElement || !dataElement || !statusElement) return;
  if (!window.maplibregl) {
    statusElement.textContent =
      "The map library could not be loaded. Check your internet connection and refresh.";
    return;
  }

  const markets = JSON.parse(dataElement.textContent);
  const points = markets.map((market) => ({
    type: "Feature",
    geometry: {
      type: "Point",
      coordinates: [market.longitude, market.latitude],
    },
    properties: market,
  }));
  const map = new maplibregl.Map({
    container: mapElement,
    style: "https://tiles.openfreemap.org/styles/positron",
    center: [-73.95, 40.72],
    zoom: 10,
    maxZoom: 18,
    customAttribution:
      '&copy; <a href="https://openfreemap.org/">OpenFreeMap</a> contributors &middot; ' +
      '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
  });
  map.addControl(new maplibregl.NavigationControl(), "top-left");

  map.on("error", (event) => {
    if (!map.isStyleLoaded() || event.sourceId === "openmaptiles") {
      statusElement.textContent =
        "The map could not load. Check your internet connection and refresh.";
    }
  });

  map.on("load", () => {
    map.addSource("farmers-markets", {
      type: "geojson",
      data: { type: "FeatureCollection", features: points },
    });
    map.addLayer({
      id: "farmers-market-points",
      type: "circle",
      source: "farmers-markets",
      paint: {
        "circle-radius": ["interpolate", ["linear"], ["zoom"], 8, 5, 14, 9],
        "circle-color": "#1f5fbf",
        "circle-stroke-color": "#ffffff",
        "circle-stroke-width": 2,
      },
    });

    map.on("mouseenter", "farmers-market-points", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "farmers-market-points", () => {
      map.getCanvas().style.cursor = "";
    });
    map.on("click", "farmers-market-points", (event) => {
      const feature = event.features?.[0];
      if (!feature) return;

      const popup = createPopup(feature.properties);
      const mapPopup = new maplibregl.Popup({ closeButton: true, maxWidth: "320px" })
        .setLngLat(event.lngLat)
        .setDOMContent(popup)
        .addTo(map);
      const updateStatus = () => {
        const status = getMarketStatus(feature.properties, new Date());
        const statusElement = popup.querySelector(".market-status");
        statusElement.textContent = status;
        statusElement.className =
          `market-status market-status--${status.toLowerCase().replace(" ", "-")}`;
      };
      updateStatus();
      const statusInterval = window.setInterval(updateStatus, 60_000);
      mapPopup.on("close", () => window.clearInterval(statusInterval));
    });

    if (points.length) {
      const bounds = new maplibregl.LngLatBounds();
      points.forEach((point) => bounds.extend(point.geometry.coordinates));
      map.fitBounds(bounds, { padding: 48, maxZoom: 13 });
      statusElement.textContent = `${points.length} market locations shown.`;
    } else {
      statusElement.textContent = "No mapped markets are available for this dataset year.";
    }
  });

  map.on("style.load", () => map.resize());

  function createPopup(market) {
    const container = document.createElement("div");
    container.className = "market-popup";

    const heading = document.createElement("h2");
    heading.textContent = market.market_name || "Farmers market";
    container.appendChild(heading);

    const hoursRow = document.createElement("div");
    hoursRow.className = "market-popup__hours";
    const hours = document.createElement("p");
    const hoursLabel = document.createElement("strong");
    hoursLabel.textContent = "Hours: ";
    hours.append(hoursLabel, document.createTextNode(market.hours_of_operations || "Not listed"));
    hoursRow.appendChild(hours);
    const status = document.createElement("span");
    status.className = "market-status";
    status.setAttribute("aria-live", "polite");
    hoursRow.appendChild(status);
    container.appendChild(hoursRow);

    if (market.days_of_operation) {
      appendDetail(container, "Days", market.days_of_operation);
    }
    if (market.street_address) appendDetail(container, "Address", market.street_address);
    if (market.borough) appendDetail(container, "Borough", market.borough);

    const directions = document.createElement("a");
    directions.href =
      `https://www.google.com/maps/search/?api=1&query=${market.latitude},${market.longitude}`;
    directions.target = "_blank";
    directions.rel = "noopener noreferrer";
    directions.textContent = "Get directions";
    container.appendChild(directions);
    return container;
  }

  function getMarketStatus(market, now) {
    const weekday = new Intl.DateTimeFormat("en-US", {
      timeZone: "America/New_York",
      weekday: "long",
    }).format(now);
    const dayIndex = WEEKDAYS.indexOf(weekday);
    if (dayIndex < 0 || !marketOperatesOnDay(market.days_of_operation, dayIndex)) {
      return "Closed";
    }

    const { hour, minute } = Object.fromEntries(
      new Intl.DateTimeFormat("en-US", {
        timeZone: "America/New_York",
        hour: "numeric",
        minute: "numeric",
        hourCycle: "h23",
      })
        .formatToParts(now)
        .filter((part) => part.type === "hour" || part.type === "minute")
        .map((part) => [part.type, Number(part.value)]),
    );
    const currentMinutes = hour * 60 + minute;
    const hours = getHoursForDay(market.hours_of_operations, dayIndex);
    if (!hours || currentMinutes < hours.open || currentMinutes >= hours.close) {
      return "Closed";
    }
    return hours.close - currentMinutes < 60 ? "Closing soon" : "Open";
  }

  const WEEKDAYS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
  ];
  const DAY_TOKEN_PATTERN =
    /\b(Mondays?|Mon|Tuesdays?|Tues?|Wednesdays?|Weds?|Thursdays?|Thurs?|Fridays?|Fris?|Saturdays?|Sats?|Sundays?|Suns?)\b/gi;

  function marketOperatesOnDay(days, selectedDay) {
    const matches = [...(days || "").matchAll(DAY_TOKEN_PATTERN)];
    const operatingDays = new Set();
    matches.forEach((match, index) => {
      const dayIndex = WEEKDAYS.findIndex((day) =>
        day.toLowerCase().startsWith(match[0].toLowerCase().slice(0, 3)),
      );
      if (dayIndex < 0) return;
      operatingDays.add(dayIndex);
      const nextMatch = matches[index + 1];
      if (
        nextMatch &&
        /^\s*[-–]\s*$/.test(days.slice(match.index + match[0].length, nextMatch.index))
      ) {
        let current = dayIndex;
        const end = WEEKDAYS.findIndex((day) =>
          day.toLowerCase().startsWith(nextMatch[0].toLowerCase().slice(0, 3)),
        );
        while (end >= 0 && current !== end) {
          current = (current + 1) % WEEKDAYS.length;
          operatingDays.add(current);
        }
      }
    });
    return operatingDays.has(selectedDay);
  }

  function getHoursForDay(hours, dayIndex) {
    for (const segment of (hours || "").split(";")) {
      const annotations = [...segment.matchAll(/\(([^)]*)\)/g)].map((match) =>
        match[1].trim(),
      );
      const dayAnnotations = annotations.filter(
        (annotation) =>
          new RegExp(DAY_TOKEN_PATTERN.source, "i").test(annotation) ||
          /\b(?:W|SU)\b/i.test(annotation),
      );
      if (
        dayAnnotations.length &&
        !dayAnnotations.some((annotation) => annotationIncludesDay(annotation, dayIndex))
      ) {
        continue;
      }
      const range = segment.replace(/\bnoon\b/gi, "12 p.m.").match(
        /(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\s*(?:-|–|to)\s*(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?/i,
      );
      if (range) {
        const startHour = Number(range[1]);
        const endHour = Number(range[4]);
        const explicitStartPeriod = normalizePeriod(range[3]);
        const endPeriod = normalizePeriod(range[6]);
        const startPeriod =
          explicitStartPeriod ||
          (endPeriod && startHour < endHour
            ? endPeriod === "pm" ? "am" : "pm"
            : endPeriod);
        const inferredEndPeriod =
          endPeriod ||
          (startPeriod && startHour > endHour
            ? startPeriod === "pm" ? "am" : "pm"
            : startPeriod);
        const open = parseTime(range[1], range[2], startPeriod);
        const close = parseTime(
          range[4],
          range[5],
          inferredEndPeriod,
          open,
        );
        if (open !== null && close !== null) return { open, close };
      }
    }
    return null;
  }

  function annotationIncludesDay(annotation, dayIndex) {
    if (/\bW\b/i.test(annotation) && dayIndex === 2) return true;
    if (/\bSU\b/i.test(annotation) && dayIndex === 6) return true;
    DAY_TOKEN_PATTERN.lastIndex = 0;
    return marketOperatesOnDay(annotation, dayIndex);
  }

  function normalizePeriod(period) {
    if (!period) return null;
    return period.toLowerCase().includes("p") ? "pm" : "am";
  }

  function parseTime(hourText, minuteText, period, startMinutes = null) {
    let hour = Number(hourText);
    const minute = Number(minuteText || 0);
    if (!period || hour < 1 || hour > 12 || minute > 59) return null;
    if (hour === 12) hour = 0;
    let result = hour * 60 + minute + (period === "pm" ? 12 * 60 : 0);
    if (startMinutes !== null && result <= startMinutes) result += 12 * 60;
    return result;
  }

  function appendDetail(container, label, value) {
    const paragraph = document.createElement("p");
    const strong = document.createElement("strong");
    strong.textContent = `${label}: `;
    paragraph.append(strong, document.createTextNode(value));
    container.appendChild(paragraph);
  }
})();
