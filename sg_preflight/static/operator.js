(function () {
  const runForm = document.querySelector("#run-form");
  if (runForm) {
    runForm.addEventListener("submit", async function (event) {
      event.preventDefault();

      const profileId = runForm.getAttribute("data-profile-id");
      const launchStatus = document.querySelector("#launch-status");
      const selectedPacks = Array.from(runForm.querySelectorAll('input[name="packs"]:checked'))
        .map((item) => item.value);
      const context = {};
      Array.from(runForm.querySelectorAll('input[name^="context-"]')).forEach((input) => {
        const key = input.name.replace(/^context-/, "");
        context[key] = input.value;
      });

      launchStatus.textContent = "Launching...";

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
        launchStatus.textContent = "Launch failed";
        return;
      }

      const payload = await response.json();
      window.location.href = payload.result_url;
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
})();
