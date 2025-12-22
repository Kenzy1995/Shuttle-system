

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
    clearScheduleCache();
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
  // 輸入時只清除錯誤提示，允許輸入任何文字，不過濾字符
  const nameErr = document.getElementById("nameErr");
  if (nameErr) {
    nameErr.style.display = "none";
  }
  // 恢復邊框顏色（如果之前有錯誤）
  if (input.style.borderColor === "#b00020") {
    input.style.borderColor = "#ddd";
  }
}

function validateNameOnBlur(input) {
  const value = input.value || "";
  const nameErr = document.getElementById("nameErr");
  
  // 檢查是否為空
  if (!value.trim()) {
    nameErr.textContent = t("errName");
    nameErr.style.display = "block";
    shake(input);
    input.style.borderColor = "#b00020";
    return;
  }
  
  // 檢查是否符合規則（只允許中文、英文、空格）
  if (!nameRegex.test(value)) {
    nameErr.textContent = t("errName");
    nameErr.style.display = "block";
    shake(input);
    input.style.borderColor = "#b00020";
    return;
  }
  
  // 驗證通過，清除錯誤
  nameErr.style.display = "none";
  input.style.borderColor = "#ddd";
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
  // 輸入時不驗證，只清除之前的錯誤
  const emailErr = document.getElementById("emailErr");
  emailErr.style.display = "none";
  input.style.borderColor = "#ddd";
}

function validateEmailOnBlur(input) {
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
    const now = Date.now();
    const ONE_HOUR_MS = 60 * 60 * 1000; // 一小時的毫秒數
    // 只有當班次時間超過一小時才標記為已過期
    // 邏輯：tripTime < (now - ONE_HOUR_MS) 表示班次時間早於（現在時間 - 1小時）
    // 也就是說，班次時間已經超過1小時了
    return tripTime < (now - ONE_HOUR_MS);
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

// 優化：班次資料快取
const SCHEDULE_CACHE_KEY = 'schedule_data_cache';
const SCHEDULE_CACHE_TTL = 5 * 60 * 1000; // 5 分鐘

// 優化：班次資料快取 - 在本地快取班次資料，減少 API 調用
async function loadScheduleData() {
  const resultsEl = document.getElementById("scheduleResults");
  if (!resultsEl) return;

  // 檢查快取
  try {
    const cached = localStorage.getItem(SCHEDULE_CACHE_KEY);
    if (cached) {
      const cacheData = JSON.parse(cached);
      const now = Date.now();
      if (cacheData.timestamp && (now - cacheData.timestamp) < SCHEDULE_CACHE_TTL) {
        // 使用快取資料
        scheduleData.rows = cacheData.rows || [];
        scheduleData.directions = new Set(cacheData.directions || []);
        scheduleData.dates = new Set(cacheData.dates || []);
        scheduleData.stations = new Set(cacheData.stations || []);
        
        renderScheduleFilters();
        renderScheduleResults();
        return; // 直接返回，不發送 API 請求
      }
    }
  } catch (e) {
  }

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

    // 更新快取
    try {
      localStorage.setItem(SCHEDULE_CACHE_KEY, JSON.stringify({
        timestamp: Date.now(),
        rows: scheduleData.rows,
        directions: Array.from(scheduleData.directions),
        dates: Array.from(scheduleData.dates),
        stations: Array.from(scheduleData.stations)
      }));
    } catch (e) {
    }

    renderScheduleFilters();
    renderScheduleResults();
  } catch (error) {
    resultsEl.innerHTML = `<div class="empty-state">${t(
      "queryFailedPrefix"
    )}${sanitize(error.message)}</div>`;
  }
}

// 清除班次快取的函數（可在手動刷新時調用）
function clearScheduleCache() {
  try {
    localStorage.removeItem(SCHEDULE_CACHE_KEY);
  } catch (e) {
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

  // 檢查 GPS 系統總開關（從 booking-api 讀取，該 API 會從 Sheet 的「系統」E19 讀取）
  try {
    const apiUrl = "https://booking-api-995728097341.asia-east1.run.app/api/realtime/location";
    const r = await fetch(apiUrl);
    if (r.ok) {
      const data = await r.json();
      // 如果 gps_system_enabled 不是 true，隱藏整個即時位置區塊
      if (!data.gps_system_enabled) {
        sec.style.display = "none";
        mount.innerHTML = "";
        return;
      }
    } else {
      // API 請求失敗，為了安全起見，隱藏區塊
      sec.style.display = "none";
      mount.innerHTML = "";
      return;
    }
  } catch (e) {
    // 發生錯誤時，為了安全起見，隱藏區塊
    sec.style.display = "none";
    mount.innerHTML = "";
    return;
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
  // 即時位置區塊：資訊顯示在上方，不覆蓋地圖
  mount.innerHTML = `
    <!-- 資訊區塊：顯示在上方 -->
    <div id="rt-info-panel" style="margin-bottom:12px;padding:16px;background:#ffffff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);display:none;">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap;">
        <div id="rt-status-light" style="width:12px;height:12px;border-radius:50%;background:#28a745;box-shadow:0 0 8px rgba(40,167,69,0.6);"></div>
        <span id="rt-status-text" style="font-size:15px;color:#333;font-weight:500;">良好</span>
        <button id="rt-refresh" style="margin-left:auto;padding:8px 16px;background:#fff;border:1px solid #ddd;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;box-shadow:0 2px 4px rgba(0,0,0,0.1);">刷新</button>
      </div>
      
      <!-- 站點列表 -->
      <div id="rt-stations-list" style="display:flex;flex-direction:column;gap:12px;">
        <!-- 站點將動態生成 -->
      </div>
    </div>
    
    <div id="rt-map-wrapper" style="position:relative;width:100%;height:500px;min-height:500px;border-radius:12px;overflow:hidden;">
      <div id="rt-map" style="width:100%;height:100%;"></div>
      <!-- 灰色透明遮罩，預設顯示 -->
      <div id="rt-overlay" style="position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;z-index:10;">
        <button id="rt-start-btn" class="button" style="padding:16px 32px;font-size:18px;font-weight:700;background:var(--primary);color:#fff;border:none;border-radius:12px;cursor:pointer;">查看即時位置</button>
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
  const infoPanel = mount.querySelector("#rt-info-panel");
  const stationsList = mount.querySelector("#rt-stations-list");
  
  // 根據設備選擇對應的元素
  const statusLight = mount.querySelector("#rt-status-light");
  const statusText = mount.querySelector("#rt-status-text");
  const btnRefresh = mount.querySelector("#rt-refresh");
  
  // 手動刷新速率限制
  let lastManualRefreshTime = 0;
  let refreshCountdownTimer = null;
  const MANUAL_REFRESH_COOLDOWN = 30 * 1000; // 30秒
  
  // 更新刷新按鈕狀態的函數
  const updateRefreshButton = (enabled, countdown = 0) => {
    if (btnRefresh) {
      if (enabled) {
        btnRefresh.disabled = false;
        btnRefresh.style.opacity = "1";
        btnRefresh.style.cursor = "pointer";
        btnRefresh.style.background = "#fff";
        btnRefresh.textContent = countdown > 0 ? `刷新 (${countdown}秒)` : "刷新";
      } else {
        btnRefresh.disabled = true;
        btnRefresh.style.opacity = "0.5";
        btnRefresh.style.cursor = "not-allowed";
        btnRefresh.style.background = "#f0f0f0";
        btnRefresh.textContent = countdown > 0 ? `刷新 (${countdown}秒)` : "刷新";
      }
    }
  };
  
  // 更新狀態的輔助函數
  const updateStatus = (color, text) => {
    if (statusLight && statusText) {
      statusLight.style.background = color;
      statusLight.style.boxShadow = `0 0 8px ${color}66`;
      statusText.textContent = text;
      statusText.style.color = color;
    }
  };
  
  // 更新站點列表
  const updateStationsList = (data, driverPos) => {
    if (!stationsList || !data.current_trip_route || !data.current_trip_route.stops) {
      return;
    }
    
    const stops = data.current_trip_route.stops || [];
    const completedStops = data.current_trip_completed_stops || [];
    const tripDateTime = data.current_trip_datetime || "";
    const driverLocation = driverPos || (data.driver_location && typeof data.driver_location.lat === "number" ? { lat: data.driver_location.lat, lng: data.driver_location.lng } : null);
    
    // 解析主班次時間（第一站使用）
    let mainTripTime = null;
    if (tripDateTime) {
      try {
        const parts = tripDateTime.split(' ');
        if (parts.length >= 2) {
          const datePart = parts[0].replace(/\//g, '-');
          const timePart = parts[1];
          mainTripTime = new Date(`${datePart}T${timePart}:00`);
        }
      } catch (e) {
      }
    }
    
    // 生成站點HTML
    let stationsHTML = "";
    stops.forEach((stop, index) => {
      const stopName = typeof stop === "object" && stop.name ? stop.name : (typeof stop === "string" ? stop : "");
      const stopCoord = typeof stop === "object" && stop.lat ? { lat: stop.lat, lng: stop.lng } : stationCoords[stopName] || null;
      const isCompleted = completedStops.includes(stopName);
      
      // 判斷站點是否已經過了（根據司機位置和路線）
      let isPassed = false;
      if (driverLocation && stopCoord && data.current_trip_route && data.current_trip_route.path) {
        // 獲取路線路徑
        const routePath = data.current_trip_route.path || [];
        if (routePath.length > 0) {
          // 找到站點在路線上的最近點索引
          let stationNearestIdx = 0;
          let stationBestDist = Infinity;
          for (let i = 0; i < routePath.length; i++) {
            const point = routePath[i];
            const dx = point.lat - stopCoord.lat;
            const dy = point.lng - stopCoord.lng;
            const dist = dx * dx + dy * dy;
            if (dist < stationBestDist) {
              stationBestDist = dist;
              stationNearestIdx = i;
            }
          }
          
          // 找到司機當前位置在路線上的最近點索引
          let driverNearestIdx = 0;
          let driverBestDist = Infinity;
          for (let i = 0; i < routePath.length; i++) {
            const point = routePath[i];
            const dx = point.lat - driverLocation.lat;
            const dy = point.lng - driverLocation.lng;
            const dist = dx * dx + dy * dy;
            if (dist < driverBestDist) {
              driverBestDist = dist;
              driverNearestIdx = i;
            }
          }
          
          // 如果司機位置在路線上的索引 > 站點在路線上的索引，表示已經過了這個站點
          // 或者如果有GPS歷史，檢查歷史中是否有點在站點之後
          if (driverNearestIdx > stationNearestIdx) {
            isPassed = true;
          } else if (data.current_trip_path_history && Array.isArray(data.current_trip_path_history) && data.current_trip_path_history.length > 0) {
            // 檢查GPS歷史中是否有點在站點之後
            for (const historyPoint of data.current_trip_path_history) {
              let historyNearestIdx = 0;
              let historyBestDist = Infinity;
              for (let i = 0; i < routePath.length; i++) {
                const point = routePath[i];
                const dx = point.lat - historyPoint.lat;
                const dy = point.lng - historyPoint.lng;
                const dist = dx * dx + dy * dy;
                if (dist < historyBestDist) {
                  historyBestDist = dist;
                  historyNearestIdx = i;
                }
              }
              if (historyNearestIdx > stationNearestIdx) {
                isPassed = true;
                break;
              }
            }
          }
        }
      }
      
      // 如果已完成站點數量 > 當前站點索引，也表示已經過了這個站點（備用判斷）
      if (!isPassed && completedStops.length > index) {
        isPassed = true;
      }
      
      const isCurrent = index === stops.findIndex((s, i) => {
        const sName = typeof s === "object" && s.name ? s.name : (typeof s === "string" ? s : "");
        return !completedStops.includes(sName) && i >= completedStops.length;
      });
      
      // 計算預計抵達時間
      let timeLabel = "";
      let timeText = "--";
      let etaTime = null;
      
      if (index === 0 && mainTripTime) {
        // 第一站顯示發車時間（格式：發車時間:2025/12/23 10:00）
        etaTime = mainTripTime;
        const year = mainTripTime.getFullYear();
        const month = String(mainTripTime.getMonth() + 1).padStart(2, '0');
        const day = String(mainTripTime.getDate()).padStart(2, '0');
        const hours = String(mainTripTime.getHours()).padStart(2, '0');
        const minutes = String(mainTripTime.getMinutes()).padStart(2, '0');
        timeLabel = "發車時間";
        timeText = `${year}/${month}/${day} ${hours}:${minutes}`;
      } else if (isCompleted) {
        // 已抵達的站點
        timeLabel = "狀態";
        timeText = "已抵達";
      } else if (isPassed && !isCompleted) {
        // 已經過了但還沒標記為已抵達的站點
        timeLabel = "狀態";
        timeText = "已過站";
      } else if (driverLocation && stopCoord) {
        // 其他站點計算ETA
        const eta = calculateETA(driverLocation.lat, driverLocation.lng, stopCoord.lat, stopCoord.lng);
        if (eta) {
          const now = new Date();
          etaTime = new Date(now.getTime() + eta.minutes * 60 * 1000);
          const hours = String(etaTime.getHours()).padStart(2, '0');
          const minutes = String(etaTime.getMinutes()).padStart(2, '0');
          timeLabel = "預計抵達";
          timeText = `${hours}:${minutes}`;
        } else {
          timeLabel = "預計抵達";
        }
      } else {
        timeLabel = "預計抵達";
      }
      
      // 站點樣式
      const stationStyle = `
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px;
        background: ${isCompleted || isPassed ? '#f5f5f5' : (isCurrent ? '#e8f5e9' : '#ffffff')};
        border-radius: 8px;
        border-left: 3px solid ${isCompleted ? '#808080' : (isPassed ? '#999999' : (isCurrent ? '#28a745' : '#e0e0e0'))};
      `;
      
      stationsHTML += `
        <div style="${stationStyle}">
          <div style="flex: 1;">
            <div style="font-size:15px;color:#333;font-weight:${isCurrent ? '600' : '500'};margin-bottom:4px;">${stopName}</div>
            <div style="font-size:13px;color:#666;">${timeLabel}: ${timeText}</div>
          </div>
          ${isCompleted ? '<div style="color:#28a745;font-size:20px;">✓</div>' : (isPassed ? '<div style="color:#999999;font-size:20px;">→</div>' : '')}
        </div>
      `;
    });
    
    stationsList.innerHTML = stationsHTML;
  };
  
  // 計算兩點間距離（公尺）
  const haversineDistance = (lat1, lng1, lat2, lng2) => {
    const R = 6371000; // 地球半徑（公尺）
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLng = (lng2 - lng1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
              Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
              Math.sin(dLng / 2) * Math.sin(dLng / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  };

  // 計算預計抵達時間（ETA）
  const calculateETA = (driverLat, driverLng, destinationLat, destinationLng) => {
    if (!driverLat || !driverLng || !destinationLat || !destinationLng) {
      return null;
    }
    
    const distance = haversineDistance(driverLat, driverLng, destinationLat, destinationLng);
    // 假設平均車速為 40 km/h (約 11.11 m/s)
    const avgSpeed = 11.11; // 公尺/秒
    const timeSeconds = distance / avgSpeed;
    const timeMinutes = Math.round(timeSeconds / 60);
    
    return {
      distance: distance,
      minutes: timeMinutes,
      formatted: timeMinutes > 60 ? `${Math.floor(timeMinutes / 60)} 小時 ${timeMinutes % 60} 分鐘` : `${timeMinutes} 分鐘`
    };
  };

  // 格式化時間（簡短版，用於 ETA）
  const formatTimeShort = (timestamp) => {
    if (!timestamp) return '--';
    const date = new Date(timestamp);
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${hours}:${minutes}`;
  };

  // 格式化時間（完整版）
  const formatTime = (timestamp) => {
    if (!timestamp) return '--';
    const date = new Date(timestamp);
    const days = ['日', '一', '二', '三', '四', '五', '六'];
    const month = date.getMonth() + 1;
    const day = date.getDate();
    const dayName = days[date.getDay()];
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${hours}:${minutes} ${month}/${day} 週${dayName}`;
  };

  // 計算提前/延遲時間
  const calculateTimeDifference = (estimatedTime, scheduledTime) => {
    if (!estimatedTime || !scheduledTime) return null;
    
    const estimated = new Date(estimatedTime);
    const scheduled = new Date(scheduledTime);
    const diffMs = estimated.getTime() - scheduled.getTime();
    const diffMinutes = Math.round(diffMs / (1000 * 60));
    
    if (Math.abs(diffMinutes) < 1) {
      return { text: '準時', isEarly: true, minutes: 0 };
    }
    
    const hours = Math.floor(Math.abs(diffMinutes) / 60);
    const minutes = Math.abs(diffMinutes) % 60;
    
    if (diffMinutes < 0) {
      // 提前
      if (hours > 0) {
        return { 
          text: `提前 ${hours} 小時 ${minutes} 分鐘`, 
          isEarly: true, 
          minutes: Math.abs(diffMinutes) 
        };
      } else {
        return { 
          text: `提前 ${minutes} 分鐘`, 
          isEarly: true, 
          minutes: Math.abs(diffMinutes) 
        };
      }
    } else {
      // 延遲
      if (hours > 0) {
        return { 
          text: `延遲 ${hours} 小時 ${minutes} 分鐘`, 
          isEarly: false, 
          minutes: diffMinutes 
        };
      } else {
        return { 
          text: `延遲 ${minutes} 分鐘`, 
          isEarly: false, 
          minutes: diffMinutes 
        };
      }
    }
  };
  
  // 更新下一站的輔助函數（已移除，不再顯示"即將抵達"資訊）
  const updateNextStop = (stopName) => {
    // 不再更新任何內容
  };
  
  // 改進：更新已走過的路線（基於GPS位置歷史，使用時間戳判斷）
  const updateWalkedRoute = async (data, driverPos = null) => {
    if (!mainPolyline || !data.current_trip_route) {
      return;
    }
    
    const path = mainPolyline.getPath().getArray();
    
    // 改進：使用GPS位置歷史來判斷走過的路線
    // 這樣可以準確處理折返情況，不會誤判
    let walkedPath = [];
    
    // 如果有GPS位置歷史，使用歷史來繪製走過的路線
    if (data.current_trip_path_history && Array.isArray(data.current_trip_path_history) && data.current_trip_path_history.length > 0) {
      // 將GPS歷史位置轉換為Google Maps LatLng對象
      walkedPath = data.current_trip_path_history.map(point => 
        new google.maps.LatLng(point.lat, point.lng)
      );
    } else if (driverPos) {
      // 如果沒有歷史，使用當前位置和路線的最近點來判斷
      // 找到當前位置在路線上的最近點
      let nearestIdx = 0, best = Infinity;
      for (let i = 0; i < path.length; i++) {
        const dx = path[i].lat() - driverPos.lat;
        const dy = path[i].lng() - driverPos.lng;
        const dist = dx * dx + dy * dy;
        if (dist < best) {
          best = dist;
          nearestIdx = i;
        }
      }
      // 繪製從起點到最近點的路線
      walkedPath = path.slice(0, Math.max(1, nearestIdx + 1));
    }
    
    // 清除舊的路線
    if (walkedPolyline) walkedPolyline.setMap(null);
    
    // 如果有走過的路線，繪製灰色路線
    if (walkedPath.length > 1) {
      walkedPolyline = new google.maps.Polyline({ 
        path: walkedPath, 
        strokeColor: "#808080", // 灰色（走過的路線）
        strokeOpacity: 0.8, 
        strokeWeight: 6, 
        map,
        zIndex: 2
      });
    }
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
        reject(new Error("缺少地圖 key"));
        return; 
      }
      // 檢查 Google Maps API 是否已經載入
      if (window.google && window.google.maps) {
        resolve();
        return;
      }
      // 檢查是否已經有載入中的 script 標籤
      const existingScript = document.querySelector('script[src*="maps.googleapis.com/maps/api/js"]');
      if (existingScript) {
        // 如果已有 script 標籤，等待它載入完成
        if (window.google && window.google.maps) {
          resolve();
        } else {
          existingScript.addEventListener('load', resolve);
          existingScript.addEventListener('error', reject);
        }
        return;
      }
      const s = document.createElement("script");
      s.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(cfg.key)}&libraries=places&loading=async`;
      s.async = true;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });

  let map, marker, mainPolyline, walkedPolyline, stationMarkers = [];
  let currentTripData = null;
  let isInitialized = false;
  let markerCircle = null; // 司機位置圓形外圈（呼吸光圈）
  let breathingAnimation = null; // 呼吸光圈動畫計時器
  let firebaseListeners = []; // Firebase 監聽器引用，用於清理
  let firebaseConnected = false; // Firebase 連接狀態
  let fallbackTimer = null; // 備用定時輪詢計時器
  
  // 光子動畫已移除
  const ensureFirebase = async () => {
    if (!cfg.fbdb || !cfg.fbkey) return false;
    // 動態載入 Firebase SDK
    await new Promise((resolve, reject) => {
      if (window.firebase && firebase.app) { resolve(); return; }
      const s = document.createElement("script");
      s.src = "https://www.gstatic.com/firebasejs/9.23.0/firebase-app-compat.js";
      s.onload = resolve; s.onerror = reject; document.head.appendChild(s);
    });
    await new Promise((resolve, reject) => {
      if (window.firebase && firebase.database) { resolve(); return; }
      const s = document.createElement("script");
      s.src = "https://www.gstatic.com/firebasejs/9.23.0/firebase-database-compat.js";
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
            strokeColor: "#0b63ce", // 深藍色（未走過的路線）
            strokeOpacity: 0.9, 
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
          // 確保地圖實例已正確初始化
          if (mapInstance && mapInstance instanceof google.maps.Map && bounds.getNorthEast && bounds.getSouthWest) {
            try {
              mapInstance.fitBounds(bounds);
            } catch (e) {
            }
          }
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
              // 檢查最後一站是否已經是飯店
              const lastStop = displayStops[displayStops.length - 1];
              const isLastStopHotel = lastStop && (
                (typeof lastStop === "object" && lastStop.lat === hotelBackCoord.lat && lastStop.lng === hotelBackCoord.lng) ||
                (typeof lastStop === "string" && (lastStop.includes("福泰") || lastStop.includes("Forte Hotel"))) ||
                (typeof lastStop === "object" && lastStop.name && (lastStop.name.includes("福泰") || lastStop.name.includes("Forte Hotel")))
              );
              
              // 如果最後一站不是飯店，強制添加飯店作為最後一站
              if (!isLastStopHotel) {
                displayStops.push({ 
                  name: "福泰大飯店(回) Forte Hotel (Back)", 
                  lat: hotelBackCoord.lat, 
                  lng: hotelBackCoord.lng 
                });
              } else {
                // 如果最後一站是飯店，確保座標正確
                displayStops[displayStops.length - 1] = { 
                  name: "福泰大飯店(回) Forte Hotel (Back)", 
                  lat: hotelBackCoord.lat, 
                  lng: hotelBackCoord.lng 
                };
              }
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
      let routeNeedsRegeneration = false; // 標記是否需要重新生成路線
      const hotelBackCoord = stationCoords["福泰大飯店(回) Forte Hotel (Back)"];
      if (hotelBackCoord) {
        // 檢查最後一站是否已經是飯店
        const lastStop = displayStops.length > 0 ? displayStops[displayStops.length - 1] : null;
        const isLastStopHotel = lastStop && (
          (typeof lastStop === "object" && lastStop.lat === hotelBackCoord.lat && lastStop.lng === hotelBackCoord.lng) ||
          (typeof lastStop === "string" && (lastStop.includes("福泰") || lastStop.includes("Forte Hotel"))) ||
          (typeof lastStop === "object" && lastStop.name && (lastStop.name.includes("福泰") || lastStop.name.includes("Forte Hotel")))
        );
        
        // 如果最後一站不是飯店，強制添加飯店作為最後一站
        if (!isLastStopHotel) {
          displayStops.push({ 
            name: "福泰大飯店(回) Forte Hotel (Back)", 
            lat: hotelBackCoord.lat, 
            lng: hotelBackCoord.lng 
          });
          routeNeedsRegeneration = true; // 需要重新生成路線
        } else if (displayStops.length > 0) {
          // 如果最後一站是飯店，確保座標正確
          const currentLastStop = displayStops[displayStops.length - 1];
          if (typeof currentLastStop === "object" && 
              (currentLastStop.lat !== hotelBackCoord.lat || currentLastStop.lng !== hotelBackCoord.lng)) {
            displayStops[displayStops.length - 1] = { 
              name: "福泰大飯店(回) Forte Hotel (Back)", 
              lat: hotelBackCoord.lat, 
              lng: hotelBackCoord.lng 
            };
            routeNeedsRegeneration = true; // 座標改變，需要重新生成路線
          }
        }
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
          return "起點";
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
          
          // 創建站點標記（使用舊的 Marker API，將 DOM 元素轉換為圖標）
          const createStationIcon = (label, isStartOrEnd) => {
            const size = isStartOrEnd ? 28 : 24;
            const canvas = document.createElement('canvas');
            canvas.width = size;
            canvas.height = size;
            const ctx = canvas.getContext('2d');
            
            // 繪製圓形背景
            ctx.beginPath();
            ctx.arc(size / 2, size / 2, size / 2 - 1, 0, 2 * Math.PI);
            ctx.fillStyle = '#0b63ce';
            ctx.fill();
            ctx.strokeStyle = '#fff';
            ctx.lineWidth = 2;
            ctx.stroke();
            
            // 繪製文字
            ctx.fillStyle = '#fff';
            ctx.font = `${isStartOrEnd ? 'bold 11px' : '14px'} Arial`;
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(label, size / 2, size / 2);
            
            return {
              url: canvas.toDataURL(),
              scaledSize: new google.maps.Size(size, size),
              anchor: new google.maps.Point(size / 2, size / 2)
            };
          };
          
          const isStartOrEnd = idx === 0 || idx === displayStops.length - 1;
          const icon = createStationIcon(displayLabel, isStartOrEnd);
          
          const marker = new google.maps.Marker({
            position: { lat: coord.lat, lng: coord.lng },
            map: map,
            icon: icon,
            title: fullName
          });
          
          marker.addListener('click', () => {
            const infoWindow = new google.maps.InfoWindow({
              content: `<div style="padding: 8px; font-weight: 600; font-size: 14px;">${fullName}</div>`
            });
            infoWindow.open(map, marker);
            setTimeout(() => {
              infoWindow.close();
            }, 3000);
          });
          
          stationMarkers.push(marker);
        }
      });
      
      // 繪製路線
      // 如果路線需要重新生成（因為添加了終點站），使用 Google Directions API 重新生成
      if (routeNeedsRegeneration && displayStops.length >= 2) {
        // 重新生成路線（包含終點站）
        await drawRouteFromStops(displayStops, map);
      } else if (path && Array.isArray(path) && path.length > 1) {
        // 使用現有的路線數據
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
        // 確保地圖實例已正確初始化
        if (map && map instanceof google.maps.Map && bounds.getNorthEast && bounds.getSouthWest) {
          try {
            map.fitBounds(bounds);
          } catch (e) {
            console.error("fitBounds 錯誤:", e);
          }
        }
      } else if (displayStops.length >= 2) {
        // 如果沒有 polyline，使用 Google Directions API 生成路線
        await drawRouteFromStops(displayStops, map);
      }
      
      // 路線繪製完成後，立即更新已走過的路線（如果有數據）
      if (currentTripData) {
        const driverLoc = currentTripData.driver_location;
        const pos = driverLoc && typeof driverLoc.lat === "number" && typeof driverLoc.lng === "number" 
          ? { lat: driverLoc.lat, lng: driverLoc.lng } 
          : null;
        await updateWalkedRoute(currentTripData, pos);
      }
    } catch (e) {
    }
  };
  // 從 Firebase 資料更新前端（用於監聽器回調）
  const updateLocationFromFirebase = async (firebaseData) => {
    if (!isInitialized || !map) return;
    
    try {
      // 直接使用傳入的資料結構（已在監聽器中構建）
      await processLocationData(firebaseData);
    } catch (e) {
      updateStatus("#dc3545", "更新失敗");
    }
  };
  
  // 處理位置資料的共用函數（從 fetchLocation 和 updateLocationFromFirebase 調用）
  const processLocationData = async (data) => {
      
      // 檢查 GPS 系統總開關
      if (!data.gps_system_enabled) {
        if (overlayEl) overlayEl.style.display = "flex";
        if (infoPanel) infoPanel.style.display = "none";
        return;
      }
      
      // 檢查班次時間是否超過1小時
      let shouldShowNoTrip = false;
      if (data.current_trip_datetime) {
        try {
          const parts = data.current_trip_datetime.split(' ');
          if (parts.length >= 2) {
            const datePart = parts[0].replace(/\//g, '-');
            const timePart = parts[1];
            const tripTime = new Date(`${datePart}T${timePart}:00`);
            const now = Date.now();
            const tripTimeMs = tripTime.getTime();
            const ONE_HOUR_MS = 60 * 60 * 1000; // 1小時
            // 如果班次時間超過現在時間1小時以上，顯示"目前無可顯示班次"
            if (tripTimeMs < (now - ONE_HOUR_MS)) {
              shouldShowNoTrip = true;
            }
          }
        } catch (e) {
        }
      }
      
      // 如果班次時間超過1小時，顯示"目前無可顯示班次"
      if (shouldShowNoTrip) {
        if (infoPanel) {
          infoPanel.style.display = "block";
          if (stationsList) {
            stationsList.innerHTML = '<div style="padding:24px;text-align:center;color:#666;font-size:16px;">目前無可顯示班次</div>';
          }
        }
        if (endedOverlay) endedOverlay.style.display = "none";
        if (overlayEl) overlayEl.style.display = "none";
        return;
      }
      
      // 檢查班次狀態
      // 方案 3：前端過期檢查（額外保障）
      // 即使狀態不是 "ended"，如果發車時間超過 40 分鐘，也顯示結束畫面
      let shouldShowEnded = false;
      if (data.current_trip_status === "ended") {
        shouldShowEnded = true;
      } else if (data.current_trip_start_time && data.current_trip_start_time > 0) {
        // 檢查是否超過 40 分鐘
        const now = Date.now();
        const elapsed = now - data.current_trip_start_time;
        const AUTO_SHUTDOWN_MS = 40 * 60 * 1000; // 40分鐘
        if (elapsed >= AUTO_SHUTDOWN_MS) {
          shouldShowEnded = true;
        }
      }
      
      if (shouldShowEnded) {
        if (endedOverlay) {
          endedOverlay.style.display = "flex";
          if (endedDatetimeEl) {
            endedDatetimeEl.textContent = data.last_trip_datetime || data.current_trip_datetime || "";
          }
        }
        if (infoPanel) infoPanel.style.display = "none";
        return;
      } else {
        if (endedOverlay) endedOverlay.style.display = "none";
        if (infoPanel) infoPanel.style.display = "block";
      }
      
      // 更新司機位置
      const driverLoc = data.driver_location;
      let driverPos = null;
      if (driverLoc && typeof driverLoc.lat === "number" && typeof driverLoc.lng === "number") {
        driverPos = { lat: driverLoc.lat, lng: driverLoc.lng };
        if (marker) {
          marker.setPosition(driverPos);
          map.panTo(driverPos);
        }
        // 更新圓形外圈位置
        if (markerCircle) {
          markerCircle.setCenter(driverPos);
        }
        
        // 更新已走過的路線
        await updateWalkedRoute(data, driverPos);
        
        updateStatus("#28a745", "良好");
      } else {
        updateStatus("#ffc107", "連線中");
      }
      
      // 更新站點列表
      updateStationsList(data, driverPos);
      
      currentTripData = data;
  };
  
  const fetchLocation = async () => {
    try {
      // 從 booking-api 讀取即時位置資料（作為備用方案）
      const apiUrl = "https://booking-api-995728097341.asia-east1.run.app/api/realtime/location";
      const r = await fetch(apiUrl);
      if (!r.ok) {
        updateStatus("#dc3545", "連線失敗");
        return;
      }
      const data = await r.json();
      await processLocationData(data);
    } catch (e) {
      updateStatus("#dc3545", "錯誤");
    }
  };

  // 初始化地圖（點擊"查看即時位置"按鈕後）
  let initMap = async () => {
    if (isInitialized) return;
    isInitialized = true;
    
    await loadMaps();
    
    // 確保 Google Maps API 已完全載入和初始化
    if (!window.google || !window.google.maps) {
      throw new Error("Google Maps API 載入失敗");
    }
    
    // 等待 Google Maps API 完全初始化（額外檢查）
    let retries = 0;
    while ((!window.google.maps.LatLngBounds || !window.google.maps.Map) && retries < 50) {
      await new Promise(resolve => setTimeout(resolve, 100));
      retries++;
    }
    
    if (!window.google.maps.LatLngBounds || !window.google.maps.Map) {
      throw new Error("Google Maps API 初始化超時");
    }
    
    // 灰白黑色地圖樣式 - 隱藏所有不必要的資訊，讓畫面乾淨
    const mapStyles = [
      {
        featureType: "all",
        elementType: "labels",
        stylers: [{ visibility: "off" }]
      },
      {
        featureType: "all",
        elementType: "labels.text",
        stylers: [{ visibility: "off" }]
      },
      {
        featureType: "all",
        elementType: "labels.icon",
        stylers: [{ visibility: "off" }]
      },
      {
        featureType: "all",
        elementType: "geometry",
        stylers: [{ color: "#e0e0e0" }]
      },
      {
        featureType: "road",
        elementType: "geometry",
        stylers: [{ color: "#d0d0d0" }]
      },
      {
        featureType: "road",
        elementType: "labels",
        stylers: [{ visibility: "off" }]
      },
      {
        featureType: "water",
        elementType: "geometry",
        stylers: [{ color: "#c0c0c0" }]
      },
      {
        featureType: "water",
        elementType: "labels",
        stylers: [{ visibility: "off" }]
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
      },
      {
        featureType: "administrative",
        elementType: "labels",
        stylers: [{ visibility: "off" }]
      }
    ];
    
    // 計算地圖顯示範圍限制（方圓4公里）
    const centerLat = 25.054933909333368;
    const centerLng = 121.61876667836735;
    const radiusKm = 4; // 4公里
    
    // 計算邊界（近似值：1度緯度約111公里，經度根據緯度調整）
    const latDelta = radiusKm / 111; // 緯度變化（約0.045度）
    const lngDelta = radiusKm / (111 * Math.cos(centerLat * Math.PI / 180)); // 經度變化（考慮緯度）
    
    // 確保 Google Maps API 已完全載入
    if (!google || !google.maps || !google.maps.LatLngBounds) {
      throw new Error("Google Maps API 尚未完全載入");
    }
    
    const restrictionBounds = new google.maps.LatLngBounds(
      { lat: centerLat - latDelta, lng: centerLng - lngDelta }, // 西南角
      { lat: centerLat + latDelta, lng: centerLng + lngDelta }   // 東北角
    );
    
    // 初始化地圖（使用 styles 設置灰色地圖，不使用 mapId）
    // 隱藏所有不必要的 UI 元素，讓畫面乾淨
    map = new google.maps.Map(mapEl, { 
      center: { lat: 25.055550556928008, lng: 121.63210245291367 }, 
      zoom: 14, 
      disableDefaultUI: true, // 隱藏所有預設 UI
      zoomControl: false, 
      mapTypeControl: false, 
      streetViewControl: false,
      fullscreenControl: false,
      styles: mapStyles,
      restriction: {
        latLngBounds: restrictionBounds,
        strictBounds: true // 嚴格限制，不允許拖動到邊界外
      }
    });
    
    // 創建司機位置標記（綠色點，使用舊的 Marker API）
    marker = new google.maps.Marker({ 
      position: { lat: 25.055550556928008, lng: 121.63210245291367 }, 
      map: map, 
      title: "司機位置",
      icon: {
        path: google.maps.SymbolPath.CIRCLE,
        scale: 8,
        fillColor: "#28a745",
        fillOpacity: 1,
        strokeColor: "#ffffff",
        strokeWeight: 2,
      },
      zIndex: 10
    });
    
    // 添加呼吸光圈效果（淺綠色光圈閃爍）
    markerCircle = new google.maps.Circle({
      strokeColor: "#90EE90", // 淺綠色
      strokeOpacity: 0.6,
      strokeWeight: 2,
      fillColor: "#90EE90",
      fillOpacity: 0.2,
      map: map,
      center: { lat: 25.055550556928008, lng: 121.63210245291367 },
      radius: 30
    });
    
    // 呼吸光圈動畫
    let breathingRadius = 30;
    let breathingDirection = 1;
    let breathingOpacity = 0.2;
    let breathingOpacityDirection = 1;
    const breathingAnimation = setInterval(() => {
      // 半徑呼吸效果（30-50之間）
      breathingRadius += breathingDirection * 2;
      if (breathingRadius >= 50) {
        breathingRadius = 50;
        breathingDirection = -1;
      } else if (breathingRadius <= 30) {
        breathingRadius = 30;
        breathingDirection = 1;
      }
      
      // 透明度呼吸效果（0.1-0.4之間）
      breathingOpacity += breathingOpacityDirection * 0.02;
      if (breathingOpacity >= 0.4) {
        breathingOpacity = 0.4;
        breathingOpacityDirection = -1;
      } else if (breathingOpacity <= 0.1) {
        breathingOpacity = 0.1;
        breathingOpacityDirection = 1;
      }
      
      if (markerCircle) {
        markerCircle.setOptions({
          radius: breathingRadius,
          fillOpacity: breathingOpacity,
          strokeOpacity: breathingOpacity * 2
        });
      }
    }, 50); // 每50毫秒更新一次，實現平滑呼吸效果
    
    // 隱藏遮罩，顯示資訊
    if (overlayEl) overlayEl.style.display = "none";
    if (infoPanel) infoPanel.style.display = "block";
    
    // 首次獲取數據並繪製路線
    await fetchLocation();
    if (currentTripData) {
      await drawRoute(currentTripData);
      // 繪製路線完成後，立即繪製已走過的路線（如果有）
      // 從 currentTripData 中獲取司機位置
      const driverLoc = currentTripData.driver_location;
      const driverPos = driverLoc && typeof driverLoc.lat === "number" && typeof driverLoc.lng === "number"
        ? { lat: driverLoc.lat, lng: driverLoc.lng }
        : null;
      await updateWalkedRoute(currentTripData, driverPos);
    }
  };
  
  // 設置 Firebase 監聽器（主要更新機制）
  // 優化：Firebase 監聽器優化 - 只監聽需要的特定路徑，減少資料傳輸
  const setupFirebaseListeners = async () => {
    if (!await ensureFirebase()) {
      startFallbackPolling();
      return;
    }
    
    try {
      const db = firebase.database();
      
      // 清理舊的監聽器
      firebaseListeners.forEach(ref => ref.off());
      firebaseListeners = [];
      
      // 需要監聽的路徑列表
      const pathsToWatch = [
        'driver_location',
        'current_trip_status',
        'current_trip_completed_stops',
        'current_trip_datetime',
        'current_trip_route',
        'current_trip_stations',
        'gps_system_enabled',
        'current_trip_start_time',
        'last_trip_datetime',
        'current_trip_id'
      ];
      
      // 用於構建完整資料結構的快取
      let firebaseDataCache = {
        gps_system_enabled: true,
        driver_location: null,
        current_trip_status: "",
        current_trip_datetime: "",
        current_trip_route: {},
        current_trip_stations: {},
        current_trip_start_time: 0,
        current_trip_completed_stops: [],
        last_trip_datetime: "",
        current_trip_id: ""
      };
      
      // 優化：防抖機制，避免短時間內多次更新
      let updateDebounceTimer = null;
      const UPDATE_DEBOUNCE_MS = 300; // 300 毫秒防抖
      
      const debouncedUpdate = async () => {
        if (updateDebounceTimer) {
          clearTimeout(updateDebounceTimer);
        }
        updateDebounceTimer = setTimeout(async () => {
          if (!isInitialized || !map) return;
          // 更新位置資料（使用快取的完整資料）
          await updateLocationFromFirebase(firebaseDataCache);
        }, UPDATE_DEBOUNCE_MS);
      };
      
      // 優化：為每個路徑創建單獨的監聽器，只接收該路徑的變化
      pathsToWatch.forEach(path => {
        const ref = db.ref(`/${path}`);
        const listener = ref.on('value', async (snapshot) => {
          if (!isInitialized || !map) return;
          
          const value = snapshot.val();
          
          // 更新快取
          if (path === 'driver_location') {
            firebaseDataCache.driver_location = value;
          } else if (path === 'current_trip_status') {
            firebaseDataCache.current_trip_status = value || "";
          } else if (path === 'current_trip_datetime') {
            firebaseDataCache.current_trip_datetime = value || "";
          } else if (path === 'current_trip_route') {
            firebaseDataCache.current_trip_route = value || {};
          } else if (path === 'current_trip_stations') {
            firebaseDataCache.current_trip_stations = value || {};
          } else if (path === 'current_trip_start_time') {
            firebaseDataCache.current_trip_start_time = value || 0;
          } else if (path === 'current_trip_completed_stops') {
            firebaseDataCache.current_trip_completed_stops = value || [];
          } else if (path === 'gps_system_enabled') {
            firebaseDataCache.gps_system_enabled = value !== undefined ? value : true;
          } else if (path === 'last_trip_datetime') {
            firebaseDataCache.last_trip_datetime = value || "";
          } else if (path === 'current_trip_id') {
            firebaseDataCache.current_trip_id = value || "";
          }
          
          // 使用防抖機制更新位置資料
          await debouncedUpdate();
          
          // 如果路線資料更新且與當前路線不同，重新繪製路線（立即執行，不防抖）
          if (path === 'current_trip_route' && firebaseDataCache.current_trip_route && Object.keys(firebaseDataCache.current_trip_route).length > 0) {
            const needsRouteUpdate = !currentTripData || 
              JSON.stringify(currentTripData.current_trip_route) !== JSON.stringify(firebaseDataCache.current_trip_route);
            
            if (needsRouteUpdate) {
              await drawRoute(firebaseDataCache);
            }
          }
        }, (error) => {
          firebaseConnected = false;
          updateStatus("#dc3545", "連線失敗");
          updateRefreshButtonVisibility();
          startFallbackPolling();
        });
        
        firebaseListeners.push(ref);
      });
      
      firebaseConnected = true;
      updateStatus("#28a745", "良好");
      
      // 更新刷新按鈕顯示狀態
      updateRefreshButtonVisibility();
      
      // 停止備用輪詢（如果正在運行）
      stopFallbackPolling();
    } catch (e) {
      firebaseConnected = false;
      updateRefreshButtonVisibility();
      startFallbackPolling();
    }
  };
  
  // 備用定時輪詢機制（當 Firebase 連接失敗時使用）
  const AUTO_REFRESH_MS = 3 * 60 * 1000; // 3分鐘
  const startFallbackPolling = () => {
    if (fallbackTimer) return; // 已經在運行
    fallbackTimer = setInterval(async () => {
      if (isInitialized && !firebaseConnected) {
        await fetchLocation();
        if (currentTripData) {
          await drawRoute(currentTripData);
        }
      }
    }, AUTO_REFRESH_MS);
  };
  
  const stopFallbackPolling = () => {
    if (fallbackTimer) {
      clearInterval(fallbackTimer);
      fallbackTimer = null;
    }
  };
  
  // 包裝 initMap 以在初始化完成後設置 Firebase 監聽器
  let isInitializing = false;
  const wrappedInitMap = async () => {
    if (isInitializing) {
      return;
    }
    if (isInitialized) {
      return;
    }
    try {
      isInitializing = true;
      await initMap();
      // 設置 Firebase 監聽器（主要機制）
      await setupFirebaseListeners();
    } catch (e) {
      isInitialized = false; // 允許重試
    } finally {
      isInitializing = false;
    }
  };
  
  // "查看即時位置"按鈕點擊事件
  if (startBtn) {
    startBtn.addEventListener("click", wrappedInitMap);
  }
  
  const handleManualRefresh = async () => {
    const now = Date.now();
    if (now - lastManualRefreshTime < MANUAL_REFRESH_COOLDOWN) {
      return;
    }
    
    if (firebaseConnected) {
      updateStatus("#28a745", "資料已自動更新");
      setTimeout(() => {
        updateStatus("#28a745", "良好");
      }, 2000);
      lastManualRefreshTime = now;
      updateRefreshButton(false, 30);
      
      if (refreshCountdownTimer) {
        clearInterval(refreshCountdownTimer);
      }
      
      let countdown = 30;
      refreshCountdownTimer = setInterval(() => {
        countdown--;
        if (countdown > 0) {
          updateRefreshButton(false, countdown);
        } else {
          clearInterval(refreshCountdownTimer);
          refreshCountdownTimer = null;
          updateRefreshButton(true);
        }
      }, 1000);
      return;
    }
    
    lastManualRefreshTime = now;
    updateRefreshButton(false, 30);
    
    if (refreshCountdownTimer) {
      clearInterval(refreshCountdownTimer);
    }
    
    let countdown = 30;
    refreshCountdownTimer = setInterval(() => {
      countdown--;
      if (countdown > 0) {
        updateRefreshButton(false, countdown);
      } else {
        clearInterval(refreshCountdownTimer);
        refreshCountdownTimer = null;
        updateRefreshButton(true);
      }
    }, 1000);
    
    await fetchLocation();
    if (currentTripData) {
      await drawRoute(currentTripData);
    }
  };
  
  const updateRefreshButtonVisibility = () => {
    if (btnRefresh) {
      if (firebaseConnected) {
        btnRefresh.title = "資料已自動更新，無需手動刷新";
        btnRefresh.style.opacity = "0.6";
      } else {
        btnRefresh.title = "點擊手動刷新";
        btnRefresh.style.opacity = "1";
      }
    }
  };
  
  if (btnRefresh) {
    btnRefresh.addEventListener("click", handleManualRefresh);
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
    // 即使初始化失敗，也要確保按鈕可以點擊
    try {
      showPage('reservation');
    } catch (e2) {
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
    const now = Date.now();
    const ONE_HOUR_MS = 60 * 60 * 1000; // 一小時的毫秒數
    // 只有當班次時間超過一小時才標記為已過期
    // 邏輯：tripTime < (now - ONE_HOUR_MS) 表示班次時間早於（現在時間 - 1小時）
    // 也就是說，班次時間已經超過1小時了
    return tripTime < (now - ONE_HOUR_MS);
  } catch (e) { return true; }
}
