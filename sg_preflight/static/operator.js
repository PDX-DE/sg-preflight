(function () {
  const rootElement = document.documentElement;
  const overlay = document.getElementById("loading-overlay");
  const overlayFill = document.getElementById("loading-progress-fill");
  const overlayPercent = document.getElementById("loading-progress-percent");
  const overlayEta = document.getElementById("loading-progress-eta");
  const overlayLabel = document.getElementById("loading-progress-label");
  const overlayDetail = document.getElementById("loading-progress-detail");
  const overlayStatus = document.getElementById("loading-progress-status");
  const overlayToggle = document.getElementById("loading-toggle");
  const overlayExpanded = document.getElementById("loading-expanded");
  const overlaySteps = document.getElementById("loading-step-list");
  const overlayStepDetail = document.getElementById("loading-step-detail");
  const overlayEvents = document.getElementById("loading-event-list");
  const overlayLogTail = document.getElementById("loading-log-tail");
  const overlayWordmark = document.querySelector(".loading-native-wordmark");
  const themeToggle = document.getElementById("theme-toggle");
  const uiModeToggle = document.getElementById("ui-mode-toggle");
  const guideToggle = document.getElementById("guide-toggle");
  let selectedStepKey = "";
  let nestedStepRequestId = 0;
  let lastOverlayDetailSignature = "";
  let lastOverlayLogSignature = "";
  let wordmarkFrameIndex = 0;
  let wordmarkTimerId = 0;

  const rawWordmarkFrames = [
    { x: 0, y: 0, scale: 0.91, opacity: 0.98, blueX: -1.2, blueY: 0, blueScale: 1, blueOpacity: 0.62, redX: 1.1, redY: 0, redScale: 1, redOpacity: 0.5 },
    { x: 0, y: 0, scale: 0.91, opacity: 0.98, blueX: -1.2, blueY: 0, blueScale: 1, blueOpacity: 0.62, redX: 1.1, redY: 0, redScale: 1, redOpacity: 0.5 },
    { x: 0, y: 0, scale: 0.91, opacity: 0.98, blueX: -1.2, blueY: 0, blueScale: 1, blueOpacity: 0.62, redX: 1.1, redY: 0, redScale: 1, redOpacity: 0.5 },
    { x: 1, y: -0.4, scale: 0.912, opacity: 0.97, blueX: -2, blueY: 0, blueScale: 1.002, blueOpacity: 0.64, redX: 1.5, redY: 0, redScale: 1.002, redOpacity: 0.52 },
    { x: 1, y: -0.2, scale: 0.913, opacity: 0.965, blueX: -2.5, blueY: 0, blueScale: 1.004, blueOpacity: 0.66, redX: 1.8, redY: 0, redScale: 1.003, redOpacity: 0.54 },
    { x: 1.4, y: -0.2, scale: 0.914, opacity: 0.97, blueX: -3, blueY: 0, blueScale: 1.006, blueOpacity: 0.68, redX: 2.2, redY: 0, redScale: 1.004, redOpacity: 0.56 },
    { x: 0.2, y: 0, scale: 0.91, opacity: 0.965, blueX: -2.1, blueY: 0, blueScale: 1.002, blueOpacity: 0.63, redX: 1.4, redY: 0, redScale: 1.002, redOpacity: 0.51 },
    { x: 0.2, y: 0, scale: 0.91, opacity: 0.965, blueX: -2.1, blueY: 0, blueScale: 1.002, blueOpacity: 0.63, redX: 1.4, redY: 0, redScale: 1.002, redOpacity: 0.51 },
    { x: -2.8, y: 0, scale: 0.916, opacity: 0.94, blueX: -18, blueY: 0, blueScale: 1.055, blueOpacity: 0.8, redX: 5, redY: 0, redScale: 1.015, redOpacity: 0.36 },
    { x: -1.4, y: 0, scale: 0.918, opacity: 0.93, blueX: -28, blueY: 0, blueScale: 1.085, blueOpacity: 0.76, redX: 10, redY: 0, redScale: 1.03, redOpacity: 0.46 },
    { x: 0.8, y: 0, scale: 0.918, opacity: 0.93, blueX: -22, blueY: 0, blueScale: 1.07, blueOpacity: 0.73, redX: 12, redY: 0, redScale: 1.034, redOpacity: 0.48 },
    { x: 0, y: 0, scale: 0.92, opacity: 0.91, blueX: -34, blueY: 0, blueScale: 1.115, blueOpacity: 0.6, redX: 18, redY: 0, redScale: 1.055, redOpacity: 0.4 },
    { x: -2.2, y: 0, scale: 0.914, opacity: 0.94, blueX: -12, blueY: 0, blueScale: 1.03, blueOpacity: 0.66, redX: 6, redY: 0, redScale: 1.018, redOpacity: 0.44 },
    { x: -2.6, y: 0, scale: 0.913, opacity: 0.945, blueX: -9, blueY: 0, blueScale: 1.024, blueOpacity: 0.64, redX: 5, redY: 0, redScale: 1.015, redOpacity: 0.44 },
    { x: -2.8, y: 0, scale: 0.912, opacity: 0.947, blueX: -8, blueY: 0, blueScale: 1.02, blueOpacity: 0.62, redX: 4.2, redY: 0, redScale: 1.012, redOpacity: 0.43 },
    { x: -3, y: 0, scale: 0.912, opacity: 0.945, blueX: -8, blueY: 0, blueScale: 1.019, blueOpacity: 0.61, redX: 4, redY: 0, redScale: 1.011, redOpacity: 0.42 },
    { x: -3.2, y: 0, scale: 0.911, opacity: 0.94, blueX: -7, blueY: 0, blueScale: 1.017, blueOpacity: 0.59, redX: 3.5, redY: 0, redScale: 1.01, redOpacity: 0.41 },
    { x: -3.4, y: 0, scale: 0.91, opacity: 0.938, blueX: -6, blueY: 0, blueScale: 1.014, blueOpacity: 0.57, redX: 3.1, redY: 0, redScale: 1.009, redOpacity: 0.4 },
    { x: -2.4, y: 0, scale: 0.91, opacity: 0.94, blueX: -5, blueY: 0, blueScale: 1.012, blueOpacity: 0.58, redX: 2.7, redY: 0, redScale: 1.008, redOpacity: 0.41 },
    { x: -1.2, y: 0, scale: 0.91, opacity: 0.95, blueX: -3.5, blueY: 0, blueScale: 1.008, blueOpacity: 0.59, redX: 2.2, redY: 0, redScale: 1.006, redOpacity: 0.43 },
    { x: 0, y: 0, scale: 0.91, opacity: 0.96, blueX: -2.2, blueY: 0, blueScale: 1.004, blueOpacity: 0.61, redX: 1.8, redY: 0, redScale: 1.004, redOpacity: 0.46 },
    { x: 0, y: 0, scale: 0.91, opacity: 0.97, blueX: -1.8, blueY: 0, blueScale: 1.003, blueOpacity: 0.62, redX: 1.5, redY: 0, redScale: 1.003, redOpacity: 0.48 },
    { x: 0, y: 0, scale: 0.91, opacity: 0.975, blueX: -1.4, blueY: 0, blueScale: 1.001, blueOpacity: 0.62, redX: 1.2, redY: 0, redScale: 1.001, redOpacity: 0.49 }
  ];
  const wordmarkFrames = rawWordmarkFrames.map(function (frame) {
    return {
      x: frame.x * 0.72,
      y: frame.y * 0.72,
      scale: 0.88 + ((frame.scale - 0.91) * 0.58),
      opacity: 0.96 + ((frame.opacity - 0.96) * 0.55),
      blueX: frame.blueX * 0.36,
      blueY: frame.blueY * 0.5,
      blueScale: 1 + ((frame.blueScale - 1) * 0.42),
      blueOpacity: 0.48 + ((frame.blueOpacity - 0.48) * 0.5),
      redX: frame.redX * 0.34,
      redY: frame.redY * 0.5,
      redScale: 1 + ((frame.redScale - 1) * 0.4),
      redOpacity: 0.4 + ((frame.redOpacity - 0.4) * 0.5)
    };
  });

  const applyTheme = function (theme) {
    const resolved = theme === "light" ? "light" : "dark";
    rootElement.dataset.theme = resolved;
    if (themeToggle) {
      const usingLight = resolved === "light";
      themeToggle.setAttribute("aria-pressed", usingLight ? "false" : "true");
      themeToggle.textContent = usingLight ? "Dark mode" : "Light mode";
    }
  };

  const applyUiMode = function (mode) {
    const resolved = mode === "clean" ? "clean" : "cinematic";
    rootElement.dataset.uiMode = resolved;
    if (uiModeToggle) {
      const cleanMode = resolved === "clean";
      uiModeToggle.setAttribute("aria-pressed", cleanMode ? "true" : "false");
      uiModeToggle.textContent = cleanMode ? "Cinematic mode" : "Clean mode";
    }
  };

  const applyGuideMode = function (mode) {
    const resolved = mode === "off" ? "off" : "on";
    document.body.dataset.guideMode = resolved;
    if (guideToggle) {
      const enabled = resolved === "on";
      guideToggle.setAttribute("aria-pressed", enabled ? "true" : "false");
      guideToggle.textContent = enabled ? "Hide guide" : "Show guide";
    }
  };

  try {
    const query = new URLSearchParams(window.location.search);
    const cleanThemeAlias = query.toString().includes("theme=clean") || query.get("theme") === "clean";
    const requestedUiMode = query.get("ui-mode") || (cleanThemeAlias ? "clean" : "");
    applyTheme(window.localStorage.getItem("sg-theme") || rootElement.dataset.theme || "dark");
    applyUiMode(requestedUiMode || window.localStorage.getItem("sg-ui-mode") || rootElement.dataset.uiMode || "cinematic");
    applyGuideMode(window.localStorage.getItem("sg-guide-mode") || document.body.dataset.guideMode || "on");
  } catch (_error) {
    applyTheme(rootElement.dataset.theme || "dark");
    applyUiMode(rootElement.dataset.uiMode || "cinematic");
    applyGuideMode(document.body.dataset.guideMode || "on");
  }

  const applyWordmarkFrame = function (frame) {
    if (!overlayWordmark || !frame) {
      return;
    }
    overlayWordmark.style.setProperty("--wordmark-x", frame.x + "px");
    overlayWordmark.style.setProperty("--wordmark-y", frame.y + "px");
    overlayWordmark.style.setProperty("--wordmark-scale", String(frame.scale));
    overlayWordmark.style.setProperty("--wordmark-opacity", String(frame.opacity));
    overlayWordmark.style.setProperty("--wordmark-blue-x", frame.blueX + "px");
    overlayWordmark.style.setProperty("--wordmark-blue-y", frame.blueY + "px");
    overlayWordmark.style.setProperty("--wordmark-blue-scale", String(frame.blueScale));
    overlayWordmark.style.setProperty("--wordmark-blue-opacity", String(frame.blueOpacity));
    overlayWordmark.style.setProperty("--wordmark-red-x", frame.redX + "px");
    overlayWordmark.style.setProperty("--wordmark-red-y", frame.redY + "px");
    overlayWordmark.style.setProperty("--wordmark-red-scale", String(frame.redScale));
    overlayWordmark.style.setProperty("--wordmark-red-opacity", String(frame.redOpacity));
  };

  const startWordmarkLoop = function () {
    if (!overlayWordmark || wordmarkTimerId) {
      return;
    }
    applyWordmarkFrame(wordmarkFrames[0]);
    wordmarkTimerId = window.setInterval(function () {
      wordmarkFrameIndex = (wordmarkFrameIndex + 1) % wordmarkFrames.length;
      applyWordmarkFrame(wordmarkFrames[wordmarkFrameIndex]);
    }, 50);
  };

  startWordmarkLoop();

  const setOverlayVisibility = function (visible) {
    if (!overlay) {
      return;
    }
    overlay.hidden = !visible;
    document.body.classList.toggle("with-loading-overlay", visible);
    if (!visible) {
      overlay.classList.remove("loading-overlay--expanded");
      overlay.scrollTop = 0;
      lastOverlayDetailSignature = "";
      lastOverlayLogSignature = "";
    }
  };

  const syncOverlayExpandedState = function (resetScroll) {
    if (!overlay || !overlayExpanded) {
      return;
    }
    const expanded = !overlayExpanded.hidden;
    overlay.classList.toggle("loading-overlay--expanded", expanded);
    if (resetScroll && expanded) {
      window.requestAnimationFrame(function () {
        overlay.scrollTop = 0;
      });
    }
  };

  const formatEta = function (startedAt, percent) {
    if (!startedAt || !percent || percent < 12 || percent >= 100) {
      return percent >= 100 ? "Done" : "ETA still stabilizing";
    }

    const started = Date.parse(startedAt);
    if (Number.isNaN(started)) {
      return "ETA still stabilizing";
    }

    const elapsedSeconds = Math.max(1, Math.round((Date.now() - started) / 1000));
    const remainingSeconds = Math.max(0, Math.round((elapsedSeconds / (percent / 100)) - elapsedSeconds));
    if (remainingSeconds <= 10) {
      return "ETA under 10s";
    }
    if (remainingSeconds < 120) {
      return "ETA about " + remainingSeconds + "s";
    }
    return "ETA about " + Math.round(remainingSeconds / 60) + "m";
  };

  const appendKeyValueGrid = function (container, values) {
    const entries = Object.entries(values || {}).filter((entry) => {
      return entry[1] !== null && entry[1] !== undefined && String(entry[1]).trim() !== "";
    });
    if (!entries.length) {
      return;
    }

    const grid = document.createElement("div");
    grid.className = "loading-step-meta-grid";
    entries.forEach((entry) => {
      const item = document.createElement("div");
      item.className = "loading-step-meta-item";

      const label = document.createElement("span");
      label.className = "detail-label";
      label.textContent = entry[0].replace(/_/g, " ");

      const value = document.createElement("div");
      value.className = "path-text";
      value.textContent = String(entry[1]);

      item.appendChild(label);
      item.appendChild(value);
      grid.appendChild(item);
    });
    container.appendChild(grid);
  };

  const renderInlineEvents = function (container, events, emptyCopy) {
    const items = Array.isArray(events) ? events.slice().reverse() : [];
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "loading-inline-empty";
      empty.textContent = emptyCopy;
      container.appendChild(empty);
      return;
    }

    items.forEach((event) => {
      const row = document.createElement("div");
      row.className = "loading-inline-event";

      const head = document.createElement("strong");
      head.textContent = event.label || "Event";
      row.appendChild(head);

      if (event.timestamp_utc) {
        const stamp = document.createElement("div");
        stamp.className = "muted";
        stamp.textContent = event.timestamp_utc;
        row.appendChild(stamp);
      }
      if (event.detail) {
        const detail = document.createElement("div");
        detail.className = "path-text";
        detail.textContent = event.detail;
        row.appendChild(detail);
      }
      container.appendChild(row);
    });
  };

  const renderOverlaySteps = function (stepDetails, currentStepKey, payload) {
    if (!overlaySteps) {
      return;
    }
    overlaySteps.innerHTML = "";
    const items = Array.isArray(stepDetails) ? stepDetails : [];
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "loading-inline-empty";
      empty.textContent = "No step breakdown is available yet.";
      overlaySteps.appendChild(empty);
      return;
    }

    const availableKeys = items.map((item) => item.key);
    if (!selectedStepKey || availableKeys.indexOf(selectedStepKey) === -1) {
      selectedStepKey = currentStepKey || availableKeys[0];
    }

    items.forEach((step) => {
      const row = document.createElement("button");
      row.type = "button";
      row.className = "loading-step" + (step.key === selectedStepKey ? " loading-step--selected" : "");

      const copy = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = step.label || step.key || "Step";
      copy.appendChild(title);
      if (step.detail) {
        const detail = document.createElement("div");
        detail.className = "muted";
        detail.textContent = step.detail;
        copy.appendChild(detail);
      }

      const badge = document.createElement("span");
      badge.className = "badge " + (
        step.state === "done" ? "ok" : step.state === "active" ? "info" : "subtle"
      );
      badge.textContent = step.state || "pending";

      row.appendChild(copy);
      row.appendChild(badge);
      row.addEventListener("click", function () {
        selectedStepKey = step.key || "";
        renderOverlaySteps(items, currentStepKey, payload);
        renderOverlayStepDetail(items, payload);
      });
      overlaySteps.appendChild(row);
    });
  };

  const renderOverlayEvents = function (events) {
    if (!overlayEvents) {
      return;
    }
    overlayEvents.innerHTML = "";
    const items = (events || []).slice().reverse();
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "loading-event loading-event--empty";
      empty.textContent = "No framework events recorded yet.";
      overlayEvents.appendChild(empty);
      return;
    }
    items.forEach((event) => {
      const row = document.createElement("div");
      row.className = "loading-event";

      const stamp = document.createElement("span");
      stamp.className = "loading-event-time";
      stamp.textContent = event.timestamp_utc || "";

      const copy = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = event.label || "Event";
      copy.appendChild(title);
      if (event.detail) {
        const detail = document.createElement("div");
        detail.className = "muted";
        detail.textContent = event.detail;
        copy.appendChild(detail);
      }

      row.appendChild(stamp);
      row.appendChild(copy);
      overlayEvents.appendChild(row);
    });
  };

  const renderOverlayStepDetail = function (stepDetails, payload) {
    if (!overlayStepDetail) {
      return;
    }
    overlayStepDetail.innerHTML = "";
    const items = Array.isArray(stepDetails) ? stepDetails : [];
    const selected = items.find((item) => item.key === selectedStepKey) || items[0];
    if (!selected) {
      overlayStepDetail.textContent = "No step detail is available yet.";
      return;
    }

    const header = document.createElement("div");
    header.className = "loading-step-detail-header";

    const title = document.createElement("strong");
    title.textContent = selected.label || selected.key || "Step";
    header.appendChild(title);

    const badge = document.createElement("span");
    badge.className = "badge " + (
      selected.state === "done" ? "ok" : selected.state === "active" ? "info" : "subtle"
    );
    badge.textContent = selected.state || "pending";
    header.appendChild(badge);
    overlayStepDetail.appendChild(header);

    const detail = document.createElement("p");
    detail.className = "loading-step-detail-copy";
    detail.textContent = selected.detail || "No exact detail has been recorded for this step yet.";
    overlayStepDetail.appendChild(detail);

    if (selected.last_timestamp_utc || selected.last_label) {
      const latest = document.createElement("div");
      latest.className = "loading-step-latest";
      latest.textContent = selected.last_timestamp_utc
        ? selected.last_timestamp_utc + (selected.last_label ? " - " + selected.last_label : "")
        : selected.last_label;
      overlayStepDetail.appendChild(latest);
    }

    appendKeyValueGrid(
      overlayStepDetail,
      Object.assign(
        {},
        payload && payload.command_preview && !selected.meta.command ? { command: payload.command_preview } : {},
        selected.meta || {}
      )
    );

    const stepEventsHeading = document.createElement("span");
    stepEventsHeading.className = "detail-label";
    stepEventsHeading.textContent = "Step events";
    overlayStepDetail.appendChild(stepEventsHeading);

    const stepEvents = document.createElement("div");
    stepEvents.className = "loading-inline-event-list";
    renderInlineEvents(stepEvents, selected.events || [], "No step-specific events have been recorded yet.");
    overlayStepDetail.appendChild(stepEvents);

    if (selected.meta && selected.meta.child_status_url) {
      const nestedHeading = document.createElement("span");
      nestedHeading.className = "detail-label";
      nestedHeading.textContent = "Nested child status";
      overlayStepDetail.appendChild(nestedHeading);

      const nestedBox = document.createElement("div");
      nestedBox.className = "loading-nested-box";
      nestedBox.textContent = "Loading nested child progress...";
      overlayStepDetail.appendChild(nestedBox);

      const currentRequestId = ++nestedStepRequestId;
      fetch(selected.meta.child_status_url)
        .then(function (response) {
          if (!response.ok) {
            throw new Error("Nested status fetch failed");
          }
          return response.json();
        })
        .then(function (nestedPayload) {
          if (currentRequestId !== nestedStepRequestId) {
            return;
          }
          nestedBox.innerHTML = "";

          const nestedStatus = document.createElement("div");
          nestedStatus.className = "loading-nested-status";
          nestedStatus.textContent = (nestedPayload.status || "unknown") + (
            nestedPayload.progress && nestedPayload.progress.label
              ? " - " + nestedPayload.progress.label
              : ""
          );
          nestedBox.appendChild(nestedStatus);

          if (nestedPayload.progress && nestedPayload.progress.detail) {
            const nestedDetail = document.createElement("div");
            nestedDetail.className = "path-text";
            nestedDetail.textContent = nestedPayload.progress.detail;
            nestedBox.appendChild(nestedDetail);
          }

          if (selected.meta.child_result_url) {
            const link = document.createElement("a");
            link.href = selected.meta.child_result_url;
            link.textContent = "Open nested child page";
            nestedBox.appendChild(link);
          }

          appendKeyValueGrid(
            nestedBox,
            nestedPayload.command_preview ? { command: nestedPayload.command_preview } : {}
          );

          const nestedEvents = document.createElement("div");
          nestedEvents.className = "loading-inline-event-list";
          renderInlineEvents(
            nestedEvents,
            nestedPayload.progress ? nestedPayload.progress.events : [],
            "No nested child events have been recorded yet."
          );
          nestedBox.appendChild(nestedEvents);

          if (Array.isArray(nestedPayload.live_log_tail) && nestedPayload.live_log_tail.length) {
            const nestedLog = document.createElement("pre");
            nestedLog.className = "loading-nested-log";
            nestedLog.textContent = nestedPayload.live_log_tail.join("\n");
            nestedBox.appendChild(nestedLog);
          }
        })
        .catch(function () {
          if (currentRequestId !== nestedStepRequestId) {
            return;
          }
          nestedBox.textContent = "Nested child progress is not available yet.";
        });
    }
  };

  const renderOverlay = function (payload) {
    if (!overlay) {
      return;
    }
    const progress = payload && payload.progress ? payload.progress : {};
    const percent = typeof progress.percent === "number" ? progress.percent : 0;
    const status = payload && payload.status ? payload.status : "queued";
    const label = progress.label || "Preparing local run";
    const detail = progress.detail || "Waiting for the local record to report the next step.";

    if (overlayFill) {
      overlayFill.style.width = percent + "%";
    }
    if (overlayPercent) {
      overlayPercent.textContent = percent + "%";
    }
    if (overlayEta) {
      overlayEta.textContent = formatEta(payload ? payload.started_at_utc : "", percent);
    }
    if (overlayLabel) {
      overlayLabel.textContent = label;
    }
    if (overlayDetail) {
      overlayDetail.textContent = detail;
    }
    if (overlayStatus) {
      overlayStatus.textContent = status;
    }
    const stepDetails = Array.isArray(progress.step_details)
      ? progress.step_details
      : (progress.steps || []).map(function (step) {
          return Object.assign({}, step, { detail: "", events: [], meta: {} });
        });
    const detailSignature = JSON.stringify({
      step_key: progress.step_key || "",
      step_details: stepDetails,
      events: progress.events || []
    });
    if (detailSignature !== lastOverlayDetailSignature) {
      renderOverlaySteps(stepDetails, progress.step_key || "", payload);
      renderOverlayStepDetail(stepDetails, payload);
      renderOverlayEvents(progress.events || []);
      lastOverlayDetailSignature = detailSignature;
    }
    if (overlayLogTail) {
      const logLines = payload && Array.isArray(payload.live_log_tail) ? payload.live_log_tail : [];
      const logSignature = JSON.stringify(logLines);
      if (logSignature !== lastOverlayLogSignature) {
        overlayLogTail.textContent = logLines.length ? logLines.join("\n") : "No live log output yet.";
        lastOverlayLogSignature = logSignature;
      }
    }
  };

  if (overlayToggle && overlayExpanded) {
    overlayToggle.addEventListener("click", function () {
      const expanded = overlayToggle.getAttribute("aria-expanded") === "true";
      overlayToggle.setAttribute("aria-expanded", expanded ? "false" : "true");
      overlayExpanded.hidden = expanded;
      syncOverlayExpandedState(true);
      overlayToggle.textContent = expanded
        ? "Show exactly what the tool is doing"
        : "Hide the exact live detail";
    });
  }

  if (themeToggle) {
    themeToggle.addEventListener("click", function () {
      const nextTheme = rootElement.dataset.theme === "light" ? "dark" : "light";
      applyTheme(nextTheme);
      try {
        window.localStorage.setItem("sg-theme", nextTheme);
      } catch (_error) {
        return;
      }
    });
  }

  if (uiModeToggle) {
    uiModeToggle.addEventListener("click", function () {
      const nextMode = rootElement.dataset.uiMode === "clean" ? "cinematic" : "clean";
      applyUiMode(nextMode);
      try {
        window.localStorage.setItem("sg-ui-mode", nextMode);
      } catch (_error) {
        return;
      }
    });
  }

  if (guideToggle) {
    guideToggle.addEventListener("click", function () {
      const nextMode = document.body.dataset.guideMode === "off" ? "on" : "off";
      applyGuideMode(nextMode);
      try {
        window.localStorage.setItem("sg-guide-mode", nextMode);
      } catch (_error) {
        return;
      }
    });
  }

  const showLoadingOverlay = function (payload) {
    if (!overlay) {
      return;
    }
    renderOverlay(payload || { status: "queued", progress: { percent: 0, steps: [] } });
    setOverlayVisibility(true);
    syncOverlayExpandedState(false);
  };

  const hideLoadingOverlay = function () {
    setOverlayVisibility(false);
  };

  const updateStatusMessage = function (selector, label, detail) {
    const node = document.querySelector(selector);
    if (!node) {
      return;
    }
    node.textContent = detail ? label + ". " + detail : label;
  };

  const writeToClipboard = async function (text) {
    if (navigator.clipboard && window.isSecureContext) {
      await navigator.clipboard.writeText(text);
      return;
    }

    const helper = document.createElement("textarea");
    helper.value = text;
    helper.setAttribute("readonly", "true");
    helper.style.position = "absolute";
    helper.style.left = "-9999px";
    document.body.appendChild(helper);
    helper.select();
    document.execCommand("copy");
    document.body.removeChild(helper);
  };

  document.querySelectorAll(".copy-button").forEach((button) => {
    button.addEventListener("click", async function () {
      const targetId = button.getAttribute("data-copy-target");
      const source = targetId ? document.getElementById(targetId) : null;
      const text = source ? (source.value || source.textContent || "") : "";
      if (!text.trim()) {
        return;
      }

      const originalText = button.textContent;
      try {
        await writeToClipboard(text);
        button.textContent = "Copied";
        window.setTimeout(function () {
          button.textContent = originalText;
        }, 1400);
      } catch (_error) {
        button.textContent = "Copy failed";
        window.setTimeout(function () {
          button.textContent = originalText;
        }, 1800);
      }
    });
  });

  document.querySelectorAll(".review-decision-form").forEach((form) => {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();

      const ticketId = form.getAttribute("data-ticket-id") || "";
      const decisionKey = form.getAttribute("data-decision-key") || "";
      const title = form.getAttribute("data-decision-title") || "";
      const statusField = form.querySelector('select[name="status"]');
      const ownerField = form.querySelector('input[name="owner"]');
      const noteField = form.querySelector('textarea[name="note"]');
      const submitButton = form.querySelector('button[type="submit"]');
      if (!ticketId || !decisionKey || !statusField || !submitButton) {
        return;
      }

      const originalText = submitButton.textContent;
      submitButton.disabled = true;
      submitButton.textContent = "Saving...";
      try {
        const response = await fetch("/ui/api/review-decisions", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ticket_id: ticketId,
            decision_key: decisionKey,
            title: title,
            status: statusField.value,
            owner: ownerField ? ownerField.value : "",
            note: noteField ? noteField.value : ""
          })
        });
        if (!response.ok) {
          submitButton.textContent = "Save failed";
          window.setTimeout(function () {
            submitButton.disabled = false;
            submitButton.textContent = originalText;
          }, 1800);
          return;
        }

        submitButton.textContent = "Saved";
        window.setTimeout(function () {
          window.location.reload();
        }, 250);
      } catch (_error) {
        submitButton.textContent = "Save failed";
        window.setTimeout(function () {
          submitButton.disabled = false;
          submitButton.textContent = originalText;
        }, 1800);
      }
    });
  });

  document.querySelectorAll(".external-finding-form").forEach((form) => {
    form.addEventListener("submit", async function (event) {
      event.preventDefault();

      const ticketId = form.getAttribute("data-ticket-id") || "";
      const sourceField = form.querySelector('input[name="source"]');
      const reportedByField = form.querySelector('input[name="reported_by"]');
      const categoryField = form.querySelector('input[name="category"]');
      const typeField = form.querySelector('input[name="finding_type"]');
      const scopeField = form.querySelector('input[name="scope"]');
      const findingField = form.querySelector('textarea[name="finding"]');
      const ownerField = form.querySelector('input[name="owner"]');
      const statusField = form.querySelector('input[name="status"]');
      const relatedField = form.querySelector('input[name="related_investigation_surfaces"]');
      const noteField = form.querySelector('textarea[name="note"]');
      const submitButton = form.querySelector('button[type="submit"]');
      if (!ticketId || !sourceField || !reportedByField || !categoryField || !scopeField || !findingField || !submitButton) {
        return;
      }

      const originalText = submitButton.textContent;
      submitButton.disabled = true;
      submitButton.textContent = "Saving...";
      try {
        const response = await fetch("/ui/api/external-findings", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ticket_id: ticketId,
            source: sourceField.value,
            reported_by: reportedByField.value,
            category: categoryField.value,
            finding_type: typeField ? typeField.value : "",
            scope: scopeField.value,
            finding: findingField.value,
            owner: ownerField ? ownerField.value : "",
            status: statusField ? statusField.value : "",
            related_investigation_surfaces: relatedField ? relatedField.value : "",
            note: noteField ? noteField.value : ""
          })
        });
        if (!response.ok) {
          submitButton.textContent = "Save failed";
          window.setTimeout(function () {
            submitButton.disabled = false;
            submitButton.textContent = originalText;
          }, 1800);
          return;
        }

        submitButton.textContent = "Saved";
        window.setTimeout(function () {
          window.location.reload();
        }, 250);
      } catch (_error) {
        submitButton.textContent = "Save failed";
        window.setTimeout(function () {
          submitButton.disabled = false;
          submitButton.textContent = originalText;
        }, 1800);
      }
    });
  });

  const launchWithFeedback = async function (button, payloadBuilder, endpoint, startingCopy) {
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "Starting...";
    showLoadingOverlay({
      status: "queued",
      started_at_utc: new Date().toISOString(),
      progress: {
        percent: 3,
        label: startingCopy.label,
        detail: startingCopy.detail,
        steps: [],
        events: [
          {
            timestamp_utc: new Date().toISOString(),
            label: startingCopy.label,
            detail: startingCopy.detail
          }
        ]
      }
    });

    try {
      const response = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payloadBuilder())
      });

      if (!response.ok) {
        hideLoadingOverlay();
        button.textContent = "Start failed";
        window.setTimeout(function () {
          button.disabled = false;
          button.textContent = originalText;
        }, 1800);
        return;
      }

      const payload = await response.json();
      window.location.href = payload.result_url;
    } catch (_error) {
      hideLoadingOverlay();
      button.textContent = "Start failed";
      window.setTimeout(function () {
        button.disabled = false;
        button.textContent = originalText;
      }, 1800);
    }
  };

  document.querySelectorAll(".action-launch").forEach((button) => {
    button.addEventListener("click", async function () {
      const actionId = button.getAttribute("data-action-id");
      if (!actionId) {
        return;
      }
      await launchWithFeedback(
        button,
        function () {
          return { action_id: actionId };
        },
        "/ui/api/actions",
        {
          label: "Starting SG automation",
          detail: "Creating the local action record and opening the live status page."
        }
      );
    });
  });

  document.querySelectorAll(".guided-run-launch").forEach((button) => {
    button.addEventListener("click", async function () {
      const profileId = button.getAttribute("data-profile-id");
      const packsValue = button.getAttribute("data-packs") || "";
      const jobKey = button.getAttribute("data-job-key") || "";
      const jobLabel = button.getAttribute("data-job-label") || "";
      const stageKey = button.getAttribute("data-stage-key") || "";
      const stageLabel = button.getAttribute("data-stage-label") || "";
      if (!profileId) {
        return;
      }

      await launchWithFeedback(
        button,
        function () {
          return {
            profile_id: profileId,
            packs: packsValue.split(",").map((item) => item.trim()).filter(Boolean),
            fail_on: "never",
            context: {
              operator_job: jobKey,
              operator_job_label: jobLabel,
              workflow_stage: stageKey,
              workflow_stage_label: stageLabel
            }
          };
        },
        "/ui/api/runs",
        {
          label: "Starting recommended check",
          detail: "Creating the local run record and opening the live result page."
        }
      );
    });
  });

  const runForm = document.querySelector("#run-form");
  if (runForm) {
    runForm.addEventListener("submit", async function (event) {
      event.preventDefault();

      const profileId = runForm.getAttribute("data-profile-id");
      const launchStatus = document.querySelector("#launch-status");
      const submitButton = runForm.querySelector('button[type="submit"]');
      const selectedPacks = Array.from(runForm.querySelectorAll('input[name="packs"]:checked'))
        .map((item) => item.value);
      const context = {};
      Array.from(runForm.querySelectorAll('input[name^="context-"]')).forEach((input) => {
        const key = input.name.replace(/^context-/, "");
        context[key] = input.value;
      });

      if (submitButton) {
        submitButton.disabled = true;
      }
      if (launchStatus) {
        launchStatus.textContent = "Starting the quick check...";
      }
      showLoadingOverlay({
        status: "queued",
        started_at_utc: new Date().toISOString(),
        progress: {
          percent: 3,
          label: "Starting quick check",
          detail: "Creating the local run record and opening the live result page.",
          steps: [],
          events: [
            {
              timestamp_utc: new Date().toISOString(),
              label: "Starting quick check",
              detail: "Creating the local run record and opening the live result page."
            }
          ]
        }
      });

      try {
        const response = await fetch("/ui/api/runs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            profile_id: profileId,
            packs: selectedPacks,
            fail_on: runForm.querySelector('select[name="fail_on"]').value,
            context: context
          })
        });

        if (!response.ok) {
          hideLoadingOverlay();
          if (launchStatus) {
            launchStatus.textContent = "Could not start the check. Open the setup detail below and try again.";
          }
          if (submitButton) {
            submitButton.disabled = false;
          }
          return;
        }

        if (launchStatus) {
          launchStatus.textContent = "Opening the result page...";
        }
        const payload = await response.json();
        window.location.href = payload.result_url;
      } catch (_error) {
        hideLoadingOverlay();
        if (launchStatus) {
          launchStatus.textContent = "Could not start the check. Make sure the local UI server is still running.";
        }
        if (submitButton) {
          submitButton.disabled = false;
        }
      }
    });
  }

  document.querySelectorAll(".severity-filter").forEach((button) => {
    button.addEventListener("click", function () {
      const selected = button.getAttribute("data-severity-filter");
      document.querySelectorAll("[data-severity]").forEach((node) => {
        const severity = node.getAttribute("data-severity");
        node.setAttribute("data-hidden", String(selected !== "all" && severity !== selected));
      });
    });
  });

  const pollStatus = async function (url, options) {
    const response = await fetch(url);
    if (!response.ok) {
      return;
    }
    const payload = await response.json();
    const pill = document.querySelector(options.pillSelector);
    if (pill) {
      pill.textContent = payload.status;
    }

    if (payload.status === "running" || payload.status === "queued") {
      showLoadingOverlay(payload);
      updateStatusMessage(options.messageSelector, payload.progress && payload.progress.label ? payload.progress.label : payload.status, payload.progress && payload.progress.detail ? payload.progress.detail : "");
    }

    if (payload.status === "completed" || payload.status === "failed" || payload.status === "blocked") {
      hideLoadingOverlay();
      window.location.reload();
      return;
    }

    window.setTimeout(function () {
      pollStatus(url, options);
    }, 1500);
  };

  const runStatus = document.body.getAttribute("data-run-status");
  const runId = document.body.getAttribute("data-run-id");
  if (runId && runStatus && runStatus !== "completed" && runStatus !== "failed") {
    showLoadingOverlay({
      status: runStatus,
      progress: {
        percent: 0,
        label: runStatus === "running" ? "Loading live run status" : "Waiting in queue",
        detail: "Pulling the latest SG run progress from the local status record.",
        steps: [],
        events: []
      }
    });
    pollStatus("/ui/api/runs/" + runId, {
      pillSelector: "#run-status-pill",
      messageSelector: "#run-state-message"
    });
  }

  const actionStatus = document.body.getAttribute("data-action-status");
  const actionRunId = document.body.getAttribute("data-action-run-id");
  if (actionRunId && actionStatus && actionStatus !== "completed" && actionStatus !== "failed" && actionStatus !== "blocked") {
    showLoadingOverlay({
      status: actionStatus,
      progress: {
        percent: 0,
        label: actionStatus === "running" ? "Loading live action status" : "Waiting in queue",
        detail: "Pulling the latest automation progress from the local status record.",
        steps: [],
        events: []
      }
    });
    pollStatus("/ui/api/actions/" + actionRunId, {
      pillSelector: "#action-status-pill",
      messageSelector: "#action-state-message"
    });
  }
})();
