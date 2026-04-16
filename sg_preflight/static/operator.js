(function () {
  const copyButtons = document.querySelectorAll(".copy-button");
  if (copyButtons.length) {
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

    copyButtons.forEach((button) => {
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
  }

  const actionButtons = document.querySelectorAll(".action-launch");
  if (actionButtons.length) {
    actionButtons.forEach((button) => {
      button.addEventListener("click", async function () {
        const actionId = button.getAttribute("data-action-id");
        if (!actionId) {
          return;
        }

        const originalText = button.textContent;
        button.disabled = true;
        button.textContent = "Starting...";

        try {
          const response = await fetch("/ui/api/actions", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action_id: actionId })
          });

          if (!response.ok) {
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
          button.textContent = "Start failed";
          window.setTimeout(function () {
            button.disabled = false;
            button.textContent = originalText;
          }, 1800);
        }
      });
    });
  }

  const guidedRunButtons = document.querySelectorAll(".guided-run-launch");
  if (guidedRunButtons.length) {
    guidedRunButtons.forEach((button) => {
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

        const originalText = button.textContent;
        button.disabled = true;
        button.textContent = "Starting...";

        try {
          const response = await fetch("/ui/api/runs", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              profile_id: profileId,
              packs: packsValue.split(",").map((item) => item.trim()).filter(Boolean),
              fail_on: "never",
              context: {
                operator_job: jobKey,
                operator_job_label: jobLabel,
                workflow_stage: stageKey,
                workflow_stage_label: stageLabel
              }
            })
          });

          if (!response.ok) {
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
          button.textContent = "Start failed";
          window.setTimeout(function () {
            button.disabled = false;
            button.textContent = originalText;
          }, 1800);
        }
      });
    });
  }

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
      launchStatus.textContent = "Starting the quick check...";

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
          launchStatus.textContent = "Could not start the check. Open the setup detail below and try again.";
          if (submitButton) {
            submitButton.disabled = false;
          }
          return;
        }

        launchStatus.textContent = "Opening the result page...";
        const payload = await response.json();
        window.location.href = payload.result_url;
      } catch (_error) {
        launchStatus.textContent = "Could not start the check. Make sure the local UI server is still running.";
        if (submitButton) {
          submitButton.disabled = false;
        }
      }
    });
  }

  const filterButtons = document.querySelectorAll(".severity-filter");
  if (filterButtons.length) {
    filterButtons.forEach((button) => {
      button.addEventListener("click", function () {
        const selected = button.getAttribute("data-severity-filter");
        document.querySelectorAll("[data-severity]").forEach((node) => {
          const severity = node.getAttribute("data-severity");
          node.setAttribute("data-hidden", String(selected !== "all" && severity !== selected));
        });
      });
    });
  }

  const runStatus = document.body.getAttribute("data-run-status");
  const runId = document.body.getAttribute("data-run-id");
  if (runId && runStatus && runStatus !== "completed" && runStatus !== "failed") {
    const poll = async function () {
      const response = await fetch("/ui/api/runs/" + runId);
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      const pill = document.querySelector("#run-status-pill");
      if (pill) {
        pill.textContent = payload.status;
      }
      if (payload.status === "completed" || payload.status === "failed") {
        window.location.reload();
        return;
      }
      window.setTimeout(poll, 1500);
    };
    window.setTimeout(poll, 1500);
  }

  const actionStatus = document.body.getAttribute("data-action-status");
  const actionRunId = document.body.getAttribute("data-action-run-id");
  if (actionRunId && actionStatus && actionStatus !== "completed" && actionStatus !== "failed" && actionStatus !== "blocked") {
    const pollAction = async function () {
      const response = await fetch("/ui/api/actions/" + actionRunId);
      if (!response.ok) {
        return;
      }
      const payload = await response.json();
      const pill = document.querySelector("#action-status-pill");
      if (pill) {
        pill.textContent = payload.status;
      }
      if (payload.status === "completed" || payload.status === "failed" || payload.status === "blocked") {
        window.location.reload();
        return;
      }
      window.setTimeout(pollAction, 1500);
    };
    window.setTimeout(pollAction, 1500);
  }
})();
