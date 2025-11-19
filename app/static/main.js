document.addEventListener("DOMContentLoaded", () => {
  const uploadBtn = document.getElementById("uploadBtn");
  const retryBtn = document.getElementById("retryBtn");
  const stopPollingBtn = document.getElementById("stopPollingBtn");
  const fileInput = document.getElementById("csvFile");
  const bar = document.getElementById("bar");
  const status = document.getElementById("status");
  const taskDetails = document.getElementById("task-details");
  const filterForm = document.getElementById("productFilters");
  const resetFiltersBtn = document.getElementById("resetFilters");

  let pollInterval = null;
  let currentTaskId = null;
  let lastFile = null;

  const setStatus = (text, variant = "") => {
    if (!status) return;
    status.textContent = text;
    status.classList.remove("success", "error");
    if (variant) {
      status.classList.add(variant);
    }
  };

  const setProgress = (percent = 0) => {
    if (bar) {
      bar.style.width = `${Math.min(Math.max(percent, 0), 100)}%`;
    }
  };

  const stopPolling = (message) => {
    if (pollInterval) {
      clearInterval(pollInterval);
      pollInterval = null;
    }
    currentTaskId = null;
    if (stopPollingBtn) {
      stopPollingBtn.hidden = true;
    }
    if (message) {
      setStatus(message);
    }
  };

  const refreshProducts = () => {
    if (window.htmx) {
      htmx.ajax("GET", "/products-fragment", "#products-list");
    }
  };

  const startPolling = (taskId) => {
    stopPolling();
    currentTaskId = taskId;
    if (stopPollingBtn) {
      stopPollingBtn.hidden = false;
    }
    pollInterval = setInterval(async () => {
      try {
        const response = await fetch(`/task-status/${taskId}`);
        if (!response.ok) throw new Error("Failed to fetch status");
        const data = await response.json();
        const percent = data.percent ?? null;
        const processed = data.processed ?? 0;
        const total = data.total ?? 0;
        const invalid = data.invalid ?? 0;
        const statusText = data.status || "processing";

        if (percent !== null) {
          setProgress(percent);
          setStatus(`${statusText} (${percent}% complete)`);
        } else {
          setStatus(`${statusText} — processed ${processed}`);
          setProgress(95);
        }

        if (taskDetails) {
          taskDetails.innerHTML = `
            <p><strong>Processed:</strong> ${processed}${total ? ` / ${total}` : ""}</p>
            <p><strong>Invalid rows skipped:</strong> ${invalid}</p>
          `;
        }

        if (data.error || (statusText && statusText.toLowerCase().startsWith("error"))) {
          stopPolling(`Error: ${data.error || statusText}`);
          if (retryBtn) retryBtn.hidden = !lastFile;
        }

        if (statusText.toLowerCase() === "complete") {
          stopPolling("Import complete");
          setProgress(100);
          refreshProducts();
          if (retryBtn) retryBtn.hidden = true;
        }
      } catch (err) {
        console.error(err);
        stopPolling("Could not fetch progress");
        if (retryBtn) retryBtn.hidden = !lastFile;
      }
    }, 1500);
  };

  const uploadFile = (file) => {
    if (!file) return;
    lastFile = file;
    setStatus("Uploading…");
    setProgress(0);
    if (taskDetails) taskDetails.innerHTML = "";
    if (retryBtn) retryBtn.hidden = true;

    const form = new FormData();
    form.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/upload");

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        const percent = Math.round((event.loaded / event.total) * 100);
        setProgress(percent);
        setStatus(`Uploading ${percent}%`);
      }
    };

    xhr.onload = () => {
      if (xhr.status === 200) {
        const payload = JSON.parse(xhr.responseText);
        setStatus("Upload complete. Importing…");
        startPolling(payload.task_id);
      } else {
        setStatus("Upload failed", "error");
        if (retryBtn) retryBtn.hidden = !lastFile;
      }
    };

    xhr.onerror = () => {
      setStatus("Upload error", "error");
      if (retryBtn) retryBtn.hidden = !lastFile;
    };

    xhr.send(form);
  };

  if (uploadBtn) {
    uploadBtn.addEventListener("click", () => {
      const file = fileInput?.files?.[0];
      if (!file) {
        setStatus("Please choose a CSV file", "error");
        return;
      }
      uploadFile(file);
    });
  }

  if (retryBtn) {
    retryBtn.addEventListener("click", () => {
      if (lastFile) {
        uploadFile(lastFile);
      }
    });
  }

  if (stopPollingBtn) {
    stopPollingBtn.addEventListener("click", () => stopPolling("Polling stopped"));
  }

  if (resetFiltersBtn && filterForm) {
    resetFiltersBtn.addEventListener("click", () => {
      filterForm.reset();
      const perPage = filterForm.querySelector('[name="per_page"]');
      if (perPage) perPage.value = "20";
      const statusSelect = filterForm.querySelector('[name="filter_active"]');
      if (statusSelect) statusSelect.value = "all";
      if (window.htmx) {
        htmx.ajax("GET", "/products-fragment", "#products-list");
      }
    });
  }
});
