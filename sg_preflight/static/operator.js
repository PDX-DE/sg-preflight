(function () {
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

  const setOverlayVisibility = function (visible) {
    if (!overlay) {
      return;
    }
    overlay.hidden = !visible;
    document.body.classList.toggle("with-loading-overlay", visible);
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

  const renderOverlaySteps = function (steps) {
    if (!overlaySteps) {
      return;
    }
    overlaySteps.innerHTML = "";
    (steps || []).forEach((step) => {
      const row = document.createElement("div");
      row.className = "loading-step";

      const copy = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = step.label || step.key || "Step";
      copy.appendChild(title);

      const badge = document.createElement("span");
      badge.className = "badge " + (
        step.state === "done" ? "ok" : step.state === "active" ? "info" : "subtle"
      );
      badge.textContent = step.state || "pending";

      row.appendChild(copy);
      row.appendChild(badge);
      overlaySteps.appendChild(row);
    });
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
    renderOverlaySteps(progress.steps || []);
  };

  if (overlayToggle && overlayExpanded) {
    overlayToggle.addEventListener("click", function () {
      const expanded = overlayToggle.getAttribute("aria-expanded") === "true";
      overlayToggle.setAttribute("aria-expanded", expanded ? "false" : "true");
      overlayExpanded.hidden = expanded;
      overlayToggle.textContent = expanded
        ? "Show what is happening under the hood"
        : "Hide under-the-hood detail";
    });
  }

  const showLoadingOverlay = function (payload) {
    if (!overlay) {
      return;
    }
    renderOverlay(payload || { status: "queued", progress: { percent: 0, steps: [] } });
    setOverlayVisibility(true);
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
        steps: []
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
          steps: []
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
        steps: []
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
        steps: []
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
