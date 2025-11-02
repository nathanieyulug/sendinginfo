document.addEventListener("DOMContentLoaded", () => {
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
  const downloadMessage = document.getElementById("download-message");

  // Optional controls
  const multiToggleBtn = document.getElementById("multi-toggle");
  const multiInputWrap = document.getElementById("multi-input-wrap");
  const maxDownloadsInput = document.getElementById("max-downloads");
  const agreeTermsCheckbox = document.getElementById("agree-terms");

  let selectedFile = null;
  let multiMode = false;

  // ✅ Handle missing elements safely
  if (!dropArea || !fileInput) return;

  // Toggle multi-mode
  multiToggleBtn?.addEventListener("click", () => {
    multiMode = !multiMode;
    if (multiMode) {
      multiInputWrap.classList.remove("hidden");
      multiToggleBtn.textContent = "Sharing with more people (click to undo)";
    } else {
      multiInputWrap.classList.add("hidden");
      multiToggleBtn.textContent = "Share with more people";
    }
  });

  // Open file picker
  dropArea.addEventListener("click", () => fileInput.click());

  // Handle manual file selection
  fileInput.addEventListener("change", (e) => {
    const file = e.target.files[0];
    if (file) showFile(file);
  });

  // Drag & Drop events
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

  // Upload
  uploadButton?.addEventListener("click", async () => {
    if (!selectedFile) return alert("Please select a file first!");
    if (!agreeTermsCheckbox?.checked) {
      alert("Please accept the Terms, Privacy Policy & Disclaimer before uploading.");
      return;
    }

    let maxDownloads = 1;
    if (multiMode) {
      const val = parseInt(maxDownloadsInput.value, 10);
      if (!isNaN(val) && val >= 1) maxDownloads = Math.min(val, 100);
    }

    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("max_downloads", String(maxDownloads));
    formData.append("agreed_terms", "true");

    uploadResult.textContent = "Uploading...";

    try {
      const response = await fetch("/upload", { method: "POST", body: formData });
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
      console.error(err);
      uploadResult.textContent = "⚠️ Upload failed. Please try again.";
    }
  });

  // Clear
  clearButton?.addEventListener("click", () => {
    fileInput.value = "";
    selectedFile = null;
    uploadControls.classList.add("hidden");
    uploadResult.textContent = "";
    dropText.textContent = "Drag & Drop or Click to Upload";
  });

  // Download file
  downloadButton?.addEventListener("click", async () => {
    const code = downloadCodeInput.value.trim();
    if (!code) {
      downloadMessage.textContent = "⚠️ Please enter a valid code!";
      downloadMessage.className = "text-yellow-500 text-center mt-2";
      return;
    }

    downloadMessage.textContent = "⏳ Checking code...";
    try {
      const response = await fetch(`/download/${code}`);
      if (response.ok) {
        const blob = await response.blob();
        const fileName = response.headers.get("Content-Disposition")
          ?.split("filename=")[1]
          ?.replace(/['"]/g, "")
          || "downloaded_file";
        const link = document.createElement("a");
        link.href = window.URL.createObjectURL(blob);
        link.download = fileName;
        link.click();
        downloadMessage.textContent = "✅ Download started!";
        downloadMessage.className = "text-green-600 text-center mt-2";
      } else {
        const err = await response.json();
        downloadMessage.textContent = "❌ " + (err.error || "Invalid or expired code!");
        downloadMessage.className = "text-red-500 text-center mt-2";
      }
    } catch (err) {
      console.error(err);
      downloadMessage.textContent = "⚠️ Something went wrong. Try again!";
      downloadMessage.className = "text-yellow-600 text-center mt-2";
    }
  });
});
