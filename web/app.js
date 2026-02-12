

/* ====== 常數（API） ====== */
// 統一後端 API 基礎 URL
const BASE_API_URL = "https://server-api-509045429779.asia-east1.run.app";
const API_URL = `${BASE_API_URL}/api/sheet`;
const OPS_URL = `${BASE_API_URL}/api/ops`;
const QR_ORIGIN = BASE_API_URL;

const LIVE_LOCATION_CONFIG = {
  key: "AIzaSyB1PtwlsIgr026u29gU2L8ZXcozbkHpHco",
  api: BASE_API_URL,
  trip: "",
  fbdb: "https://shuttle-system-487204-default-rtdb.asia-southeast1.firebasedatabase.app/",
  fbkey: "AIzaSyDatr-z00tNMnXD7WMoTJ0vygdVCJKNuQA"
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

// 是否啟用入住/退房/用餐日期（目前先關閉，保留代碼）
const ENABLE_BOOKING_DATES = false;

// 查詢分頁狀態
let queryDateList = [];
let currentQueryDate = "";
let currentDateRows = [];

/* ====== Timer 管理器（優化：統一管理所有定時器） ====== */
const timerManager = {
  _timers: new Set(),
  _intervals: new Set(),
  
  setTimeout(callback, delay) {
    const id = setTimeout(() => {
      this._timers.delete(id);
      callback();
    }, delay);
    this._timers.add(id);
    return id;
  },
  
  setInterval(callback, delay) {
    const id = setInterval(callback, delay);
    this._intervals.add(id);
    return id;
  },
  
  clearTimeout(id) {
    if (this._timers.has(id)) {
      clearTimeout(id);
      this._timers.delete(id);
    }
  },
  
  clearInterval(id) {
    if (this._intervals.has(id)) {
      clearInterval(id);
      this._intervals.delete(id);
    }
  },
  
  clearAll() {
    this._timers.forEach(id => clearTimeout(id));
    this._intervals.forEach(id => clearInterval(id));
    this._timers.clear();
    this._intervals.clear();
  }
};

/* ====== DOM 元素緩存（優化：避免重複查詢） ====== */
const domCache = {
  _elements: new Map(), // ID 緩存
  _selectors: new Map(), // 選擇器緩存
  
  // 初始化緩存（在 DOM 加載完成後調用）
  init() {
    const commonIds = [
      "scrollToTop", "marqueeContainer", "marqueeContent", "dialogOverlay",
      "dialogTitle", "dialogContent", "dialogCancelBtn", "dialogConfirmBtn",
      "loading", "loadingConfirm", "expiredOverlay", "initialLoading",
      "homeHero", "step1", "step2", "step3", "step4", "step5", "step6",
      "successCard", "passengers", "passengersErr", "passengersHint",
      "identitySelect", "checkInDate", "checkOutDate", "diningDate",
      "roomNumber", "name", "phone", "email", "scheduleResults"
    ];
    commonIds.forEach(id => {
      const el = document.getElementById(id);
      if (el) this._elements.set(id, el);
    });
    
    const commonSelectors = [".navbar"];
    commonSelectors.forEach(selector => {
      const el = document.querySelector(selector);
      if (el) this._selectors.set(selector, el);
    });
  },
  
  // 獲取元素（如果緩存中沒有，則查詢並緩存）
  get(id) {
    return this.getElement(id);
  },
  
  // 通用獲取元素（自動緩存）
  getElement(id) {
    if (!this._elements.has(id)) {
      const el = document.getElementById(id);
      if (el) {
        this._elements.set(id, el);
      }
      return el;
    }
    return this._elements.get(id);
  },
  
  // 通用查詢選擇器（自動緩存）
  querySelector(selector) {
    if (!this._selectors.has(selector)) {
      const el = document.querySelector(selector);
      if (el) {
        this._selectors.set(selector, el);
      }
      return el;
    }
    return this._selectors.get(selector);
  },
  
  // 清除緩存（用於動態內容）
  clear(id) {
    if (id) {
      this._elements.delete(id);
      this._selectors.delete(id);
    } else {
      this._elements.clear();
      this._selectors.clear();
    }
  }
};

// 包裝函數，方便全局使用
function getElement(id) {
  return domCache.getElement(id);
}

function querySelector(selector) {
  return domCache.querySelector(selector);
}

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

function getDirectionLabel(direction) {
  if (direction === "去程") return t("dirOutLabel");
  if (direction === "回程") return t("dirInLabel");
  return direction || "";
}

/* ====== 日期時間工具函數（統一管理） ====== */
// 這些函數被多處使用，統一放在這裡便於維護和優化

function handleScroll() {
  const btn = domCache.get("scrollToTop");
  if (!btn) return;
  
  // 支援多種滾動位置獲取方式，確保手機版也能正常運作
  // 優先使用 scrollingElement（手機瀏覽器更穩定）
  const windowScrollY = Math.max(
    document.documentElement ? document.documentElement.scrollTop || 0 : 0,
    document.body ? document.body.scrollTop || 0 : 0,
    window.scrollY !== undefined ? window.scrollY : 0,
    window.pageYOffset || 0
  );
  let containerScrollY = 0;
  if (scrollContainers.length) {
    scrollContainers.forEach((el) => {
      if (el && typeof el.scrollTop === "number") {
        containerScrollY = Math.max(containerScrollY, el.scrollTop);
      }
    });
  }
  const y = Math.max(windowScrollY, containerScrollY);
  
  // 手機版使用更小的滾動閾值（因為畫面高度較小）
  const isMobile = window.innerWidth <= 768;
  let scrollThreshold;
  if (isMobile) {
    // 手機版：滾動超過 200px 或視窗高度的 30% 就顯示（取較小值）
    const screenHeight = window.innerHeight || document.documentElement.clientHeight || 300;
    scrollThreshold = Math.min(200, screenHeight * 0.3);
  } else {
    // 電腦版：超過一個畫面高度就顯示
    scrollThreshold = window.innerHeight || document.documentElement.clientHeight || 300;
  }
  
  const shouldShow = y > scrollThreshold;
  
  // 強制更新 display 狀態，確保手機版也能正確觸發
  // 直接操作 style.display，確保樣式優先級最高
  // 移除所有可能影響顯示的屬性
  if (shouldShow) {
    btn.style.display = "block";
    btn.style.visibility = "visible";
    btn.removeAttribute("hidden");
    btn.style.opacity = "1";
  } else {
    btn.style.display = "none";
    btn.style.visibility = "hidden";
    btn.setAttribute("hidden", "true");
  }
}

let scrollContainers = [];
function refreshScrollContainers() {
  const candidates = new Set();
  const activePage = document.querySelector(".page.active");
  if (activePage) {
    candidates.add(activePage);
    activePage.querySelectorAll("*").forEach((el) => {
      const style = window.getComputedStyle(el);
      if (
        (style.overflowY === "auto" || style.overflowY === "scroll") &&
        el.scrollHeight > el.clientHeight
      ) {
        candidates.add(el);
      }
    });
  }
  if (document.documentElement) candidates.add(document.documentElement);
  if (document.body) candidates.add(document.body);

  scrollContainers = Array.from(candidates);
  scrollContainers.forEach((el) => {
    if (!el || el.dataset.scrollListenerBound) return;
    el.addEventListener("scroll", handleScroll, { passive: true });
    el.dataset.scrollListenerBound = "true";
  });
}

// 回到頂部函數（確保手機版也能正常觸發）
function scrollToTop() {
  // 使用多種方式確保滾動到頂部
  window.scrollTo({ top: 0, behavior: "smooth" });
  document.documentElement.scrollTo({ top: 0, behavior: "smooth" });
  document.body.scrollTo({ top: 0, behavior: "smooth" });
  // 立即更新按鈕狀態
  setTimeout(() => {
    handleScroll();
  }, 100);
}

function showPage(id) {
  hardResetOverlays();

  // 優化：簡化 DOM 查詢，使用緩存
  const pages = document.querySelectorAll(".page");
  pages.forEach((p) => p.classList.remove("active"));
  const pageEl = getElement(id);
  if (pageEl) pageEl.classList.add("active");
  refreshScrollContainers();
  handleScroll();

  // 優化：使用緩存的查詢結果
  const navButtons = document.querySelectorAll(".nav-links button");
  navButtons.forEach((b) => b.classList.remove("active"));
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
  const navEl = getElement(navId);
  if (navEl) navEl.classList.add("active");

  // 批量操作優化
  requestAnimationFrame(() => {
    const tabbar = querySelector(".mobile-tabbar");
    if (tabbar) {
      tabbar.querySelectorAll("button").forEach((b) => b.classList.remove("active"));
    }
  });
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
  const mEl = getElement(mId);
  if (mEl) mEl.classList.add("active");

  window.scrollTo({ top: 0, behavior: "smooth" });
  
  // 確保在頁面切換後更新按鈕狀態（延遲執行以確保滾動完成）
  setTimeout(() => {
    handleScroll();
  }, 100);
  // 再次延遲執行，確保平滑滾動完成後也能正確更新
  setTimeout(() => {
    handleScroll();
  }, 500);

  if (id === "reservation") {
    const homeHero = getElement("homeHero");
    if (homeHero) homeHero.style.display = "";
    ["step1", "step2", "step3", "step4", "step5", "step6", "successCard"].forEach(
      (s) => {
        const el = getElement(s);
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
  const el = domCache.get("loading");
  if (el) el.classList.toggle("show", s);
}
function showVerifyLoading(s = true) {
  const el = domCache.get("loadingConfirm");
  if (el) el.classList.toggle("show", s);
}
function showExpiredOverlay(s = true) {
  const el = domCache.get("expiredOverlay");
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
  const bar = domCache.get("marqueeContainer");
  if (bar) {
    bar.style.display = 'none';
  }
  // 移除 has-marquee 類別，讓 navbar 回到 top: 0（通過 CSS 自動處理）
  document.body.classList.remove("has-marquee");
}

function toggleCollapse(id) {
  const el = getElement(id);
  if (!el) return;
  el.classList.toggle("open");
  const icon = el.querySelector(".toggle-icon");
  if (icon) icon.textContent = el.classList.contains("open") ? "▾" : "▸";
}

function hardResetOverlays() {
  // 使用緩存的元素
  const elements = {
    loading: domCache.get("loading"),
    loadingConfirm: domCache.get("loadingConfirm"),
    expiredOverlay: domCache.get("expiredOverlay"),
    dialogOverlay: domCache.get("dialogOverlay"),
    successAnimation: getElement("successAnimation")
  };
  
  Object.entries(elements).forEach(([id, el]) => {
    if (!el) return;
    if (id === "successAnimation") {
      el.classList.remove("show");
      el.style.display = "none";
    } else {
      el.classList.remove("show");
    }
  });
}

/* ====== 跑馬燈 ====== */
function showMarquee() {
  const marqueeContainer = domCache.get("marqueeContainer");
  const marqueeContent = domCache.get("marqueeContent");
  if (!marqueeContainer || !marqueeContent) return;

  // 如果跑馬燈被關閉或沒有內容，隱藏容器並移除 body 類別
  if (marqueeClosed || !marqueeData.text || !marqueeData.text.trim()) {
    marqueeContainer.style.display = "none";
    document.body.classList.remove("has-marquee");
    return;
  }

  // 有內容時顯示跑馬燈
  marqueeContent.textContent = marqueeData.text;
  marqueeContainer.style.display = "block";
  document.body.classList.add("has-marquee");
  restartMarqueeAnimation();
}

function restartMarqueeAnimation() {
  const marqueeContent = domCache.get("marqueeContent");
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

function showErrorCard(message, options = {}) {
  const overlay = domCache.get("dialogOverlay");
  const title = domCache.get("dialogTitle");
  const content = domCache.get("dialogContent");
  const cancelBtn = domCache.get("dialogCancelBtn");
  const confirmBtn = domCache.get("dialogConfirmBtn");
  if (!overlay || !title || !content || !cancelBtn || !confirmBtn) return;

  title.textContent = t("errorTitle");
  content.innerHTML = `<p>${sanitize(message || t("errorGeneric"))}</p>`;
  cancelBtn.style.display = "none";
  confirmBtn.disabled = false;
  confirmBtn.textContent = options.confirmText || t("ok");
  confirmBtn.onclick = () => {
    overlay.classList.remove("show");
    if (typeof options.onConfirm === "function") {
      options.onConfirm();
    }
  };
  overlay.classList.add("show");
}

function showConfirmDelete(bookingId, onConfirm) {
  const overlay = domCache.get("dialogOverlay");
  const title = domCache.get("dialogTitle");
  const content = domCache.get("dialogContent");
  const cancelBtn = domCache.get("dialogCancelBtn");
  const confirmBtn = domCache.get("dialogConfirmBtn");
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

  // 保存定時器引用以便清理
  let confirmTimerRef = timer;
  
  confirmBtn.onclick = () => {
    if (confirmTimerRef) {
      clearInterval(confirmTimerRef);
      confirmTimerRef = null;
    }
    overlay.classList.remove("show");
    onConfirm && onConfirm();
  };
  
  // 當對話框關閉時也清理定時器（監聽 class 變化）
  const observer = new MutationObserver((mutations) => {
    mutations.forEach((mutation) => {
      if (mutation.type === 'attributes' && mutation.attributeName === 'class') {
        if (!overlay.classList.contains('show') && confirmTimerRef) {
          clearInterval(confirmTimerRef);
          confirmTimerRef = null;
          observer.disconnect();
        }
      }
    });
  });
  observer.observe(overlay, { attributes: true });
  
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
  const nameErr = getElement("nameErr");
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
  const nameErr = getElement("nameErr");
  
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
  const phoneErr = getElement("phoneErr");
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
  const emailErr = getElement("emailErr");
  emailErr.style.display = "none";
  input.style.borderColor = "#ddd";
}

function validateEmailOnBlur(input) {
  const value = input.value || "";
  const emailErr = getElement("emailErr");
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
  const roomErr = getElement("roomErr");
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
  const hero = getElement("homeHero");
  if (hero) hero.style.display = "none";
  refreshData().then(() => {
    buildStep1();
    const s1 = getElement("step1");
    if (s1) s1.style.display = "";
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

function goStep(n) {
  ["step1", "step2", "step3", "step4", "step5", "step6"].forEach((id) => {
    const el = getElement(id);
    if (el) el.style.display = "none";
  });
  const target = getElement("step" + n);
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
  const hero = getElement("homeHero");
  if (hero) hero.style.display = "";
  [
    "directionList",
    "dateList",
    "stationList",
    "scheduleList",
    "bookingSlots-dateFilter",
    "bookingSlots-totalSlots",
    "bookingSlots-tableContainer"
  ].forEach((id) => {
    const el = getElement(id);
    if (el) el.innerHTML = "";
  });
  ["step1", "step2", "step3", "step4", "step5", "step6", "successCard"].forEach(
    (id) => {
      const el = getElement(id);
      if (el) el.style.display = "none";
    }
  );
  showPage("reservation");
  window.scrollTo({ top: 0, behavior: "smooth" });
}

/* ====== Step 1 ====== */
function buildStep1() {
  const list = getElement("directionList");
  if (!list) return;
  list.innerHTML = "";
  const opts = [
    { valueZh: "去程", labelKey: "dirOutLabel" },
    { valueZh: "回程", labelKey: "dirInLabel" }
  ];
  const fragment = document.createDocumentFragment();
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
    fragment.appendChild(btn);
  });
  list.appendChild(fragment);
}

function toStep2() {
  if (!selectedDirection) {
    showErrorCard(t("labelDirection"));
    return;
  }
  const step2Title = getElement("step2TitleText");
  if (step2Title) {
    step2Title.textContent =
      selectedDirection === "回程" ? t("step2TitleInbound") : t("step2TitleOutbound");
  }
  updateStep2Hints();
  updateStep2StationLabel();
  bookingSlotsLoadData();
  goStep(2);
}

/* ====== Step 2：班次/站點列表 ====== */
let bookingSlotsData = {
  allTimeSlots: [],
  filteredTimeSlots: [],
  currentFilter: {
    date: "all",
    direction: "all",
    station: "all"
  }
};

const bookingSlotsStationNameMap = {
  mrt: "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3",
  train: "南港火車站 Nangang Train Station",
  lala: "LaLaport Shopping Park"
};

function bookingSlotsComputeMainDateTime(directionKey, dateStr, timeStr, stationName) {
  if (!dateStr || !timeStr) return { date: dateStr, time: timeStr };
  const stationText = String(stationName || "");
  let offsetMin = 0;
  if (directionKey === "inbound") {
    if (/捷運|Exhibition Center/i.test(stationText)) offsetMin = 5;
    else if (/火車|Train Station/i.test(stationText)) offsetMin = 10;
    else if (/LaLaport/i.test(stationText)) offsetMin = 20;
  }

  const base = new Date(`${dateStr}T${timeStr}:00`);
  if (Number.isNaN(base.getTime())) return { date: dateStr, time: timeStr };
  base.setMinutes(base.getMinutes() - offsetMin);
  const y = base.getFullYear();
  const m = String(base.getMonth() + 1).padStart(2, "0");
  const d = String(base.getDate()).padStart(2, "0");
  const hh = String(base.getHours()).padStart(2, "0");
  const mm = String(base.getMinutes()).padStart(2, "0");
  return { date: `${y}-${m}-${d}`, time: `${hh}:${mm}` };
}

function bookingSlotsGetDirectionKey() {
  return selectedDirection === "回程" ? "inbound" : "outbound";
}

function bookingSlotsNormalizeStationKey(name) {
  const s = String(name || "");
  if (!s) return null;
  if (/捷運|MRT/i.test(s)) return "mrt";
  if (/火車|Train/i.test(s)) return "train";
  if (/Lala|Laport/i.test(s)) return "lala";
  return null;
}

function bookingSlotsParseAvailability(text) {
  const digits = onlyDigits(text || "");
  if (!digits) return null;
  return Number(digits) || 0;
}

function bookingSlotsFormatDate(dateStr) {
  if (!dateStr) return "";
  return String(dateStr).replace(/-/g, "/");
}

function bookingSlotsIsDeparted(dateStr, timeStr) {
  try {
    const dateTime = new Date(`${dateStr} ${timeStr}`.replace(/-/g, "/"));
    if (Number.isNaN(dateTime.getTime())) return false;
    return dateTime.getTime() < Date.now();
  } catch (e) {
    return false;
  }
}

function bookingSlotsLoadData() {
  const container = getElement("bookingSlots-tableContainer");
  if (container) {
    container.innerHTML = `<div class="loading">${t("loading")}</div>`;
  }

  const directionKey = bookingSlotsGetDirectionKey();
  const step2Title = getElement("step2TitleText");
  if (step2Title) {
    step2Title.textContent =
      directionKey === "inbound" ? t("step2TitleInbound") : t("step2TitleOutbound");
  }
  updateStep2Hints(directionKey);
  updateStep2StationLabel(directionKey);
  const rows = allRows.filter(
    (r) => String(r["去程 / 回程"]).trim() === selectedDirection
  );
  const slotsMap = new Map();

  rows.forEach((r) => {
    const date = fmtDateLabel(r["日期"]);
    const time = fmtTimeLabel(r["班次"] || r["車次"]);
    const stationName = String(r["站點"] || "").trim();
    const stationKey = bookingSlotsNormalizeStationKey(stationName);
    if (!date || !time || !stationKey) return;

    const mainDt = bookingSlotsComputeMainDateTime(directionKey, date, time, stationName);
    const key = `${mainDt.date}|${mainDt.time}`;
    if (!slotsMap.has(key)) {
      slotsMap.set(key, {
        date: mainDt.date,
        time: mainDt.time,
        datetime: `${mainDt.date} ${mainDt.time}`,
        stations: {
          outbound: { mrt: null, train: null, lala: null },
          inbound: { mrt: null, train: null, lala: null }
        },
        stationNames: {
          outbound: {},
          inbound: {}
        }
      });
    }
    const slot = slotsMap.get(key);
    const availText = String(
      r["可預約人數"] || r["可約人數 / Available"] || ""
    ).trim();
    const avail = bookingSlotsParseAvailability(availText);
    slot.stations[directionKey][stationKey] = {
      avail,
      time
    };
    slot.stationNames[directionKey][stationKey] = stationName;
  });

  bookingSlotsData.allTimeSlots = Array.from(slotsMap.values()).sort((a, b) => {
    if (a.date !== b.date) return a.date.localeCompare(b.date);
    return a.time.localeCompare(b.time);
  });

  bookingSlotsData.currentFilter.date = "all";
  bookingSlotsData.currentFilter.station = "all";
  bookingSlotsData.currentFilter.direction = directionKey;

  bookingSlotsInitDateFilter();
  bookingSlotsInitStationFilter();
  bookingSlotsUpdateFilterButtons("direction", directionKey);
  bookingSlotsLockDirectionButtons(directionKey);
  bookingSlotsApplyFilters();
}

function bookingSlotsInitDateFilter() {
  const dateFilter = getElement("bookingSlots-dateFilter");
  if (!dateFilter) return;
  const dates = [
    ...new Set(bookingSlotsData.allTimeSlots.map((s) => s.date))
  ].sort();
  dateFilter.innerHTML = "";
  const optAll = document.createElement("option");
  optAll.value = "all";
  optAll.textContent = t("allDates");
  dateFilter.appendChild(optAll);
  dates.forEach((date) => {
    const option = document.createElement("option");
    option.value = date;
    option.textContent = bookingSlotsFormatDate(date);
    dateFilter.appendChild(option);
  });
}

function bookingSlotsFilterByDate() {
  const dateFilter = getElement("bookingSlots-dateFilter");
  bookingSlotsData.currentFilter.date = dateFilter ? dateFilter.value : "all";
  bookingSlotsApplyFilters();
}

function bookingSlotsFilterByDirection(direction) {
  const directionKey = bookingSlotsGetDirectionKey();
  bookingSlotsData.currentFilter.direction = directionKey;
  bookingSlotsApplyFilters();
}

function bookingSlotsFilterByStation(station) {
  const stationFilter = getElement("bookingSlots-stationFilter");
  bookingSlotsData.currentFilter.station = stationFilter ? stationFilter.value : "all";
  bookingSlotsApplyFilters();
}

function bookingSlotsInitStationFilter() {
  const stationFilter = getElement("bookingSlots-stationFilter");
  if (!stationFilter) return;
  stationFilter.innerHTML = "";
  const optAll = document.createElement("option");
  optAll.value = "all";
  optAll.textContent = t("allStations");
  stationFilter.appendChild(optAll);

  const stationOptions = [
    { key: "mrt", label: t("stationMrtFull") },
    { key: "train", label: t("stationTrainFull") },
    { key: "lala", label: t("stationLalaFull") }
  ];
  stationOptions.forEach((station) => {
    const option = document.createElement("option");
    option.value = station.key;
    option.textContent = station.label;
    stationFilter.appendChild(option);
  });
  stationFilter.value = bookingSlotsData.currentFilter.station || "all";
}

function updateStep2Hints(directionKey = bookingSlotsGetDirectionKey()) {
  const pickupValue = getElement("pickupHintValue");
  const dropoffValue = getElement("dropoffHintValue");
  if (!pickupValue || !dropoffValue) return;
  const hotelText = t("forteHotel");
  const selectText = t("pleaseSelect");
  if (directionKey === "inbound") {
    pickupValue.textContent = selectText;
    pickupValue.classList.add("hint-alert");
    dropoffValue.textContent = hotelText;
    dropoffValue.classList.remove("hint-alert");
  } else {
    pickupValue.textContent = hotelText;
    pickupValue.classList.remove("hint-alert");
    dropoffValue.textContent = selectText;
    dropoffValue.classList.add("hint-alert");
  }
}

function updateStep2StationLabel(directionKey = bookingSlotsGetDirectionKey()) {
  const labelEl = getElement("bookingStationLabel");
  if (!labelEl) return;
  labelEl.textContent = directionKey === "inbound" ? t("labelPickupStation") : t("labelDropoffStation");
}

function bookingSlotsUpdateFilterButtons(type, value) {
  const buttons = document.querySelectorAll(
    `#bookingTimeSlots [data-filter-type="${type}"]`
  );
  buttons.forEach((btn) => {
    if (btn.dataset.filter === value) btn.classList.add("active");
    else btn.classList.remove("active");
  });
}

function bookingSlotsLockDirectionButtons(directionKey) {
  const buttons = document.querySelectorAll(
    `#bookingTimeSlots [data-filter-type="direction"]`
  );
  buttons.forEach((btn) => {
    const isAllowed = btn.dataset.filter === directionKey;
    if (!isAllowed) {
      btn.classList.add("disabled");
      btn.disabled = true;
    } else {
      btn.classList.remove("disabled");
      btn.disabled = false;
    }
  });
}

function bookingSlotsApplyFilters() {
  bookingSlotsData.filteredTimeSlots = bookingSlotsData.allTimeSlots.filter((slot) => {
    if (bookingSlotsData.currentFilter.date !== "all" && slot.date !== bookingSlotsData.currentFilter.date) {
      return false;
    }

    const directionKey = bookingSlotsData.currentFilter.direction;
    const stationFilter = bookingSlotsData.currentFilter.station;

    if (stationFilter === "all") return true;

    const entry = slot.stations[directionKey][stationFilter];
    return entry !== null;
  });

  bookingSlotsUpdateStats();
  bookingSlotsRenderTable();
}

function bookingSlotsUpdateStats() {
  const totalSlotsEl = getElement("bookingSlots-totalSlots");
  if (totalSlotsEl) {
    totalSlotsEl.textContent = bookingSlotsData.filteredTimeSlots.length;
  }
}

function bookingSlotsRenderTable() {
  const container = getElement("bookingSlots-tableContainer");
  if (!container) return;

  if (bookingSlotsData.filteredTimeSlots.length === 0) {
    container.innerHTML = `<div class="empty-state">${t("noSchedules")}</div>`;
    return;
  }

  const directionKey = bookingSlotsData.currentFilter.direction;
  const showOutbound = directionKey === "outbound";
  const showInbound = directionKey === "inbound";
  const showAllStations = bookingSlotsData.currentFilter.station === "all";
  const showMrt = showAllStations || bookingSlotsData.currentFilter.station === "mrt";
  const showTrain = showAllStations || bookingSlotsData.currentFilter.station === "train";
  const showLala = showAllStations || bookingSlotsData.currentFilter.station === "lala";
  const colCount =
    (showMrt ? 1 : 0) + (showTrain ? 1 : 0) + (showLala ? 1 : 0);

  let html = '<div class="time-slot-table">';
  const groupedByDate = {};
  bookingSlotsData.filteredTimeSlots.forEach((slot) => {
    if (!groupedByDate[slot.date]) groupedByDate[slot.date] = [];
    groupedByDate[slot.date].push(slot);
  });

  Object.keys(groupedByDate)
    .sort()
    .forEach((date) => {
      const slots = groupedByDate[date];
      const pickHintKey = directionKey === "inbound" ? "slotPickHintInbound" : "slotPickHintOutbound";
      html += `
        <div class="date-card">
          <div class="date-card-header">
            <span class="date-title">${bookingSlotsFormatDate(date)}</span>
            <span class="date-hint">(${t(pickHintKey)})</span>
          </div>
          <div class="date-card-content">
            <table>
              <thead>
                <tr>
                  <th class="time-col">${t("labelScheduleOnly")}</th>
                  ${showOutbound || showInbound ? `
                  ${showMrt ? `<th class="station">${t("stationMrtFull")}</th>` : ""}
                  ${showTrain ? `<th class="station">${t("stationTrainFull")}</th>` : ""}
                  ${showLala ? `<th class="station">${t("stationLalaFull")}</th>` : ""}
                  ` : ""}
                </tr>
              </thead>
              <tbody>
      `;
      slots.forEach((slot) => {
        html += `<tr>`;
        html += `<td class="time-col"><span class="datetime-time">${slot.time}</span></td>`;
        if (showOutbound || showInbound) {
          if (showMrt) {
            html += `<td class="station-cell">${bookingSlotsRenderStationCell(slot, directionKey, "mrt")}</td>`;
          }
          if (showTrain) {
            html += `<td class="station-cell">${bookingSlotsRenderStationCell(slot, directionKey, "train")}</td>`;
          }
          if (showLala) {
            html += `<td class="station-cell">${bookingSlotsRenderStationCell(slot, directionKey, "lala")}</td>`;
          }
        }
        html += `</tr>`;
      });
      html += `
              </tbody>
            </table>
          </div>
        </div>
      `;
    });

  html += "</div>";
  container.innerHTML = html;

  container.querySelectorAll(".station-value[data-capacity]").forEach((btn) => {
    btn.addEventListener("click", () => {
      container.querySelectorAll(".station-value.selected").forEach((el) => {
        el.classList.remove("selected");
      });
      btn.classList.add("selected");
      selectedDateRaw = btn.getAttribute("data-date") || "";
      selectedScheduleTime = btn.getAttribute("data-time") || "";
      const stRaw = btn.getAttribute("data-station") || "";
      selectedStationRaw = decodeURIComponent(stRaw);
      selectedAvailableSeats = Number(btn.getAttribute("data-capacity") || "0") || 0;
      toStep6();
    });
  });
}

function bookingSlotsRenderStationCell(slot, directionKey, stationKey) {
  const entry = slot.stations[directionKey][stationKey];
  const stationName =
    slot.stationNames[directionKey][stationKey] ||
    bookingSlotsStationNameMap[stationKey] ||
    "";

  if (entry === null) {
    const departed = bookingSlotsIsDeparted(slot.date, slot.time);
    const label = departed ? t("slotDeparted") : t("slotNotOpen");
    const tip = t("slotUnavailableTitle");
    return `<span class="station-value unavailable" title="${tip}">${label}</span>`;
  }
  const available = entry && typeof entry.avail === "number" ? entry.avail : 0;
  if (available <= 0) {
    const tip = t("slotUnavailableTitle");
    return `<span class="station-value soldout" title="${tip}">${t("soldOut")}</span>`;
  }

  const stationAttr = encodeURIComponent(stationName);
  return `
    <button class="station-value" data-date="${slot.date}" data-time="${entry.time}" data-station="${stationAttr}" data-capacity="${available}">
      ${available}
    </button>
  `;
}

/* ====== Step 5 ====== */
function onIdentityChange() {
  const v = (getElement("identitySelect") || {}).value;
  const today = todayISO();
  const hotelWrapper1 = getElement("hotelDates");
  const hotelWrapper2 = getElement("hotelDates2");
  const roomNumberDiv = getElement("roomNumberDiv");
  const diningDateDiv = getElement("diningDateDiv");

  if (hotelWrapper1) hotelWrapper1.style.display = ENABLE_BOOKING_DATES && v === "hotel" ? "block" : "none";
  if (hotelWrapper2) hotelWrapper2.style.display = ENABLE_BOOKING_DATES && v === "hotel" ? "block" : "none";
  if (roomNumberDiv) roomNumberDiv.style.display = v === "hotel" ? "block" : "none";
  if (diningDateDiv) diningDateDiv.style.display = ENABLE_BOOKING_DATES && v === "dining" ? "block" : "none";

  if (!ENABLE_BOOKING_DATES) {
    const ci = getElement("checkInDate");
    const co = getElement("checkOutDate");
    const din = getElement("diningDate");
    if (ci) ci.value = "";
    if (co) co.value = "";
    if (din) din.value = "";
    return;
  }

  if (v === "hotel") {
    const ci = getElement("checkInDate");
    const co = getElement("checkOutDate");
    if (ci && !ci.value) ci.value = today;
    if (co && !co.value) co.value = today;
  } else if (v === "dining") {
    const din = getElement("diningDate");
    if (din && !din.value) din.value = today;
  }
}

function toStep5() {
  toStep6();
}

function validateStep5() {
  const idEl = getElement("identitySelect");
  const id = idEl ? idEl.value : "";
  const nameEl = getElement("guestName");
  const name = (nameEl ? nameEl.value : "").trim();
  const phoneEl = getElement("guestPhone");
  const phone = (phoneEl ? phoneEl.value : "").trim();
  const emailEl = getElement("guestEmail");
  const email = (emailEl ? emailEl.value : "").trim();

  if (!id) {
    const identityErr = getElement("identityErr");
    if (identityErr) identityErr.style.display = "block";
    return false;
  } else {
    const identityErrEl = getElement("identityErr");
    if (identityErrEl) identityErrEl.style.display = "none";
  }

  if (!name) {
    const nameErrEl = getElement("nameErr");
    if (nameErrEl) nameErrEl.style.display = "block";
    const guestNameEl = getElement("guestName");
    if (guestNameEl) shake(guestNameEl);
    return false;
  } else {
    const nameErrEl = getElement("nameErr");
    if (nameErrEl) nameErrEl.style.display = "none";
  }

  if (!phoneRegex.test(phone)) {
    const phoneErrEl = getElement("phoneErr");
    if (phoneErrEl) phoneErrEl.style.display = "block";
    const guestPhoneEl = getElement("guestPhone");
    if (guestPhoneEl) shake(guestPhoneEl);
    return false;
  } else {
    const phoneErrEl = getElement("phoneErr");
    if (phoneErrEl) phoneErrEl.style.display = "none";
  }

  if (!emailRegex.test(email)) {
    const emailErrEl = getElement("emailErr");
    if (emailErrEl) emailErrEl.style.display = "block";
    const guestEmailEl = getElement("guestEmail");
    if (guestEmailEl) shake(guestEmailEl);
    return false;
  } else {
    const emailErrEl = getElement("emailErr");
    if (emailErrEl) emailErrEl.style.display = "none";
  }

  if (id === "hotel") {
    const checkInEl = getElement("checkInDate");
    const checkOutEl = getElement("checkOutDate");
    const cin = checkInEl ? checkInEl.value : "";
    const cout = checkOutEl ? checkOutEl.value : "";
    if (ENABLE_BOOKING_DATES && (!cin || !cout)) {
      showErrorCard(t("labelCheckIn") + "/" + t("labelCheckOut"));
      if (checkInEl) shake(checkInEl);
      if (checkOutEl) shake(checkOutEl);
      return false;
    }
    const roomEl = getElement("roomNumber");
    const room = (roomEl ? roomEl.value : "").trim();
    if (!roomRegex.test(room)) {
      const roomErrEl = getElement("roomErr");
      if (roomErrEl) roomErrEl.style.display = "block";
      if (roomEl) shake(roomEl);
      return false;
    } else {
      const roomErrEl = getElement("roomErr");
      if (roomErrEl) roomErrEl.style.display = "none";
    }
  } else {
    const diningDateEl = getElement("diningDate");
    const din = diningDateEl ? diningDateEl.value : "";
    if (ENABLE_BOOKING_DATES && !din) {
      showErrorCard(t("labelDiningDate"));
      if (diningDateEl) shake(diningDateEl);
      return false;
    }
  }

  return true;
}

function toStep6() {
  if (!selectedScheduleTime) {
    showErrorCard(t("labelSchedule"));
    return;
  }

  const cfDirectionEl = getElement("cf_direction");
  if (cfDirectionEl) cfDirectionEl.value = getDirectionLabel(selectedDirection);
  const cfDateEl = getElement("cf_date");
  if (cfDateEl) cfDateEl.value = selectedDateRaw;

  const pick =
    selectedDirection === "回程"
      ? selectedStationRaw
      : "福泰大飯店 Forte Hotel";
  const drop =
    selectedDirection === "回程"
      ? "福泰大飯店 Forte Hotel"
      : selectedStationRaw;

  const cfPickEl = getElement("cf_pick");
  if (cfPickEl) cfPickEl.value = pick;
  const cfDropEl = getElement("cf_drop");
  if (cfDropEl) cfDropEl.value = drop;
  const cfTimeEl = getElement("cf_time");
  if (cfTimeEl) cfTimeEl.value = selectedScheduleTime;
  const cfNameEl = getElement("cf_name");
  const guestNameEl = getElement("guestName");
  if (cfNameEl) cfNameEl.value = (guestNameEl ? guestNameEl.value : "").trim();

  const sel = getElement("passengers");
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
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = t("selectPassengers") || "請選擇";
    placeholder.disabled = true;
    placeholder.selected = true;
    sel.appendChild(placeholder);
    for (let i = 1; i <= maxPassengers; i++) {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = String(i);
      sel.appendChild(opt);
    }
  }
  const passengersHintEl = getElement("passengersHint");
  if (passengersHintEl) {
    passengersHintEl.textContent = `${t("paxHintPrefix")}${selectedAvailableSeats}${t("paxHintSuffix")}`;
  }

  ["step1", "step2", "step3", "step4", "step5"].forEach((id) => {
    const el = getElement(id);
    if (el) el.style.display = "none";
  });
  const s6 = getElement("step6");
  if (s6) s6.style.display = "";
  window.scrollTo({ top: 0, behavior: "smooth" });

  const errEl = getElement("passengersErr");
  if (errEl) errEl.style.display = "none";
  if (sel) {
    sel.onchange = () => {
      if (errEl) errEl.style.display = sel.value ? "none" : "block";
    };
  }

  onIdentityChange();
  startSubmitCountdown();
}

function startSubmitCountdown(seconds = 3) {
  const btn = getElement("step6")?.querySelector('button[data-i18n="submit"]');
  if (!btn) return;
  let remaining = seconds;
  btn.disabled = true;
  btn.textContent = `${t("submit")} (${remaining})`;
  const timer = setInterval(() => {
    remaining -= 1;
    if (remaining <= 0) {
      clearInterval(timer);
      btn.disabled = false;
      btn.textContent = t("submit");
      return;
    }
    btn.textContent = `${t("submit")} (${remaining})`;
  }, 1000);
}

function updateStep6I18N() {
  const step6 = getElement("step6");
  if (step6 && step6.style.display !== "none") {
    const cfDirectionEl = getElement("cf_direction");
    if (cfDirectionEl) cfDirectionEl.value = getDirectionLabel(selectedDirection);

    const sel = getElement("passengers");
    if (sel) {
      const placeholder = sel.querySelector('option[value=""]');
      if (placeholder) placeholder.textContent = t("selectPassengers");
    }

    const passengersHintEl = getElement("passengersHint");
    if (passengersHintEl) {
      passengersHintEl.textContent = `${t("paxHintPrefix")}${selectedAvailableSeats}${t("paxHintSuffix")}`;
    }
  }

  const successCard = getElement("successCard");
  if (successCard && successCard.style.display !== "none") {
    const directionEl = getElement("ticketDirection");
    if (directionEl && currentBookingData && currentBookingData.direction) {
      directionEl.textContent = getDirectionLabel(currentBookingData.direction);
    }
    const paxEl = getElement("ticketPassengers");
    if (paxEl && currentBookingData && currentBookingData.passengers != null) {
      paxEl.textContent = currentBookingData.passengers + " " + t("labelPassengersShort");
    }
  }
}

/* ====== 成功動畫 ====== */
function showSuccessAnimation() {
  const el = getElement("successAnimation");
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

  if (!validateStep5()) return;

  const pSel = getElement("passengers");
  const pValue = pSel?.value || "";
  const p = Number(pValue || 0);
  if (!pValue || !p || p < 1 || p > 4) {
    const errEl = getElement("passengersErr");
    if (errEl) errEl.style.display = "block";
    if (pSel) shake(pSel);
    if (navigator.vibrate) navigator.vibrate(200);
    return;
  }
  const errEl = getElement("passengersErr");
  if (errEl) errEl.style.display = "none";

  const identityEl = getElement("identitySelect");
  const identity = identityEl ? identityEl.value : "";
  const payload = {
    direction: selectedDirection,
    date: selectedDateRaw,
    station: selectedStationRaw,
    time: selectedScheduleTime,
    identity,
    checkIn:
      identity === "hotel"
        ? (getElement("checkInDate")?.value || null)
        : null,
    checkOut:
      identity === "hotel"
        ? (getElement("checkOutDate")?.value || null)
        : null,
    diningDate:
      identity === "dining"
        ? (getElement("diningDate")?.value || null)
        : null,
    roomNumber:
      identity === "hotel"
        ? (getElement("roomNumber")?.value || null)
        : null,
    name: ((getElement("guestName")?.value || "")).trim(),
    phone: ((getElement("guestPhone")?.value || "")).trim(),
    email: ((getElement("guestEmail")?.value || "")).trim(),
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
  const step6 = getElement("step6");
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
    const backendMsgStr = String(backendMsg || "");
    const isCapacityError =
      res.status === 409 ||
      backendMsgStr.includes("capacity_exceeded") ||
      backendMsgStr.includes("capacity_not_found") ||
      backendMsgStr.includes("capacity_header_missing") ||
      backendMsgStr.includes("capacity_not_numeric");

    if (!res.ok) {
      if (res.status === 503) {
        showErrorCard(t("busyRetry"));
      } else if (isCapacityError) {
        showErrorCard(t("overPaxOrMissing"), {
          confirmText: t("backToHome"),
          onConfirm: () => restart()
        });
      } else {
        showErrorCard(t("submitFailedPrefix") + `HTTP ${res.status}`);
      }
      if (step6) step6.style.display = "";
      return;
    }

    if (!result || result.status !== "success") {
      if (isCapacityError) {
        showErrorCard(t("overPaxOrMissing"), {
          confirmText: t("backToHome"),
          onConfirm: () => restart()
        });
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
      qrUrl: qrPath,
      // ========== 母子車票信息 ==========
      sub_tickets: result.sub_tickets || [],
      mother_ticket: result.mother_ticket || null
    };
    
    // 保存到全局變量，供分票功能使用
    window.currentBookingData = currentBookingData;

    mountTicketAndShow(currentBookingData);
  } catch (err) {
    const errMsg = String((err && (err.error || err.message || err.detail || err.code)) || "");
    const maybeCapacity =
      err &&
      (errMsg.includes("capacity_exceeded") ||
        errMsg.includes("capacity_not_found") ||
        errMsg.includes("capacity_header_missing") ||
        errMsg.includes("capacity_not_numeric"));
    if (maybeCapacity) {
      showErrorCard(t("overPaxOrMissing"), {
        confirmText: t("backToHome"),
        onConfirm: () => restart()
      });
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
  const bookingIdEl = getElement("ticketBookingId");
  if (bookingIdEl) bookingIdEl.textContent = ticket.bookingId || "";

  // ✅ 修改這裡：將固定標題改為日期+班次
  const titleEl = getElement("ticketHeaderTitle");
  if (titleEl) {
    titleEl.textContent = formatTicketHeader(ticket.date, ticket.time);
  }

  const directionEl = getElement("ticketDirection");
  if (directionEl) directionEl.textContent = getDirectionLabel(ticket.direction);

  const pickEl = getElement("ticketPick");
  if (pickEl) pickEl.textContent = ticket.pickLocation || "";

  const dropEl = getElement("ticketDrop");
  if (dropEl) dropEl.textContent = ticket.dropLocation || "";

  const nameEl = getElement("ticketName");
  if (nameEl) nameEl.textContent = ticket.name || "";

  const phoneEl = getElement("ticketPhone");
  if (phoneEl) phoneEl.textContent = ticket.phone || "";

  const emailEl = getElement("ticketEmail");
  if (emailEl) emailEl.textContent = ticket.email || "";

  // ========== 母子車票處理 ==========
  const subTickets = ticket.sub_tickets || [];
  const motherTicket = ticket.mother_ticket || null;
  const hasSubTickets = subTickets.length > 0;
  
  let totalSubPax = 0;
  if (hasSubTickets) {
    totalSubPax = subTickets.reduce((sum, t) => sum + (t.pax || 0), 0);
  } else {
    // 如果沒有子票，使用總人數
    totalSubPax = ticket.passengers || 0;
  }

  const paxEl = getElement("ticketPassengers");
  if (paxEl) {
    const paxText = ticket.passengers + " " + t("labelPassengersShort");
    const subTicketText = hasSubTickets ? ` (${totalSubPax}人，分${subTickets.length}張子票)` : "";
    paxEl.textContent = paxText + subTicketText;
  }

  // ========== 更新 QR Code 顯示區域（支持左右切換） ==========
  const qrContainer = getElement("ticketQrContainer");
  
  // 調試：打印票卷數據
  console.log("[mountTicketAndShow] ticket:", ticket);
  console.log("[mountTicketAndShow] subTickets:", subTickets);
  console.log("[mountTicketAndShow] motherTicket:", motherTicket);
  console.log("[mountTicketAndShow] hasSubTickets:", hasSubTickets);
  
  if (hasSubTickets) {
    // 母子車票模式：使用輪播顯示（母票 + 所有子票）
    // 計算已上車人數
    let checkedPax = 0;
    subTickets.forEach(t => {
      if (t.status === "checked_in") checkedPax += (t.pax || 0);
    });
    
    // 構建所有票卷（母票A + 子票BCD...）
    const allTickets = [];
    
    // 添加母票（第一個，標記為A）
    if (motherTicket) {
      const motherQrUrl = motherTicket.qr_url || (motherTicket.qr_content ? `${QR_ORIGIN}/api/qr/${encodeURIComponent(motherTicket.qr_content)}` : "");
      if (motherQrUrl) {
        const motherBookingId = `${ticket.bookingId}_A`;
        allTickets.push({
          type: "mother",
          booking_id: motherBookingId,
          original_booking_id: ticket.bookingId,
          pax: totalSubPax,
          qr_url: motherQrUrl,
          qr_content: motherTicket.qr_content || "",
          label: "A",
          status: "mother"
        });
      }
    }
    
    // 添加所有子票（B, C, D, E...）
    subTickets.forEach((t, idx) => {
      const qrUrl = t.qr_url || (t.qr_content ? `${QR_ORIGIN}/api/qr/${encodeURIComponent(t.qr_content)}` : "");
      // 子票編號：B=66, C=67, D=68... (65='A'是母票)
      const ticketLetter = String.fromCharCode(66 + idx); // B, C, D, E...
      const subBookingId = `${ticket.bookingId}_${ticketLetter}`;
      allTickets.push({
        type: "sub",
        booking_id: subBookingId,
        original_booking_id: ticket.bookingId,
        sub_index: t.sub_index,
        pax: t.pax || 0,
        qr_url: qrUrl,
        qr_content: t.qr_content || "",
        status: t.status || "not_checked_in",
        label: ticketLetter
      });
    });
    
    // 保存所有票卷數據到全局變量，供切換時使用
    window.allTicketsData = allTickets;
    
    // 構建輪播 HTML
    let carouselHTML = `
      <div class="ticket-status-summary">
        <strong>上車狀態：</strong>
        <span class="status-text">${checkedPax}/${totalSubPax} 人已上車</span>
      </div>
      <div class="ticket-carousel-container">
        <button class="carousel-btn carousel-prev" onclick="switchTicket(-1)" aria-label="上一張">‹</button>
        <div class="ticket-carousel-track" id="ticketCarouselTrack">
    `;
    
    allTickets.forEach((tkt, idx) => {
      const isActive = idx === 0 ? "active" : "";
      const statusBadge = tkt.type === "mother" 
        ? `<div class="sub-ticket-status info">一次性核銷所有人</div>`
        : (tkt.status === "checked_in" 
          ? `<div class="sub-ticket-status checked-in">✓ 已上車</div>`
          : `<div class="sub-ticket-status not-checked-in">未上車</div>`);
      
      // 如果是已上車的子票，添加視覺標記
      const checkedInClass = tkt.status === "checked_in" ? " checked-in-ticket" : "";
      
      // 確保 QR URL 正確
      const qrUrlToUse = tkt.qr_url || (tkt.qr_content ? `${QR_ORIGIN}/api/qr/${encodeURIComponent(tkt.qr_content)}` : "");
      
      carouselHTML += `
        <div class="ticket-carousel-item ${isActive}" data-ticket-index="${idx}">
          <div class="sub-ticket-qr-item ${tkt.type === 'mother' ? 'mother-ticket' : ''}${checkedInClass}">
            <div class="sub-ticket-label" style="font-size:24px;font-weight:bold;margin-bottom:8px;">${tkt.label}</div>
            <div class="sub-ticket-pax" style="font-size:14px;color:#666;margin-bottom:12px;">${tkt.pax} 人</div>
            <div class="sub-ticket-qr"><img src="${qrUrlToUse}" alt="票卷 ${tkt.label}" onerror="this.src='${QR_ORIGIN}/api/qr/error'; console.error('QR load failed:', '${qrUrlToUse}');" /></div>
            ${statusBadge}
          </div>
        </div>
      `;
    });
    
    carouselHTML += `
        </div>
        <button class="carousel-btn carousel-next" onclick="switchTicket(1)" aria-label="下一張">›</button>
      </div>
      <div class="ticket-carousel-indicators">
    `;
    
    allTickets.forEach((tkt, idx) => {
      const isActive = idx === 0 ? "active" : "";
      carouselHTML += `<span class="carousel-dot ${isActive}" onclick="switchTicketTo(${idx})"></span>`;
    });
    
    carouselHTML += `</div>`;
    
    if (qrContainer) {
      qrContainer.innerHTML = carouselHTML;
      qrContainer.className = "ticket-qr multi-ticket";
    }
    
    // 保存當前票卷索引和所有票卷數據
    window.currentTicketIndex = 0;
    window.totalTickets = allTickets.length;
    window.allTicketsData = allTickets;
    
    // 初始化顯示第一個票卷的資訊
    if (allTickets.length > 0) {
      const firstTicket = allTickets[0];
      const bookingIdEl = getElement("ticketBookingId");
      if (bookingIdEl) {
        bookingIdEl.textContent = firstTicket.booking_id || ticket.bookingId || "";
      }
      const paxEl = getElement("ticketPassengers");
      if (paxEl) {
        const paxText = firstTicket.pax + " " + t("labelPassengersShort");
        paxEl.textContent = paxText;
      }
    }
  } else {
    // 單一車票模式（向後兼容）：顯示母票 + 分票按鈕
    if (qrContainer) {
      let singleTicketHTML = `
        <div class="ticket-qr-single">
          <img id="ticketQrImg" src="${ticket.qrUrl || ""}" alt="QR Code"/>
        </div>
      `;
      qrContainer.innerHTML = singleTicketHTML;
      qrContainer.className = "ticket-qr";
    }
    
    // 添加分票按鈕（如果人數 > 1，且未分票或有未上車的子票）
    const actionsContainer = getElement("ticketActionsContainer");
    if (actionsContainer && ticket.passengers > 1) {
      // 檢查是否有未上車的子票（如果有未上車的，可以重新分票）
      const hasUncheckedTickets = hasSubTickets && subTickets.some(t => t.status !== "checked_in");
      const canReSplit = hasSubTickets && hasUncheckedTickets;
      
      // 檢查是否已有分票按鈕
      if (!actionsContainer.querySelector(".split-ticket-btn")) {
        const splitBtn = document.createElement("button");
        splitBtn.className = "button split-ticket-btn";
        // 如果已分票且有未上車的子票，顯示「重新分票」
        splitBtn.textContent = canReSplit ? "重新分票" : "分票";
        splitBtn.onclick = () => showSplitTicketDialog(ticket, canReSplit);
        actionsContainer.insertBefore(splitBtn, actionsContainer.firstChild);
      }
    }
  }

  const card = getElement("successCard");
  if (card) card.style.display = "";
  window.scrollTo({ top: 0, behavior: "smooth" });

  // ✅ 先顯示票卡，再跑成功動畫
  showSuccessAnimation();
}

// ========== 分票功能 ==========
function showSplitTicketDialog(ticket, isReSplit = false) {
  const totalPax = ticket.passengers || 1;
  if (totalPax < 2) {
    showErrorCard("至少需要2人才能分票");
    return;
  }
  
  // 計算已上車人數和剩餘人數（如果是重新分票）
  let checkedInPax = 0;
  let remainingPax = totalPax;
  if (isReSplit && ticket.sub_tickets) {
    checkedInPax = ticket.sub_tickets
      .filter(t => t.status === "checked_in")
      .reduce((sum, t) => sum + (t.pax || 0), 0);
    remainingPax = totalPax - checkedInPax;
    
    if (remainingPax <= 0) {
      showErrorCard("所有人已上車，無法重新分票");
      return;
    }
  }
  
  // 創建分票對話框
  const dialog = document.createElement("div");
  dialog.className = "modal-overlay";
  dialog.style.cssText = "position:fixed;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.5);z-index:10000;display:flex;align-items:center;justify-content:center;";
  
  const content = document.createElement("div");
  content.className = "card";
  content.style.cssText = "max-width:500px;width:90%;max-height:90vh;overflow-y:auto;";
  
  const titleText = isReSplit ? "重新分票設定" : "分票設定";
  const infoText = isReSplit 
    ? `總人數：${totalPax} 人<br>已上車：${checkedInPax} 人<br><strong>剩餘可重新分票：${remainingPax} 人</strong>`
    : `總人數：${totalPax} 人`;
  
  // 最多可以分幾張票（每張至少1人，所以最多 = 剩餘人數）
  const maxTickets = remainingPax;
  
  content.innerHTML = `
    <h2>${titleText}</h2>
    <p style="margin-bottom:16px;">${infoText}</p>
    <div class="field">
      <label class="label">要分成幾張票卷？</label>
      <select id="splitTicketCount" class="select" onchange="updateSplitTicketInputs(${remainingPax})">
        ${Array.from({length: maxTickets - 1}, (_, i) => i + 2)
          .map(n => `<option value="${n}" ${n === 2 ? 'selected' : ''}>${n} 張</option>`)
          .join('')}
      </select>
    </div>
    <div id="splitTicketInputs"></div>
    <div id="splitTicketSummary" style="margin-top:12px;padding:12px;background:#f0f0f0;border-radius:8px;font-size:14px;">
      <strong>已分配：</strong><span id="splitTotalAssigned">0</span> / ${remainingPax} 人
    </div>
    <div class="actions" style="margin-top:20px;">
      <button class="button btn-ghost" onclick="this.closest('.modal-overlay').remove()">取消</button>
      <button class="button" id="confirmSplitBtn" onclick="handleConfirmSplitTicket('${ticket.bookingId}', ${remainingPax}, ${isReSplit})" disabled>確認${isReSplit ? '重新' : ''}分票</button>
    </div>
  `;
  
  dialog.appendChild(content);
  document.body.appendChild(dialog);
  
  // 初始化：生成默認2張票的輸入框
  updateSplitTicketInputs(remainingPax);
  
  dialog.onclick = (e) => {
    if (e.target === dialog) dialog.remove();
  };
}

function updateSplitTicketInputs(totalPax) {
  const countSelect = document.getElementById("splitTicketCount");
  const inputsContainer = document.getElementById("splitTicketInputs");
  const summaryEl = document.getElementById("splitTotalAssigned");
  const confirmBtn = document.getElementById("confirmSplitBtn");
  
  if (!countSelect || !inputsContainer) return;
  
  const ticketCount = parseInt(countSelect.value) || 2;
  inputsContainer.innerHTML = "";
  
  // 計算每張票的默認人數（盡量平均分配）
  const basePax = Math.floor(totalPax / ticketCount);
  const remainder = totalPax % ticketCount;
  const defaultSplit = Array(ticketCount).fill(basePax);
  for (let i = 0; i < remainder; i++) {
    defaultSplit[i]++;
  }
  
  // 生成輸入框
  defaultSplit.forEach((val, idx) => {
    const field = document.createElement("div");
    field.className = "field";
    const ticketLabel = String.fromCharCode(65 + idx); // A, B, C, D, E...
    field.innerHTML = `
      <label class="label">子票 ${ticketLabel} 人數</label>
      <input type="number" class="input split-pax-input" min="1" max="${totalPax}" value="${val}" data-index="${idx}" oninput="updateSplitTicketSummary(${totalPax})" />
    `;
    inputsContainer.appendChild(field);
  });
  
  // 更新總和顯示
  updateSplitTicketSummary(totalPax);
}

function updateSplitTicketSummary(totalPax) {
  const inputs = document.querySelectorAll(".split-pax-input");
  const summaryEl = document.getElementById("splitTotalAssigned");
  const confirmBtn = document.getElementById("confirmSplitBtn");
  
  if (!summaryEl || !confirmBtn) return;
  
  const ticketSplit = Array.from(inputs).map(inp => parseInt(inp.value) || 0);
  const sum = ticketSplit.reduce((a, b) => a + b, 0);
  
  summaryEl.textContent = sum;
  
  // 驗證：總和必須等於總人數，且每張至少1人
  const isValid = sum === totalPax && ticketSplit.every(pax => pax >= 1);
  
  if (isValid) {
    summaryEl.style.color = "#166534"; // 綠色
    confirmBtn.disabled = false;
    confirmBtn.style.opacity = "1";
  } else {
    summaryEl.style.color = "#dc2626"; // 紅色
    confirmBtn.disabled = true;
    confirmBtn.style.opacity = "0.5";
  }
}

function handleConfirmSplitTicket(bookingId, totalPax, isReSplit = false) {
  const inputs = document.querySelectorAll(".split-pax-input");
  const ticketSplit = Array.from(inputs).map(inp => parseInt(inp.value) || 0);
  const sum = ticketSplit.reduce((a, b) => a + b, 0);
  
  // 驗證：每張至少1人
  if (ticketSplit.some(pax => pax < 1)) {
    showErrorCard("每張票卷至少需要1人");
    return;
  }
  
  // 驗證：總和必須等於總人數
  if (sum !== totalPax) {
    showErrorCard(`分票總和 (${sum}) 必須等於${isReSplit ? '剩餘' : '總'}人數 (${totalPax})`);
    return;
  }
  
  // 驗證：至少2張票
  if (ticketSplit.length < 2) {
    showErrorCard("至少需要分成2張子票");
    return;
  }
  
  // 立即關閉對話框
  const overlay = document.querySelector(".modal-overlay");
  if (overlay) overlay.remove();
  
  // 執行分票
  confirmSplitTicket(bookingId, ticketSplit, isReSplit);
}

async function confirmSplitTicket(bookingId, ticketSplit, isReSplit = false) {
  // 顯示載入動畫
  showLoading(true);
  
  try {
    const res = await fetch(OPS_URL, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "split_ticket", data: { booking_id: bookingId, ticket_split: ticketSplit } })
    });
    
    const result = await res.json();
    if (!res.ok || result.status !== "success") {
      throw new Error(result.detail || result.message || "分票失敗");
    }
    
    // 分票成功：重新查詢訂單以獲取完整更新數據
    showSuccessAnimation();
    
    // 重新查詢訂單以獲取完整的分票數據
    try {
      const queryRes = await fetch(OPS_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ 
          action: "query", 
          data: { booking_id: bookingId } 
        })
      });
      
      const queryData = await queryRes.json();
      if (queryRes.ok && queryData && queryData.length > 0) {
        const updatedTicket = queryData[0];
        
        // 調試：打印查詢結果
        console.log("[split_ticket] Query result:", updatedTicket);
        console.log("[split_ticket] sub_tickets:", updatedTicket.sub_tickets);
        console.log("[split_ticket] mother_ticket:", updatedTicket.mother_ticket);
        
        // 構建完整的 ticket 對象（與 submitBooking 中的格式一致）
        // 注意：查詢結果使用中文字段名（如 "日期", "班次" 等）
        const ticketData = {
          bookingId: updatedTicket["預約編號"] || updatedTicket.booking_id || bookingId,
          date: updatedTicket["日期"] || updatedTicket.date || window.currentBookingData?.date || "",
          time: updatedTicket["班次"] || updatedTicket.time || window.currentBookingData?.time || "",
          direction: updatedTicket["往返"] || updatedTicket.direction || window.currentBookingData?.direction || "",
          pickLocation: updatedTicket["上車地點"] || updatedTicket.pick || window.currentBookingData?.pickLocation || "",
          dropLocation: updatedTicket["下車地點"] || updatedTicket.drop || window.currentBookingData?.dropLocation || "",
          name: updatedTicket["姓名"] || updatedTicket.name || window.currentBookingData?.name || "",
          phone: updatedTicket["手機"] || updatedTicket.phone || window.currentBookingData?.phone || "",
          email: updatedTicket["信箱"] || updatedTicket.email || window.currentBookingData?.email || "",
          passengers: parseInt(updatedTicket["預約人數"] || updatedTicket["確認人數"] || updatedTicket.pax || updatedTicket.passengers || window.currentBookingData?.passengers || "1"),
          qrUrl: updatedTicket["QRCode編碼"] ? `${QR_ORIGIN}/api/qr/${encodeURIComponent(updatedTicket["QRCode編碼"])}` : (updatedTicket.qr_url || window.currentBookingData?.qrUrl || ""),
          // ========== 母子車票信息（從查詢結果獲取） ==========
          sub_tickets: updatedTicket.sub_tickets || result.sub_tickets || [],
          mother_ticket: updatedTicket.mother_ticket || result.mother_ticket || null
        };
        
        // 調試：打印構建後的 ticketData
        console.log("[split_ticket] Built ticketData:", ticketData);
        console.log("[split_ticket] ticketData.sub_tickets:", ticketData.sub_tickets);
        console.log("[split_ticket] ticketData.mother_ticket:", ticketData.mother_ticket);
        
        // 更新全局變量
        window.currentBookingData = ticketData;
        
        // 重新渲染票卷（顯示所有子票和母票，支持切換）
        mountTicketAndShow(ticketData);
      } else {
        // 如果查詢失敗，至少更新現有數據
        if (window.currentBookingData) {
          window.currentBookingData.sub_tickets = result.sub_tickets || [];
          window.currentBookingData.mother_ticket = result.mother_ticket || null;
          mountTicketAndShow(window.currentBookingData);
        }
      }
    } catch (queryErr) {
      console.error("Failed to query updated ticket:", queryErr);
      // 如果查詢失敗，至少更新現有數據
      if (window.currentBookingData) {
        window.currentBookingData.sub_tickets = result.sub_tickets || [];
        window.currentBookingData.mother_ticket = result.mother_ticket || null;
        mountTicketAndShow(window.currentBookingData);
      }
    }
  } catch (e) {
    showErrorCard(`${isReSplit ? '重新' : ''}分票失敗：` + (e.message || ""));
  } finally {
    showLoading(false);
  }
}

// ========== 票卷切換功能 ==========
function switchTicket(direction) {
  const track = getElement("ticketCarouselTrack");
  if (!track) return;
  
  const items = track.querySelectorAll(".ticket-carousel-item");
  if (items.length === 0) return;
  
  const currentIdx = window.currentTicketIndex || 0;
  const newIdx = Math.max(0, Math.min(items.length - 1, currentIdx + direction));
  
  if (newIdx === currentIdx) return;
  
  switchTicketTo(newIdx);
}

function switchTicketTo(index) {
  const track = getElement("ticketCarouselTrack");
  if (!track) return;
  
  const items = track.querySelectorAll(".ticket-carousel-item");
  if (index < 0 || index >= items.length) return;
  
  const currentIdx = window.currentTicketIndex || 0;
  if (index === currentIdx) return;
  
  // 更新活動項
  items[currentIdx].classList.remove("active");
  items[index].classList.add("active");
  
  // 更新指示器
  const dots = document.querySelectorAll(".carousel-dot");
  if (dots[currentIdx]) dots[currentIdx].classList.remove("active");
  if (dots[index]) dots[index].classList.add("active");
  
  // 更新索引
  window.currentTicketIndex = index;
  
  // 滑動動畫
  track.style.transform = `translateX(-${index * 100}%)`;
  
  // ========== 同步更新下方資訊欄 ==========
  if (window.allTicketsData && window.allTicketsData[index]) {
    const currentTicket = window.allTicketsData[index];
    
    // 更新預約編號
    const bookingIdEl = getElement("ticketBookingId");
    if (bookingIdEl) {
      bookingIdEl.textContent = currentTicket.booking_id || "";
    }
    
    // 更新人數
    const paxEl = getElement("ticketPassengers");
    if (paxEl) {
      const paxText = currentTicket.pax + " " + t("labelPassengersShort");
      paxEl.textContent = paxText;
    }
  }
}

function closeTicketToHome() {
  const card = getElement("successCard");
  if (card) card.style.display = "none";
  const hero = getElement("homeHero");
  if (hero) hero.style.display = "";
  ["step1", "step2", "step3", "step4", "step5", "step6"].forEach((id) => {
    const el = getElement(id);
    if (el) el.style.display = "none";
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

async function downloadTicket() {
  const card = getElement("ticketCard");
  if (!card) {
    showErrorCard(t("ticketNotFound"));
    return;
  }
  try {
    const rect = card.getBoundingClientRect();
    const dpr = Math.max(window.devicePixelRatio || 1, 1);
    const width = Math.round(rect.width);
    const height = Math.round(rect.height);
    if (!window.domtoimage) throw new Error(t("domToImageNotFound"));
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
      (getElement("ticketBookingId")?.textContent || "ticket").trim();
    a.href = dataUrl;
    a.download = `ticket_${bid}.png`;
    a.click();
  } catch (e) {
    showErrorCard(t("downloadFailedPrefix") + (e?.message || e));
  }
}

/* ====== 查詢我的預約 ====== */
function showCheckQueryForm() {
  const qForm = getElement("queryForm");
  const dateStep = getElement("checkDateStep");
  const ticketStep = getElement("checkTicketStep");
  if (qForm) qForm.style.display = "flex";
  if (dateStep) dateStep.style.display = "none";
  if (ticketStep) ticketStep.style.display = "none";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showCheckDateStep() {
  const qForm = getElement("queryForm");
  const dateStep = getElement("checkDateStep");
  const ticketStep = getElement("checkTicketStep");
  // 保持搜尋框可見，只顯示日期選擇頁面
  if (qForm) qForm.style.display = "flex";
  if (dateStep) dateStep.style.display = "block";
  if (ticketStep) ticketStep.style.display = "none";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function showCheckTicketStep() {
  const qForm = getElement("queryForm");
  const dateStep = getElement("checkDateStep");
  const ticketStep = getElement("checkTicketStep");
  if (qForm) qForm.style.display = "none";
  if (dateStep) dateStep.style.display = "none";
  if (ticketStep) ticketStep.style.display = "block";
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function closeCheckTicket() {
  // 關閉車票頁面時，返回到日期選擇頁面（如果有查詢結果），否則返回到查詢表單
  const checkTicketStep = getElement("checkTicketStep");
  const checkDateStep = getElement("checkDateStep");
  if (checkTicketStep) checkTicketStep.style.display = "none";
  
  // 檢查是否有查詢結果
  if (lastQueryResults && lastQueryResults.length > 0) {
    // 提取所有唯一的日期
    const uniqueDates = new Set();
    lastQueryResults.forEach((r) => {
      const dt = getDateFromCarDateTime(String(r["車次-日期時間"] || ""));
      if (dt) uniqueDates.add(dt);
    });
    
    // 如果有日期（無論多少個），都返回到日期選擇頁面，保持搜尋框可見
    if (uniqueDates.size > 0) {
      showCheckDateStep();
    } else {
      // 沒有有效日期，返回到查詢表單
      showCheckQueryForm();
    }
  } else {
    // 沒有查詢結果，返回到查詢表單
    showCheckQueryForm();
  }
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
  if (p.length <= 4) return p;
  const last4 = p.slice(-4);
  const hiddenCount = p.length - 4;
  // 用*取代前面的數字，保持總長度（有幾個被隱藏的就要有幾個*）
  return "*".repeat(hiddenCount) + last4;
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
  const rbLabel = getDirectionLabel(rb);
  const pick = String(row["上車地點"] || "");
  const drop = String(row["下車地點"] || "");
  const bookingId = String(row["預約編號"] || "");
  const pax =
    Number(row["確認人數"] || row["預約人數"] || "1") || 1;
  const qrCodeContent = String(row["QRCode編碼"] || "");
  const qrUrl = qrCodeContent
    ? QR_ORIGIN + "/api/qr/" + encodeURIComponent(qrCodeContent)
    : "";

  // ========== 母子車票處理 ==========
  const subTickets = row["sub_tickets"] || [];
  const motherTicket = row["mother_ticket"] || null;
  const hasSubTickets = subTickets.length > 0;
  
  // 計算子票狀態
  let checkedPax = 0;
  let totalSubPax = 0;
  if (hasSubTickets) {
    totalSubPax = subTickets.reduce((sum, t) => sum + (t.pax || 0), 0);
    checkedPax = subTickets
      .filter(t => t.status === "checked_in")
      .reduce((sum, t) => sum + (t.pax || 0), 0);
  }

  // 使用模板字符串一次性構建 HTML，減少 DOM 操作
  const statusPillClass = `status-pill ${expired ? "status-expired" : "status-" + statusCode}`;
  const statusPillText = expired ? ts("expired") : ts(statusCode);
  const rejectedTipBtn = statusCode === "rejected"
    ? `<button class="badge-alert" title="${sanitize(t("rejectedTip"))}">!</button>`
    : "";
  
  // 構建 QR Code 顯示區域
  let qrSection = "";
  if (statusCode === "cancelled") {
    qrSection = `<div class="ticket-qr"><img src="/images/qr-placeholder.png" alt="QR placeholder" /></div>`;
  } else if (hasSubTickets) {
    // 母子車票模式：使用輪播顯示（母票 + 所有子票）
    // 構建所有票卷（母票 + 子票）
    const allTickets = [];
    
    // 添加母票（第一個）
    if (motherTicket && motherTicket.qr_url) {
      allTickets.push({
        type: "mother",
        booking_id: bookingId,
        pax: totalSubPax,
        qr_url: motherTicket.qr_url,
        label: "母票（全部）"
      });
    }
    
    // 添加所有子票（顯示子票編號，例如：26021205_A）
    subTickets.forEach((t) => {
      const qrUrl = t.qr_url || (t.qr_content ? `${QR_ORIGIN}/api/qr/${encodeURIComponent(t.qr_content)}` : "");
      const subBookingId = t.booking_id || `${bookingId}_${String.fromCharCode(64 + t.sub_index)}`;
      allTickets.push({
        type: "sub",
        booking_id: subBookingId,
        sub_index: t.sub_index,
        pax: t.pax || 0,
        qr_url: qrUrl,
        status: t.status || "not_checked_in",
        label: `子票 ${t.sub_index}`
      });
    });
    
    // 構建輪播 HTML
    let carouselHTML = `
      <div class="ticket-status-summary">
        <strong>上車狀態：</strong>
        <span class="status-text">${checkedPax}/${totalSubPax} 人已上車</span>
      </div>
      <div class="ticket-carousel-container">
        <button class="carousel-btn carousel-prev" onclick="switchTicket(-1)" aria-label="上一張">‹</button>
        <div class="ticket-carousel-track" id="ticketCarouselTrack">
    `;
    
    allTickets.forEach((tkt, idx) => {
      const isActive = idx === 0 ? "active" : "";
      const statusBadge = tkt.type === "mother" 
        ? `<div class="sub-ticket-status info">一次性核銷所有人</div>`
        : (tkt.status === "checked_in" 
          ? `<div class="sub-ticket-status checked-in">✓ 已上車</div>`
          : `<div class="sub-ticket-status not-checked-in">未上車</div>`);
      
      carouselHTML += `
        <div class="ticket-carousel-item ${isActive}" data-ticket-index="${idx}">
          <div class="sub-ticket-qr-item ${tkt.type === 'mother' ? 'mother-ticket' : ''}">
            <div class="sub-ticket-label">${tkt.label} (${tkt.pax}人)</div>
            <div class="sub-ticket-booking-id">${tkt.booking_id}</div>
            <div class="sub-ticket-qr"><img src="${sanitize(tkt.qr_url)}" alt="${tkt.label}" /></div>
            ${statusBadge}
          </div>
        </div>
      `;
    });
    
    carouselHTML += `
        </div>
        <button class="carousel-btn carousel-next" onclick="switchTicket(1)" aria-label="下一張">›</button>
      </div>
      <div class="ticket-carousel-indicators">
    `;
    
    allTickets.forEach((tkt, idx) => {
      const isActive = idx === 0 ? "active" : "";
      carouselHTML += `<span class="carousel-dot ${isActive}" onclick="switchTicketTo(${idx})"></span>`;
    });
    
    carouselHTML += `</div>`;
    
    qrSection = `
      <div class="ticket-qr multi-ticket">
        ${carouselHTML}
      </div>
    `;
    
    // 保存當前票卷索引（用於查詢頁面的切換）
    window.currentTicketIndex = 0;
    window.totalTickets = allTickets.length;
  } else {
    // 單一車票模式（向後兼容）
    qrSection = `<div class="ticket-qr"><img src="${sanitize(qrUrl)}" alt="QR" /></div>`;
  }

  const cardHTML = `
    <div class="ticket-card${expired ? " expired" : ""}">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;">
        <div style="display:flex;align-items:center;gap:8px;">
          <div class="${statusPillClass}" style="position:relative;left:0;top:0;">${sanitize(statusPillText)}</div>
          ${rejectedTipBtn}
        </div>
        <button class="ticket-close" aria-label="${t("closeLabel")}" style="position:relative;right:0;top:0;">✕</button>
      </div>
      <div class="ticket-header">
        <h2>${sanitize(carDateTime)}</h2>
      </div>
      <div class="ticket-content">
        ${qrSection}
        <div class="ticket-info">
          <div class="ticket-field"><span class="ticket-label">${t("labelBookingId")}</span><span class="ticket-value">${sanitize(hasSubTickets ? bookingId + " (母票)" : bookingId)}</span></div>
          <div class="ticket-field"><span class="ticket-label">${t("labelDirection")}</span><span class="ticket-value">${sanitize(rbLabel)}</span></div>
          <div class="ticket-field"><span class="ticket-label">${t("labelPick")}</span><span class="ticket-value">${sanitize(pick)}</span></div>
          <div class="ticket-field"><span class="ticket-label">${t("labelDrop")}</span><span class="ticket-value">${sanitize(drop)}</span></div>
          <div class="ticket-field"><span class="ticket-label">${t("labelName")}</span><span class="ticket-value">${sanitize(name)}</span></div>
          <div class="ticket-field"><span class="ticket-label">${t("labelPhone")}</span><span class="ticket-value">${sanitize(phone)}</span></div>
          <div class="ticket-field"><span class="ticket-label">${t("labelEmail")}</span><span class="ticket-value">${sanitize(email)}</span></div>
          ${hasSubTickets ? subTickets.map(t => {
            const subBookingId = t.booking_id || `${bookingId}_${String.fromCharCode(64 + t.sub_index)}`;
            return `<div class="ticket-field"><span class="ticket-label">${subBookingId}</span><span class="ticket-value">${t.pax} 人</span></div>`;
          }).join("") : `<div class="ticket-field"><span class="ticket-label">${t("labelPassengersShort")}</span><span class="ticket-value">${sanitize(String(pax))}</span></div>`}
          ${hasSubTickets ? `<div class="ticket-field"><span class="ticket-label">上車狀態</span><span class="ticket-value">${checkedPax}/${totalSubPax} 人已上車</span></div>` : ""}
        </div>
      </div>
      <div class="ticket-actions"></div>
    </div>
  `;

  // 創建臨時容器來解析 HTML
  const temp = document.createElement("div");
  temp.innerHTML = cardHTML.trim();
  const card = temp.firstElementChild;

  // 設置事件處理器
  const closeBtn = card.querySelector(".ticket-close");
  if (closeBtn) {
    closeBtn.onclick = () => closeCheckTicket();
  }

  if (statusCode === "rejected") {
    const tipBtn = card.querySelector(".badge-alert");
    if (tipBtn) {
      tipBtn.onclick = () => showErrorCard(t("rejectedTip"));
    }
  }

  const actions = card.querySelector(".ticket-actions");
  if (actions) {
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

    // ========== 添加分票按鈕（查詢頁面） ==========
    if (pax > 1 && statusCode !== "cancelled" && statusCode !== "rejected") {
      // 檢查是否有未上車的子票（如果有未上車的，可以重新分票）
      const hasUncheckedTickets = hasSubTickets && subTickets.some(t => t.status !== "checked_in");
      const canReSplit = hasSubTickets && hasUncheckedTickets;
      
      const splitBtn = document.createElement("button");
      splitBtn.className = "button btn-ghost split-ticket-btn";
      splitBtn.textContent = canReSplit ? "重新分票" : "分票";
      splitBtn.onclick = () => {
        // 構建 ticket 對象供分票對話框使用
        const ticketData = {
          bookingId: bookingId,
          passengers: pax,
          sub_tickets: subTickets,
          mother_ticket: motherTicket,
          date: dateIso,
          time: time,
          direction: rb,
          pickLocation: pick,
          dropLocation: drop,
          name: name,
          phone: phone,
          email: email
        };
        showSplitTicketDialog(ticketData, canReSplit);
      };
      actions.appendChild(splitBtn);
    }

    if (!expired && statusCode !== "cancelled" && statusCode !== "rejected" && statusCode !== "boarded") {
      const mdBtn = document.createElement("button");
      mdBtn.className = "button btn-ghost";
      mdBtn.textContent = ts("modify");
      mdBtn.onclick = () => openModifyPage({
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
  }

  return card;
}

/* ====== 查詢/刪改 ====== */
async function queryOrders() {
  const qBookIdEl = getElement("qBookId");
  const qPhoneEl = getElement("qPhone");
  const qEmailEl = getElement("qEmail");
  const id = (qBookIdEl ? qBookIdEl.value : "").trim();
  const phone = (qPhoneEl ? qPhoneEl.value : "").trim();
  const email = (qEmailEl ? qEmailEl.value : "").trim();
  const queryHint = getElement("queryHint");
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
    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      throw new Error(t("serverResponseParseFailed"));
    }
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
  const wrap = getElement("dateChoices");
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

  const fragment = document.createDocumentFragment();
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
    fragment.appendChild(btn);
  });
  wrap.appendChild(fragment);
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

  const mount = getElement("checkTicketMount");
  if (!mount) return;
  mount.innerHTML = "";
  const fragment = document.createDocumentFragment();
  currentDateRows.forEach((row) =>
    fragment.appendChild(buildTicketCard(row, { mask: true }))
  );
  mount.appendChild(fragment);
  showCheckTicketStep();
}

function rerenderQueryPages() {
  const dateStep = getElement("checkDateStep");
  const ticketStep = getElement("checkTicketStep");
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
      let j = null;
      try {
        j = await r.json();
      } catch (e) {
        throw new Error(t("serverResponseParseFailed"));
      }
      if (j && j.status === "success") {
        showSuccessAnimation();
        setTimeout(async () => {
          const qBookIdEl = getElement("qBookId");
          const qPhoneEl = getElement("qPhone");
          const qEmailEl = getElement("qEmail");
          const id = (qBookIdEl ? qBookIdEl.value : "").trim();
          const phone = (qPhoneEl ? qPhoneEl.value : "").trim();
          const email = (qEmailEl ? qEmailEl.value : "").trim();
          const queryRes = await fetch(OPS_URL, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              action: "query",
              data: { booking_id: id, phone, email },
              lang: getCurrentLang()
            })
          });
          let queryData = null;
          try {
            queryData = await queryRes.json();
          } catch (e) {
            queryData = [];
          }
          lastQueryResults = Array.isArray(queryData)
            ? queryData
            : (queryData && queryData.results) || [];
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

  const qForm = getElement("queryForm");
  const dateStep = getElement("checkDateStep");
  const ticketStep = getElement("checkTicketStep");
  if (qForm) qForm.style.display = "none";
  if (dateStep) dateStep.style.display = "none";
  if (ticketStep) ticketStep.style.display = "none";

  const holderId = "editHolder";
  let holder = getElement(holderId);
  if (!holder) {
    holder = document.createElement("div");
    holder.id = holderId;
    holder.className = "card wizard-fixed";
    const checkPage = getElement("check");
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
      const backendMsgStr = String(backendMsg || "");
      const isCapacityError =
        r.status === 409 ||
        backendMsgStr.includes("capacity_exceeded") ||
        backendMsgStr.includes("capacity_not_found") ||
        backendMsgStr.includes("capacity_header_missing") ||
        backendMsgStr.includes("capacity_not_numeric");

      // 4️⃣ HTTP 錯誤
      if (!r.ok) {
        if (r.status === 503) {
          showErrorCard(t("busyRetry"));
        } else if (isCapacityError) {
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
      const id = (getElement("qBookId")?.value || "").trim();
      const phoneInput = (getElement("qPhone")?.value || "").trim();
      const emailInput = (getElement("qEmail")?.value || "").trim();

      const queryRes = await fetch(OPS_URL, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "query",
          data: { booking_id: id, phone: phoneInput, email: emailInput }
        })
      });
      let queryData = null;
      try {
        queryData = await queryRes.json();
      } catch (e) {
        queryData = [];
      }
      lastQueryResults = Array.isArray(queryData)
        ? queryData
        : (queryData && queryData.results) || [];
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
    let raw = null;
    try {
      raw = await res.json();
    } catch (e) {
      throw new Error(t("serverResponseParseFailed"));
    }
    if (!raw || !Array.isArray(raw) || raw.length === 0) {
      throw new Error(t("serverResponseFormatError"));
    }
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
  const resultsEl = getElement("scheduleResults");
  if (!resultsEl) return;

  // 檢查快取
  try {
    const cached = localStorage.getItem(SCHEDULE_CACHE_KEY);
    if (cached) {
      const cacheData = JSON.parse(cached);
      const now = Date.now();
      if (cacheData.timestamp && (now - cacheData.timestamp) < SCHEDULE_CACHE_TTL) {
        // 輔助函數：檢查是否為 #N/A 或無效值
        const isNA = (value) => {
          if (!value) return true;
          const str = String(value).trim().toUpperCase();
          return str === '#N/A' || str === 'N/A' || str === '';
        };

        // 使用快取資料，但也要過濾掉 #N/A 值
        scheduleData.rows = (cacheData.rows || []).filter(row => {
          return !isNA(row.direction) && 
                 !isNA(row.date) && 
                 !isNA(row.time) && 
                 !isNA(row.station);
        });
        scheduleData.directions = new Set(
          (cacheData.directions || []).filter(dir => !isNA(dir))
        );
        scheduleData.dates = new Set(
          (cacheData.dates || []).filter(date => !isNA(date))
        );
        scheduleData.stations = new Set(
          (cacheData.stations || []).filter(station => !isNA(station))
        );
        
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
    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      throw new Error(t("serverResponseParseFailed"));
    }
    if (!data || !Array.isArray(data) || data.length === 0) {
      throw new Error(t("serverResponseFormatError"));
    }
    const headers = data[0];
    const rows = data.slice(1);

    const directionIndex = headers.indexOf("去程 / 回程");
    const dateIndex = headers.indexOf("日期");
    const timeIndex = headers.indexOf("班次");
    const stationIndex = headers.indexOf("站點");
    const capacityIndex = headers.indexOf("可預約人數");

    // 輔助函數：檢查是否為 #N/A 或無效值
    const isNA = (value) => {
      if (!value) return true;
      const str = String(value).trim().toUpperCase();
      return str === '#N/A' || str === 'N/A' || str === '';
    };

    scheduleData.rows = rows
      .map((row) => ({
        direction: row[directionIndex] || "",
        date: row[dateIndex] || "",
        time: row[timeIndex] || "",
        station: row[stationIndex] || "",
        capacity: row[capacityIndex] || ""
      }))
      .filter((row) => {
        // 過濾掉任何欄位為 #N/A 或空的資料行
        return !isNA(row.direction) && 
               !isNA(row.date) && 
               !isNA(row.time) && 
               !isNA(row.station);
      });

    // 建立 Set 時也要過濾掉 #N/A 值
    scheduleData.directions = new Set(
      scheduleData.rows
        .map((r) => r.direction)
        .filter(dir => !isNA(dir))
    );
    scheduleData.dates = new Set(
      scheduleData.rows
        .map((r) => r.date)
        .filter(date => !isNA(date))
    );
    scheduleData.stations = new Set(
      scheduleData.rows
        .map((r) => r.station)
        .filter(station => !isNA(station))
    );

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
  const allWrap = getElement("allFilter");
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
  const container = getElement(containerId);
  if (!container) return;
  container.innerHTML = "";

  // 輔助函數：檢查是否為 #N/A 或無效值
  const isNA = (value) => {
    if (!value) return true;
    const str = String(value).trim().toUpperCase();
    return str === '#N/A' || str === 'N/A' || str === '';
  };

  // 過濾掉 #N/A 值
  const validItems = items.filter(item => !isNA(item));

  // ✅ 站點用自訂排序：捷運 > 火車 > LALA
  if (containerId === "stationFilter" || containerId === "bookingStationFilter") {
    validItems.sort((a, b) => {
      const pa = getStationPriority(a);
      const pb = getStationPriority(b);
      if (pa !== pb) return pa - pb;
      // 同一類型時，用字典序當次排序（避免順序亂跳）
      return String(a).localeCompare(String(b), "zh-Hant");
    });
  } else {
    // 其他（方向、日期）維持原本字串排序
    validItems.sort();
  }

  const fragment = document.createDocumentFragment();
  validItems.forEach((item) => {
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
    fragment.appendChild(pill);
  });
  container.appendChild(fragment);
}

function renderScheduleResults() {
  const container = getElement('scheduleResults');
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
  const noScheduleDataText = t("noScheduleData");

  function translateDirection(direction) {
    if (direction === '去程') return texts.dirOutLabel || direction;
    if (direction === '回程') return texts.dirInLabel || direction;
    return direction;
  }

  // 輔助函數：檢查是否為 #N/A 或無效值
  const isNA = (value) => {
    if (!value) return true;
    const str = String(value).trim().toUpperCase();
    return str === '#N/A' || str === 'N/A' || str === '';
  };

  // 輔助函數：處理顯示值，如果是 #N/A 則顯示友好訊息
  const formatValue = (value, defaultValue = noScheduleDataText) => {
    return isNA(value) ? defaultValue : sanitize(value);
  };

  container.innerHTML = filtered.map(row => {
    // 只抓數字，例如「可預約 / Available：7」→ "7"
    const digits = onlyDigits(row.capacity);
    const capNumber = digits || row.capacity; // 如果沒有數字就 fallback 原字串
    
    // 檢查是否為 #N/A 或類似的無效值
    const capIsNA = isNA(capNumber);
    const displayCapacity = capIsNA ? noScheduleDataText : `${sanitize(capLabel)}：${sanitize(capNumber)}`;

    // 處理所有欄位的 #N/A 情況
    // 方向需要先翻譯再處理 #N/A
    const displayDirection = isNA(row.direction) 
      ? noScheduleDataText 
      : sanitize(translateDirection(row.direction));
    const displayDate = formatValue(row.date);
    const displayTime = formatValue(row.time);
    const displayStation = formatValue(row.station);

    return `
      <div class="schedule-card">
        <div class="schedule-line">
          <span class="schedule-direction">${displayDirection}</span>
          <span class="schedule-date">${displayDate}</span>
          <span class="schedule-time">${displayTime}</span>
        </div>
        <div class="schedule-line">
          <span class="schedule-station">${displayStation}</span>
          <span class="schedule-capacity">${sanitize(displayCapacity)}</span>
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
    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      console.error("無法解析系統設定回應:", e);
      return;
    }

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

    // 只有在有內容時才顯示跑馬燈
    if (marqueeData.text && marqueeData.text.trim()) {
      showMarquee();
    }

    // ========= 圖片牆處理 =========
    const gallery = getElement("imageGallery");
    if (gallery) {
      gallery.innerHTML = "";
      let hasImages = false;
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
          hasImages = true;
        }
      }
      // 如果沒有圖片，隱藏圖片展示區
      if (!hasImages) {
        gallery.style.display = "none";
      } else {
        gallery.style.display = "";
      }
    }
  } catch (err) {
    console.error("載入系統設定時發生錯誤:", err);
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
  const id = getElement("qBookId");
  const phone = getElement("qPhone");
  const email = getElement("qEmail");
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
  const sec = querySelector('[data-feature="liveLocation"]');
  if (!sec) return;

  const mount = getElement("realtimeMount");
  if (!mount) return;

  // 檢查 GPS 系統總開關（從 booking-api 讀取，該 API 會從 Sheet 的「系統」E19 讀取）
  try {
    const apiUrl = `${BASE_API_URL}/api/realtime/location`;
    const r = await fetch(apiUrl);
    if (r.ok) {
      let data = null;
      try {
        data = await r.json();
      } catch (e) {
        console.error("無法解析即時位置回應:", e);
        return;
      }
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

// 站點名稱映射表（各語系）
const stationNames = {
  "福泰大飯店 Forte Hotel": {
    zh: "福泰大飯店",
    en: "Forte Hotel",
    ja: "フォルテホテル",
    ko: "포르테 호텔"
  },
  "南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3": {
    zh: "南港展覽館捷運站",
    en: "Nangang Exhibition Center - MRT Exit 3",
    ja: "南港展示館MRT3番出口",
    ko: "난강 전람관 MRT 3번 출구"
  },
  "南港火車站 Nangang Train Station": {
    zh: "南港火車站",
    en: "Nangang Train Station",
    ja: "南港駅",
    ko: "난강역"
  },
  "LaLaport Shopping Park": {
    zh: "LaLaport Shopping Park",
    en: "LaLaport Shopping Park",
    ja: "LaLaportショッピングパーク",
    ko: "라라포트 쇼핑파크"
  },
  "福泰大飯店(回) Forte Hotel (Back)": {
    zh: "福泰大飯店",
    en: "Forte Hotel",
    ja: "フォルテホテル",
    ko: "포르테 호텔"
  }
};

// 格式化站點名稱（根據語系顯示）
function formatStationName(stationName) {
  if (!stationName) return "";
  
  const lang = getCurrentLang();
  
  // 先嘗試直接匹配
  let station = stationNames[stationName];
  
  // 如果找不到，嘗試匹配變體
  if (!station) {
    // 處理 "1. 福泰大飯店 (去)" 格式
    if (stationName.includes("福泰大飯店") && (stationName.includes("(去)") || stationName.includes("去"))) {
      station = stationNames["福泰大飯店 Forte Hotel"];
    }
    // 處理 "福泰大飯店(回) Forte Hotel (Back)" 格式
    else if (stationName.includes("福泰大飯店") && (stationName.includes("(回)") || stationName.includes("回") || stationName.includes("Back"))) {
      station = stationNames["福泰大飯店(回) Forte Hotel (Back)"];
    }
    // 處理 "南港展覽館捷運站" 或包含 "南港" 和 "捷運" 的格式
    else if (stationName.includes("南港") && (stationName.includes("捷運") || stationName.includes("MRT") || stationName.includes("展覽館"))) {
      station = stationNames["南港展覽館捷運站 Nangang Exhibition Center - MRT Exit 3"];
    }
    // 處理 "南港火車站" 或包含 "南港" 和 "火車" 的格式
    else if (stationName.includes("南港") && (stationName.includes("火車") || stationName.includes("Train"))) {
      station = stationNames["南港火車站 Nangang Train Station"];
    }
    // 處理 LaLaport 相關
    else if (stationName.toLowerCase().includes("lalaport")) {
      station = stationNames["LaLaport Shopping Park"];
    }
  }
  
  if (station) {
    const zhName = station.zh;
    const enName = station.en;
    const currentName = station[lang] || station.en;
    
    // 中文和英文：顯示 "中文 / 英文"
    if (lang === "zh" || lang === "en") {
      return `${zhName} / ${enName}`;
    }
    
    // 其他語系：顯示 "選擇的語系 / 英文"
    return `${currentName} / ${enName}`;
  }
  
  // 如果找不到映射，嘗試從原始名稱中提取
  // 檢查是否包含 " / " 分隔符
  if (stationName.includes(" / ")) {
    const parts = stationName.split(" / ");
    const zhName = parts[0].trim();
    const enName = parts[1].trim();
    
    if (lang === "zh" || lang === "en") {
      return `${zhName} / ${enName}`;
    } else {
      // 其他語系：使用英文
      return `${enName}`;
    }
  }
  
  // 如果沒有分隔符，直接返回原始名稱
  return stationName;
}

function initLiveLocation(mount) {
  const cfg = getLiveConfig();
  // 即時位置區塊：資訊顯示在上方，不覆蓋地圖
  mount.innerHTML = `
    <!-- 資訊區塊：顯示在上方 -->
    <div id="rt-info-panel" style="margin-bottom:12px;padding:16px;background:#ffffff;border-radius:12px;box-shadow:0 2px 8px rgba(0,0,0,0.1);display:none;">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:16px;flex-wrap:wrap;">
        <div id="rt-status-light" style="width:12px;height:12px;border-radius:50%;background:#28a745;box-shadow:0 0 8px rgba(40,167,69,0.6);"></div>
        <span id="rt-status-text" style="font-size:15px;color:#333;font-weight:500;">${t("rtStatusGood")}</span>
        <button id="rt-refresh" style="margin-left:auto;padding:8px 16px;background:#fff;border:1px solid #ddd;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;box-shadow:0 2px 4px rgba(0,0,0,0.1);">${t("rtRefresh")}</button>
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
        <button id="rt-start-btn" class="button" style="padding:16px 32px;font-size:18px;font-weight:700;background:var(--primary);color:#fff;border:none;border-radius:12px;cursor:pointer;">${t("rtViewLocation")}</button>
      </div>
      <!-- 班次結束提示 -->
      <div id="rt-ended-overlay" style="position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);display:none;align-items:center;justify-content:center;z-index:15;pointer-events:none;">
        <div style="text-align:center;color:#fff;font-size:20px;font-weight:700;">
          <div id="rt-ended-text"><span id="rt-ended-datetime-label"></span><span id="rt-ended-datetime"></span></div>
        </div>
      </div>
      <!-- 無可顯示班次遮罩 -->
      <div id="rt-no-trip-overlay" style="position:absolute;top:0;left:0;right:0;bottom:0;background:rgba(0,0,0,0.7);display:none;align-items:center;justify-content:center;z-index:15;pointer-events:none;">
        <div style="text-align:center;color:#fff;font-size:20px;font-weight:700;">
          <div id="rt-no-trip-text">${t("rtNoTripAvailable")}</div>
        </div>
      </div>
    </div>
  `;
  const overlayEl = mount.querySelector("#rt-overlay");
  const startBtn = mount.querySelector("#rt-start-btn");
  const infoPanel = mount.querySelector("#rt-info-panel");
  const stationsList = mount.querySelector("#rt-stations-list");
  const noTripOverlay = mount.querySelector("#rt-no-trip-overlay");
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
        btnRefresh.textContent = countdown > 0 ? `${t("rtRefresh")} (${countdown}秒)` : t("rtRefresh");
      } else {
        btnRefresh.disabled = true;
        btnRefresh.style.opacity = "0.5";
        btnRefresh.style.cursor = "not-allowed";
        btnRefresh.style.background = "#f0f0f0";
        btnRefresh.textContent = countdown > 0 ? `${t("rtRefresh")} (${countdown}秒)` : t("rtRefresh");
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
  
  // 優化：更新已走過的路線（基於路線進度索引）
  let lastProgressIndex = -1;
  let lastRenderedProgressIndex = -1;
  let lastHistoryLength = 0;

  function getNearestPathIndex(path, lat, lng) {
    if (!path || !path.length || typeof lat !== "number" || typeof lng !== "number") {
      return null;
    }
    let nearestIdx = 0;
    let best = Infinity;
    for (let i = 0; i < path.length; i++) {
      const pt = path[i];
      const dx = pt.lat() - lat;
      const dy = pt.lng() - lng;
      const dist = dx * dx + dy * dy;
      if (dist < best) {
        best = dist;
        nearestIdx = i;
      }
    }
    return nearestIdx;
  }

  function getProgressIndex(data, driverPos, path) {
    let progressIdx = -1;
    const history = data.current_trip_path_history;
    if (history && Array.isArray(history) && history.length > 0) {
      lastHistoryLength = history.length;
      const step = history.length > 200 ? 5 : 1;
      for (let i = 0; i < history.length; i += step) {
        const p = history[i];
        const idx = getNearestPathIndex(path, p.lat, p.lng);
        if (idx !== null && idx > progressIdx) {
          progressIdx = idx;
        }
      }
    } else if (driverPos) {
      const idx = getNearestPathIndex(path, driverPos.lat, driverPos.lng);
      if (idx !== null) {
        progressIdx = idx;
      }
    }
    if (progressIdx < 0) {
      return null;
    }
    if (progressIdx < lastProgressIndex) {
      progressIdx = lastProgressIndex;
    } else {
      lastProgressIndex = progressIdx;
    }
    return progressIdx;
  }

  // 更新站點列表
  const updateStationsList = (data, driverPos) => {
    if (!stationsList || !data.current_trip_route || !data.current_trip_route.stops) {
      return;
    }
    
    const stops = data.current_trip_route.stops || [];
    const completedStops = data.current_trip_completed_stops || [];
    const tripDateTime = data.current_trip_datetime || "";
    const driverLocation = driverPos || (data.driver_location && typeof data.driver_location.lat === "number" ? { lat: data.driver_location.lat, lng: data.driver_location.lng } : null);
    const routePath = mainPolyline ? mainPolyline.getPath().getArray() : [];
    const progressIdx = routePath.length > 0 ? getProgressIndex(data, driverLocation, routePath) : null;
    
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
      
      // 判斷站點是否已經過了（使用路線進度索引，避免折返誤判）
      let isPassed = false;
      if (stopCoord && routePath.length > 0 && progressIdx !== null) {
        const stationIdx = getNearestPathIndex(routePath, stopCoord.lat, stopCoord.lng);
        if (stationIdx !== null && progressIdx > stationIdx) {
          isPassed = true;
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
      
      // 檢查是否已經發車（當前時間是否超過發車時間）
      const now = new Date();
      const hasDeparted = mainTripTime ? now >= mainTripTime : false;
      
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
      } else if (hasDeparted && driverLocation && stopCoord) {
        // 只有發車後才計算ETA
        const eta = calculateETA(driverLocation.lat, driverLocation.lng, stopCoord.lat, stopCoord.lng);
        if (eta) {
          etaTime = new Date(now.getTime() + eta.minutes * 60 * 1000);
          const hours = String(etaTime.getHours()).padStart(2, '0');
          const minutes = String(etaTime.getMinutes()).padStart(2, '0');
          timeLabel = "預計抵達";
          timeText = `${hours}:${minutes}`;
        } else {
          timeLabel = "預計抵達";
        }
      } else if (!hasDeparted) {
        // 還沒發車，留空白
        timeLabel = "";
        timeText = "";
      } else {
        // 其他情況（沒有司機位置或站點座標）
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
      
      const formattedStopName = formatStationName(stopName);
      
      // 只有當 timeLabel 和 timeText 都有值時才顯示時間信息
      const timeInfoHTML = (timeLabel && timeText) ? `<div style="font-size:13px;color:#666;">${timeLabel}: ${timeText}</div>` : '';
      
      stationsHTML += `
        <div style="${stationStyle}">
          <div style="flex: 1;">
            <div style="font-size:15px;color:#333;font-weight:bold;margin-bottom:4px;">${formattedStopName}</div>
            ${timeInfoHTML}
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
  
  const updateWalkedRoute = async (data, driverPos = null) => {
    // 檢查 Google Maps API 是否已載入
    if (!window.google || !window.google.maps || !mainPolyline || !data.current_trip_route) {
      return;
    }
    
    const path = mainPolyline.getPath().getArray();
    const progressIdx = getProgressIndex(data, driverPos, path);
    if (progressIdx === null) {
      return;
    }
    if (progressIdx === lastRenderedProgressIndex) {
      return;
    }
    lastRenderedProgressIndex = progressIdx;
    
    const walkedPath = path.slice(0, Math.max(1, progressIdx + 1));
    if (!walkedPolyline) {
      walkedPolyline = new google.maps.Polyline({ 
        path: walkedPath, 
        strokeColor: "#808080", // 灰色（走過的路線）
        strokeOpacity: 0.8, 
        strokeWeight: 6, 
        map,
        zIndex: 2
      });
    } else {
      walkedPolyline.setPath(walkedPath);
    }
  };
  const endedOverlay = mount.querySelector("#rt-ended-overlay");
  const endedTextEl = mount.querySelector("#rt-ended-text");
  const endedDatetimeLabelEl = mount.querySelector("#rt-ended-datetime-label");
  const endedDatetimeEl = mount.querySelector("#rt-ended-datetime");
  const mapEl = mount.querySelector("#rt-map");
  const mapWrapper = mount.querySelector("#rt-map-wrapper");

  const loadMaps = () =>
    new Promise((resolve, reject) => {
      if (!cfg.key) { 
        if (startBtn) startBtn.textContent = t("missingMapKey");
        reject(new Error(t("missingMapKey")));
        return; 
      }
      // 檢查 Google Maps API 是否已經載入
      if (window.google && window.google.maps) {
        resolve();
        return;
      }
      // 檢查是否已經有載入中的 script 標籤
      const existingScript = querySelector('script[src*="maps.googleapis.com/maps/api/js"]');
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
  let hasCenteredOnce = false;
  let lastAutoPanAt = 0;
  const AUTO_PAN_COOLDOWN_MS = 5000;
  
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
      // 檢查 Google Maps API 是否已載入
      if (!window.google || !window.google.maps || !mapInstance) {
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
      // 重置路線進度快取，避免跨班次或路線更新造成誤判
      lastProgressIndex = -1;
      lastRenderedProgressIndex = -1;
      lastHistoryLength = 0;
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
            // 靜默處理 fitBounds 錯誤（可能是 bounds 無效）
            // 不影響主要功能，無需記錄到控制台
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
      updateStatus("#dc3545", t("rtStatusUpdateFailed"));
    }
  };
  
  // 處理位置資料的共用函數（從 fetchLocation 和 updateLocationFromFirebase 調用）
  // Geocoder（在 initMap 中初始化，保留以備將來需要）
  let geocoder = null;

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
      
      // 如果班次時間超過1小時，顯示"目前無可顯示班次"遮罩
      if (shouldShowNoTrip) {
        // 隱藏上方資訊區塊
        if (infoPanel) {
          infoPanel.style.display = "none";
        }
        // 顯示"目前無可顯示班次"遮罩
        if (noTripOverlay) {
          noTripOverlay.style.display = "flex";
        }
        // 隱藏其他遮罩
        if (endedOverlay) endedOverlay.style.display = "none";
        if (overlayEl) overlayEl.style.display = "none";
        return;
      }

      // 若已結束班次且距離最後班次超過 24 小時，則不顯示歷史
      let lastTripTooOld = false;
      if (data.last_trip_datetime) {
        try {
          const parts = data.last_trip_datetime.split(' ');
          if (parts.length >= 2) {
            const datePart = parts[0].replace(/\//g, '-');
            const timePart = parts[1];
            const lastTripTime = new Date(`${datePart}T${timePart}:00`);
            const now = Date.now();
            const TWENTY_FOUR_HOURS_MS = 24 * 60 * 60 * 1000;
            if (lastTripTime.getTime() < (now - TWENTY_FOUR_HOURS_MS)) {
              lastTripTooOld = true;
            }
          }
        } catch (e) {
        }
      }

      if (lastTripTooOld) {
        if (infoPanel) infoPanel.style.display = "none";
        if (noTripOverlay) noTripOverlay.style.display = "flex";
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
          const datetime = data.last_trip_datetime || data.current_trip_datetime || "";
          if (endedDatetimeLabelEl) {
            endedDatetimeLabelEl.textContent = t("rtTripEnded").replace("{datetime}", datetime);
          }
          if (endedDatetimeEl) {
            endedDatetimeEl.textContent = "";
          }
        }
        if (infoPanel) infoPanel.style.display = "none";
        if (noTripOverlay) noTripOverlay.style.display = "none";
        return;
      } else {
        if (endedOverlay) endedOverlay.style.display = "none";
        if (noTripOverlay) noTripOverlay.style.display = "none";
        if (infoPanel) infoPanel.style.display = "block";
      }
      
      // 更新司機位置（只有在 Google Maps API 已載入且地圖已初始化時才執行）
      const driverLoc = data.driver_location;
      let driverPos = null;
      if (driverLoc && typeof driverLoc.lat === "number" && typeof driverLoc.lng === "number") {
        driverPos = { lat: driverLoc.lat, lng: driverLoc.lng };
        // 只有在 Google Maps API 已載入且地圖已初始化時才更新地圖
        if (window.google && window.google.maps && map && marker) {
          marker.setPosition(driverPos);
          const now = Date.now();
          const bounds = map.getBounds && map.getBounds();
          const shouldPan =
            !hasCenteredOnce ||
            (bounds && typeof bounds.contains === "function" && !bounds.contains(driverPos));
          if (shouldPan && now - lastAutoPanAt > AUTO_PAN_COOLDOWN_MS) {
            map.panTo(driverPos);
            lastAutoPanAt = now;
            hasCenteredOnce = true;
          }
        }
        // 更新圓形外圈位置
        if (window.google && window.google.maps && markerCircle) {
          markerCircle.setCenter(driverPos);
        }
        
        // 更新已走過的路線（updateWalkedRoute 內部會檢查 Google Maps API）
        await updateWalkedRoute(data, driverPos);
        
        updateStatus("#28a745", t("rtStatusGood"));
      } else {
        updateStatus("#ffc107", t("rtStatusConnecting"));
      }
      
      // 更新站點列表
      updateStationsList(data, driverPos);
      
      currentTripData = data;
  };
  
  const fetchLocation = async () => {
    try {
      // 從 booking-api 讀取即時位置資料（作為備用方案）
      const apiUrl = `${BASE_API_URL}/api/realtime/location`;
      const r = await fetch(apiUrl);
      if (!r.ok) {
        updateStatus("#dc3545", t("rtStatusFailed"));
        return;
      }
      let data = null;
      try {
        data = await r.json();
      } catch (e) {
        updateStatus("#dc3545", t("rtStatusParseError"));
        return;
      }
      await processLocationData(data);
    } catch (e) {
      updateStatus("#dc3545", t("rtStatusError"));
    }
  };

  // 初始化地圖（點擊"查看即時位置"按鈕後）
  let initMap = async () => {
    if (isInitialized) return;
    isInitialized = true;
    
    await loadMaps();
    
    // 確保 Google Maps API 已完全載入和初始化
    if (!window.google || !window.google.maps) {
      throw new Error(t("mapsLoadFailed"));
    }
    
    // 等待 Google Maps API 完全初始化（額外檢查）
    let retries = 0;
    while ((!window.google.maps.LatLngBounds || !window.google.maps.Map) && retries < 50) {
      await new Promise(resolve => setTimeout(resolve, 100));
      retries++;
    }
    
    if (!window.google.maps.LatLngBounds || !window.google.maps.Map) {
      throw new Error(t("mapsInitTimeout"));
    }
    
    // 灰色地圖樣式 - 地圖灰色，隱藏地標，但保留路名
    const mapStyles = [
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
        featureType: "water",
        elementType: "geometry",
        stylers: [{ color: "#c0c0c0" }]
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
    
    // 計算地圖顯示範圍限制（方圓4公里）
    const centerLat = 25.054933909333368;
    const centerLng = 121.61876667836735;
    const radiusKm = 4; // 4公里
    
    // 計算邊界（近似值：1度緯度約111公里，經度根據緯度調整）
    const latDelta = radiusKm / 111; // 緯度變化（約0.045度）
    const lngDelta = radiusKm / (111 * Math.cos(centerLat * Math.PI / 180)); // 經度變化（考慮緯度）
    
    // 確保 Google Maps API 已完全載入
    if (!window.google || !window.google.maps || !window.google.maps.LatLngBounds) {
      throw new Error(t("mapsNotReady"));
    }
    
    const restrictionBounds = new google.maps.LatLngBounds(
      { lat: centerLat - latDelta, lng: centerLng - lngDelta }, // 西南角
      { lat: centerLat + latDelta, lng: centerLng + lngDelta }   // 東北角
    );
    
    // 初始化地圖（使用 styles 設置灰色地圖，不使用 mapId）
    // 保留縮放控制功能
    map = new google.maps.Map(mapEl, { 
      center: { lat: 25.055550556928008, lng: 121.63210245291367 }, 
      zoom: 14, 
      disableDefaultUI: false, // 啟用預設 UI（保留縮放控制）
      zoomControl: true, // 啟用縮放控制（右下角）
      zoomControlOptions: {
        position: google.maps.ControlPosition.RIGHT_BOTTOM
      },
      mapTypeControl: false, 
      streetViewControl: false,
      fullscreenControl: false,
      styles: mapStyles,
      restriction: {
        latLngBounds: restrictionBounds,
        strictBounds: true // 嚴格限制，不允許拖動到邊界外
      }
    });
    
    // 初始化 Geocoder 實例（保留以備將來需要）
    geocoder = new google.maps.Geocoder();
    
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
    // 清理之前的動畫（如果存在）
    if (breathingAnimation) {
      clearInterval(breathingAnimation);
      breathingAnimation = null;
    }
    let breathingRadius = 30;
    let breathingDirection = 1;
    let breathingOpacity = 0.2;
    let breathingOpacityDirection = 1;
    breathingAnimation = setInterval(() => {
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
          updateStatus("#dc3545", t("rtStatusFailed"));
          updateRefreshButtonVisibility();
          startFallbackPolling();
        });
        
        firebaseListeners.push(ref);
      });
      
      firebaseConnected = true;
      // Firebase 連接成功時，調整輪詢間隔（使用更長間隔）
      // 保留輪詢作為備用機制，但使用更長間隔以減少資源消耗
      startFallbackPolling();
      updateStatus("#28a745", t("rtStatusGood"));
      
      // 更新刷新按鈕顯示狀態
      updateRefreshButtonVisibility();
    } catch (e) {
      firebaseConnected = false;
      updateRefreshButtonVisibility();
      startFallbackPolling();
    }
  };
  
  // 優化：根據 Firebase 連接狀態動態調整輪詢間隔
  // Firebase 連接正常時使用較長間隔（5分鐘），斷線時使用較短間隔（1分鐘）
  const getPollingInterval = () => {
    if (firebaseConnected) {
      return 5 * 60 * 1000; // Firebase 連接正常：5分鐘
    } else {
      return 1 * 60 * 1000; // Firebase 斷線：1分鐘（更頻繁檢查）
    }
  };
  
  const startFallbackPolling = () => {
    // 如果已經有定時器在運行，先清除
    if (fallbackTimer) {
      clearTimeout(fallbackTimer);
      fallbackTimer = null;
    }
    
    const poll = async () => {
      if (isInitialized && !firebaseConnected) {
        await fetchLocation();
        if (currentTripData) {
          await drawRoute(currentTripData);
        }
      }
      // 動態調整下一次輪詢間隔
      const interval = getPollingInterval();
      fallbackTimer = setTimeout(() => {
        poll();
      }, interval);
    };
    
    // 立即執行一次，然後根據狀態設置間隔
    poll();
  };
  
  const stopFallbackPolling = () => {
    if (fallbackTimer) {
      clearTimeout(fallbackTimer);
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
      updateStatus("#28a745", t("rtDataUpdated"));
      setTimeout(() => {
        updateStatus("#28a745", t("rtStatusGood"));
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
        btnRefresh.title = t("rtDataUpdated") + "，無需手動刷新";
        btnRefresh.style.opacity = "0.6";
      } else {
        btnRefresh.title = t("rtRefresh");
        btnRefresh.style.opacity = "1";
      }
    }
  };
  
  // 語言切換時更新即時位置文字
  window.updateLiveLocationI18N = function() {
    if (statusText) {
      const currentColor = statusLight ? statusLight.style.background : "#28a745";
      if (currentColor === "#28a745") {
        statusText.textContent = t("rtStatusGood");
      } else if (currentColor === "#ffc107") {
        statusText.textContent = t("rtStatusConnecting");
      }
    }
    if (btnRefresh) {
      const countdown = btnRefresh.textContent.match(/\((\d+)秒\)/);
      if (countdown) {
        btnRefresh.textContent = `${t("rtRefresh")} (${countdown[1]}秒)`;
      } else {
        btnRefresh.textContent = t("rtRefresh");
      }
      if (firebaseConnected) {
        btnRefresh.title = t("rtDataUpdated") + "，無需手動刷新";
      } else {
        btnRefresh.title = t("rtRefresh");
      }
    }
    const startBtn = mount.querySelector("#rt-start-btn");
    if (startBtn) {
      startBtn.textContent = t("rtViewLocation");
    }
    const noTripText = mount.querySelector("#rt-no-trip-text");
    if (noTripText) {
      noTripText.textContent = t("rtNoTripAvailable");
    }
    if (endedDatetimeLabelEl && endedDatetimeEl.textContent) {
      const datetime = endedDatetimeEl.textContent;
      endedDatetimeLabelEl.textContent = t("rtTripEnded").replace("{datetime}", datetime);
    }
    // 更新站點列表（如果存在）
    if (currentTripData && stationsList) {
      const driverPos = currentTripData.driver_location && typeof currentTripData.driver_location.lat === "number" 
        ? { lat: currentTripData.driver_location.lat, lng: currentTripData.driver_location.lng } 
        : null;
      updateStationsList(currentTripData, driverPos);
    }
  };
  
  if (btnRefresh) {
    btnRefresh.addEventListener("click", handleManualRefresh);
  }
}

async function init() {
  // 0. 先從 URL 參數初始化語言（如果有的話）
  if (typeof initLanguageFromURL === "function") {
    initLanguageFromURL();
  }

  const tday = todayISO();
  const ci = getElement('checkInDate');
  const co = getElement('checkOutDate');
  const dining = getElement('diningDate');

  if (ci) ci.value = tday;
  if (co) co.value = tday;
  if (dining) dining.value = tday;

  hardResetOverlays();

  // 1. 先套語系，避免一開始有文字還是舊語言
  applyI18N();

  // 2. 立即隱藏初始載入遮罩，讓網頁先顯示出來
  hideInitialLoading();

  // 3. 顯示預約分頁
  showPage('reservation');

  // 4. 其他 UI 初始化
  handleScroll();

  // 5. 在背景載入系統設定（跑馬燈、圖片展示），不阻塞頁面顯示
  loadSystemConfig().catch(e => {
    console.error("載入系統設定失敗:", e);
  });

  // 6. 在背景載入即時位置，不阻塞頁面顯示
  try {
    await renderLiveLocationPlaceholder();
  } catch (e) {
    console.error("載入即時位置失敗:", e);
  }
}

// 隱藏初始載入遮罩的輔助函數
function hideInitialLoading() {
  const initialLoading = getElement("initialLoading");
  if (initialLoading) {
    initialLoading.classList.remove("show");
  }
}


document.addEventListener("DOMContentLoaded", () => {
  // 初始化 DOM 元素緩存（優化：避免重複查詢）
  domCache.init();
  // 使用 DocumentFragment 進行批量操作（優化）
  requestAnimationFrame(() => {
    document.querySelectorAll(".actions").forEach((a) => {
      const btns = a.querySelectorAll("button");
      if (btns.length === 3) a.classList.add("has-three");
    });
    document.querySelectorAll(".ticket-actions").forEach((a) => {
      const btns = a.querySelectorAll("button");
      if (btns.length === 3) a.classList.add("has-three");
    });
  });
  ["stopHotel", "stopMRT", "stopTrain", "stopLala"].forEach((id) => {
    const el = getElement(id);
    if (el) el.classList.remove("open");
  });

  // 使用 try-catch 確保 init() 的錯誤不會阻塞整個頁面
  init().catch(e => {
    // 即使初始化失敗，也要確保按鈕可以點擊並隱藏載入遮罩
    try {
      showPage('reservation');
    } catch (e2) {
    }
    // 確保載入遮罩被隱藏
    hideInitialLoading();
  });
});

// 監聽滾動事件，確保手機版也能正常運作
// 使用 capture 模式確保能捕獲到所有滾動事件
window.addEventListener("scroll", handleScroll, { passive: true, capture: true });
window.addEventListener("resize", handleScroll, { passive: true });
// 手機版觸摸滾動事件（使用 throttle 避免過度觸發）
let scrollTimeout = null;
function throttledHandleScroll() {
  if (scrollTimeout) return;
  scrollTimeout = setTimeout(() => {
    handleScroll();
    scrollTimeout = null;
  }, 50);
}
window.addEventListener("touchmove", throttledHandleScroll, { passive: true, capture: true });
window.addEventListener("touchend", handleScroll, { passive: true, capture: true });
// 監聽 document 和 body 的滾動事件（某些手機瀏覽器可能使用這些）
document.addEventListener("scroll", handleScroll, { passive: true, capture: true });
if (document.documentElement) {
  document.documentElement.addEventListener("scroll", handleScroll, { passive: true, capture: true });
}
if (document.body) {
  document.body.addEventListener("scroll", handleScroll, { passive: true, capture: true });
}

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
