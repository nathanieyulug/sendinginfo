const createBtn = document.getElementById("create-paste");
const resultEl = document.getElementById("paste-result");
const toggleViewsBtn = document.getElementById("toggle-views");
const viewsWrap = document.getElementById("views-wrap");
const maxViewsInput = document.getElementById("max-views");
const openBtn = document.getElementById("open-paste");
const openRawBtn = document.getElementById("open-raw");
const pasteCodeInput = document.getElementById("paste-code");

let showViews = false;

// toggle input visibility
toggleViewsBtn.addEventListener("click", () => {
  showViews = !showViews;
  viewsWrap.classList.toggle("hidden", !showViews);
});

// create new paste
createBtn.addEventListener("click", async () => {
  const content = document.getElementById("paste-content").value.trim();
  const lang = document.getElementById("lang-select").value;
  const maxViews = parseInt(maxViewsInput.value) || 1;

  if (!content) {
    resultEl.textContent = "⚠️ Please enter some text before generating.";
    resultEl.className = "mt-2 text-red-500";
    return;
  }

  resultEl.textContent = "⏳ Generating...";
  resultEl.className = "mt-2 text-gray-700";

  try {
    const res = await fetch("/create_paste", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ content, lang, max_views: maxViews }),
    });

    const data = await res.json();

    if (res.ok) {
      resultEl.innerHTML = `
        ✅ <b>${data.message}</b><br>
        🔑 Your Code: <b>${data.code}</b><br>
        👥 Max Views: <b>${data.max_views}</b><br><br>
        <a href="/view/${data.code}" target="_blank" class="text-purple-600 underline">Open Formatted View</a><br>
        <a href="/raw/${data.code}" target="_blank" class="text-purple-600 underline">Open Raw Text</a>
      `;
      resultEl.className = "mt-2 text-green-600";
    } else {
      resultEl.textContent = "❌ " + (data.error || "Failed to create paste.");
      resultEl.className = "mt-2 text-red-500";
    }
  } catch (err) {
    console.error(err);
    resultEl.textContent = "⚠️ Network error.";
    resultEl.className = "mt-2 text-yellow-600";
  }
});

// open paste in formatted view
openBtn.addEventListener("click", () => {
  const code = pasteCodeInput.value.trim();
  if (!code) {
    alert("Please enter a valid code!");
    return;
  }
  window.open(`/view/${code}`, "_blank");
});

// open paste in raw view
openRawBtn.addEventListener("click", () => {
  const code = pasteCodeInput.value.trim();
  if (!code) {
    alert("Please enter a valid code!");
    return;
  }
  window.open(`/raw/${code}`, "_blank");
});
