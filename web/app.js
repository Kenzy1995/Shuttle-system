

/* ====== 常數（API） ====== */
const API_URL =
  "https://booking-api-995728097341.asia-east1.run.app/api/sheet";
const OPS_URL =
  "https://booking-manager-995728097341.asia-east1.run.app/api/ops";
const QR_ORIGIN = "https://booking-manager-995728097341.asia-east1.run.app";

const LIVE_LOCATION_CONFIG = {
  key: "AIzaSyAsWWGuZ8XRY_H5MWCuM4o4TWHsO0hYW5s",
  api: "https://driver-api2-995728097341.asia-east1.run.app",
  trip: "",
  fbdb: "https://forte-booking-system-default-rtdb.asia-southeast1.firebasedatabase.app/",
  fbkey: "AIzaSyBg_oMW6M90HHlTBjgfWUDZuRdFBGzMTjQ"
};

function getLiveConfig() {
  const qs = new URLSearchParams(location.search);
  const cfg = { ...LIVE_LOCATION_CONFIG };
  if (qs.get("key")) cfg.key = qs.get("key");
  if (qs.get("api")) cfg.api = qs.get("api");
  if (qs.get("trip")) cfg.trip = qs.get("trip");
  if (qs.get("fbdb")) cfg.fbdb = qs.get("fbdb");
  if (qs.get("fbkey")) cfg.fbkey = qs.get("fbkey");
  return cfg;
}

/* ====== 狀態與工具 ====== */
let allRows = [];
let selectedDirection = "";
let selectedDateRaw = "";
let selectedStationRaw = "";
let selectedScheduleTime = "";
let selectedAvailableSeats = 0;
let currentBookingData = {};
let lastQueryResults = [];
let marqueeData = {
  text: "",
  isLoaded: false
};
let marqueeClosed = false;

// 查詢分頁狀態
let queryDateList = [];
let currentQueryDate = "";
let currentDateRows = [];

/* ====== 小工具 ====== */

// 取得目前語系，優先用 i18n.js 的 currentLang，全都不在預期範圍就 fallback zh
function getCurrentLang() {
  if (window.currentLang && ["zh", "en", "ja", "ko"].includes(window.currentLang)) {
    return window.currentLang;
  }
  // 再保險一層：看 <html lang="...">
  const htmlLang = (document.documentElement.getAttribute("lang") || "").toLowerCase();
  if (["zh", "en", "ja", "ko"].includes(htmlLang)) {
    return htmlLang;
  }
  return "zh";
}

function handleScroll() {
  // 支援多種滾動位置獲取方式，確保手機版也能正常運作
  const y = Math.max(
    window.scrollY || 0,
    document.documentElement.scrollTop || 0,
    document.body.scrollTop || 0,
    window.pageYOffset || 0
  );
  const btn = document.getElementById("backToTop");
  if (!btn) return;
  // 超過一個畫面高度就顯示（使用 window.innerHeight 作為一個畫面高度）
  const oneScreenHeight = window.innerHeight || document.documentElement.clientHeight || 300;
  btn.style.display = y > oneScreenHeight ? "block" : "none";
}

function showPage(id) {
  hardResetOverlays();

  document.querySelectorAll(".page").forEach((p) => p.classList.remove("active"));
  document.getElementById(id).classList.add("active");

  document
    .querySelectorAll(".nav-links button")
    .forEach((b) => b.classList.remove("active"));
  const navId =
    id === "reservation"
      ? "nav-reservation"
      : id === "check"
      ? "nav-check"
      : id === "schedule"
      ? "nav-schedule"
      : id === "station"
      ? "nav-station"
      : "nav-contact";
  const navEl = document.getElementById(navId);
  if (navEl) navEl.classList.add("active");

  document
    .querySelectorAll(".mobile-tabbar button")
    .forEach((b) => b.classList.remove("active"));
  const mId =
    id === "reservation"
      ? "m-reservation"
      : id === "check"
      ? "m-check"
      : id === "schedule"
      ? "m-schedule"
      : id === "station"
      ? "m-station"
      : "m-contact";
  const mEl = document.getElementById(mId);
  if (mEl) mEl.classList.add("active");

  window.scrollTo({ top: 0, behavior: "smooth" });

  if (id === "reservation") {
    const homeHero = document.getElementById("homeHero");
    if (homeHero) homeHero.style.display = "";
    ["step1", "step2", "step3", "step4", "step5", "step6", "successCard"].forEach(
      (s) => {
        const el = document.getElementById(s);
        if (el) el.style.display = "none";
      }
    );
  }

  if (id === "schedule") {
    loadScheduleData();
  }
  if (id === "station") {
    renderLiveLocationPlaceholder();
  }
  handleScroll();
}

function showLoading(s = true) {
  const el = document.getElementById("loading");
  if (el) el.classList.toggle("show", s);
}
function showVerifyLoading(s = true) {
  const el = document.getElementById("loadingConfirm");
  if (el) el.classList.toggle("show", s);
}
function showExpiredOverlay(s = true) {
  const el = document.getElementById("expiredOverlay");
  if (el) el.classList.toggle("show", s);
}
function overlayRestart() {
  showExpiredOverlay(false);
  restart();
}

function shake(el) {
  if (!el) return;
  el.classList.add("shake");
  setTimeout(() => el.classList.remove("shake"), 500);
}

// 關閉跑馬燈：只在本次畫面隱藏（不寫入 storage）
function closeMarquee() {
  const bar = document.getElementById('marqueeContainer');
  if (bar) {
    bar.style.display = 'none';
  }

  // 跑馬燈沒了，讓 navbar 貼到最上方
  const nav = document.querySelector('.navbar');
  if (nav) {
    nav.style.top = '0';
  }

  // 跑馬燈關閉，不需要額外操作
}

function toggleCollapse(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle("open");
  const icon = el.querySelector(".toggle-icon");
  if (icon) icon.textContent = el.classList.contains("open") ? "▾" : "▸";
}

function hardResetOverlays() {
  ["loading", "loadingConfirm", "expiredOverlay", "dialogOverlay", "successAnimation"].forEach(
    (id) => {
      const el = document.getElementById(id);
      if (!el) return;
      if (id === "successAnimation") {
        el.classList.remove("show");
        el.style.display = "none";
      } else {
        el.classList.remove("show");
      }
    }
  );
}

/* ====== 跑馬燈 ====== */
function showMarquee() {
  if (marqueeClosed) {
    const marqueeContainer = document.getElementById("marqueeContainer");
    if (marqueeContainer) {
      marqueeContainer.style.display = "none";
    }
    document.body.classList.remove("has-marquee");
    return;
  }

  const marqueeContainer = document.getElementById("marqueeContainer");
  const marqueeContent = document.getElementById("marqueeContent");
  if (!marqueeContainer || !marqueeContent) return;

  if (!marqueeData.text) {
    marqueeContainer.style.display = "none";
    return;
  }

  marqueeContent.textContent = marqueeData.text;
  marqueeContainer.style.display = "block";
  restartMarqueeAnimation();
}

function restartMarqueeAnimation() {
  const marqueeContent = document.getElementById("marqueeContent");
  if (!marqueeContent) return;

  marqueeContent.style.animation = "none";
  void marqueeContent.offsetHeight; // 強迫 reflow
  marqueeContent.style.animation = null;
}


function restartMarqueeAnimation() {
  const marqueeContent = document.getElementById("marqueeContent");
  if (!marqueeContent) return;

  marqueeContent.style.animation = "none";
  // 強迫 reflow
  void marqueeContent.offsetHeight;
  marqueeContent.style.animation = null;
}

/* ====== 對話框（卡片） ====== */
function sanitize(s) {
  return String(s || "").replace(/[<>&]/g, (c) => ({
    "<": "&lt;",
    ">": "&gt;",
    "&": "&amp;"
  }[c]));
}

function showErrorCard(message) {
  const overlay = document.getElementById("dialogOverlay");
  const title = document.getElementById("dialogTitle");
  const content = document.getElementById("dialogContent");
  const cancelBtn = document.getElementById("dialogCancelBtn");
  const confirmBtn = document.getElementById("dialogConfirmBtn");
  if (!overlay || !title || !content || !cancelBtn || !confirmBtn) return;

  title.textContent = t("errorTitle");
  content.innerHTML = `<p>${sanitize(message || t("errorGeneric"))}</p>`;
  cancelBtn.style.display = "none";
  confirmBtn.disabled = false;
  confirmBtn.textContent = t("ok");
  confirmBtn.onclick = () => overlay.classList.remove("show");
  overlay.classList.add("show");
}

function showConfirmDelete(bookingId, onConfirm) {
  const overlay = document.getElementById("dialogOverlay");
  const title = document.getElementById("dialogTitle");
  const content = document.getElementById("dialogContent");
  const cancelBtn = document.getElementById("dialogCancelBtn");
  const confirmBtn = document.getElementById("dialogConfirmBtn");
  if (!overlay || !title || !content || !cancelBtn || !confirmBtn) return;

  title.textContent = t("confirmDeleteTitle");
  content.innerHTML = `<p>${t("confirmDeleteText")}</p><p style="color:#b00020;font-weight:700">${sanitize(
    bookingId
  )}</p>`;

  cancelBtn.style.display = "";
  cancelBtn.textContent = t("cancel");
  cancelBtn.onclick = () => overlay.classList.remove("show");

  let seconds = 5;
  confirmBtn.disabled = true;
  confirmBtn.textContent = `${t("confirm")} (${seconds})`;
  const timer = setInterval(() => {
    seconds -= 1;
    confirmBtn.textContent = `${t("confirm")} (${seconds})`;
    if (seconds <= 0) {
      clearInterval(timer);
      confirmBtn.disabled = false;
      confirmBtn.textContent = t("confirm");
    }
  }, 1000);

  confirmBtn.onclick = () => {
    overlay.classList.remove("show");
    onConfirm && onConfirm();
  };
  overlay.classList.add("show");
}

/* ====== 時間/格式化 ====== */
function fmtDateLabel(v) {
  if (!v) return "";
  const s = String(v).trim();
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) return s.slice(0, 10);
  if (/^\d{4}\/\d{1,2}\/\d{1,2}$/.test(s)) {
    const [y, m, d] = s.split("/");
    return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  }
  if (/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(s)) {
    const [m, d, y] = s.split("/");
    return `${y}-${String(m).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  }
  if (/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  return s;
}

function fmtTimeLabel(v) {
  if (v == null) return "";
  const s = String(v).trim().replace("：", ":");
  if (/^\d{4}-\d{2}-\d{2}T/.test(s)) return s.slice(11, 16);
  if (/^\d{1,2}:\d{1,2}/.test(s)) {
    const [h, m] = s.split(":");
    return `${String(h).padStart(2, "0")}:${String(m)
      .slice(0, 2)
      .padStart(2, "0")}`;
  }
  if (/\//.test(s) && /:/.test(s)) {
    return s.split(" ").pop().slice(0, 5);
  }
  return s.slice(0, 5);
}

function formatTicketHeader(dateStr, timeStr) {
  // 先把日期轉成 ISO：2025-11-19
  const iso = fmtDateLabel(dateStr);
  if (!iso) {
    // 萬一解析不到，就退回原始字串組合
    return `${dateStr || ""} ${timeStr || ""}`.trim();
  }

  let y, m, d;
  // iso 形態應該是 2025-11-19
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    [y, m, d] = iso.split("-");
  } else if (/^\d{4}\/\d{1,2}\/\d{1,2}$/.test(iso)) {
    [y, m, d] = iso.split("/");
  } else {
    return `${dateStr || ""} ${timeStr || ""}`.trim();
  }

  const datePart = `${y}/${String(m).padStart(2, "0")}/${String(d).padStart(2, "0")}`;
  const timePart = fmtTimeLabel(timeStr || "");
  return `${datePart} ${timePart}`.trim();
}


function todayISO() {
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, "0");
  const d = String(now.getDate()).padStart(2, "0");
  return `${y}-${m}-${d}`;
}

function onlyDigits(t) {
  return (t || "").replace(/\D/g, "");
}

/* ====== 驗證 ====== */
const phoneRegex = /^\+?\d{1,3}?\d{7,}$/;
const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const roomRegex =
  /^(0000|501|502|503|505|506|507|508|509|510|511|512|515|516|517|518|519|520|521|522|523|525|526|527|528|601|602|603|605|606|607|608|609|610|611|612|615|616|617|618|619|620|621|622|623|625|626|627|628|701|702|703|705|706|707|708|709|710|711|712|715|716|717|718|719|720|721|722|723|725|726|727|728|801|802|803|805|806|807|808|809|810|811|812|815|816|817|818|819|820|821|822|823|825|826|827|828|901|902|903|905|906|907|908|909|910|911|912|915|916|917|918|919|920|921|922|923|925|926|927|928|1001|1002|1003|1005|1006|1007|1008|1009|1010|1011|1012|1015|1016|1017|1018|1019|1020|1021|1022|1023|1025|1026|1027|1028|1101|1102|1103|1105|1106|1107|1108|1109|1110|1111|1112|1115|1116|1117|1118|1119|1120|1121|1122|1123|1125|1126|1127|1128|1201|1202|1206|1207|1208|1209|1210|1211|1212|1215|1216|1217|1218|1219|1220|1221|1222|1223|1225|1226|1227|1228|1301|1302|1303|1305|1306|1307|1308|1309|1310|1311|1312|1315|1316|1317|1318|1319|1320|1321|1322|1323|1325|1326|1327|1328)$/;
const nameRegex = /^[\u4e00-\u9fa5a-zA-Z\s]*$/;

function validateName(input) {
  const value = input.value || "";
  const nameErr = document.getElementById("nameErr");
  if (!nameRegex.test(value)) {
    input.value = value.replace(/[^\u4e00-\u9fa5a-zA-Z\s]/g, "");
    nameErr.textContent = t("errName");
    nameErr.style.display = "block";
    shake(input);
    input.style.borderColor = "#b00020";
    setTimeout(() => {
      input.style.borderColor = "#ddd";
      nameErr.style.display = "none";
    }, 2000);
  } else if (!value.trim()) {
    nameErr.textContent = t("errName");
    nameErr.style.display = "block";
    shake(input);
    input.style.borderColor = "#b00020";
  } else {
    nameErr.style.display = "none";
    input.style.borderColor = "#ddd";
  }
}

function validatePhone(input) {
  const value = input.value || "";
  const phoneErr = document.getElementById("phoneErr");
  if (!phoneRegex.test(value)) {
    phoneErr.textContent = t("errPhone");
    phoneErr.style.display = "block";
    shake(input);
    input.style.borderColor = "#b00020";
  } else {
    phoneErr.style.display = "none";
    input.style.borderColor = "#ddd";
  }
}

function validateEmail(input) {
  const value = input.value || "";
  const emailErr = document.getElementById("emailErr");
  if (!emailRegex.test(value)) {
    emailErr.textContent = t("errEmail");
    emailErr.style.display = "block";
    shake(input);
    input.style.borderColor = "#b00020";
  } else {
    emailErr.style.display = "none";
    input.style.borderColor = "#ddd";
  }
}

function validateRoom(input) {
  const value = input.value || "";
  const roomErr = document.getElementById("roomErr");
  if (!roomRegex.test(value)) {
    roomErr.textContent = t("errRoom");
    roomErr.style.display = "block";
    shake(input);
    input.style.borderColor = "#b00020";
  } else {
    roomErr.style.display = "none";
    input.style.borderColor = "#ddd";
  }
}

/* ======站點排序邏輯 ====== */
function getStationPriority(name) {
  const s = String(name || "");

  if (s.includes("捷運") || s.includes("MRT")) return 1;          // 捷運站
  if (s.includes("火車") || s.toLowerCase().includes("train")) return 2; // 火車站
  if (s.toLowerCase().includes("lalaport")) return 3;             // LaLaport
  return 99; // 
}

/* ====== 初始化/頁面 ====== */
function startBooking() {
  const hero = document.getElementById("homeHero");
  if (hero) hero.style.display = "none";
  refreshData().then(() => {
    buildStep1();
    const s1 = document.getElementById("step1");
    if (s1) s1.style.display = "";
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

function goStep(n) {
  ["step1", "step2", "step3", "step4", "step5", "step6"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  });
  const target = document.getElementById("step" + n);
  if (target) target.style.display = "";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function restart() {
  selectedDirection = "";
  selectedDateRaw = "";
  selectedStationRaw = "";
  selectedScheduleTime = "";
  selectedAvailableSeats = 0;
  hardResetOverlays();
  const hero = document.getElementById("homeHero");
  if (hero) hero.style.display = "";
  ["directionList", "dateList", "stationList", "scheduleList"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.innerHTML = "";
  });
  ["step1", "step2", "step3", "step4", "step5", "step6", "successCard"].forEach(
    (id) => {
      const el = document.getElementById(id);
      if (el) el.style.display = "none";
    }
  );
  showPage("reservation");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ====== Step 1 ====== */
function buildStep1() {
  const list = document.getElementById("directionList");
  if (!list) return;
  list.innerHTML = "";
  const opts = [
    { valueZh: "去程", labelKey: "dirOutLabel" },
    { valueZh: "回程", labelKey: "dirInLabel" }
  ];
  opts.forEach((opt) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "opt-btn";
    btn.textContent = t(opt.labelKey);
    btn.onclick = () => {
      selectedDirection = opt.valueZh;
      list.querySelectorAll(".opt-btn").forEach((b) =>
        b.classList.remove("active")
      );
      btn.classList.add("active");
      toStep2();
    };
    list.appendChild(btn);
  });
}

function toStep2() {
  if (!selectedDirection) {
    showErrorCard(t("labelDirection"));
    return;
  }
  const dateSet = new Set(
    allRows
      .filter((r) => String(r["去程 / 回程"]).trim() === selectedDirection)
      .map((r) => fmtDateLabel(r["日期"]))
  );
  const sorted = [...dateSet].sort((a, b) => new Date(a) - new Date(b));
  const list = document.getElementById("dateList");
  if (!list) return;
  list.innerHTML = "";
  sorted.forEach((dateStr) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "opt-btn";
    btn.textContent = dateStr;
    btn.onclick = () => {
      selectedDateRaw = dateStr;
      list.querySelectorAll(".opt-btn").forEach((b) =>
        b.classList.remove("active")
      );
      btn.classList.add("active");
      toStep3();
    };
    list.appendChild(btn);
  });
  goStep(2);
}

/* ====== Step 3 ====== */
function toStep3() {
  if (!selectedDateRaw) {
    showErrorCard(t("labelDate"));
    return;
  }
  const fixed = document.getElementById("fixedStation");
  if (fixed) fixed.value = "福泰大飯店 Forte Hotel";

  const stations = new Set(
    allRows
      .filter(
        (r) =>
          String(r["去程 / 回程"]).trim() === selectedDirection &&
          fmtDateLabel(r["日期"]) === selectedDateRaw
      )
      .map((r) => String(r["站點"]).trim())
  );
  const list = document.getElementById("stationList");
  if (!list) return;
  list.innerHTML = "";
  [...stations].forEach((st) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "opt-btn";
    btn.textContent = st;
    btn.onclick = () => {
      selectedStationRaw = st;
      list.querySelectorAll(".opt-btn").forEach((b) =>
        b.classList.remove("active")
      );
      btn.classList.add("active");
      toStep4();
    };
    list.appendChild(btn);
  });
  goStep(3);
}

/* ====== Step 4 ====== */
function toStep4() {
  if (!selectedStationRaw) {
    showErrorCard(t("labelStation"));
    return;
  }
  const list = document.getElementById("scheduleList");
  if (!list) return;
  list.innerHTML = "";
  const entries = allRows
    .filter(
      (r) =>
        String(r["去程 / 回程"]).trim() === selectedDirection &&
        fmtDateLabel(r["日期"]) === selectedDateRaw &&
        String(r["站點"]).trim() === selectedStationRaw
    )
    .sort((a, b) =>
      fmtTimeLabel(a["班次"]).localeCompare(fmtTimeLabel(b["班次"]))
    );

  if (entries.length === 0) {
    showExpiredOverlay(true);
    return;
  }

  entries.forEach((r) => {
    const time = fmtTimeLabel(r["班次"] || r["車次"]);
    const availText = String(
      r["可預約人數"] || r["可約人數 / Available"] || ""
    ).trim();
    const avail = Number(onlyDigits(availText)) || 0;

    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "opt-btn";

    if (avail <= 0) {
      btn.classList.add("disabled");
      // 「已額滿」如果之後也要多語系，可以另外在 TEXTS 加一個 key
      btn.innerHTML = `
        <span style="color:#999;font-weight:700">${time}</span>
        <span style="color:#999;font-size:13px">(已額滿)</span>
      `;
    } else {
      const texts = TEXTS[currentLang] || TEXTS.zh;
      const prefix = texts.paxHintPrefix || "";
      const suffix = texts.paxHintSuffix || "";

      // 這樣不同語系就會自動換字
      const paxText = `${prefix}${avail}${suffix}`;

      btn.innerHTML = `
        <span style="color:var(--primary);font-weight:700">${time}</span>
        <span style="color:#777;font-size:13px">(${paxText})</span>
      `;

      btn.onclick = () => {
        selectedScheduleTime = time;
        selectedAvailableSeats = avail;
        list.querySelectorAll(".opt-btn").forEach((b) =>
          b.classList.remove("active")
        );
        btn.classList.add("active");
        toStep5();
      };
    }

    list.appendChild(btn);
  });
  goStep(4);
}

/* ====== Step 5 ====== */
function onIdentityChange() {
  const v = document.getElementById("identitySelect").value;
  const today = todayISO();
  const hotelWrapper1 = document.getElementById("hotelDates");
  const hotelWrapper2 = document.getElementById("hotelDates2");
  const roomNumberDiv = document.getElementById("roomNumberDiv");
  const diningDateDiv = document.getElementById("diningDateDiv");

  if (hotelWrapper1) hotelWrapper1.style.display = v === "hotel" ? "block" : "none";
  if (hotelWrapper2) hotelWrapper2.style.display = v === "hotel" ? "block" : "none";
  if (roomNumberDiv) roomNumberDiv.style.display = v === "hotel" ? "block" : "none";
  if (diningDateDiv) diningDateDiv.style.display = v === "dining" ? "block" : "none";

  if (v === "hotel") {
    const ci = document.getElementById("checkInDate");
    const co = document.getElementById("checkOutDate");
    if (ci && !ci.value) ci.value = today;
    if (co && !co.value) co.value = today;
  } else if (v === "dining") {
    const din = document.getElementById("diningDate");
    if (din && !din.value) din.value = today;
  }
}

function toStep5() {
  if (!selectedScheduleTime) {
    showErrorCard(t("labelSchedule"));
    return;
  }
  onIdentityChange();
  goStep(5);
}

function validateStep5() {
  const id = document.getElementById("identitySelect").value;
  const name = (document.getElementById("guestName").value || "").trim();
  const phone = (document.getElementById("guestPhone").value || "").trim();
  const email = (document.getElementById("guestEmail").value || "").trim();

  if (!id) {
    document.getElementById("identityErr").style.display = "block";
    return false;
  } else document.getElementById("identityErr").style.display = "none";

  if (!name) {
    document.getElementById("nameErr").style.display = "block";
    shake(document.getElementById("guestName"));
    return false;
  } else document.getElementById("nameErr").style.display = "none";

  if (!phoneRegex.test(phone)) {
    document.getElementById("phoneErr").style.display = "block";
    shake(document.getElementById("guestPhone"));
    return false;
  } else document.getElementById("phoneErr").style.display = "none";

  if (!emailRegex.test(email)) {
    document.getElementById("emailErr").style.display = "block";
    shake(document.getElementById("guestEmail"));
    return false;
  } else document.getElementById("emailErr").style.display = "none";

  if (id === "hotel") {
    const cin = document.getElementById("checkInDate").value;
    const cout = document.getElementById("checkOutDate").value;
    if (!cin || !cout) {
      showErrorCard(t("labelCheckIn") + "/" + t("labelCheckOut"));
      shake(document.getElementById("checkInDate"));
      shake(document.getElementById("checkOutDate"));
      return false;
    }
    const room = (document.getElementById("roomNumber").value || "").trim();
    if (!roomRegex.test(room)) {
      document.getElementById("roomErr").style.display = "block";
      shake(document.getElementById("roomNumber"));
      return false;
    } else document.getElementById("roomErr").style.display = "none";
  } else {
    const din = document.getElementById("diningDate").value;
    if (!din) {
      showErrorCard(t("labelDiningDate"));
      shake(document.getElementById("diningDate"));
      return false;
    }
  }

  return true;
}

function toStep6() {
  if (!validateStep5()) return;

  document.getElementById("cf_direction").value = selectedDirection;
  document.getElementById("cf_date").value = selectedDateRaw;

  const pick =
    selectedDirection === "回程"
      ? selectedStationRaw
      : "福泰大飯店 Forte Hotel";
  const drop =
    selectedDirection === "回程"
      ? "福泰大飯店 Forte Hotel"
      : selectedStationRaw;

  document.getElementById("cf_pick").value = pick;
  document.getElementById("cf_drop").value = drop;
  document.getElementById("cf_time").value = selectedScheduleTime;
  document.getElementById("cf_name").value = (
    document.getElementById("guestName").value || ""
  ).trim();

  const sel = document.getElementById("passengers");
  sel.innerHTML = "";
  const maxPassengers = Math.min(4, Math.max(0, selectedAvailableSeats));
  if (maxPassengers <= 0) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "0";
    sel.appendChild(opt);
    sel.disabled = true;
  } else {
    sel.disabled = false;
    for (let i = 1; i <= maxPassengers; i++) {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = String(i);
      sel.appendChild(opt);
    }
    sel.value = "1";
  }
  document.getElementById(
    "passengersHint"
  ).textContent = `此班次可預約：${selectedAvailableSeats} 人；單筆最多 4 人`;

  ["step1", "step2", "step3", "step4", "step5"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  });
  const s6 = document.getElementById("step6");
  if (s6) s6.style.display = "";
  window.scrollTo({ top: 0, behavior: "smooth" });

  const errEl = document.getElementById("passengersErr");
  if (errEl) errEl.style.display = "none";
}

/* ====== 成功動畫 ====== */
function showSuccessAnimation() {
  const el = document.getElementById("successAnimation");
  if (!el) return;
  el.style.display = "flex";
  el.classList.add("show");
  setTimeout(() => {
    el.classList.remove("show");
    el.style.display = "none";
  }, 3000);
}

/* ====== 送出預約 ====== */
let bookingSubmitting = false;
async function submitBooking() {
  if (bookingSubmitting) return;

  const pSel = document.getElementById("passengers");
  const p = Number(pSel?.value || 0);
  if (!p || p < 1 || p > 4) {
    const errEl = document.getElementById("passengersErr");
    if (errEl) errEl.style.display = "block";
    return;
  }
  const errEl = document.getElementById("passengersErr");
  if (errEl) errEl.style.display = "none";

  const identity = document.getElementById("identitySelect").value;
  const payload = {
    direction: selectedDirection,
    date: selectedDateRaw,
    station: selectedStationRaw,
    time: selectedScheduleTime,
    identity,
    checkIn:
      identity === "hotel"
        ? document.getElementById("checkInDate").value || null
        : null,
    checkOut:
      identity === "hotel"
        ? document.getElementById("checkOutDate").value || null
        : null,
    diningDate:
      identity === "dining"
        ? document.getElementById("diningDate").value || null
        : null,
    roomNumber:
      identity === "hotel"
        ? document.getElementById("roomNumber").value || null
        : null,
    name: (document.getElementById("guestName").value || "").trim(),
    phone: (document.getElementById("guestPhone").value || "").trim(),
    email: (document.getElementById("guestEmail").value || "").trim(),
    passengers: p,
    dropLocation:
      selectedDirection === "回程"
        ? "福泰大飯店 Forte Hotel"
        : selectedStationRaw,
    pickLocation:
      selectedDirection === "回程"
        ? selectedStationRaw
        : "福泰大飯店 Forte Hotel",
    lang: getCurrentLang()
  };

  bookingSubmitting = true;
  const step6 = document.getElementById("step6");
  if (step6) step6.style.display = "none";
  showVerifyLoading(true);

  try {
    const res = await fetch(OPS_URL, {
      method: "POST",
      mode: "cors",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json"
      },
      body: JSON.stringify({ action: "book", data: payload })
    });

    let result = null;
    try {
      result = await res.json();
    } catch (e) {
      result = null;
    }

    const backendMsg =
      result && (result.error || result.code || result.detail || result.message || "");
    const isCapacityError =
      res.status === 409 ||
      backendMsg === "capacity_not_found" ||
      String(backendMsg || "").includes("capacity_not_found");

    if (!res.ok) {
      if (isCapacityError) {
        showErrorCard(t("overPaxOrMissing"));
      } else {
        showErrorCard(t("submitFailedPrefix") + `HTTP ${res.status}`);
      }
      if (step6) step6.style.display = "";
      return;
    }

    if (!result || result.status !== "success") {
      if (isCapacityError) {
        showErrorCard(t("overPaxOrMissing"));
      } else {
        showErrorCard(
          (result && (result.detail || result.message)) || t("errorGeneric")
        );
      }
      if (step6) step6.style.display = "";
      return;
    }

    const qrPath = result.qr_content
      ? `${QR_ORIGIN}/api/qr/${encodeURIComponent(result.qr_content)}`
      : result.qr_url || "";

    // 後端已經確認成功、寫進 Sheet，也在後端開始寄信
    // 前端這裡只負責顯示票卡
    currentBookingData = {
      bookingId: result.booking_id || "",
      date: selectedDateRaw,
      time: selectedScheduleTime,
      direction: selectedDirection,
      pickLocation: payload.pickLocation,
      dropLocation: payload.dropLocation,
      name: payload.name,
      phone: payload.phone,
      email: payload.email,
      passengers: p,
      qrUrl: qrPath
    };

    mountTicketAndShow(currentBookingData);
  } catch (err) {
    const maybeCapacity =
      err &&
      (err.error === "capacity_not_found" ||
        String(err.message || "").includes("capacity_not_found"));
    if (maybeCapacity) {
      showErrorCard(t("overPaxOrMissing"));
    } else {
      showErrorCard(t("submitFailedPrefix") + (err.message || ""));
    }
    if (step6) step6.style.display = "";
  } finally {
    showVerifyLoading(false);
    bookingSubmitting = false;
  }
}


function mountTicketAndShow(ticket) {
  const qrImg = document.getElementById("ticketQrImg");
  if (qrImg) qrImg.src = ticket.qrUrl || "";

  const bookingIdEl = document.getElementById("ticketBookingId");
  if (bookingIdEl) bookingIdEl.textContent = ticket.bookingId || "";

  // ✅ 修改這裡：將固定標題改為日期+班次
  const titleEl = document.getElementById("ticketHeaderTitle");
  if (titleEl) {
    titleEl.textContent = formatTicketHeader(ticket.date, ticket.time);
  }

  const directionEl = document.getElementById("ticketDirection");
  if (directionEl) directionEl.textContent = ticket.direction || "";

  const pickEl = document.getElementById("ticketPick");
  if (pickEl) pickEl.textContent = ticket.pickLocation || "";

  const dropEl = document.getElementById("ticketDrop");
  if (dropEl) dropEl.textContent = ticket.dropLocation || "";

  const nameEl = document.getElementById("ticketName");
  if (nameEl) nameEl.textContent = ticket.name || "";

  const phoneEl = document.getElementById("ticketPhone");
  if (phoneEl) phoneEl.textContent = ticket.phone || "";

  const emailEl = document.getElementById("ticketEmail");
  if (emailEl) emailEl.textContent = ticket.email || "";

  const paxEl = document.getElementById("ticketPassengers");
  if (paxEl) paxEl.textContent = ticket.passengers + " " + t("labelPassengersShort");

  const card = document.getElementById("successCard");
  if (card) card.style.display = "";
  window.scrollTo({ top: 0, behavior: "smooth" });

  // ✅ 先顯示票卡，再跑成功動畫
  showSuccessAnimation();
}


function closeTicketToHome() {
  const card = document.getElementById("successCard");
  if (card) card.style.display = "none";
  const hero = document.getElementById("homeHero");
  if (hero) hero.style.display = "";
  ["step1", "step2", "step3", "step4", "step5", "step6"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.style.display = "none";
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function downloadTicket() {
  const card = document.getElementById("ticketCard");
  if (!card) {
    showErrorCard("找不到票卡");
    return;
  }
  try {
    const rect = card.getBoundingClientRect();
    const dpr = Math.max(window.devicePixelRatio || 1, 1);
    const width = Math.round(rect.width);
    const height = Math.round(rect.height);
    if (!window.domtoimage) throw new Error("domtoimage not found");
    const dataUrl = await domtoimage.toPng(card, {
      width,
      height,
      bgcolor: "#ffffff",
      pixelRatio: dpr,
      style: {
        margin: "0",
        transform: "none",
        boxShadow: "none",
        overflow: "visible"
      }
    });
    const a = document.createElement("a");
    const bid =
      (document.getElementById("ticketBookingId")?.textContent || "ticket").trim();
    a.href = dataUrl;
    a.download = `ticket_${bid}.png`;
    a.click();
  } catch (e) {
    showErrorCard("下載失敗：" + (e?.message || e));
  }
}

/* ====== 查詢我的預約 ====== */
function showCheckQueryForm() {
  const qForm = document.getElementById("queryForm");
  const dateStep = document.getElementById("checkDateStep");
  const ticketStep = document.getElementById("checkTicketStep");
  if (qForm) qForm.style.display = "flex";
  if (dateStep) dateStep.style.display = "none";
  if (ticketStep) ticketStep.style.display = "none";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showCheckDateStep() {
  const qForm = document.getElementById("queryForm");
  const dateStep = document.getElementById("checkDateStep");
  const ticketStep = document.getElementById("checkTicketStep");
  if (qForm) qForm.style.display = "none";
  if (dateStep) dateStep.style.display = "block";
  if (ticketStep) ticketStep.style.display = "none";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showCheckTicketStep() {
  const qForm = document.getElementById("queryForm");
  const dateStep = document.getElementById("checkDateStep");
  const ticketStep = document.getElementById("checkTicketStep");
  if (qForm) qForm.style.display = "none";
  if (dateStep) dateStep.style.display = "none";
  if (ticketStep) ticketStep.style.display = "block";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function closeCheckTicket() {
  showCheckDateStep();
}

function withinOneMonth(dateIso) {
  try {
    const d = new Date((fmtDateLabel(dateIso) || todayISO()) + "T00:00:00");
    const now = new Date();
    const pastLimit = new Date(now);
    pastLimit.setMonth(now.getMonth() - 1);
    return d >= pastLimit;
  } catch (e) {
    return true;
  }
}

function getStatusCode(row) {
  const s = String(row["預約狀態"] || row["訂單狀態"] || "").toLowerCase();
  const audited = String(row["櫃台審核"] || "").trim().toUpperCase();
  const boarded = String(row["乘車狀態"] || "").includes("已上車");
  if (boarded) return "boarded";
  if (audited === "N") return "rejected";
  if (s.includes("取消")) return "cancelled";
  if (s.includes("預約")) return "booked";
  return "booked";
}

function maskName(name) {
  const s = String(name || "").trim();
  if (!s) return "";
  if (/[\u4e00-\u9fa5]/.test(s)) {
    return s.charAt(0) + "*".repeat(Math.max(0, s.length - 1));
  }
  const prefix = s.slice(0, 3);
  return prefix + "*".repeat(Math.max(0, s.length - 3));
}

function maskPhone(phone) {
  const p = String(phone || "");
  return p.slice(-4);
}

function maskEmail(email) {
  const e = String(email || "").trim();
  const at = e.indexOf("@");
  if (at <= 0) return e ? e[0] + "***" : "";
  const name = e.slice(0, at);
  const prefix = name.slice(0, 3);
  const stars = "*".repeat(Math.max(0, name.length - 3));
  const domain = e.slice(at + 1).toLowerCase();
  return `${prefix}${stars}@${domain}`;
}

function getDateFromCarDateTime(carDateTime) {
  if (!carDateTime) return "";
  const parts = String(carDateTime).split(" ");
  if (parts.length < 1) return "";
  const datePart = parts[0];
  return datePart.replace(/\//g, "-");
}

function getTimeFromCarDateTime(carDateTime) {
  if (!carDateTime) return "00:00";
  const parts = String(carDateTime).split(" ");
  return parts.length > 1 ? parts[1] : "00:00";
}

function isExpiredByCarDateTime(carDateTime) {
  if (!carDateTime) return true;
  try {
    const [datePart, timePart] = String(carDateTime).split(" ");
    const [year, month, day] = datePart.split("/").map(Number);
    const [hour, minute] = timePart.split(":").map(Number);
    const tripTime = new Date(year, month - 1, day, hour, minute, 0).getTime();
    return tripTime < Date.now();
  } catch (e) {
    return true;
  }
}

function buildTicketCard(row, { mask = false } = {}) {
  const carDateTime = String(row["車次-日期時間"] || "");
  const dateIso = getDateFromCarDateTime(carDateTime);
  const time = getTimeFromCarDateTime(carDateTime);
  const expired = isExpiredByCarDateTime(carDateTime);

  const statusCode = getStatusCode(row);
  const name = mask
    ? maskName(String(row["姓名"] || ""))
    : String(row["姓名"] || "");
  const phone = mask
    ? maskPhone(String(row["手機"] || ""))
    : String(row["手機"] || "");
  const email = mask
    ? maskEmail(String(row["信箱"] || ""))
    : String(row["信箱"] || "");
  const rb = String(row["往返"] || row["往返方向"] || "");
  const pick = String(row["上車地點"] || "");
  const drop = String(row["下車地點"] || "");
  const bookingId = String(row["預約編號"] || "");
  const pax =
    Number(row["確認人數"] || row["預約人數"] || "1") || 1;
  const qrCodeContent = String(row["QRCode編碼"] || "");
  const qrUrl = qrCodeContent
    ? QR_ORIGIN + "/api/qr/" + encodeURIComponent(qrCodeContent)
    : "";

  const card = document.createElement("div");
  card.className = "ticket-card" + (expired ? " expired" : "");

  const pill = document.createElement("div");
  pill.className =
    "status-pill " +
    (expired ? "status-expired" : "status-" + statusCode);
  pill.textContent = expired ? ts("expired") : ts(statusCode);
  card.appendChild(pill);

  if (statusCode === "rejected") {
    const tip = document.createElement("button");
    tip.className = "badge-alert";
    tip.title = t("rejectedTip");
    tip.textContent = "!";
    tip.onclick = () => showErrorCard(t("rejectedTip"));
    card.appendChild(tip);
  }

  const header = document.createElement("div");
  header.className = "ticket-header";
  header.innerHTML = `<h2>${sanitize(carDateTime)}</h2>`;
  card.appendChild(header);

  const content = document.createElement("div");
  content.className = "ticket-content";

  const qr = document.createElement("div");
  qr.className = "ticket-qr";
  qr.innerHTML =
    statusCode === "cancelled"
      ? `<img src="/images/qr-placeholder.png" alt="QR placeholder" />`
      : `<img src="${qrUrl}" alt="QR" />`;

  const info = document.createElement("div");
  info.className = "ticket-info";
  info.innerHTML = `
    <div class="ticket-field"><span class="ticket-label">${t(
      "labelBookingId"
    )}</span><span class="ticket-value">${sanitize(
    bookingId
  )}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t(
      "labelDirection"
    )}</span><span class="ticket-value">${sanitize(rb)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t(
      "labelPick"
    )}</span><span class="ticket-value">${sanitize(pick)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t(
      "labelDrop"
    )}</span><span class="ticket-value">${sanitize(drop)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t(
      "labelName"
    )}</span><span class="ticket-value">${sanitize(name)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t(
      "labelPhone"
    )}</span><span class="ticket-value">${sanitize(phone)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t(
      "labelEmail"
    )}</span><span class="ticket-value">${sanitize(email)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t(
      "labelPassengersShort"
    )}</span><span class="ticket-value">${sanitize(String(pax))}</span></div>
  `;
  content.appendChild(qr);
  content.appendChild(info);
  card.appendChild(content);

  const actions = document.createElement("div");
  actions.className = "ticket-actions";

  if (statusCode !== "cancelled" && statusCode !== "rejected") {
    const dlBtn = document.createElement("button");
    dlBtn.className = "button";
    dlBtn.textContent = ts("download");
    dlBtn.onclick = () => {
      if (!window.domtoimage) return;
      domtoimage
        .toPng(card, { bgcolor: "#fff", pixelRatio: 2 })
        .then((dataUrl) => {
          const a = document.createElement("a");
          a.href = dataUrl;
          a.download = `ticket_${sanitize(bookingId)}.png`;
          a.click();
        });
    };
    actions.appendChild(dlBtn);
  }

  if (
    !expired &&
    statusCode !== "cancelled" &&
    statusCode !== "rejected" &&
    statusCode !== "boarded"
  ) {
    const mdBtn = document.createElement("button");
    mdBtn.className = "button btn-ghost";
    mdBtn.textContent = ts("modify");
    mdBtn.onclick = () =>
      openModifyPage({
        row,
        bookingId,
        rb,
        date: dateIso,
        pick,
        drop,
        time,
        pax
      });
    actions.appendChild(mdBtn);

    const delBtn = document.createElement("button");
    delBtn.className = "button btn-ghost";
    delBtn.textContent = ts("remove");
    delBtn.onclick = () => deleteOrder(bookingId);
    actions.appendChild(delBtn);
  }

  card.appendChild(actions);
  return card;
}

/* ====== 查詢/刪改 ====== */
async function queryOrders() {
  const id = (document.getElementById("qBookId").value || "").trim();
  const phone = (document.getElementById("qPhone").value || "").trim();
  const email = (document.getElementById("qEmail").value || "").trim();
  const queryHint = document.getElementById("queryHint");
  if (!id && !phone && !email) {
    if (queryHint) shake(queryHint);
    return;
  }
  showLoading(true);
  try {
    const res = await fetch(OPS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "query", data: { booking_id: id, phone, email } })
    });
    const data = await res.json();
    const arr = Array.isArray(data) ? data : data.results || [];
    lastQueryResults = arr;
    buildDateListFromResults(arr);
    showCheckDateStep();
  } catch (e) {
    showErrorCard(t("queryFailedPrefix") + (e?.message || ""));
  } finally {
    showLoading(false);
  }
}

function buildDateListFromResults(rows) {
  const dateMap = new Map();
  rows.forEach((r) => {
    const carDateTime = String(r["車次-日期時間"] || "");
    const dateIso = getDateFromCarDateTime(carDateTime);
    if (withinOneMonth(dateIso)) {
      dateMap.set(dateIso, (dateMap.get(dateIso) || 0) + 1);
    }
  });

  queryDateList = Array.from(dateMap.entries()).sort(
    (a, b) => new Date(a[0]) - new Date(b[0])
  );
  const wrap = document.getElementById("dateChoices");
  if (!wrap) return;
  wrap.innerHTML = "";

  if (!queryDateList.length) {
    const empty = document.createElement("div");
    empty.className = "card";
    empty.style.textAlign = "center";
    empty.style.color = "#666";
    empty.textContent =
      (I18N_STATUS[currentLang] || I18N_STATUS.zh).noRecords;
    wrap.appendChild(empty);
    return;
  }

  // ✅ 改這裡：從 TEXTS 拿字，而不是 I18N_STATUS
  const texts = TEXTS[currentLang] || TEXTS.zh;
  const prefix = texts.dateCountPrefix || "";
  const suffix = texts.dateCountSuffix || "";

  queryDateList.forEach(([date, count]) => {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "opt-btn";

    btn.innerHTML = `
      ${date}
      <span style="color:#777;font-size:13px">
        (${prefix}${count}${suffix})
      </span>
    `;

    btn.onclick = () => openTicketsForDate(date);
    wrap.appendChild(btn);
  });
}


function openTicketsForDate(dateIso) {
  currentQueryDate = dateIso;
  const dateRows = lastQueryResults.filter((r) => {
    const carDateTime = String(r["車次-日期時間"] || "");
    const rowDateIso = getDateFromCarDateTime(carDateTime);
    return rowDateIso === dateIso;
  });

  currentDateRows = dateRows.sort((a, b) => {
    const statusA = getStatusCode(a);
    const statusB = getStatusCode(b);
    const carDateTimeA = String(a["車次-日期時間"] || "");
    const carDateTimeB = String(b["車次-日期時間"] || "");
    const isValidA =
      (statusA === "booked" || statusA === "boarded") &&
      !isExpiredByCarDateTime(carDateTimeA);
    const isValidB =
      (statusB === "booked" || statusB === "boarded") &&
      !isExpiredByCarDateTime(carDateTimeB);

    if (isValidA && !isValidB) return -1;
    if (!isValidA && isValidB) return 1;

    if (isValidA && isValidB) {
      const timeA = getTimeFromCarDateTime(carDateTimeA);
      const timeB = getTimeFromCarDateTime(carDateTimeB);
      return timeA.localeCompare(timeB);
    }

    const order = {
      cancelled: 1,
      rejected: 2,
      expired: 3,
      booked: 4,
      boarded: 5
    };
    return (order[statusA] || 6) - (order[statusB] || 6);
  });

  const mount = document.getElementById("checkTicketMount");
  if (!mount) return;
  mount.innerHTML = "";
  currentDateRows.forEach((row) =>
    mount.appendChild(buildTicketCard(row, { mask: true }))
  );
  showCheckTicketStep();
}

function rerenderQueryPages() {
  const dateStep = document.getElementById("checkDateStep");
  const ticketStep = document.getElementById("checkTicketStep");
  if (dateStep && dateStep.style.display !== "none") {
    buildDateListFromResults(lastQueryResults);
  }
  if (ticketStep && ticketStep.style.display !== "none") {
    openTicketsForDate(currentQueryDate);
  }
}

async function deleteOrder(bookingId) {
  showConfirmDelete(bookingId, async () => {
    showLoading(true);
    try {
      const r = await fetch(OPS_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "delete",
          data: {
            booking_id: bookingId,
            lang: getCurrentLang()      
          }
        })
      });
      const j = await r.json();
      if (j.status === "success") {
        showSuccessAnimation();
        setTimeout(async () => {
          const id = (document.getElementById("qBookId").value || "").trim();
          const phone = (document.getElementById("qPhone").value || "").trim();
          const email = (document.getElementById("qEmail").value || "").trim();
          const queryRes = await fetch(OPS_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "query",
              data: { booking_id: id, phone, email },
              lang: getCurrentLang()
            })
          });
          const queryData = await queryRes.json();
          lastQueryResults = Array.isArray(queryData)
            ? queryData
            : queryData.results || [];
          buildDateListFromResults(lastQueryResults);
          if (currentQueryDate) openTicketsForDate(currentQueryDate);
          else showCheckDateStep();
        }, 3000);
      } else {
        showErrorCard(j.detail || t("errorGeneric"));
      }
    } catch (e) {
      showErrorCard(t("deleteFailedPrefix") + (e?.message || ""));
    } finally {
      showLoading(false);
    }
  });
}

/* ====== 修改：新頁面 ====== */
async function openModifyPage({ row, bookingId, rb, date, pick, drop, time, pax }) {
  await refreshData();
  showPage("check");

  const qForm = document.getElementById("queryForm");
  const dateStep = document.getElementById("checkDateStep");
  const ticketStep = document.getElementById("checkTicketStep");
  if (qForm) qForm.style.display = "none";
  if (dateStep) dateStep.style.display = "none";
  if (ticketStep) ticketStep.style.display = "none";

  const holderId = "editHolder";
  let holder = document.getElementById(holderId);
  if (!holder) {
    holder = document.createElement("div");
    holder.id = holderId;
    holder.className = "card wizard-fixed";
    const checkPage = document.getElementById("check");
    if (checkPage) checkPage.appendChild(holder);
  }

  holder.innerHTML = `
    <h2>${t("editBookingTitle") || "修改預約"} ${sanitize(bookingId)}</h2>
    <div class="field"><label class="label">${t(
      "labelDirection"
    )}</label>
      <select id="md_dir" class="select">
        <option value="去程" ${rb === "去程" ? "selected" : ""}>${t(
    "dirOutLabel"
  )}</option>
        <option value="回程" ${rb === "回程" ? "selected" : ""}>${t(
    "dirInLabel"
  )}</option>
      </select>
    </div>
    <div class="field"><label class="label">${t(
      "labelDate"
    )}</label><div id="md_dates" class="options"></div></div>
    <div class="field"><label class="label">${t(
      "labelStation"
    )}</label><div id="md_stations" class="options"></div></div>
    <div class="field"><label class="label">${t(
      "labelSchedule"
    )}</label><div id="md_schedules" class="options"></div></div>
    <div class="field"><label class="label">${t(
      "labelPassengersShort"
    )}</label><select id="md_pax" class="select"></select><div id="md_hint" class="hint"></div></div>
    <div class="field"><label class="label">${t(
      "labelPhone"
    )}</label><input id="md_phone" class="input" value="${sanitize(
    String(row["手機"] || "")
  )}" /></div>
    <div class="field"><label class="label">${t(
      "labelEmail"
    )}</label><input id="md_email" class="input" value="${sanitize(
    String(row["信箱"] || "")
  )}" /></div>
    <div class="actions row" style="justify-content:flex-end">
      <button class="button btn-ghost" id="md_cancel">${t("back")}</button>
      <button class="button" id="md_save">${ts("modify")}</button>
    </div>
  `;

  holder.style.display = "block";

  let mdDirection = rb;
  let mdDate = fmtDateLabel(date);
  let mdStation = rb === "回程" ? pick : drop;
  let mdTime = fmtTimeLabel(time);
  let mdAvail = 0;

  function buildDateOptions() {
    const dateSet = new Set(
      allRows
        .filter((r) => String(r["去程 / 回程"]).trim() === mdDirection)
        .map((r) => fmtDateLabel(r["日期"]))
    );
    const sorted = [...dateSet].sort((a, b) => new Date(a) - new Date(b));
    const list = holder.querySelector("#md_dates");
    list.innerHTML = "";
    sorted.forEach((dateStr) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "opt-btn";
      btn.textContent = dateStr;
      if (dateStr === mdDate) btn.classList.add("active");
      btn.onclick = () => {
        mdDate = dateStr;
        list.querySelectorAll(".opt-btn").forEach((b) =>
          b.classList.remove("active")
        );
        btn.classList.add("active");
        buildStationOptions();
      };
      list.appendChild(btn);
    });
  }

  function buildStationOptions() {
    const stations = new Set(
      allRows
        .filter(
          (r) =>
            String(r["去程 / 回程"]).trim() === mdDirection &&
            fmtDateLabel(r["日期"]) === mdDate
        )
        .map((r) => String(r["站點"]).trim())
    );
    const list = holder.querySelector("#md_stations");
    list.innerHTML = "";
    [...stations].forEach((st) => {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "opt-btn";
      btn.textContent = st;
      if (st === mdStation) btn.classList.add("active");
      btn.onclick = () => {
        mdStation = st;
        list.querySelectorAll(".opt-btn").forEach((b) =>
          b.classList.remove("active")
        );
        btn.classList.add("active");
        buildScheduleOptions();
      };
      list.appendChild(btn);
    });
    buildScheduleOptions();
  }

  function buildScheduleOptions() {
    const list = holder.querySelector("#md_schedules");
    list.innerHTML = "";

    const entries = allRows
      .filter(
        (r) =>
          String(r["去程 / 回程"]).trim() === mdDirection &&
          fmtDateLabel(r["日期"]) === mdDate &&
          String(r["站點"]).trim() === mdStation
      )
      .sort((a, b) =>
        fmtTimeLabel(a["班次"]).localeCompare(fmtTimeLabel(b["班次"]))
      );

    entries.forEach((r) => {
      const timeVal = fmtTimeLabel(r["班次"] || r["車次"]);
      const availText = String(
        r["可預約人數"] || r["可約人數 / Available"] || ""
      ).trim();
      const baseAvail = Number(onlyDigits(availText)) || 0;

      const sameAsOriginal =
        rb === mdDirection &&
        fmtDateLabel(date) === mdDate &&
        mdStation === (rb === "回程" ? pick : drop) &&
        fmtTimeLabel(time) === timeVal;

      const availPlusSelf = baseAvail + (sameAsOriginal ? pax : 0);

      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "opt-btn";
      if (timeVal === mdTime) btn.classList.add("active");

      const texts = TEXTS[currentLang] || TEXTS.zh;
      const prefix = texts.paxHintPrefix || "";
      const suffixRaw = texts.paxHintSuffix || "";
      const suffixShort = suffixRaw.split(/[；;]/)[0] || suffixRaw;
      const includeSelfText = sameAsOriginal
        ? (I18N_STATUS[currentLang] || I18N_STATUS.zh).includeSelf
        : "";

      const paxInfo = `(${prefix}${availPlusSelf}${suffixShort}${includeSelfText})`;

      btn.innerHTML = `
        <span style="color:var(--primary);font-weight:700">${timeVal}</span>
        <span style="color:#777;font-size:13px">${paxInfo}</span>
      `;

      btn.onclick = () => {
        mdTime = timeVal;
        mdAvail = availPlusSelf;
        list.querySelectorAll(".opt-btn").forEach((b) =>
          b.classList.remove("active")
        );
        btn.classList.add("active");
        buildPax();
      };

      list.appendChild(btn);
    });

    buildPax();
  }

  function buildPax() {
    const sel = holder.querySelector("#md_pax");
    sel.innerHTML = "";
    const maxPassengers = Math.min(4, Math.max(0, mdAvail || pax || 4));
    for (let i = 1; i <= maxPassengers; i++) {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = String(i);
      sel.appendChild(opt);
    }
    sel.value = String(Math.min(pax, maxPassengers));
    const hint = holder.querySelector("#md_hint");
    hint.textContent =
      (TEXTS[currentLang] || TEXTS.zh).paxHintPrefix +
      (mdAvail || 0) +
      (TEXTS[currentLang] || TEXTS.zh).paxHintSuffix;
  }

  holder.querySelector("#md_dir").addEventListener("change", (e) => {
    mdDirection = e.target.value;
    mdStation = mdDirection === "回程" ? pick : drop;
    buildDateOptions();
  });

  holder.querySelector("#md_cancel").onclick = () => {
    holder.style.display = "none";
    showCheckDateStep();
  };


  holder.querySelector("#md_save").onclick = async () => {
    // 1️⃣ 讀取畫面上的修改值
    const passengers = Number(holder.querySelector("#md_pax").value || "1");
    const newPhone = (holder.querySelector("#md_phone").value || "").trim();
    const newEmail = (holder.querySelector("#md_email").value || "").trim();

    // 2️⃣ 前端格式驗證
    if (!phoneRegex.test(newPhone)) {
      showErrorCard(t("errPhone"));
      return;
    }
    if (!emailRegex.test(newEmail)) {
      showErrorCard(t("errEmail"));
      return;
    }

    try {
      showVerifyLoading(true);
      // 避免重複送出，先把編輯面板收起來
      holder.style.display = "none";

      const payload = {
        booking_id: bookingId,
        direction: mdDirection,
        date: mdDate,
        time: mdTime,
        passengers,
        pickLocation:
          mdDirection === "回程" ? mdStation : "福泰大飯店 Forte Hotel",
        dropLocation:
          mdDirection === "回程" ? "福泰大飯店 Forte Hotel" : mdStation,
        phone: newPhone,
        email: newEmail,
        station: mdStation,
        lang: getCurrentLang()
      };

      // 3️⃣ 呼叫後端做 modify
      const r = await fetch(OPS_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: "modify", data: payload })
      });

      let j = null;
      try {
        j = await r.json();
      } catch (e) {
        j = null;
      }

      const backendMsg =
        j && (j.error || j.code || j.detail || j.message || "");
      const isCapacityError =
        r.status === 409 ||
        backendMsg === "capacity_not_found" ||
        String(backendMsg || "").includes("capacity_not_found");

      // 4️⃣ HTTP 錯誤
      if (!r.ok) {
        if (isCapacityError) {
          showErrorCard(t("overPaxOrMissing"));
        } else {
          showErrorCard(t("updateFailedPrefix") + `HTTP ${r.status}`);
        }
        holder.style.display = "block";
        return;
      }

      // 5️⃣ 回傳內容錯誤
      if (!j || j.status !== "success") {
        if (isCapacityError) {
          showErrorCard(t("overPaxOrMissing"));
        } else {
          showErrorCard(
            (j && (j.detail || j.message)) || t("errorGeneric")
          );
        }
        holder.style.display = "block";
        return;
      }

      // 6️⃣ ✅ 修改成功：先重新查詢並更新列表
      const id = (document.getElementById("qBookId").value || "").trim();
      const phoneInput =
        (document.getElementById("qPhone").value || "").trim();
      const emailInput =
        (document.getElementById("qEmail").value || "").trim();

      const queryRes = await fetch(OPS_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "query",
          data: { booking_id: id, phone: phoneInput, email: emailInput }
        })
      });
      const queryData = await queryRes.json();
      lastQueryResults = Array.isArray(queryData)
        ? queryData
        : queryData.results || [];
      buildDateListFromResults(lastQueryResults);
      if (currentQueryDate) {
        openTicketsForDate(currentQueryDate);
      } else {
        showCheckDateStep();
      }

      // 7️⃣ 列表更新後再顯示成功動畫 ✅（你要的流程）
      showSuccessAnimation();
    } catch (e) {
      showErrorCard(t("updateFailedPrefix") + (e?.message || ""));
      holder.style.display = "block";
    } finally {
      showVerifyLoading(false);
    }
  };


  buildDateOptions();
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ====== 系統與資料 ====== */
async function refreshData() {
  showLoading(true);
  try {
    const res = await fetch(API_URL);
    const raw = await res.json();
    const headers = raw[0];
    const rows = raw.slice(1);
    allRows = rows
      .map((r) => {
        const o = {};
        headers.forEach((h, i) => (o[h] = r[i]));
        return o;
      })
      .filter((r) => r["去程 / 回程"] && r["日期"] && r["班次"] && r["站點"]);
    return true;
  } catch (e) {
    showErrorCard(t("refreshFailedPrefix") + (e?.message || ""));
    return false;
  } finally {
    showLoading(false);
  }
}

/* ====== 查詢班次（單一 ALL 清除鈕） ====== */
let scheduleData = {
  rows: [],
  directions: new Set(),
  dates: new Set(),
  stations: new Set(),
  selectedDirection: null,
  selectedDate: null,
  selectedStation: null
};

async function loadScheduleData() {
  const resultsEl = document.getElementById("scheduleResults");
  if (!resultsEl) return;

  resultsEl.innerHTML = `<div class="loading-text">${t("loading")}</div>`;
  try {
    const res = await fetch(API_URL + "?sheet=可預約班次(web)");
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const headers = data[0];
    const rows = data.slice(1);

    const directionIndex = headers.indexOf("去程 / 回程");
    const dateIndex = headers.indexOf("日期");
    const timeIndex = headers.indexOf("班次");
    const stationIndex = headers.indexOf("站點");
    const capacityIndex = headers.indexOf("可預約人數");

    scheduleData.rows = rows
      .map((row) => ({
        direction: row[directionIndex] || "",
        date: row[dateIndex] || "",
        time: row[timeIndex] || "",
        station: row[stationIndex] || "",
        capacity: row[capacityIndex] || ""
      }))
      .filter((row) => row.direction && row.date && row.time && row.station);

    scheduleData.directions = new Set(
      scheduleData.rows.map((r) => r.direction)
    );
    scheduleData.dates = new Set(scheduleData.rows.map((r) => r.date));
    scheduleData.stations = new Set(scheduleData.rows.map((r) => r.station));

    renderScheduleFilters();
    renderScheduleResults();
  } catch (error) {
    resultsEl.innerHTML = `<div class="empty-state">${t(
      "queryFailedPrefix"
    )}${sanitize(error.message)}</div>`;
  }
}

function renderScheduleFilters() {
  const allWrap = document.getElementById("allFilter");
  if (!allWrap) return;
  allWrap.innerHTML = "";
  const allBtn = document.createElement("button");
  allBtn.type = "button";
  allBtn.className = "filter-pill";
  allBtn.textContent = t("all");
  allBtn.onclick = () => {
    scheduleData.selectedDirection = null;
    scheduleData.selectedDate = null;
    scheduleData.selectedStation = null;
    renderScheduleFilters();
    renderScheduleResults();
  };
  allWrap.appendChild(allBtn);

  renderFilterPills(
    "directionFilter",
    [...scheduleData.directions],
    scheduleData.selectedDirection,
    (dir) => {
      scheduleData.selectedDirection =
        scheduleData.selectedDirection === dir ? null : dir;
      renderScheduleFilters();
      renderScheduleResults();
    }
  );
  renderFilterPills(
    "dateFilter",
    [...scheduleData.dates],
    scheduleData.selectedDate,
    (date) => {
      scheduleData.selectedDate =
        scheduleData.selectedDate === date ? null : date;
      renderScheduleFilters();
      renderScheduleResults();
    }
  );
  renderFilterPills(
    "stationFilter",
    [...scheduleData.stations],
    scheduleData.selectedStation,
    (station) => {
      scheduleData.selectedStation =
        scheduleData.selectedStation === station ? null : station;
      renderScheduleFilters();
      renderScheduleResults();
    }
  );
}

function renderFilterPills(containerId, items, selectedItem, onClick) {
  const container = document.getElementById(containerId);
  if (!container) return;
  container.innerHTML = "";

  // ✅ 站點用自訂排序：捷運 > 火車 > LALA
  if (containerId === "stationFilter") {
    items.sort((a, b) => {
      const pa = getStationPriority(a);
      const pb = getStationPriority(b);
      if (pa !== pb) return pa - pb;
      // 同一類型時，用字典序當次排序（避免順序亂跳）
      return String(a).localeCompare(String(b), "zh-Hant");
    });
  } else {
    // 其他（方向、日期）維持原本字串排序
    items.sort();
  }

  items.forEach((item) => {
    const pill = document.createElement("button");
    pill.type = "button";
    pill.className = "filter-pill" + (selectedItem === item ? " active" : "");

    if (containerId === "directionFilter") {
      if (item === "去程") pill.textContent = t("dirOutLabel");
      else if (item === "回程") pill.textContent = t("dirInLabel");
      else pill.textContent = item;
    } else {
      pill.textContent = item;
    }

    pill.onclick = () => onClick(item);
    container.appendChild(pill);
  });
}

function renderScheduleResults() {
  const container = document.getElementById('scheduleResults');
  if (!container) return;

  const filtered = scheduleData.rows.filter(row => {
    if (scheduleData.selectedDirection && row.direction !== scheduleData.selectedDirection) return false;
    if (scheduleData.selectedDate && row.date !== scheduleData.selectedDate) return false;
    if (scheduleData.selectedStation && row.station !== scheduleData.selectedStation) return false;
    return true;
  });

  if (filtered.length === 0) {
    container.innerHTML = `<div class="empty-state">${t('noSchedules')}</div>`;
    return;
  }

  const texts = TEXTS[currentLang] || TEXTS.zh;
  const capLabel = t("scheduleCapacityLabel");        // ✅ 這裡拿多語系字

  function translateDirection(direction) {
    if (direction === '去程') return texts.dirOutLabel || direction;
    if (direction === '回程') return texts.dirInLabel || direction;
    return direction;
  }

  container.innerHTML = filtered.map(row => {
    // 只抓數字，例如「可預約 / Available：7」→ "7"
    const digits = onlyDigits(row.capacity);
    const capNumber = digits || row.capacity; // 如果沒有數字就 fallback 原字串

    return `
      <div class="schedule-card">
        <div class="schedule-line">
          <span class="schedule-direction">${sanitize(translateDirection(row.direction))}</span>
          <span class="schedule-date">${sanitize(row.date)}</span>
          <span class="schedule-time">${sanitize(row.time)}</span>
        </div>
        <div class="schedule-line">
          <span class="schedule-station">${sanitize(row.station)}</span>
          <span class="schedule-capacity">${sanitize(capLabel)}：${sanitize(capNumber)}</span>
        </div>
      </div>
    `;
  }).join('');
}



/* ====== 系統設定載入（跑馬燈 + 圖片牆） ====== */
async function loadSystemConfig() {
  try {
    const url = `${API_URL}?sheet=系統`;
    const res = await fetch(url);
    const data = await res.json();

    if (!Array.isArray(data) || data.length === 0) return;

    // ========= 跑馬燈處理 =========
    let marqueeText = "";
    for (let i = 1; i <= 5; i++) {
      const row = data[i] || [];
      const text = row[3] || "";
      const flag = row[4] || "";

      if (
        /^(是|Y|1|TRUE)$/i.test(String(flag).trim()) &&
        String(text).trim()
      ) {
        marqueeText += String(text).trim() + "　　";
      }
    }

    marqueeData.text = marqueeText.trim();
    marqueeData.isLoaded = true;

    // 立即顯示跑馬燈
    showMarquee();

    // ========= 圖片牆處理 =========
    const gallery = document.getElementById("imageGallery");
    if (gallery) {
      gallery.innerHTML = "";
      for (let i = 7; i <= 11; i++) {
        const row = data[i] || [];
        const imgUrl = row[3] || "";
        const flag = row[4] || "";
        if (
          /^(是|Y|1|TRUE)$/i.test(String(flag).trim()) &&
          String(imgUrl).trim()
        ) {
          const img = document.createElement("img");
          img.className = "gallery-image";
          img.src = String(imgUrl).trim();
          gallery.appendChild(img);
        }
      }
    }
  } catch (err) {
    console.error("loadSystemConfig 錯誤:", err);
  }
}

/* ====== 其他工具 ====== */
function parseTripDateTime(dateStr, timeStr) {
  const iso = fmtDateLabel(dateStr);
  let y, m, d;
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const parts = iso.split("-").map((n) => parseInt(n, 10));
    y = parts[0];
    m = parts[1];
    d = parts[2];
  } else {
    const now = new Date();
    y = now.getFullYear();
    m = now.getMonth() + 1;
    d = now.getDate();
  }
  let H = 0,
    M = 0;
  if (timeStr) {
    const t = String(timeStr).trim().replace("：", ":");
    if (/^\d{1,2}\/\d{1,2}/.test(t)) {
      const [, hmPart] = t.split(" ");
      const hm = (hmPart || "00:00").slice(0, 5);
      const hhmm = hm.split(":");
      H = parseInt(hhmm[0] || "0", 10);
      M = parseInt(hhmm[1] || "0", 10);
    } else if (/^\d{1,2}:\d{1,2}/.test(t)) {
      const hm = t.slice(0, 5);
      const hhmm = hm.split(":");
      H = parseInt(hhmm[0] || "0", 10);
      M = parseInt(hhmm[1] || "0", 10);
    }
  }
  return new Date(y, m - 1, d, H, M, 0);
}

/* ====== 初始化 ====== */
function resetQuery() {
  const id = document.getElementById("qBookId");
  const phone = document.getElementById("qPhone");
  const email = document.getElementById("qEmail");
  if (id) id.value = "";
  if (phone) phone.value = "";
  if (email) email.value = "";
}

// === 功能開關（快速開關） ===
const FEATURE_TOGGLE = {
  LIVE_LOCATION: true
};

// === 即時位置渲染 ===
async function renderLiveLocationPlaceholder() {
  const sec = document.querySelector('[data-feature="liveLocation"]');
  if (!sec) return;

  const mount = document.getElementById("realtimeMount");
  if (!mount) return;

  // 檢查 GPS 系統總開關（從 booking-api 讀取）
  try {
    const apiUrl = "https://booking-api-995728097341.asia-east1.run.app/api/realtime/location";
    const r = await fetch(apiUrl);
    if (r.ok) {
      const data = await r.json();
      if (!data.gps_system_enabled) {
        // GPS 系統總開關關閉，隱藏整個區塊
        sec.style.display = "none";
        mount.innerHTML = "";
        return;
      }
    }
  } catch (e) {
    console.error("Check GPS system status error:", e);
  }

  // GPS 系統啟用，顯示並初始化
  sec.style.display = FEATURE_TOGGLE.LIVE_LOCATION ? "" : "none";
  if (!FEATURE_TOGGLE.LIVE_LOCATION) {
    mount.innerHTML = "";
    return;
  }
  initLiveLocation(mount);
}

// 站點座標映射（全局定義，供多處使用）
const stationCoords = {
  "1. 福泰大飯店 (去)": { lat: 25.055550556928008, lng: 121.63210245291367 },
  "福泰大飯店 Forte Hotel": { lat: 25.055550556928008, lng: 121.63210245291367 },  // 去程起點
  "2. 南港捷運站": { lat: 25.055017007293404, lng: 121.61818547695053 },
  "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": { lat: 25.055017007293404, lng: 121.61818547695053 },
  "3. 南港火車站": { lat: 25.052822671279454, lng: 121.60771823129633 },
  "南港火車站 Nangang Train Station": { lat: 25.052822671279454, lng: 121.60771823129633 },
  "4. LaLaport 購物中心": { lat: 25.05629820919232, lng: 121.61700981622211 },
  "LaLaport Shopping Park": { lat: 25.05629820919232, lng: 121.61700981622211 },
  "5. 福泰大飯店 (回)": { lat: 25.05483619868674, lng: 121.63115105443562 },
  "福泰大飯店(回) Forte Hotel (Back)": { lat: 25.05483619868674, lng: 121.63115105443562 }  // 回程終點
};

function initLiveLocation(mount) {
  const cfg = getLiveConfig();
  // 即時位置區塊：標題已在上一層父容器，手機版將狀態、班次、即將抵達、按鈕放在標題下；電腦版維持覆蓋在地圖上
  mount.innerHTML = `
    <!-- 手機版：資訊放在標題下（使用媒體查詢控制顯示） -->
    <div id="rt-info-mobile" style="margin-bottom:12px;padding:12px;background:#f9f9f9;border-radius:8px;display:none;">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
        <div id="rt-status-light" style="width:12px;height:12px;border-radius:50%;background:#28a745;box-shadow:0 0 8px rgba(40,167,69,0.6);"></div>
        <span id="rt-status-text" style="font-size:14px;color:#28a745;font-weight:700;">良好</span>
        <button id="rt-refresh" style="margin-left:auto;padding:6px 12px;background:#fff;border:1px solid #ddd;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;box-shadow:0 2px 4px rgba(0,0,0,0.1);">刷新</button>
      </div>
      <div id="rt-trip-info" style="font-size:15px;color:#333;margin:4px 0;font-weight:600;">班次: <span id="rt-trip-datetime"></span></div>
      <div id="rt-next-stop" style="font-size:15px;color:#333;margin:4px 0;font-weight:600;">即將抵達: <span id="rt-next-stop-name"></span></div>
    </div>
    <div id="rt-map-wrapper" style="position:relative;width:100%;height:500px;min-height:500px;border-radius:12px;overflow:hidden;">
      <div id="rt-map" style="width:100%;height:100%;"></div>
      <!-- 灰色透明遮罩，預設顯示 -->
      <div id="rt-overlay" style="position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:10;">
        <button id="rt-start-btn" class="button" style="padding:16px 32px;font-size:18px;font-weight:700;background:var(--primary);color:#fff;border:none;border-radius:12px;cursor:pointer;">查看即時位置</button>
      </div>
      <!-- 電腦版：左上角資訊覆蓋層（狀態燈、班次、即將抵達、刷新按鈕） -->
      <div id="rt-info-overlay" style="position:absolute;top:0;left:0;z-index:5;pointer-events:none;display:none;padding:12px;background:linear-gradient(to bottom, rgba(255,255,255,0.95), rgba(255,255,255,0.85));border-radius:0 0 12px 0;max-width:320px;">
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:8px;">
          <div id="rt-status-light-desktop" style="width:12px;height:12px;border-radius:50%;background:#28a745;box-shadow:0 0 8px rgba(40,167,69,0.6);"></div>
          <span id="rt-status-text-desktop" style="font-size:14px;color:#28a745;font-weight:700;">良好</span>
          <button id="rt-refresh-desktop" style="margin-left:auto;padding:6px 12px;background:#fff;border:1px solid #ddd;border-radius:6px;font-size:13px;font-weight:600;cursor:pointer;box-shadow:0 2px 4px rgba(0,0,0,0.1);pointer-events:auto;">刷新</button>
        </div>
        <div id="rt-trip-info-desktop" style="font-size:15px;color:#333;margin:4px 0;font-weight:600;">班次: <span id="rt-trip-datetime-desktop"></span></div>
        <div id="rt-next-stop-desktop" style="font-size:15px;color:#333;margin:4px 0;font-weight:600;">即將抵達: <span id="rt-next-stop-name-desktop"></span></div>
      </div>
      <!-- 班次結束提示 -->
      <div id="rt-ended-overlay" style="position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);display:none;align-items:center;justify-content:center;z-index:15;pointer-events:none;">
        <div style="text-align:center;color:#fff;font-size:20px;font-weight:700;">
          <div id="rt-ended-text">班次: <span id="rt-ended-datetime"></span> 已結束</div>
        </div>
      </div>
    </div>
  `;
  const overlayEl = mount.querySelector("#rt-overlay");
  const startBtn = mount.querySelector("#rt-start-btn");
  const infoOverlay = mount.querySelector("#rt-info-overlay");
  const infoMobile = mount.querySelector("#rt-info-mobile");
  
  // 檢測設備類型（使用媒體查詢或窗口寬度）
  const checkIsMobile = () => window.innerWidth <= 768;
  let isMobile = checkIsMobile();
  
  // 初始設置顯示（根據設備類型）
  if (isMobile) {
    if (infoMobile) infoMobile.style.display = "block";
    if (infoOverlay) infoOverlay.style.display = "none";
  } else {
    if (infoMobile) infoMobile.style.display = "none";
    if (infoOverlay) infoOverlay.style.display = "none"; // 初始隱藏，等待數據載入後顯示
  }
  
  // 監聽窗口大小變化
  const handleResize = () => {
    const wasMobile = isMobile;
    isMobile = checkIsMobile();
    if (wasMobile !== isMobile && infoMobile && infoOverlay) {
      // 設備類型改變時切換顯示
      if (isMobile) {
        infoMobile.style.display = "block";
        infoOverlay.style.display = "none";
      } else {
        infoMobile.style.display = "none";
        // 電腦版只有在有數據時才顯示
        if (currentTripData && currentTripData.current_trip_status !== "ended") {
          infoOverlay.style.display = "block";
        }
      }
    }
  };
  window.addEventListener("resize", handleResize);
  
  // 根據設備選擇對應的元素（手機版和電腦版都有各自的元素）
  const statusLight = mount.querySelector("#rt-status-light");
  const statusText = mount.querySelector("#rt-status-text");
  const statusLightDesktop = mount.querySelector("#rt-status-light-desktop");
  const statusTextDesktop = mount.querySelector("#rt-status-text-desktop");
  const tripDatetimeEl = mount.querySelector("#rt-trip-datetime");
  const tripDatetimeElDesktop = mount.querySelector("#rt-trip-datetime-desktop");
  const nextStopNameEl = mount.querySelector("#rt-next-stop-name");
  const nextStopNameElDesktop = mount.querySelector("#rt-next-stop-name-desktop");
  const btnRefresh = mount.querySelector("#rt-refresh");
  const btnRefreshDesktop = mount.querySelector("#rt-refresh-desktop");
  
  // 更新狀態的輔助函數（同時更新手機版和電腦版）
  const updateStatus = (color, text) => {
    if (statusLight && statusText) {
      statusLight.style.background = color;
      statusLight.style.boxShadow = `0 0 8px ${color}66`;
      statusText.textContent = text;
      statusText.style.color = color;
    }
    if (statusLightDesktop && statusTextDesktop) {
      statusLightDesktop.style.background = color;
      statusLightDesktop.style.boxShadow = `0 0 8px ${color}66`;
      statusTextDesktop.textContent = text;
      statusTextDesktop.style.color = color;
    }
  };
  
  // 更新班次信息的輔助函數
  const updateTripInfo = (datetime) => {
    if (tripDatetimeEl) tripDatetimeEl.textContent = datetime || "";
    if (tripDatetimeElDesktop) tripDatetimeElDesktop.textContent = datetime || "";
  };
  
  // 更新下一站的輔助函數（同時更新手機版和電腦版）
  const updateNextStop = (stopName) => {
    const displayText = stopName || "未知";
    if (nextStopNameEl) nextStopNameEl.textContent = displayText;
    if (nextStopNameElDesktop) nextStopNameElDesktop.textContent = displayText;
  };
  const endedOverlay = mount.querySelector("#rt-ended-overlay");
  const endedTextEl = mount.querySelector("#rt-ended-text");
  const endedDatetimeEl = mount.querySelector("#rt-ended-datetime");
  const mapEl = mount.querySelector("#rt-map");
  const mapWrapper = mount.querySelector("#rt-map-wrapper");

  const loadMaps = () =>
    new Promise((resolve, reject) => {
      if (!cfg.key) { 
        if (startBtn) startBtn.textContent = "缺少地圖 key";
        return; 
      }
      const s = document.createElement("script");
      s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(cfg.key)}&libraries=places`;
      s.async = true;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });

  let map, marker, mainPolyline, walkedPolyline, stationMarkers = [];
  let currentTripData = null;
  let isInitialized = false;
  let pulseMarker = null; // 光子動畫標記（主標記）
  let pulseMarkerLayers = []; // 光子動畫多層標記陣列
  let pulseAnimation = null; // 光子動畫定時器
  let markerCircle = null; // 司機位置圓形外圈
  
  // 光子動畫函數：沿著路線移動
  const animatePulseAlongPath = (path) => {
    if (!path || path.length < 2) {
      // 清除所有層的標記
      if (pulseMarker) {
        pulseMarker.setMap(null);
        pulseMarker = null;
      }
      pulseMarkerLayers.forEach(layer => {
        if (layer) layer.setMap(null);
      });
      pulseMarkerLayers = [];
      return;
    }
    
    // 清除舊的動畫
    if (pulseAnimation) {
      clearInterval(pulseAnimation);
      pulseAnimation = null;
    }
    
    let currentIndex = 0;
    const totalDistance = path.length - 1;
    const duration = 1200; // 1.2秒完成一次循環（加快速度）
    const interval = 30; // 每30ms更新一次（更流暢）
    const steps = duration / interval;
    
    // 創建光子標記（如果不存在）- 泛白光、光芒效果
    if (!pulseMarker || pulseMarkerLayers.length === 0) {
      // 清除舊的標記
      if (pulseMarker) {
        pulseMarker.setMap(null);
      }
      pulseMarkerLayers.forEach(layer => {
        if (layer) layer.setMap(null);
      });
      pulseMarkerLayers = [];
      
      // 創建外層圓形（光芒效果）
      pulseMarker = new google.maps.Marker({
        map: map,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 12, // 外層大圓（光芒效果）
          fillColor: "#FFFFFF",
          fillOpacity: 0.4, // 外層低透明度
          strokeColor: "#FFFFFF",
          strokeWeight: 3,
          strokeOpacity: 0.6
        },
        zIndex: 100
      });
      
      // 創建中層圓形（增強光芒效果）
      const pulseMarkerMiddle = new google.maps.Marker({
        map: map,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 8, // 中層圓
          fillColor: "#FFFFFF",
          fillOpacity: 0.7,
          strokeColor: "#FFFFFF",
          strokeWeight: 2,
          strokeOpacity: 0.8
        },
        zIndex: 101
      });
      
      // 創建內層圓形（核心）
      const pulseMarkerInner = new google.maps.Marker({
        map: map,
        icon: {
          path: google.maps.SymbolPath.CIRCLE,
          scale: 5, // 內層小圓
          fillColor: "#FFFFFF",
          fillOpacity: 1.0,
          strokeColor: "#FFFFFF",
          strokeWeight: 1,
          strokeOpacity: 1.0
        },
        zIndex: 102
      });
      
      // 將多層標記存儲到陣列
      pulseMarkerLayers = [pulseMarkerMiddle, pulseMarkerInner];
    }
    
    // 計算兩點間距離
    const getDistance = (p1, p2) => {
      const lat1 = typeof p1.lat === 'function' ? p1.lat() : p1.lat;
      const lng1 = typeof p1.lng === 'function' ? p1.lng() : p1.lng;
      const lat2 = typeof p2.lat === 'function' ? p2.lat() : p2.lat;
      const lng2 = typeof p2.lng === 'function' ? p2.lng() : p2.lng;
      return Math.sqrt(Math.pow(lat2 - lat1, 2) + Math.pow(lng2 - lng1, 2));
    };
    
    // 在兩點間插值
    const interpolate = (p1, p2, fraction) => {
      const lat1 = typeof p1.lat === 'function' ? p1.lat() : p1.lat;
      const lng1 = typeof p1.lng === 'function' ? p1.lng() : p1.lng;
      const lat2 = typeof p2.lat === 'function' ? p2.lat() : p2.lat;
      const lng2 = typeof p2.lng === 'function' ? p2.lng() : p2.lng;
      return {
        lat: lat1 + (lat2 - lat1) * fraction,
        lng: lng1 + (lng2 - lng1) * fraction
      };
    };
    
    let step = 0;
    pulseAnimation = setInterval(() => {
      if (currentIndex >= path.length - 1) {
        currentIndex = 0;
        step = 0;
      }
      
      const p1 = path[currentIndex];
      const p2 = path[currentIndex + 1];
      const fraction = step / steps;
      
      if (fraction >= 1) {
        currentIndex++;
        step = 0;
        if (currentIndex >= path.length - 1) {
          currentIndex = 0;
        }
      } else {
        const position = interpolate(p1, p2, fraction);
        // 更新所有層的位置
        if (pulseMarker) {
          pulseMarker.setPosition(position);
        }
        pulseMarkerLayers.forEach(layer => {
          if (layer) layer.setPosition(position);
        });
        step++;
      }
    }, interval);
  };
  const ensureFirebase = async () => {
    if (!cfg.fbdb || !cfg.fbkey) return false;
    // 動態載入 Firebase SDK
    await new Promise((resolve, reject) => {
      if (window.firebase && firebase.app) { resolve(); return; }
      const s = document.createElement("script");
      s.src = "https://www.gstatic.com/firebasejs/10.11.0/firebase-app.js";
      s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
    });
    await new Promise((resolve, reject) => {
      if (window.firebase && firebase.database) { resolve(); return; }
      const s = document.createElement("script");
      s.src = "https://www.gstatic.com/firebasejs/10.11.0/firebase-database.js";
      s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
    });
    try {
      if (!firebase.apps || !firebase.apps.length) {
        firebase.initializeApp({ apiKey: cfg.fbkey, databaseURL: cfg.fbdb });
      }
    } catch {}
    return true;
  };

  // 從站點列表繪製路線的輔助函數
  const drawRouteFromStops = async (stops, mapInstance) => {
    return new Promise((resolve) => {
      if (!mapInstance || !google.maps) {
        resolve();
        return;
      }
      const directionsService = new google.maps.DirectionsService();
      const directionsRenderer = new google.maps.DirectionsRenderer({ 
        map: mapInstance,
        suppressMarkers: true // 不顯示默認標記，我們自己繪製
      });
      
      // 確保至少有2個站點
      if (stops.length < 2) {
        resolve();
        return;
      }
      
      const waypoints = stops.length > 2 ? stops.slice(1, -1).map(stop => {
        const coord = typeof stop === "object" && stop.lat ? stop : stationCoords[stop.name || stop] || stop;
        if (coord && coord.lat && coord.lng) {
          return { location: { lat: coord.lat, lng: coord.lng } };
        }
        return null;
      }).filter(Boolean) : [];
      
      const origin = stops[0];
      const destination = stops[stops.length - 1];
      const originCoord = typeof origin === "object" && origin.lat ? origin : stationCoords[origin.name || origin] || origin;
      const destCoord = typeof destination === "object" && destination.lat ? destination : stationCoords[destination.name || destination] || destination;
      
      if (!originCoord || !originCoord.lat || !destCoord || !destCoord.lat) {
        resolve();
        return;
      }
      
      directionsService.route({
        origin: { lat: originCoord.lat, lng: originCoord.lng },
        destination: { lat: destCoord.lat, lng: destCoord.lng },
        waypoints: waypoints,
        travelMode: google.maps.TravelMode.DRIVING,
        optimizeWaypoints: false // 保持站點順序
      }, (result, status) => {
        if (status === "OK" && result.routes && result.routes.length > 0) {
          const route = result.routes[0];
          const path = route.overview_path;
          if (mainPolyline) mainPolyline.setMap(null);
          mainPolyline = new google.maps.Polyline({ 
            path: path, 
            strokeColor: "#87CEEB", // 淺藍色（未走過的路線）
            strokeOpacity: 0.8, 
            strokeWeight: 6, 
            map: mapInstance,
            zIndex: 1
          });
          
          // 調整地圖視圖以包含所有站點
          const bounds = new google.maps.LatLngBounds();
          path.forEach(pt => bounds.extend(pt));
          stops.forEach(stop => {
            const coord = typeof stop === "object" && stop.lat ? stop : stationCoords[stop.name || stop] || stop;
            if (coord && coord.lat && coord.lng) {
              bounds.extend({ lat: coord.lat, lng: coord.lng });
            }
          });
          mapInstance.fitBounds(bounds);
        }
        resolve();
      });
    });
  };

  const drawRoute = async (tripData) => {
    try {
      if (!tripData || !tripData.current_trip_route) {
        // 如果沒有路線數據，使用站點數據繪製基本路線
        const stations = tripData.current_trip_stations?.stops || [];
        if (stations.length > 0) {
          // 使用站點名稱對應座標
          const displayStops = stations.map(name => {
            const coord = stationCoords[name] || stationCoords[name.replace(/\(回\)|\(Back\)/g, "").trim()];
            if (coord) {
              return { name, lat: coord.lat, lng: coord.lng };
            }
            return null;
          }).filter(Boolean);
          
          // 確保路線終點固定為飯店（寫死邏輯）
          if (displayStops.length > 0) {
            const hotelBackCoord = stationCoords["福泰大飯店(回) Forte Hotel (Back)"];
            if (hotelBackCoord) {
              // 強制將最後一站設為回程飯店
              displayStops[displayStops.length - 1] = { 
                name: "福泰大飯店(回) Forte Hotel (Back)", 
                lat: hotelBackCoord.lat, 
                lng: hotelBackCoord.lng 
              };
            }
            
            // 使用 Google Directions API 生成路線
            await drawRouteFromStops(displayStops, map);
          }
        }
        return;
      }
      
      const route = tripData.current_trip_route;
      const stops = route.stops || [];
      const path = route.polyline?.path || null;
      
      // 清除舊的標記
      stationMarkers.forEach(m => m.setMap(null));
      stationMarkers = [];
      
      // 確保路線終點固定為飯店（寫死邏輯）
      let displayStops = [...stops];
      const hotelBackCoord = stationCoords["福泰大飯店(回) Forte Hotel (Back)"];
      if (hotelBackCoord && displayStops.length > 0) {
        // 強制將最後一站設為回程飯店
        displayStops[displayStops.length - 1] = { 
          name: "福泰大飯店(回) Forte Hotel (Back)", 
          lat: hotelBackCoord.lat, 
          lng: hotelBackCoord.lng 
        };
      }
      
      // 將站點名稱轉換為座標對象
      displayStops = displayStops.map(stop => {
        if (typeof stop === "object" && stop.lat && stop.lng) {
          return stop;
        }
        const name = typeof stop === "string" ? stop : (stop.name || "");
        const coord = stationCoords[name] || stationCoords[name.replace(/\(回\)|\(Back\)/g, "").trim()];
        if (coord) {
          return { name, lat: coord.lat, lng: coord.lng };
        }
        return null;
      }).filter(Boolean);
      
      // 獲取站點全名的輔助函數
      const getStationFullName = (stop, idx, totalStops) => {
        const stopName = typeof stop === "object" && stop.name ? stop.name : (typeof stop === "string" ? stop : "");
        const coord = typeof stop === "object" && stop.lat ? stop : stationCoords[stopName] || stop;
        
        // 根據座標匹配站點全名
        if (coord && coord.lat && coord.lng) {
          // 站點 1（第一個）
          if (idx === 0) {
            return "福泰大飯店 Forte Hotel";
          }
          // 最後一站
          if (idx === totalStops - 1) {
            return "福泰大飯店(回) Forte Hotel (Back)";
          }
          // 根據座標匹配其他站點
          const lat = coord.lat || (typeof coord === "object" && coord.lat ? coord.lat : null);
          const lng = coord.lng || (typeof coord === "object" && coord.lng ? coord.lng : null);
          
          if (lat === 25.055017007293404 && lng === 121.61818547695053) {
            return "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3";
          } else if (lat === 25.052822671279454 && lng === 121.60771823129633) {
            return "南港火車站 Nangang Train Station";
          } else if (lat === 25.05629820919232 && lng === 121.61700981622211) {
            return "LaLaport Shopping Park";
          } else if (lat === 25.055550556928008 && lng === 121.63210245291367) {
            return "福泰大飯店 Forte Hotel";
          } else if (lat === 25.05483619868674 && lng === 121.63115105443562) {
            return "福泰大飯店(回) Forte Hotel (Back)";
          }
        }
        
        // 如果無法匹配，返回原始名稱或默認值
        return stopName || `站點 ${idx + 1}`;
      };
      
      // 獲取站點顯示標籤的輔助函數
      const getStationDisplayLabel = (stop, idx, totalStops) => {
        if (idx === 0) {
          return "福泰大飯店 Forte Hotel";
        } else if (idx === totalStops - 1) {
          return "終站";
        } else {
          return String(idx + 1);
        }
      };
      
      displayStops.forEach((stop, idx) => {
        const coord = typeof stop === "object" && stop.lat ? stop : stationCoords[stop.name || stop] || stop;
        if (coord && coord.lat && coord.lng) {
          const fullName = getStationFullName(stop, idx, displayStops.length);
          const displayLabel = getStationDisplayLabel(stop, idx, displayStops.length);
          
          const marker = new google.maps.Marker({
            position: { lat: coord.lat, lng: coord.lng },
            map: map,
            label: { 
              text: displayLabel, 
              color: "#fff",
              fontSize: idx === 0 || idx === displayStops.length - 1 ? "11px" : "14px",
              fontWeight: idx === 0 || idx === displayStops.length - 1 ? "bold" : "normal"
            },
            icon: {
              path: google.maps.SymbolPath.CIRCLE,
              scale: idx === 0 || idx === displayStops.length - 1 ? 14 : 12,
              fillColor: "#0b63ce",
              fillOpacity: 1,
              strokeColor: "#fff",
              strokeWeight: 2
            },
            title: fullName // 滑鼠懸停時顯示全名
          });
          
          // 添加點擊事件，顯示 InfoWindow
          marker.addListener('click', () => {
            const infoWindow = new google.maps.InfoWindow({
              content: `<div style="padding: 8px; font-weight: 600; font-size: 14px;">${fullName}</div>`
            });
            infoWindow.open(map, marker);
            // 3秒後自動關閉
            setTimeout(() => {
              infoWindow.close();
            }, 3000);
          });
          
          stationMarkers.push(marker);
        }
      });
      
      // 繪製路線
      if (path && Array.isArray(path) && path.length > 1) {
        const gPath = path.map(p => new google.maps.LatLng(p.lat, p.lng));
        if (mainPolyline) mainPolyline.setMap(null);
        mainPolyline = new google.maps.Polyline({ 
          path: gPath, 
          strokeColor: "#87CEEB", // 淺藍色（未走過的路線）
          strokeOpacity: 0.8, 
          strokeWeight: 6, 
          map,
          zIndex: 1
        });
        const bounds = new google.maps.LatLngBounds();
        gPath.forEach(pt => bounds.extend(pt));
        if (displayStops.length > 0) {
          displayStops.forEach(stop => {
            const coord = typeof stop === "object" && stop.lat ? stop : stationCoords[stop.name || stop] || stop;
            if (coord && coord.lat && coord.lng) {
              bounds.extend({ lat: coord.lat, lng: coord.lng });
            }
          });
        }
        map.fitBounds(bounds);
      } else if (displayStops.length >= 2) {
        // 如果沒有 polyline，使用 Google Directions API 生成路線
        await drawRouteFromStops(displayStops, map);
      }
    } catch (e) {
      console.error("Draw route error:", e);
    }
  };
  const fetchLocation = async () => {
    try {
      // 從 booking-api 讀取即時位置資料
      const apiUrl = "https://booking-api-995728097341.asia-east1.run.app/api/realtime/location";
      const r = await fetch(apiUrl);
      if (!r.ok) {
        updateStatus("#dc3545", "連線失敗");
        return;
      }
      const data = await r.json();
      
      // 檢查 GPS 系統總開關
      if (!data.gps_system_enabled) {
        if (overlayEl) overlayEl.style.display = "flex";
        if (isMobile) {
          if (infoMobile) infoMobile.style.display = "none";
        } else {
          if (infoOverlay) infoOverlay.style.display = "none";
        }
        return;
      }
      
      // 檢查班次狀態
      if (data.current_trip_status === "ended") {
        if (endedOverlay) {
          endedOverlay.style.display = "flex";
          endedDatetimeEl.textContent = data.last_trip_datetime || data.current_trip_datetime || "";
        }
        if (isMobile) {
          if (infoMobile) infoMobile.style.display = "none";
        } else {
          if (infoOverlay) infoOverlay.style.display = "none";
        }
        return;
      } else {
        if (endedOverlay) endedOverlay.style.display = "none";
        if (isMobile) {
          if (infoMobile) infoMobile.style.display = "block";
        } else {
          if (infoOverlay) infoOverlay.style.display = "block";
        }
      }
      
      // 更新班次信息
      if (data.current_trip_datetime) {
        updateTripInfo(data.current_trip_datetime);
      }
      
      // 更新司機位置
      const driverLoc = data.driver_location;
      if (driverLoc && typeof driverLoc.lat === "number" && typeof driverLoc.lng === "number") {
        const pos = { lat: driverLoc.lat, lng: driverLoc.lng };
        if (marker) {
          marker.setPosition(pos);
          map.panTo(pos);
        }
        // 更新接駁車圖示標記位置
        if (busIconMarker) {
          busIconMarker.setPosition(pos);
        }
        // 更新圓形外圈位置
        if (markerCircle) {
          markerCircle.setCenter(pos);
        }
        
        // 更新已走過的路線（橘色）
        if (mainPolyline) {
          const path = mainPolyline.getPath().getArray();
          let nearestIdx = 0, best = Infinity;
          for (let i = 0; i < path.length; i++) {
            const dx = path[i].lat() - pos.lat, dy = path[i].lng() - pos.lng;
            const dist = dx * dx + dy * dy;
            if (dist < best) { best = dist; nearestIdx = i; }
          }
          if (walkedPolyline) walkedPolyline.setMap(null);
          walkedPolyline = new google.maps.Polyline({ 
            path: path.slice(0, Math.max(1, nearestIdx + 1)), 
            strokeColor: "#28a745", // 綠色（走過的路線）
            strokeOpacity: 1, 
            strokeWeight: 8, 
            map,
            zIndex: 2
          });
          
          // 光子動畫：沿著未走過的路線移動
          if (nearestIdx < path.length - 1) {
            const remainingPath = path.slice(nearestIdx);
            animatePulseAlongPath(remainingPath);
          } else {
            // 路線已完成，移除光子
            if (pulseMarker) {
              pulseMarker.setMap(null);
              pulseMarker = null;
            }
            if (pulseMarkerLayers && pulseMarkerLayers.length > 0) {
              pulseMarkerLayers.forEach(layer => {
                if (layer) layer.setMap(null);
              });
              pulseMarkerLayers = [];
            }
          }
        }
        
        updateStatus("#28a745", "良好");
      } else {
        updateStatus("#ffc107", "連線中");
      }
      
      // 更新下一站信息（判斷是否在發車時間前，並根據司機位置判斷下一站）
      const stations = data.current_trip_stations?.stops || [];
      const tripDateTime = data.current_trip_datetime;
      const route = data.current_trip_route;
      const nextStationFromFirebase = data.current_trip_station || "";  // 從Firebase讀取即將前往的站點
      if (nextStopNameEl) {
        if (tripDateTime) {
          // 解析班次時間
          const [datePart, timePart] = tripDateTime.split(" ");
          if (datePart && timePart) {
            const [year, month, day] = datePart.split(/[\/\-]/);
            const [hour, minute] = timePart.split(":");
            const tripTime = new Date(parseInt(year), parseInt(month) - 1, parseInt(day), parseInt(hour), parseInt(minute || 0));
            const now = new Date();
            
            // 如果還沒到發車時間，顯示"準備發車中"
            if (now < tripTime) {
              updateNextStop("準備發車中");
            } else if (nextStationFromFirebase) {
              // 優先使用Firebase中的current_trip_station（司機按了下一站後更新的）
              updateNextStop(nextStationFromFirebase);
            } else if (stations.length > 0 && driverLoc && typeof driverLoc.lat === "number" && route && route.stops && route.stops.length > 0) {
              // 已發車，根據司機位置判斷下一站
              const routeStops = route.stops;
              // 找到司機位置最接近的站點索引
              let nearestIdx = 0;
              let minDist = Infinity;
              routeStops.forEach((stop, idx) => {
                const coord = typeof stop === "object" && stop.lat ? stop : stationCoords[stop.name || stop] || stop;
                if (coord && coord.lat && coord.lng) {
                  const dx = coord.lat - driverLoc.lat;
                  const dy = coord.lng - driverLoc.lng;
                  const dist = dx * dx + dy * dy;
                  if (dist < minDist) {
                    minDist = dist;
                    nearestIdx = idx;
                  }
                }
              });
              // 下一站是最近站點的下一站（如果是最後一站，下一站是第一站形成閉環）
              const nextIdx = (nearestIdx + 1) % routeStops.length;
              const nextStop = routeStops[nextIdx];
              let nextStopName = "未知";
              if (typeof nextStop === "object" && nextStop.name) {
                nextStopName = nextStop.name;
              } else if (typeof nextStop === "string") {
                nextStopName = nextStop;
              } else if (typeof nextStop === "object" && nextStop.lat) {
                // 如果是座標對象，查找對應的站點名稱
                const found = Object.entries(stationCoords).find(([name, coord]) => 
                  Math.abs(coord.lat - nextStop.lat) < 0.0001 && Math.abs(coord.lng - nextStop.lng) < 0.0001
                );
                nextStopName = found ? found[0] : "未知";
              }
              updateNextStop(nextStopName);
            } else if (nextStationFromFirebase) {
              // 優先使用Firebase中的current_trip_station
              updateNextStop(nextStationFromFirebase);
            } else if (stations.length > 0) {
              // 沒有司機位置或路線數據，但已發車，顯示第二站（第一站是飯店）
              const nextStop = stations.length > 1 ? stations[1] : stations[0];
              let nextStopName = "未知";
              if (typeof nextStop === "object" && nextStop.name) {
                nextStopName = nextStop.name;
              } else if (typeof nextStop === "string") {
                nextStopName = nextStop;
              }
              updateNextStop(nextStopName);
            } else {
              updateNextStop("未知");
            }
          } else {
            // 優先使用Firebase中的current_trip_station
            if (nextStationFromFirebase) {
              updateNextStop(nextStationFromFirebase);
            } else {
              const nextStopName = stations.length > 0 ? (typeof stations[0] === "object" && stations[0].name ? stations[0].name : stations[0] || "未知") : "未知";
              updateNextStop(nextStopName);
            }
          }
        } else if (nextStationFromFirebase) {
          // 優先使用Firebase中的current_trip_station
          updateNextStop(nextStationFromFirebase);
        } else if (stations.length > 0) {
          const nextStopName = typeof stations[0] === "object" && stations[0].name ? stations[0].name : (stations[0] || "未知");
          updateNextStop(nextStopName);
        } else {
          updateNextStop("未知");
        }
      }
      
      currentTripData = data;
    } catch (e) {
      console.error("Fetch location error:", e);
      updateStatus("#dc3545", "錯誤");
    }
  };

  // 初始化地圖（點擊"查看即時位置"按鈕後）
  let initMap = async () => {
    if (isInitialized) return;
    isInitialized = true;
    
    await loadMaps();
    
    // 灰白黑色地圖樣式
    const mapStyles = [
      {
        featureType: "all",
        elementType: "geometry",
        stylers: [{ color: "#f5f5f5" }]
      },
      {
        featureType: "all",
        elementType: "labels.text.fill",
        stylers: [{ color: "#666666" }]
      },
      {
        featureType: "all",
        elementType: "labels.text.stroke",
        stylers: [{ color: "#ffffff" }]
      },
      {
        featureType: "road",
        elementType: "geometry",
        stylers: [{ color: "#e0e0e0" }]
      },
      {
        featureType: "water",
        elementType: "geometry",
        stylers: [{ color: "#d0d0d0" }]
      },
      {
        featureType: "poi",
        elementType: "all",
        stylers: [{ visibility: "off" }]
      },
      {
        featureType: "poi.business",
        elementType: "all",
        stylers: [{ visibility: "off" }]
      },
      {
        featureType: "poi.attraction",
        elementType: "all",
        stylers: [{ visibility: "off" }]
      },
      {
        featureType: "poi.park",
        elementType: "all",
        stylers: [{ visibility: "off" }]
      },
      {
        featureType: "transit",
        elementType: "all",
        stylers: [{ visibility: "off" }]
      }
    ];
    
    // 初始化地圖
    map = new google.maps.Map(mapEl, { 
      center: { lat: 25.055550556928008, lng: 121.63210245291367 }, 
      zoom: 14, 
      disableDefaultUI: false, 
      zoomControl: true, 
      mapTypeControl: false, 
      streetViewControl: false,
      styles: mapStyles
    });
    
    // 創建司機位置標記（圓形顯示）
    // 使用圓形標記作為背景
    marker = new google.maps.Marker({ 
      position: { lat: 25.055550556928008, lng: 121.63210245291367 }, 
      map, 
      title: "司機位置",
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: 20,
        fillColor: "#4285F4",
        fillOpacity: 1,
        strokeColor: "#fff",
        strokeWeight: 3
      },
      zIndex: 10
    });
    
    // 在圓形標記上方疊加接駁車圖示
    const busImageIcon = {
      url: '/images/接駁車圖示.png',
      scaledSize: new google.maps.Size(28, 28),
      anchor: new google.maps.Point(14, 14)
    };
    
    busIconMarker = new google.maps.Marker({
      position: { lat: 25.055550556928008, lng: 121.63210245291367 },
      map,
      icon: busImageIcon,
      zIndex: 11,
      optimized: false
    });
    
    // 添加圓形外圈效果
    markerCircle = new google.maps.Circle({
      strokeColor: "#4285F4",
      strokeOpacity: 0.6,
      strokeWeight: 2,
      fillColor: "#4285F4",
      fillOpacity: 0.2,
      map: map,
      center: { lat: 25.055550556928008, lng: 121.63210245291367 },
      radius: 30
    });
    
    // 隱藏遮罩，顯示資訊
    if (overlayEl) overlayEl.style.display = "none";
    if (isMobile) {
      if (infoMobile) infoMobile.style.display = "block";
    } else {
      if (infoOverlay) infoOverlay.style.display = "block";
    }
    
    // 首次獲取數據並繪製路線
    await fetchLocation();
    if (currentTripData) {
      await drawRoute(currentTripData);
    }
  };
  
  // 預設每3分鐘自動刷新
  const AUTO_REFRESH_MS = 3 * 60 * 1000;
  let autoTimer = null;
  
  // 開始自動刷新（僅在初始化後）
  const startAutoRefresh = () => {
    if (autoTimer) clearInterval(autoTimer);
    autoTimer = setInterval(async () => {
      if (isInitialized) {
        await fetchLocation();
        if (currentTripData) {
          await drawRoute(currentTripData);
        }
      }
    }, AUTO_REFRESH_MS);
  };
  
  // 包裝 initMap 以在初始化完成後開始自動刷新
  const wrappedInitMap = async () => {
    await initMap();
    startAutoRefresh();
  };
  
  // "查看即時位置"按鈕點擊事件
  if (startBtn) {
    startBtn.addEventListener("click", wrappedInitMap);
  }
  
  // 刷新按鈕點擊事件（手機版和電腦版）
  if (btnRefresh) {
    btnRefresh.addEventListener("click", async () => {
      await fetchLocation();
      if (currentTripData) {
        await drawRoute(currentTripData);
      }
    });
  }
  if (btnRefreshDesktop) {
    btnRefreshDesktop.addEventListener("click", async () => {
      await fetchLocation();
      if (currentTripData) {
        await drawRoute(currentTripData);
      }
    });
  }
}

async function init() {
  const tday = todayISO();
  const ci = document.getElementById('checkInDate');
  const co = document.getElementById('checkOutDate');
  const dining = document.getElementById('diningDate');

  if (ci) ci.value = tday;
  if (co) co.value = tday;
  if (dining) dining.value = tday;

  hardResetOverlays();

  // 1. 先套語系，避免一開始有文字還是舊語言
  applyI18N();

  // 2. 載入系統設定（會順便把跑馬燈文字載入 + showMarquee）
  await loadSystemConfig();

  // 3. 顯示預約分頁（此時 marqueeData 已經有內容）
  showPage('reservation');

  // 4. 其他 UI 初始化
  handleScroll();
  // 使用 try-catch 確保錯誤不會阻塞頁面
  try {
    await renderLiveLocationPlaceholder();
  } catch (e) {
    console.error("renderLiveLocationPlaceholder error:", e);
  }
}


document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".actions").forEach((a) => {
    const btns = a.querySelectorAll("button");
    if (btns.length === 3) a.classList.add("has-three");
  });
  document.querySelectorAll(".ticket-actions").forEach((a) => {
    const btns = a.querySelectorAll("button");
    if (btns.length === 3) a.classList.add("has-three");
  });
  ["stopHotel", "stopMRT", "stopTrain", "stopLala"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) el.classList.remove("open");
  });

  // 使用 try-catch 確保 init() 的錯誤不會阻塞整個頁面
  init().catch(e => {
    console.error("init() error:", e);
    // 即使初始化失敗，也要確保按鈕可以點擊
    try {
      showPage('reservation');
    } catch (e2) {
      console.error("showPage error in init catch:", e2);
    }
  });
});

window.addEventListener("scroll", handleScroll, { passive: true });
window.addEventListener("resize", handleScroll, { passive: true });

/* ====== 解析/過期判斷 (查詢頁用) ====== */
function getDateFromCarDateTime(carDateTime) {
  if (!carDateTime) return "";
  const parts = String(carDateTime).split(' ');
  if (parts.length < 1) return "";
  const datePart = parts[0];
  return datePart.replace(/\//g, '-');
}
function getTimeFromCarDateTime(carDateTime) {
  if (!carDateTime) return "00:00";
  const parts = String(carDateTime).split(' ');
  return parts.length > 1 ? parts[1] : "00:00";
}
function isExpiredByCarDateTime(carDateTime) {
  if (!carDateTime) return true;
  try {
    const [datePart, timePart] = String(carDateTime).split(' ');
    const [year, month, day] = datePart.split('/').map(Number);
    const [hour, minute] = timePart.split(':').map(Number);
    const tripTime = new Date(year, month - 1, day, hour, minute, 0).getTime();
    return tripTime < Date.now();
  } catch (e) { return true; }
    }
