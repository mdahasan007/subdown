const $ = (id) => document.getElementById(id);
let video = null, activeKind = "manual", selected = null;
$("year").textContent = new Date().getFullYear();
$("themeToggle").addEventListener("click", () => document.body.classList.toggle("light"));
function showError(message) { $("errorBox").textContent = message; $("errorBox").classList.remove("hidden"); }
function hideError() { $("errorBox").classList.add("hidden"); }
function setBusy(busy) { $("loading").classList.toggle("hidden", !busy); $("submitBtn").disabled = busy; $("submitBtn").querySelector("span").textContent = busy ? "Checking..." : "Find subtitles"; }
function duration(seconds) {
  if (!Number.isFinite(seconds)) return "Duration unavailable";
  const h = Math.floor(seconds / 3600), m = Math.floor(seconds % 3600 / 60), s = Math.floor(seconds % 60);
  return [h,m,s].map((n,i) => i === 0 && n === 0 ? null : String(n).padStart(2,"0")).filter(Boolean).join(":") || "00:00";
}
function tracks() { return (video && video[activeKind]) || []; }
function renderTracks() {
  const list = $("languageList"); list.replaceChildren(); selected = null;
  $("selectedName").textContent = "Select a language"; $("downloadBtn").disabled = true;
  const items = tracks(); $("emptyTracks").classList.toggle("hidden", items.length > 0);
  items.forEach((item) => {
    const label = document.createElement("label"); label.className = "language";
    const radio = document.createElement("input"); radio.type = "radio"; radio.name = "language"; radio.value = item.code;
    const name = document.createElement("span"); name.className = "lang-name"; name.textContent = item.name;
    const code = document.createElement("span"); code.className = "lang-code"; code.textContent = item.code;
    label.append(radio, name, code);
    label.addEventListener("click", () => {
      document.querySelectorAll(".language").forEach(el => el.classList.remove("selected"));
      label.classList.add("selected"); selected = item; $("selectedName").textContent = item.name; $("downloadBtn").disabled = false;
    });
    list.append(label);
  });
  $("trackCount").textContent = `${(video.manual?.length || 0) + (video.automatic?.length || 0)} TRACKS`;
}
document.querySelectorAll(".tab").forEach(tab => tab.addEventListener("click", () => {
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  tab.classList.add("active"); activeKind = tab.dataset.kind; renderTracks();
}));
$("inspectForm").addEventListener("submit", async (event) => {
  event.preventDefault(); hideError(); $("result").classList.add("hidden"); setBusy(true);
  try {
    const response = await fetch("/api/inspect", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:$("videoUrl").value.trim()})});
    const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Could not inspect this video.");
    video = data; $("videoTitle").textContent = data.title;
    $("videoMeta").textContent = `${data.uploader || "Video"} · ${duration(data.duration)}`;
    $("extractor").textContent = data.extractor.toUpperCase();
    const thumb = $("thumbnail");
    if (data.thumbnail) { thumb.src = data.thumbnail; thumb.classList.remove("hidden"); }
    else { thumb.classList.add("hidden"); thumb.removeAttribute("src"); }
    $("manualCount").textContent = data.manual.length; $("autoCount").textContent = data.automatic.length;
    activeKind = data.manual.length ? "manual" : "automatic";
    document.querySelectorAll(".tab").forEach(t => t.classList.toggle("active", t.dataset.kind === activeKind));
    $("result").classList.remove("hidden"); renderTracks(); $("result").scrollIntoView({behavior:"smooth",block:"start"});
  } catch (error) { showError(error.message); } finally { setBusy(false); }
});
$("downloadBtn").addEventListener("click", async () => {
  if (!selected) return;
  const btn = $("downloadBtn"); btn.disabled = true; btn.innerHTML = "Preparing...";
  try {
    const response = await fetch("/api/download", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({url:$("videoUrl").value.trim(),language:selected.code,kind:activeKind,format:$("format").value})});
    if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.detail || "Download failed."); }
    const blob = await response.blob(), objectUrl = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = objectUrl;
    a.download = `subtitle-${selected.code}.${$("format").value === "raw" ? selected.ext : $("format").value}`;
    document.body.append(a); a.click(); a.remove(); URL.revokeObjectURL(objectUrl);
  } catch (error) { showError(error.message); }
  finally { btn.disabled = !selected; btn.innerHTML = 'Download <span>↓</span>'; }
});
