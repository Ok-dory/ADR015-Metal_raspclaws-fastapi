// RaspClaws 웹 컨트롤러 (PC · 스마트폰 공용)
(() => {
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* 저장 불가 환경 */ } },
  };
  const buzz = (ms = 8) => { try { navigator.vibrate && navigator.vibrate(ms); } catch {} };

  let ws = null;
  let state = null;
  let selected = 0;

  // ================================================================ WebSocket
  function connect() {
    ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
    ws.onopen = () => { $("conn").className = "dot on"; $("connText").textContent = "연결됨"; keepAwake(); };
    ws.onclose = () => {
      $("conn").className = "dot"; $("connText").textContent = "재연결 중";
      setTimeout(connect, 1000);
    };
    ws.onmessage = (ev) => {
      const msg = JSON.parse(ev.data);
      if (msg.type === "state") { state = msg; render(msg); }
      else if (msg.type === "ack" && !msg.ok) toast(msg.error);
    };
  }
  const send = (cmd) => { if (ws && ws.readyState === 1) ws.send(cmd); };

  // ================================================================ 조이스틱
  // onMove(x, y): x = 오른쪽 +, y = 위 +, 각각 -1~1 / onEnd(): 손을 뗐을 때
  function joystick(el, onMove, onEnd) {
    const knob = el.querySelector(".knob");
    let active = null;
    const update = (e) => {
      const r = el.getBoundingClientRect();
      const max = r.width / 2 - knob.offsetWidth / 2;
      let dx = e.clientX - (r.left + r.width / 2);
      let dy = e.clientY - (r.top + r.height / 2);
      const len = Math.hypot(dx, dy);
      if (len > max) { dx *= max / len; dy *= max / len; }
      knob.style.transform = `translate(calc(-50% + ${dx}px), calc(-50% + ${dy}px))`;
      onMove(dx / max, -dy / max);
    };
    el.addEventListener("pointerdown", (e) => {
      if (active !== null) return;
      active = e.pointerId; el.setPointerCapture(e.pointerId); el.classList.add("dragging"); update(e);
    });
    el.addEventListener("pointermove", (e) => { if (e.pointerId === active) update(e); });
    const end = (e) => {
      if (e.pointerId !== active) return;
      active = null; el.classList.remove("dragging");
      knob.style.transform = "translate(-50%, -50%)";
      onEnd();
    };
    el.addEventListener("pointerup", end);
    el.addEventListener("pointercancel", end);
    el.addEventListener("lostpointercapture", end);
  }

  // 이동: 가장 큰 축으로 4방향 결정 (헥사포드 보행은 4방향)
  let moveDir = null;
  function setMove(dir) {
    if (dir === moveDir) return;
    moveDir = dir;
    $("moveJoy").dataset.dir = dir || "";
    if (!dir) delete $("moveJoy").dataset.dir;
    send(dir || "DS");
    buzz(dir ? 12 : 6);
  }
  joystick($("moveJoy"), (x, y) => {
    if (Math.hypot(x, y) < 0.35) return setMove(null);
    setMove(Math.abs(y) >= Math.abs(x) ? (y > 0 ? "forward" : "backward") : (x > 0 ? "right" : "left"));
  }, () => setMove(null));

  // 카메라: 기울인 만큼 속도 비례 (초당 최대 15회 전송)
  let camVel = [0, 0], camTimer = null, camSent = "";
  function flushCam() {
    const msg = `headvel ${camVel[0].toFixed(2)} ${camVel[1].toFixed(2)}`;
    if (msg !== camSent) { send(msg); camSent = msg; }
  }
  joystick($("camJoy"), (x, y) => {
    camVel = [-x, y];                       // pan + = 왼쪽
    if (!camTimer) { flushCam(); camTimer = setInterval(flushCam, 66); }
  }, () => {
    clearInterval(camTimer); camTimer = null; camVel = [0, 0]; flushCam();
  });

  // ================================================================ 버튼
  document.querySelectorAll("button[data-once]").forEach((b) =>
    b.addEventListener("click", () => { send(b.dataset.once); buzz(); }));

  const held = new Set();
  function press(b) { if (held.has(b)) return; held.add(b); b.classList.add("active"); send(b.dataset.hold); buzz(); }
  function release(b) { if (!held.delete(b)) return; b.classList.remove("active"); send(b.dataset.stop); }
  document.querySelectorAll("button[data-hold]").forEach((b) => {
    b.addEventListener("pointerdown", (e) => { b.setPointerCapture(e.pointerId); press(b); });
    b.addEventListener("pointerup", () => release(b));
    b.addEventListener("pointercancel", () => release(b));
  });

  $("stopBtn").onclick = () => {
    setMove(null); send("DS"); send("headvel 0 0"); send("sonarstop"); buzz(30);
  };
  $("speedBtn").onclick = () => send(state && state.speed_mode === "fast" ? "slow" : "fast");
  $("scanBtn").onclick = () => { send("sonarscan"); buzz(); };

  // ================================================================ 키보드 (PC)
  const moveKeys = { w: "forward", s: "backward", a: "left", d: "right" };
  const camKeys = { i: [0, 1], k: [0, -1], j: [1, 0], l: [-1, 0] };
  const keysDown = new Set();
  function camFromKeys() {
    let p = 0, t = 0;
    keysDown.forEach((k) => { if (camKeys[k]) { p += camKeys[k][0]; t += camKeys[k][1]; } });
    send(`headvel ${p * 0.6} ${t * 0.6}`);
  }
  addEventListener("keydown", (e) => {
    if (e.repeat || e.target.tagName === "SELECT" || e.ctrlKey || e.metaKey) return;
    const k = e.key.toLowerCase();
    if (moveKeys[k]) { keysDown.add(k); setMove(moveKeys[k]); }
    else if (camKeys[k]) { keysDown.add(k); camFromKeys(); }
    else if (k === "q" || k === "e") { const b = document.querySelector(`[data-key="${k}"]`); if (b) press(b); }
    else if (k === " ") { e.preventDefault(); $("stopBtn").click(); }
  });
  addEventListener("keyup", (e) => {
    const k = e.key.toLowerCase();
    keysDown.delete(k);
    if (moveKeys[k]) {
      const still = [...keysDown].find((x) => moveKeys[x]);
      setMove(still ? moveKeys[still] : null);
    } else if (camKeys[k]) camFromKeys();
    else if (k === "q" || k === "e") { const b = document.querySelector(`[data-key="${k}"]`); if (b) release(b); }
  });

  // 화면을 벗어나면 모두 정지 (앱 전환, 탭 이동, 화면 꺼짐)
  function stopAll() {
    keysDown.clear(); held.forEach(release); setMove(null);
    clearInterval(camTimer); camTimer = null; camVel = [0, 0]; flushCam();
  }
  addEventListener("blur", stopAll);
  document.addEventListener("visibilitychange", () => { if (document.hidden) stopAll(); else keepAwake(); });

  // ================================================================ 카메라 영상
  const img = $("stream");
  let streamOn = true;
  function startStream() { img.src = `/video_feed?t=${Date.now()}`; $("videoEmpty").textContent = "카메라 연결 중…"; }
  img.onload = () => { $("videoEmpty").style.display = "none"; };
  img.onerror = () => {
    $("videoEmpty").style.display = "grid"; $("videoEmpty").textContent = "카메라 영상을 받을 수 없습니다";
    if (streamOn) setTimeout(() => streamOn && startStream(), 3000);
  };
  $("streamBtn").onclick = () => {
    streamOn = !streamOn;
    $("streamBtn").classList.toggle("active", streamOn);
    $("streamBtn").textContent = streamOn ? "영상 ON" : "영상 OFF";
    if (streamOn) startStream();
    else { img.removeAttribute("src"); $("videoEmpty").style.display = "grid"; $("videoEmpty").textContent = "영상 꺼짐"; }
  };
  $("snapBtn").onclick = async () => {
    try {
      const r = await fetch("/api/camera/snapshot");
      if (!r.ok) throw new Error();
      const a = document.createElement("a");
      a.href = URL.createObjectURL(await r.blob());
      a.download = `raspclaws_${new Date().toISOString().replace(/[:.]/g, "-")}.jpg`;
      a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 2000);
      toast("사진을 저장했습니다");
    } catch { toast("사진을 가져오지 못했습니다"); }
  };
  $("hflipBtn").onclick = () => send("hflip");
  $("vflipBtn").onclick = () => send("vflip");

  // 영상 탭 → 그 지점으로 카메라 조준 (Pi 카메라 화각 약 62°×48° 기준)
  const FOV_H = 62, FOV_V = 48;
  let tapStart = null;
  $("video").addEventListener("pointerdown", (e) => { tapStart = { x: e.clientX, y: e.clientY, t: Date.now() }; });
  $("video").addEventListener("pointerup", (e) => {
    if (!tapStart || !state || !state.head) return;
    const moved = Math.hypot(e.clientX - tapStart.x, e.clientY - tapStart.y);
    if (moved > 12 || Date.now() - tapStart.t > 500) return;  // 스크롤·길게 누르기는 무시
    const r = $("video").getBoundingClientRect();
    let fx = (e.clientX - r.left) / r.width - 0.5;
    let fy = (e.clientY - r.top) / r.height - 0.5;
    if (state.camera && state.camera.hflip) fx = -fx;
    if (state.camera && state.camera.vflip) fy = -fy;
    const pan = state.head.pan - fx * FOV_H;     // pan + = 왼쪽
    const tilt = state.head.tilt - fy * FOV_V;   // tilt + = 위
    send(`look ${pan.toFixed(1)} ${tilt.toFixed(1)}`);
    const m = document.createElement("div");
    m.className = "tap-mark"; m.style.left = `${e.clientX - r.left}px`; m.style.top = `${e.clientY - r.top}px`;
    $("video").appendChild(m); setTimeout(() => m.remove(), 650);
    buzz();
  });

  // ================================================================ 전체화면 · 화면 꺼짐 방지
  async function toggleFullscreen() {
    try {
      if (!document.fullscreenElement) {
        await document.documentElement.requestFullscreen({ navigationUI: "hide" });
        try { await screen.orientation.lock("landscape"); } catch { /* 지원 안 하는 기기 */ }
      } else { await document.exitFullscreen(); }
    } catch { toast("이 브라우저는 전체화면을 지원하지 않습니다"); }
  }
  $("fsBtn").onclick = toggleFullscreen;
  $("fsBtn2").onclick = toggleFullscreen;

  let wakeLock = null;
  async function keepAwake() {
    try { if ("wakeLock" in navigator && !wakeLock) { wakeLock = await navigator.wakeLock.request("screen"); wakeLock.onrelease = () => { wakeLock = null; }; } } catch {}
  }

  // ================================================================ 영점 설정 (접기 상태 기억)
  const calib = $("calib");
  calib.open = store.get("calibOpen", false);
  calib.addEventListener("toggle", () => { store.set("calibOpen", calib.open); if (calib.open && state) renderServos(state); });
  $("servoRows").addEventListener("click", (e) => {
    const tr = e.target.closest("tr"); if (tr) { selected = +tr.dataset.ch; $("chSel").value = selected; renderServos(state); }
  });
  $("chSel").addEventListener("change", (e) => { selected = +e.target.value; renderServos(state); });
  $("nudgeL").onclick = () => send(`SiLeft ${selected}`);
  $("nudgeR").onclick = () => send(`SiRight ${selected}`);
  $("identify").onclick = () => fetch(`/api/servos/${selected}/identify`, { method: "POST" });
  $("relOne").onclick = () => send(`release ${selected}`);
  $("saveCal").onclick = async () => {
    const r = await fetch("/api/calibration/save", { method: "POST" });
    toast(r.ok ? "영점 저장 완료" : "저장 실패");
  };
  $("resetCal").onclick = () => {
    if (confirm("모든 서보 영점을 90°로 되돌릴까요? (SAVE 전까지 파일에는 반영되지 않습니다)")) send("resetcal");
  };

  // ================================================================ 렌더링
  const fmt = (v, unit, d = 0) => (v === null || v === undefined ? "--" : `${(+v).toFixed(d)}${unit}`);

  function render(s) {
    // 상단 칩 · HUD
    const bat = s.battery || {};
    const batText = bat.percent != null ? `${bat.percent}%` : "--";
    $("batTxt").textContent = batText; $("hudBat").textContent = batText;
    $("batChip").className = "chip" + (bat.low ? " bad" : bat.percent != null && bat.percent < 25 ? " warn" : "");
    $("batDetail").textContent = bat.voltage != null ? `${bat.voltage.toFixed(2)} V · ${bat.percent}%${bat.low ? " (충전 필요)" : ""}` : (bat.available ? "측정 중…" : "측정 불가");
    $("batBar").style.width = `${bat.percent || 0}%`;
    $("batBar").style.background = bat.low ? "var(--danger)" : bat.percent < 25 ? "var(--warn)" : "var(--ok)";

    const so = s.sonar || {};
    const near = so.distance != null && so.distance < 20;
    $("distTxt").textContent = fmt(so.distance, "cm");
    $("distChip").className = "chip" + (near ? " bad" : "");
    $("hudDist").textContent = `📡 ${fmt(so.distance, " cm")}`;
    $("hudDist").classList.toggle("near", near);
    $("distBig").textContent = so.distance != null ? so.distance.toFixed(0) : "--";
    $("distBig").parentElement.classList.toggle("near", near);
    $("sonarAngle").textContent = fmt(so.angle, "");
    $("scanBtn").disabled = !!so.scanning;
    $("scanBtn").textContent = so.scanning ? "스캔 중…" : "부채꼴 스캔";
    drawRadar(so);

    $("hudMove").textContent = { forward: "전진", backward: "후진", left: "좌회전", right: "우회전" }[s.moving] || "정지";
    $("hudSpeed").textContent = s.speed_mode === "fast" ? "FAST" : "SLOW";
    $("speedBtn").textContent = s.speed_mode === "fast" ? "FAST" : "SLOW";
    $("speedBtn").classList.toggle("active", s.speed_mode === "fast");
    if (s.head) { $("hudPan").textContent = s.head.pan.toFixed(0); $("hudTilt").textContent = s.head.tilt.toFixed(0); }

    const cam = s.camera || {};
    $("hflipBtn").classList.toggle("active", !!cam.hflip);
    $("vflipBtn").classList.toggle("active", !!cam.vflip);
    $("camSrc").textContent = cam.enabled ? `${cam.source}${cam.streaming ? " · 송출 중" : ""}` : "꺼짐";

    $("cpuTemp").textContent = fmt(s.cpu_temp, " °C", 1);
    $("cpuUsage").textContent = fmt(s.cpu_usage, " %", 0);
    $("ramUsage").textContent = fmt(s.ram_usage, " %", 0);
    $("backend").textContent = s.backend;
    const oled = s.oled || {};
    $("oledTxt").textContent = (oled.lines || []).join("\n") + (oled.available ? "" : "\n(OLED 미연결 · 미리보기)");

    if (calib.open) renderServos(s);
  }

  function renderServos(s) {
    if (!s) return;
    const sel = $("chSel");
    if (!sel.options.length) {
      s.servos.forEach((sv) => sel.add(new Option(`${sv.channel} · ${sv.name}`, sv.channel)));
      sel.value = selected;
    }
    $("servoRows").innerHTML = s.servos.map((sv) => `
      <tr data-ch="${sv.channel}" class="${sv.channel === selected ? "sel" : ""}">
        <td>${sv.channel}</td><td>${sv.name}</td><td>${sv.angle}</td>
        <td>${sv.center}</td><td>${sv.physical}</td>
        <td><span class="badge ${sv.engaged ? "on" : ""}">${sv.engaged ? "ON" : "OFF"}</span></td>
      </tr>`).join("");
  }

  // 레이더: 논리각 90° = 정면(위), 값이 클수록 왼쪽
  const radar = $("radar");
  const MAX_CM = 200;
  function drawRadar(so) {
    const ctx = radar.getContext("2d");
    const css = getComputedStyle(document.documentElement);
    const c = (n) => css.getPropertyValue(n).trim();
    const W = radar.width, H = radar.height, cx = W / 2, cy = H - 12, R = Math.min(cx - 10, cy - 8);
    const pt = (angle, cm) => {
      const t = (angle * Math.PI) / 180, r = (Math.min(cm, MAX_CM) / MAX_CM) * R;
      return [cx + r * Math.cos(t), cy - r * Math.sin(t)];
    };
    ctx.clearRect(0, 0, W, H);
    ctx.strokeStyle = c("--radar-line"); ctx.lineWidth = 1; ctx.fillStyle = c("--radar-line"); ctx.font = "10px sans-serif";
    for (let cm = 50; cm <= MAX_CM; cm += 50) {
      ctx.beginPath(); ctx.arc(cx, cy, (cm / MAX_CM) * R, Math.PI, 2 * Math.PI); ctx.stroke();
      ctx.fillText(`${cm}`, cx + 3, cy - (cm / MAX_CM) * R + 11);
    }
    for (let a = 0; a <= 180; a += 30) { const [x, y] = pt(a, MAX_CM); ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(x, y); ctx.stroke(); }

    const pts = (so.scan || []).filter((p) => p.distance != null);
    if (pts.length > 1) {
      ctx.beginPath(); ctx.moveTo(cx, cy);
      pts.forEach((p) => ctx.lineTo(...pt(p.angle, p.distance)));
      ctx.closePath(); ctx.fillStyle = c("--radar-fill"); ctx.fill();
      ctx.fillStyle = c("--radar-beam");
      pts.forEach((p) => { const [x, y] = pt(p.angle, p.distance); ctx.beginPath(); ctx.arc(x, y, 2.5, 0, 7); ctx.fill(); });
    }
    if (so.angle != null) {
      const [bx, by] = pt(so.angle, MAX_CM);
      ctx.strokeStyle = c("--radar-beam"); ctx.lineWidth = 2;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(bx, by); ctx.stroke();
      if (so.distance != null) {
        const [dx, dy] = pt(so.angle, so.distance);
        ctx.fillStyle = so.distance < 20 ? "#ef4444" : "#fde047";
        ctx.beginPath(); ctx.arc(dx, dy, 5, 0, 7); ctx.fill();
      }
    }
  }

  let toastTimer;
  function toast(text) {
    const t = $("toast"); t.textContent = text; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove("show"), 1800);
  }

  drawRadar({});
  startStream();
  connect();
})();
