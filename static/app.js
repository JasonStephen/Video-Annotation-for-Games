const $ = (id) => document.getElementById(id);

let currentVideoId = null;
let meta = { fps: null, duration: null };
let segStartSec = null;
let segEndSec = null;

function mmss(sec) {
  sec = Math.max(0, sec || 0);
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60);
  return String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
}

async function refresh() {
  const res = await fetch(`/api/videos/${currentVideoId}`);
  const data = await res.json();
  if (!data.ok) return;

  const v = data.video;
  const anns = data.annotations;

  meta.fps = v.fps;
  meta.duration = v.duration;

  const seg = anns.filter(a => a.type === "segmentation");
  const obs = anns.filter(a => a.type === "observation");

  const segList = $("segList");
  segList.innerHTML = "";
  seg.forEach((a, idx) => {

    const div = document.createElement("div");
    div.className = "item";

    div.innerHTML = `
      <div class="title">
        S${idx+1} ${mmss(a.t_start)}–${mmss(a.t_end)}
      </div>

      <div class="row">
        <button class="jumpStart">▶Start</button>
        <button class="jumpEnd">▶End</button>
      </div>
      <div class="meta">主导机制：${a.dominant_category || ""}｜决策：${a.core_decision || ""}｜风险：${a.risk || ""}</div>

      <div class="row">
        <button class="up">↑</button>
        <button class="down">↓</button>
        <button class="edit">Edit</button>
        <button data-id="${a.id}" class="danger">删除</button>
      </div>
    `;

    div.querySelector(".title").onclick = ()=>{
      $("video").currentTime = a.t_start;
    };

    div.querySelector(".jumpStart").onclick = () => {
      const video = $("video");
      video.currentTime = a.t_start;
    };

    div.querySelector(".jumpEnd").onclick = () => {
      const video = $("video");
      video.currentTime = a.t_end;
    };

    div.querySelector(".up").onclick = () => move(idx, -1);
    div.querySelector(".down").onclick = () => move(idx, 1);

    div.querySelector(".edit").onclick = () => {

      editingId = a.id;

      $("editStart").value = mmss(a.t_start);
      $("editEnd").value = mmss(a.t_end);
      $("editDominant").value = a.dominant_category || "";
      $("editDecision").value = a.core_decision || "";
      $("editRisk").value = a.risk || "";

      $("editModal").classList.remove("hidden");
    };

    div.querySelector(".danger").onclick = async () => {
      await fetch(`/api/annotations/${a.id}`, { method: "DELETE" });
      refresh();
    };

    segList.appendChild(div);
  });

  const obsList = $("obsList");
  obsList.innerHTML = "";
  obs.forEach((a) => {
    const div = document.createElement("div");
    div.className = "item";
    div.innerHTML = `
      <div class="title">${mmss(a.t_start)} ${a.note || ""}</div>
      <button data-id="${a.id}" class="danger">删除</button>
    `;
    div.querySelector("button").onclick = async () => {
      await fetch(`/api/annotations/${a.id}`, { method: "DELETE" });
      refresh();
    };
    obsList.appendChild(div);
  });

  $("exportSeg").href = `/export/${currentVideoId}/segmentation.csv`;
  $("exportObs").href = `/export/${currentVideoId}/observations.csv`;

  $("dataCard").classList.remove("hidden");
}

async function upload(file) {
  const fd = new FormData();
  fd.append("file", file);
  const fps = $("fps").value.trim();
  if (fps) fd.append("fps", fps);

  const res = await fetch(`/projects/${window.PROJECT_ID}/upload`, {
    method: "POST",
    body: fd
  });
  const data = await res.json();
  if (!data.ok) {
    alert(data.error || "上传失败");
    return;
  }
  // 直接跳转刷新页面以更新下拉框（简单粗暴）
  location.reload();
}

function bindUploadUI() {
  const drop = $("drop");
  const fileInput = $("file");

  drop.addEventListener("dragover", (e) => {
    e.preventDefault();
    drop.classList.add("hover");
  });
  drop.addEventListener("dragleave", () => drop.classList.remove("hover"));
  drop.addEventListener("drop", (e) => {
    e.preventDefault();
    drop.classList.remove("hover");
    const f = e.dataTransfer.files?.[0];
    if (f) upload(f);
  });

  $("uploadBtn").onclick = () => {
    const f = fileInput.files?.[0];
    if (!f) return alert("请选择文件");
    upload(f);
  };
}

function bindPlayer() {
  const sel = $("videoSelect");
  const video = $("video");
  const scrub = $("scrub");

  sel.onchange = async () => {
    currentVideoId = sel.value ? Number(sel.value) : null;
    if (!currentVideoId) return;

    // 取视频元数据
    const res = await fetch(`/api/videos/${currentVideoId}`);
    const data = await res.json();
    if (!data.ok) return;

    // 让视频 src 指向上传目录
    video.src = `/media/${data.video.filename}`;
    $("playerCard").classList.remove("hidden");

    // 等 metadata
    video.onloadedmetadata = async () => {
      $("dur").textContent = mmss(video.duration);
      // 更新后端 duration（fps 若为空保留）
      await fetch(`/api/videos/${currentVideoId}/update_meta`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          fps: data.video.fps,
          duration: video.duration
        })
      });

      scrub.value = 0;
      refresh();
    };

    video.ontimeupdate = () => {
      $("now").textContent = mmss(video.currentTime);
      if (video.duration && video.duration > 0) {
        scrub.value = Math.floor((video.currentTime / video.duration) * 1000);
      }
    };

    scrub.oninput = () => {
      if (!video.duration) return;
      const t = (Number(scrub.value) / 1000) * video.duration;
      video.currentTime = t;
    };
  };

  $("setStart").onclick = () => {
    segStartSec = video.currentTime;
    $("segStart").textContent = mmss(segStartSec);

    // 自动填充输入框
    $("segStartInput").value = mmss(segStartSec);
  };

  $("setEnd").onclick = () => {
    segEndSec = video.currentTime;
    $("segEnd").textContent = mmss(segEndSec);

    // 自动填充输入框
    $("segEndInput").value = mmss(segEndSec);
  };

  // 手动输入时间 → 自动跳转视频
  $("segStartInput").onchange = ()=>{
    const t = parseTime($("segStartInput").value);
    if(t!=null) video.currentTime = t;
  };

  $("segEndInput").onchange = ()=>{
    const t = parseTime($("segEndInput").value);
    if(t!=null) video.currentTime = t;
  };

  $("addSeg").onclick = async () => {

    let start = segStartSec;
    let end = segEndSec;

    // 如果手动输入时间
    const startInput = $("segStartInput").value.trim();
    const endInput = $("segEndInput").value.trim();

    if(startInput){
      const t = parseTime(startInput);
      if(t === null) return alert("开始时间格式错误，应为 mm:ss");
      start = t;
    }

    if(endInput){
      const t = parseTime(endInput);
      if(t === null) return alert("结束时间格式错误，应为 mm:ss");
      end = t;
    }

    if(start == null || end == null)
      return alert("请设置开始和结束时间");

    if(end < start)
      return alert("结束时间不能早于开始时间");

    const payload = {
      type: "segmentation",
      t_start: start,
      t_end: end,
      dominant_category: $("dominant").value,
      core_decision: $("decision").value,
      risk: $("risk").value
    };

    const res = await fetch(`/api/videos/${currentVideoId}/annotations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    const data = await res.json();

    if (!data.ok)
      return alert(data.error || "添加失败");

    // 清理输入
    $("dominant").value = "";
    $("decision").value = "";
    $("risk").value = "";
    $("segStartInput").value = "";
    $("segEndInput").value = "";

    segStartSec = null;
    segEndSec = null;

    $("segStart").textContent = "--:--";
    $("segEnd").textContent = "--:--";

    refresh();
  };

  $("addObs").onclick = async () => {
    const note = $("note").value.trim();
    if (!note) return alert("请填写观察内容（建议写可观察事实）");

    const payload = {
      type: "observation",
      t_start: video.currentTime,
      note
    };

    const res = await fetch(`/api/videos/${currentVideoId}/annotations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const data = await res.json();
    if (!data.ok) return alert(data.error || "添加失败");

    $("note").value = "";
    refresh();
  };
}

async function move(index, direction) {

  const items = [...document.querySelectorAll("#segList .item")];

  const newIndex = index + direction;

  if (newIndex < 0 || newIndex >= items.length) return;

  const order = items.map(i =>
    Number(i.querySelector("button.danger").dataset.id)
  );

  const temp = order[index];
  order[index] = order[newIndex];
  order[newIndex] = temp;

  await fetch("/api/annotations/reorder", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ order })
  });

  refresh();
}

let editingId = null;

function parseTime(t){
  const [m,s] = t.split(":").map(Number);
  return m*60 + s;
}

document.addEventListener("DOMContentLoaded", () => {

  bindUploadUI();
  bindPlayer();

  $("saveEdit").onclick = async () => {

    const payload = {
      t_start: parseTime($("editStart").value),
      t_end: parseTime($("editEnd").value),
      dominant_category: $("editDominant").value,
      core_decision: $("editDecision").value,
      risk: $("editRisk").value
    };

    await fetch(`/api/annotations/${editingId}`,{
      method:"PUT",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload)
    });

    $("editModal").classList.add("hidden");
    refresh();
  };

  $("cancelEdit").onclick = ()=>{
    $("editModal").classList.add("hidden");
  };

});