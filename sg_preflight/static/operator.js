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
  const themeToggle = document.getElementById("theme-toggle");
  const guideToggle = document.getElementById("guide-toggle");
  let selectedStepKey = "";
  let nestedStepRequestId = 0;

  const applyTheme = function (theme) {
    const resolved = theme === "light" ? "light" : "dark";
    rootElement.dataset.theme = resolved;
    if (themeToggle) {
      const usingLight = resolved === "light";
      themeToggle.setAttribute("aria-pressed", usingLight ? "false" : "true");
      themeToggle.textContent = usingLight ? "Dark mode" : "Light mode";
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
    applyTheme(window.localStorage.getItem("sg-theme") || rootElement.dataset.theme || "dark");
    applyGuideMode(window.localStorage.getItem("sg-guide-mode") || document.body.dataset.guideMode || "on");
  } catch (_error) {
    applyTheme(rootElement.dataset.theme || "dark");
    applyGuideMode(document.body.dataset.guideMode || "on");
  }

  const setOverlayVisibility = function (visible) {
    if (!overlay) {
      return;
    }
    overlay.hidden = !visible;
    document.body.classList.toggle("with-loading-overlay", visible);
    if (!visible) {
      overlay.classList.remove("loading-overlay--expanded");
      overlay.scrollTop = 0;
    }
  };

  const syncOverlayExpandedState = function () {
    if (!overlay || !overlayExpanded) {
      return;
    }
    const expanded = !overlayExpanded.hidden;
    overlay.classList.toggle("loading-overlay--expanded", expanded);
    if (expanded) {
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
    renderOverlaySteps(stepDetails, progress.step_key || "", payload);
    renderOverlayStepDetail(stepDetails, payload);
    renderOverlayEvents(progress.events || []);
    if (overlayLogTail) {
      const logLines = payload && Array.isArray(payload.live_log_tail) ? payload.live_log_tail : [];
      overlayLogTail.textContent = logLines.length ? logLines.join("\n") : "No live log output yet.";
    }
  };

  if (overlayToggle && overlayExpanded) {
    overlayToggle.addEventListener("click", function () {
      const expanded = overlayToggle.getAttribute("aria-expanded") === "true";
      overlayToggle.setAttribute("aria-expanded", expanded ? "false" : "true");
      overlayExpanded.hidden = expanded;
      syncOverlayExpandedState();
      overlayToggle.textContent = expanded
        ? "Show exact live detail"
        : "Hide exact live detail";
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
    syncOverlayExpandedState();
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
    window.setTimeout(function () {
      pollStatus("/ui/api/runs/" + runId, {
        pillSelector: "#run-status-pill",
        messageSelector: "#run-state-message"
      });
    }, 600);
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
    window.setTimeout(function () {
      pollStatus("/ui/api/actions/" + actionRunId, {
        pillSelector: "#action-status-pill",
        messageSelector: "#action-state-message"
      });
    }, 600);
  }
})();
