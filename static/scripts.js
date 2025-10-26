const dropArea = document.getElementById("drop-area");
const fileInput = document.getElementById("file-input");
const uploadButton = document.getElementById("upload-button");
const clearButton = document.getElementById("clear-button");
const uploadControls = document.getElementById("upload-controls");
const uploadResult = document.getElementById("upload-result");
const selectedFileText = document.getElementById("selected-file");
const dropText = document.getElementById("drop-text");

const downloadButton = document.getElementById("download-button");
const downloadCodeInput = document.getElementById("download-code");

// NEW controls
const multiToggleBtn = document.getElementById("multi-toggle");
const multiInputWrap = document.getElementById("multi-input-wrap");
const maxDownloadsInput = document.getElementById("max-downloads");
const agreeTermsCheckbox = document.getElementById("agree-terms");

let selectedFile = null;
let multiMode = false; // false = single share (1); true = allow multiple

// Toggle "share with more people" input
multiToggleBtn.addEventListener("click", () => {
  multiMode = !multiMode;
  if (multiMode) {
    multiInputWrap.classList.remove("hidden");
    multiToggleBtn.textContent = "Sharing with more people (click to undo)";
  } else {
    multiInputWrap.classList.add("hidden");
    multiToggleBtn.textContent = "Share with more people";
  }
});

// Open file picker when clicking drop-area
dropArea.addEventListener("click", () => fileInput.click());

// File selected manually
fileInput.addEventListener("change", (e) => {
  const file = e.target.files[0];
  if (file) showFile(file);
});

// Drag & drop behaviors
dropArea.addEventListener("dragover", (e) => {
  e.preventDefault();
  dropArea.classList.add("border-purple-600");
});
dropArea.addEventListener("dragleave", () => {
  dropArea.classList.remove("border-purple-600");
});
dropArea.addEventListener("drop", (e) => {
  e.preventDefault();
  dropArea.classList.remove("border-purple-600");
  const file = e.dataTransfer.files[0];
  if (file) showFile(file);
});

function showFile(file) {
  selectedFile = file;
  selectedFileText.textContent = "Selected: " + file.name;
  uploadControls.classList.remove("hidden");
  dropText.textContent = "File Ready to Upload ✅";
}

// Upload logic
uploadButton.addEventListener("click", async () => {
  if (!selectedFile) return alert("Please select a file first!");
  if (!agreeTermsCheckbox.checked) {
    alert("Please accept the Terms, Privacy Policy & Disclaimer before uploading.");
    return;
  }

  // Determine max downloads
  let maxDownloads = 1;
  if (multiMode) {
    const val = parseInt(maxDownloadsInput.value, 10);
    if (!isNaN(val) && val >= 1) {
      maxDownloads = Math.min(val, 100); // safety cap
    }
  }

  const formData = new FormData();
  formData.append("file", selectedFile);
  formData.append("max_downloads", String(maxDownloads));
  formData.append("agreed_terms", "true");

  uploadResult.textContent = "Uploading...";

  try {
    const response = await fetch("/upload", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();

    if (data.error) {
      uploadResult.textContent = "❌ " + data.error;
    } else {
      uploadResult.innerHTML = `
        ✅ ${data.message}<br>
        🔑 Download Code: <b>${data.code}</b><br>
        👥 Allowed Downloads: <b>${data.max_downloads}</b><br>
        ⏳ Expires in: <b>${data.expires_in_hours} hours</b><br>
        📎 <a href="/download/${data.code}" class="text-purple-600 underline">Click here to test download</a>
      `;
    }
  } catch (err) {
    uploadResult.textContent = "⚠️ Upload failed. Please try again.";
  }
});

// Clear selection
clearButton.addEventListener("click", () => {
  fileInput.value = "";
  selectedFile = null;
  uploadControls.classList.add("hidden");
  uploadResult.textContent = "";
  dropText.textContent = "Drag & Drop or Click to Upload";
  // reset multi mode UI (but keep your choice if you prefer)
  // multiMode = false; multiInputWrap.classList.add("hidden"); multiToggleBtn.textContent = "Share with more people";
});

// Download by code
downloadButton.addEventListener("click", () => {
  const code = downloadCodeInput.value.trim();
  if (!code) return alert("Please enter a valid code!");
  window.location.href = `/download/${code}`;
});
