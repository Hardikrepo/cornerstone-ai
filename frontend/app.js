const API_BASE_URL = (window.APP_CONFIG && window.APP_CONFIG.apiBaseUrl) || "";

const STEP_ORDER = ["Upload", "Extract", "Classify", "Summarize"];
const STEP_STATUS_MESSAGE = {
  Extract: "Extracting text from the document...",
  Classify: "Classifying document type...",
  Summarize: "Summarizing and extracting key fields...",
};
const POLL_INTERVAL_MS = 2500;
const POLL_TIMEOUT_MS = 120000;

const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const fileChip = document.getElementById("file-chip");
const fileChipName = document.getElementById("file-chip-name");
const fileChipClear = document.getElementById("file-chip-clear");
const uploadBtn = document.getElementById("upload-btn");
const statusEl = document.getElementById("status");
const resetBtn = document.getElementById("reset-btn");

const uploadSection = document.getElementById("upload-section");
const progressSection = document.getElementById("progress-section");
const resultSection = document.getElementById("result-section");
const stepper = document.getElementById("stepper");

let selectedFile = null;

// ---------- file selection ----------

dropzone.addEventListener("click", () => fileInput.click());
dropzone.addEventListener("keydown", (e) => {
  if (e.key === "Enter" || e.key === " ") {
    e.preventDefault();
    fileInput.click();
  }
});

["dragenter", "dragover"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.add("drag-over");
  })
);
["dragleave", "drop"].forEach((evt) =>
  dropzone.addEventListener(evt, (e) => {
    e.preventDefault();
    dropzone.classList.remove("drag-over");
  })
);
dropzone.addEventListener("drop", (e) => {
  const file = e.dataTransfer.files[0];
  if (file) selectFile(file);
});

fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) selectFile(fileInput.files[0]);
});

fileChipClear.addEventListener("click", (e) => {
  e.stopPropagation();
  clearFile();
});

function selectFile(file) {
  selectedFile = file;
  fileChipName.textContent = `${file.name} (${formatBytes(file.size)})`;
  fileChip.classList.remove("hidden");
  uploadBtn.disabled = false;
}

function clearFile() {
  selectedFile = null;
  fileInput.value = "";
  fileChip.classList.add("hidden");
  uploadBtn.disabled = true;
}

function formatBytes(bytes) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

// ---------- pipeline run ----------

uploadBtn.addEventListener("click", runPipeline);
resetBtn.addEventListener("click", resetUI);

async function runPipeline() {
  if (!selectedFile) return;
  if (!API_BASE_URL) {
    showPanels({ progress: true });
    setStatus("API_BASE_URL isn't configured — see frontend/config.js.", true);
    return;
  }

  uploadBtn.disabled = true;
  showPanels({ progress: true });
  setStep("Upload", "active");

  try {
    setStatus("Requesting upload URL...");
    const { document_id, key, upload_url } = await createUploadUrl(selectedFile);

    setStatus("Uploading document...");
    await uploadFile(upload_url, selectedFile);
    setStep("Upload", "complete");

    setStatus("Starting pipeline...");
    await startProcessing(document_id, key);
    setStep("Extract", "active");

    const result = await pollForResult(document_id);

    STEP_ORDER.forEach((s) => setStep(s, "complete"));
    setStatus("Done.");
    renderResult(result);
    showPanels({ result: true });
  } catch (err) {
    console.error(err);
    setStatus(`Error: ${err.message}`, true);
  } finally {
    uploadBtn.disabled = false;
  }
}

function resetUI() {
  clearFile();
  STEP_ORDER.forEach((s) => setStep(s, "pending"));
  showPanels({ upload: true });
}

function showPanels({ upload = false, progress = false, result = false }) {
  uploadSection.classList.toggle("hidden", !upload);
  progressSection.classList.toggle("hidden", !progress);
  resultSection.classList.toggle("hidden", !result);
}

function setStatus(message, isError = false) {
  statusEl.textContent = message;
  statusEl.classList.toggle("status-error", isError);
}

function setStep(stepName, state) {
  const el = stepper.querySelector(`[data-step="${stepName}"]`);
  if (!el) return;
  el.classList.remove("is-active", "is-complete");
  if (state === "active") el.classList.add("is-active");
  if (state === "complete") el.classList.add("is-complete");
}

function applyCurrentStep(currentStep) {
  const idx = STEP_ORDER.indexOf(currentStep);
  if (idx === -1) return;
  STEP_ORDER.forEach((s, i) => {
    if (i < idx) setStep(s, "complete");
    else if (i === idx) setStep(s, "active");
    else setStep(s, "pending");
  });
}

// ---------- API calls ----------

async function createUploadUrl(file) {
  const res = await fetch(`${API_BASE_URL}/documents`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file.name, content_type: file.type || "application/pdf" }),
  });
  if (!res.ok) throw new Error(`Failed to get upload URL (${res.status})`);
  return res.json();
}

async function uploadFile(uploadUrl, file) {
  const res = await fetch(uploadUrl, {
    method: "PUT",
    headers: { "Content-Type": file.type || "application/pdf" },
    body: file,
  });
  if (!res.ok) throw new Error(`Upload to S3 failed (${res.status})`);
}

async function startProcessing(documentId, key) {
  const res = await fetch(`${API_BASE_URL}/documents/${documentId}/process`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ key }),
  });
  if (!res.ok) throw new Error(`Failed to start processing (${res.status})`);
  return res.json();
}

async function pollForResult(documentId) {
  const deadline = Date.now() + POLL_TIMEOUT_MS;

  while (Date.now() < deadline) {
    const res = await fetch(`${API_BASE_URL}/documents/${documentId}`);
    if (!res.ok) throw new Error(`Status check failed (${res.status})`);
    const data = await res.json();

    if (data.status === "complete") return data.result;
    if (data.status === "failed") throw new Error(data.cause || "Pipeline failed");

    if (data.current_step) {
      applyCurrentStep(data.current_step);
      setStatus(STEP_STATUS_MESSAGE[data.current_step] || "Processing...");
    }

    await sleep(POLL_INTERVAL_MS);
  }

  throw new Error("Timed out waiting for the pipeline to finish");
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ---------- result rendering ----------

function renderResult(result) {
  document.getElementById("doc-type").textContent = result.classification.document_type.replace(/_/g, " ");
  document.getElementById("confidence").textContent = `${result.classification.confidence} confidence`;
  document.getElementById("summary-text").textContent = result.summary.summary;
  document.getElementById("review-status").textContent = result.review_status.replace(/_/g, " ");

  const keyFields = document.getElementById("key-fields");
  keyFields.innerHTML = "";
  const entries = Object.entries(result.summary.key_fields || {});
  if (entries.length === 0) {
    keyFields.innerHTML = `<div><dt>&nbsp;</dt><dd>No structured fields extracted.</dd></div>`;
  } else {
    for (const [field, value] of entries) {
      const wrapper = document.createElement("div");
      const dt = document.createElement("dt");
      dt.textContent = field.replace(/_/g, " ");
      const dd = document.createElement("dd");
      dd.textContent = value;
      wrapper.append(dt, dd);
      keyFields.appendChild(wrapper);
    }
  }

  const flagsList = document.getElementById("flags-list");
  flagsList.innerHTML = "";
  const flags = result.summary.flags || [];
  if (flags.length === 0) {
    const li = document.createElement("li");
    li.textContent = "No issues flagged for review.";
    li.className = "flags-empty";
    flagsList.appendChild(li);
  } else {
    for (const flag of flags) {
      const li = document.createElement("li");
      li.textContent = flag;
      flagsList.appendChild(li);
    }
  }
}
