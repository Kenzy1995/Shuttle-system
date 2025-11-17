/* ====== 常數（API） ====== */
const API_URL = "https://booking-api-995728097341.asia-east1.run.app/api/sheet";
const OPS_URL = "https://booking-manager-995728097341.asia-east1.run.app/api/ops";
const QR_ORIGIN = "https://booking-manager-995728097341.asia-east1.run.app";

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

// 全域：顯示跑馬燈及重新啟動動畫
function showMarquee() {
  const marqueeContainer = document.getElementById("marqueeContainer");
  const marqueeContent = document.getElementById("marqueeContent");
  if (!marqueeContainer || !marqueeContent) return;

  if (!marqueeData.text) {
    // 沒有文案就隱藏
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

  // Reset animation: 先停用再重新啟動
  marqueeContent.style.animation = "none";
  // 強迫 reflow
  void marqueeContent.offsetHeight;
  marqueeContent.style.animation = null;
}


// 查詢分頁狀態
let queryDateList = [];
let currentQueryDate = "";
let currentDateRows = [];

/* ====== 小工具 ====== */
function handleScroll(){
  const y = window.scrollY || document.documentElement.scrollTop || document.body.scrollTop || 0;
  const btn = document.getElementById('backToTop');
  if (!btn) return;
  btn.style.display = y > 300 ? 'block' : 'none';
}
function showPage(id){
  hardResetOverlays();
  document.querySelectorAll(".page").forEach(p=>p.classList.remove("active"));
  document.getElementById(id).classList.add("active");
  document.querySelectorAll(".page").forEach(p=>p.classList.remove("active"));
  document.getElementById(id).classList.add("active");
  document.querySelectorAll(".nav-links button").forEach(b=>b.classList.remove("active"));
  const navId = id==='reservation'?'nav-reservation':id==='check'?'nav-check':id==='schedule'?'nav-schedule':id==='station'?'nav-station':'nav-contact';
  const navEl = document.getElementById(navId); if(navEl) navEl.classList.add("active");
  document.querySelectorAll(".mobile-tabbar button").forEach(b=>b.classList.remove("active"));
  const mId = id==='reservation'?'m-reservation':id==='check'?'m-check':id==='schedule'?'m-schedule':id==='station'?'m-station':'m-contact';
  const mEl = document.getElementById(mId); if(mEl) mEl.classList.add("active");
  window.scrollTo({top:0,behavior:'smooth'});
  if(id==='reservation'){
    document.getElementById('homeHero').style.display='';
    ['step1','step2','step3','step4','step5','step6','successCard'].forEach(s=>{ const el=document.getElementById(s); if(el) el.style.display='none'; });
  }
  if(id==='schedule'){
    loadScheduleData();
  }
  if(id==='station'){
    renderLiveLocationPlaceholder(); // ← 停靠站點頁顯示保留區塊
  }

  if (marqueeData.isLoaded && typeof showMarquee === 'function') {
    try {
      showMarquee();
    } catch (e) {
      console.warn('showMarquee 發生錯誤，已略過：', e);
    }
  }

  handleScroll();
}

function showLoading(s=true){document.getElementById('loading').classList.toggle('show',s)}
function showVerifyLoading(s=true){document.getElementById('loadingConfirm').classList.toggle('show',s)}
function showExpiredOverlay(s=true){document.getElementById('expiredOverlay').classList.toggle('show',s)}
function overlayRestart(){ showExpiredOverlay(false); restart(); }
function shake(el){ if(!el) return; el.classList.add('shake'); setTimeout(()=>el.classList.remove('shake'),500); }
// 關閉跑馬燈：只在本次載入隱藏，不寫入任何 storage
function closeMarquee() {
  const marqueeContainer = document.getElementById('marqueeContainer');
  if (marqueeContainer) {
    marqueeContainer.style.display = 'none';
  }
}

function toggleCollapse(id){
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle('open');
  const icon = el.querySelector('.toggle-icon');
  if (icon) icon.textContent = el.classList.contains('open') ? '▾' : '▸';
}
function hardResetOverlays(){
  ['loading','loadingConfirm','expiredOverlay','dialogOverlay','successAnimation'].forEach(id=>{
    const el = document.getElementById(id);
    if(!el) return;
    if(id==='successAnimation'){ el.classList.remove('show'); el.style.display='none'; }
    else{ el.classList.remove('show'); }
  });
}

/* ====== 對話框（卡片） ====== */
function showErrorCard(message){
  const overlay = document.getElementById('dialogOverlay');
  const title = document.getElementById('dialogTitle');
  const content = document.getElementById('dialogContent');
  const cancelBtn = document.getElementById('dialogCancelBtn');
  const confirmBtn = document.getElementById('dialogConfirmBtn');
  title.textContent = t('errorTitle');
  content.innerHTML = `<p>${sanitize(message || t('errorGeneric'))}</p>`;
  cancelBtn.style.display = 'none';
  confirmBtn.disabled = false;
  confirmBtn.textContent = t('ok');
  confirmBtn.onclick = () => overlay.classList.remove('show');
  overlay.classList.add('show');
}
function showConfirmDelete(bookingId, onConfirm){
  const overlay = document.getElementById('dialogOverlay');
  const title = document.getElementById('dialogTitle');
  const content = document.getElementById('dialogContent');
  const cancelBtn = document.getElementById('dialogCancelBtn');
  const confirmBtn = document.getElementById('dialogConfirmBtn');

  title.textContent = t('confirmDeleteTitle');
  content.innerHTML = `<p>${t('confirmDeleteText')}</p><p style="color:#b00020;font-weight:700">${sanitize(bookingId)}</p>`;

  cancelBtn.style.display = '';
  cancelBtn.textContent = t('cancel');
  cancelBtn.onclick = () => overlay.classList.remove('show');

  let seconds = 5;
  confirmBtn.disabled = true;
  confirmBtn.textContent = `${t('confirm')} (${seconds})`;
  const timer = setInterval(()=>{
    seconds -= 1;
    confirmBtn.textContent = `${t('confirm')} (${seconds})`;
    if(seconds<=0){
      clearInterval(timer);
      confirmBtn.disabled = false;
      confirmBtn.textContent = t('confirm');
    }
  },1000);

  confirmBtn.onclick = () => {
    overlay.classList.remove('show');
    onConfirm && onConfirm();
  };
  overlay.classList.add('show');
}
function sanitize(s){ return String(s||'').replace(/[<>&]/g, c => ({'<':'&lt;','>':'&gt;','&':'&amp;'}[c])); }

/* ====== 時間/格式化 ====== */
function fmtDateLabel(v){
  if(!v) return "";
  const s = String(v).trim();
  if(/^\d{4}-\d{2}-\d{2}T/.test(s)) return s.slice(0,10);
  if(/^\d{4}\/\d{1,2}\/\d{1,2}$/.test(s)){ const [y,m,d]=s.split('/'); return `${y}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`; }
  if(/^\d{1,2}\/\d{1,2}\/\d{4}$/.test(s)){ const [m,d,y]=s.split('/'); return `${y}-${String(m).padStart(2,'0')}-${String(d).padStart(2,'0')}`; }
  if(/^\d{4}-\d{2}-\d{2}$/.test(s)) return s;
  return s;
}
function fmtTimeLabel(v){
  if(v==null) return "";
  const s = String(v).trim().replace('：',':');
  if(/^\d{4}-\d{2}-\d{2}T/.test(s)) return s.slice(11,16);
  if(/^\d{1,2}:\d{1,2}/.test(s)){ const [h,m]=s.split(':'); return `${String(h).padStart(2,'0')}:${String(m).slice(0,2).padStart(2,'0')}`; }
  if(/\//.test(s) && /:/.test(s)){ return s.split(' ').pop().slice(0,5); }
  return s.slice(0,5);
}
function todayISO(){
  const now = new Date();
  const y = now.getFullYear();
  const m = String(now.getMonth() + 1).padStart(2, '0');
  const d = String(now.getDate()).padStart(2, '0');
  return `${y}-${m}-${d}`;
}
function onlyDigits(t){return (t||'').replace(/\D/g,'')}

/* ====== 驗證 ====== */
const phoneRegex=/^\+?\d{1,3}?\d{7,}$/;
const emailRegex=/^[^\s@]+@[^\s@]+\.[^\s@]+$/;
const roomRegex=/^(0000|501|502|503|505|506|507|508|509|510|511|512|515|516|517|518|519|520|521|522|523|525|526|527|528|601|602|603|605|606|607|608|609|610|611|612|615|616|617|618|619|620|621|622|623|625|626|627|628|701|702|703|705|706|707|708|709|710|711|712|715|716|717|718|719|720|721|722|723|725|726|727|728|801|802|803|805|806|807|808|809|810|811|812|815|816|817|818|819|820|821|822|823|825|826|827|828|901|902|903|905|906|907|908|909|910|911|912|915|916|917|918|919|920|921|922|923|925|926|927|928|1001|1002|1003|1005|1006|1007|1008|1009|1010|1011|1012|1015|1016|1017|1018|1019|1020|1021|1022|1023|1025|1026|1027|1028|1101|1102|1103|1105|1106|1107|1108|1109|1110|1111|1112|1115|1116|1117|1118|1119|1120|1121|1122|1123|1125|1126|1127|1128|1201|1202|1206|1207|1208|1209|1210|1211|1212|1215|1216|1217|1218|1219|1220|1221|1222|1223|1225|1226|1227|1228|1301|1302|1303|1305|1306|1307|1308|1309|1310|1311|1312|1315|1316|1317|1318|1319|1320|1321|1322|1323|1325|1326|1327|1328)$/;
const nameRegex=/^[\u4e00-\u9fa5a-zA-Z\s]*$/;
function validateName(input){
  const value = input.value || "";
  const nameErr = document.getElementById('nameErr');
  if(!nameRegex.test(value)){
    input.value = value.replace(/[^\u4e00-\u9fa5a-zA-Z\s]/g,'');
    nameErr.textContent = t('errName');
    nameErr.style.display='block';
    shake(input);
    input.style.borderColor='#b00020';
    setTimeout(()=>{ input.style.borderColor='#ddd'; nameErr.style.display='none'; }, 2000);
  }else if(!value.trim()){
    nameErr.textContent = t('errName');
    nameErr.style.display='block';
    shake(input);
    input.style.borderColor='#b00020';
  }else{
    nameErr.style.display='none';
    input.style.borderColor='#ddd';
  }
}
function validatePhone(input){
  const value = input.value || "";
  const phoneErr = document.getElementById('phoneErr');
  if(!phoneRegex.test(value)){
    phoneErr.textContent = t('errPhone');
    phoneErr.style.display='block';
    shake(input);
    input.style.borderColor='#b00020';
  }else{
    phoneErr.style.display='none';
    input.style.borderColor='#ddd';
  }
}
function validateEmail(input){
  const value = input.value || "";
  const emailErr = document.getElementById('emailErr');
  if(!emailRegex.test(value)){
    emailErr.textContent = t('errEmail');
    emailErr.style.display='block';
    shake(input);
    input.style.borderColor='#b00020';
  }else{
    emailErr.style.display='none';
    input.style.borderColor='#ddd';
  }
}
function validateRoom(input){
  const value = input.value || "";
  const roomErr = document.getElementById('roomErr');
  if(!roomRegex.test(value)){
    roomErr.textContent = t('errRoom');
    roomErr.style.display='block';
    shake(input);
    input.style.borderColor='#b00020';
  }else{
    roomErr.style.display='none';
    input.style.borderColor='#ddd';
  }
}

/* ====== 初始化/頁面 ====== */
function startBooking(){
  document.getElementById('homeHero').style.display='none';
  refreshData().then(()=>{
    buildStep1();
    document.getElementById('step1').style.display='';
    window.scrollTo({top:0,behavior:'smooth'});
  });
}
function goStep(n){
  ['step1','step2','step3','step4','step5','step6'].forEach(id=>{ const el = document.getElementById(id); if(el) el.style.display='none'; });
  const target = document.getElementById('step'+n);
  if(target) target.style.display='';
  window.scrollTo({top:0,behavior:'smooth'});
}
function restart(){
  selectedDirection="";selectedDateRaw="";selectedStationRaw="";selectedScheduleTime="";selectedAvailableSeats=0;
  hardResetOverlays();
  document.getElementById('homeHero').style.display='';
  ['directionList','dateList','stationList','scheduleList'].forEach(id=>{ const el=document.getElementById(id); if(el) el.innerHTML=''; });
  ['step1','step2','step3','step4','step5','step6','successCard'].forEach(id=>{ const el=document.getElementById(id); if(el) el.style.display='none'; });
  showPage('reservation');
  window.scrollTo({top:0,behavior:'smooth'});
}

/* ====== Step 1 ====== */
function buildStep1(){
  const list = document.getElementById('directionList');
  list.innerHTML = '';
  const opts = [
    { valueZh: '去程', labelKey: 'dirOutLabel' },
    { valueZh: '回程', labelKey: 'dirInLabel' },
  ];
  opts.forEach(opt=>{
    const btn = document.createElement('button');
    btn.type='button';
    btn.className='opt-btn';
    btn.textContent = t(opt.labelKey);
    btn.onclick = () => {
      selectedDirection = opt.valueZh;
      list.querySelectorAll('.opt-btn').forEach(b=>b.classList.remove('active'));
      btn.classList.add('active');
      toStep2();
    };
    list.appendChild(btn);
  });
}
function toStep2(){
  if(!selectedDirection){ showErrorCard(t('labelDirection')); return; }
  const dateSet = new Set(allRows.filter(r=>String(r["去程 / 回程"]).trim()===selectedDirection).map(r=>fmtDateLabel(r["日期"])));
  const sorted=[...dateSet].sort((a,b)=>new Date(a)-new Date(b));
  const list = document.getElementById('dateList');
  list.innerHTML='';
  sorted.forEach(dateStr=>{
    const btn=document.createElement('button');
    btn.type='button'; btn.className='opt-btn'; btn.textContent=dateStr;
    btn.onclick=()=>{ selectedDateRaw=dateStr; list.querySelectorAll('.opt-btn').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); toStep3(); };
    list.appendChild(btn);
  });
  goStep(2);
}

/* ====== Step 3 ====== */
function toStep3(){
  if(!selectedDateRaw){ showErrorCard(t('labelDate')); return; }
  document.getElementById('fixedStation').value = '福泰大飯店 Forte Hotel';
  const stations = new Set(allRows.filter(r=>String(r["去程 / 回程"]).trim()===selectedDirection && fmtDateLabel(r["日期"])===selectedDateRaw).map(r=>String(r["站點"]).trim()));
  const list = document.getElementById('stationList');
  list.innerHTML='';
  [...stations].forEach(st=>{
    const btn=document.createElement('button');
    btn.type='button'; btn.className='opt-btn'; btn.textContent=st;
    btn.onclick=()=>{ selectedStationRaw=st; list.querySelectorAll('.opt-btn').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); toStep4(); };
    list.appendChild(btn);
  });
  goStep(3);
}

/* ====== Step 4 ====== */
function toStep4(){
  if(!selectedStationRaw){ showErrorCard(t('labelStation')); return; }
  const list=document.getElementById('scheduleList');
  list.innerHTML='';
  const entries = allRows.filter(r=>
    String(r["去程 / 回程"]).trim()===selectedDirection &&
    fmtDateLabel(r["日期"])===selectedDateRaw &&
    String(r["站點"]).trim()===selectedStationRaw
  ).sort((a,b)=>fmtTimeLabel(a["班次"]).localeCompare(fmtTimeLabel(b["班次"])));
  if(entries.length===0){ showExpiredOverlay(true); return; }

  entries.forEach(r=>{
    const time=fmtTimeLabel(r["班次"]||r["車次"]);
    const availText=String(r["可預約人數"]||r["可約人數 / Available"]||'').trim();
    const avail=Number(onlyDigits(availText))||0;
    const btn=document.createElement('button');
    btn.type='button'; btn.className='opt-btn';
    if(avail<=0){
      btn.classList.add('disabled');
      btn.innerHTML = `<span style="color:#999;font-weight:700">${time}</span> <span style="color:#999;font-size:13px">(已額滿)</span>`;
    }else{
      btn.innerHTML = `<span style="color:var(--primary);font-weight:700">${time}</span> <span style="color:#777;font-size:13px">(可預約：${avail} 人)</span>`;
      btn.onclick=()=>{ selectedScheduleTime=time; selectedAvailableSeats=avail; list.querySelectorAll('.opt-btn').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); toStep5(); };
    }
    list.appendChild(btn);
  });
  goStep(4);
}

/* ====== Step 5 ====== */
function onIdentityChange(){
  const v=document.getElementById('identitySelect').value;
  const today = todayISO();
  document.getElementById('hotelDates').style.display = v==='hotel'?'block':'none';
  document.getElementById('hotelDates2').style.display = v==='hotel'?'block':'none';
  document.getElementById('roomNumberDiv').style.display = v==='hotel'?'block':'none';
  document.getElementById('diningDateDiv').style.display = v==='dining'?'block':'none';
  if(v==='hotel'){
    const ci = document.getElementById('checkInDate');
    const co = document.getElementById('checkOutDate');
    if(ci && !ci.value) ci.value = today;
    if(co && !co.value) co.value = today;
  } else if(v==='dining'){
    const dining = document.getElementById('diningDate');
    if(dining && !dining.value) dining.value = today;
  }
}
function toStep5(){
  if(!selectedScheduleTime){ showErrorCard(t('labelSchedule')); return; }
  onIdentityChange();
  goStep(5);
}
function validateStep5(){
  const id=document.getElementById('identitySelect').value;
  const name=(document.getElementById('guestName').value||'').trim();
  const phone=(document.getElementById('guestPhone').value||'').trim();
  const email=(document.getElementById('guestEmail').value||'').trim();
  if(!id){document.getElementById('identityErr').style.display='block'; return false} else document.getElementById('identityErr').style.display='none';
  if(!name){document.getElementById('nameErr').style.display='block'; shake(document.getElementById('guestName')); return false}else document.getElementById('nameErr').style.display='none';
  if(!phoneRegex.test(phone)){document.getElementById('phoneErr').style.display='block'; shake(document.getElementById('guestPhone')); return false}else document.getElementById('phoneErr').style.display='none';
  if(!emailRegex.test(email)){document.getElementById('emailErr').style.display='block'; shake(document.getElementById('guestEmail')); return false}else document.getElementById('emailErr').style.display='none';
  if(id==='hotel'){
    const cin=document.getElementById('checkInDate').value;
    const cout=document.getElementById('checkOutDate').value;
    if(!cin||!cout){ showErrorCard(t('labelCheckIn')+'/'+t('labelCheckOut')); shake(document.getElementById('checkInDate')); shake(document.getElementById('checkOutDate')); return false; }
    const room=(document.getElementById('roomNumber').value||'').trim();
    if(!roomRegex.test(room)){document.getElementById('roomErr').style.display='block'; shake(document.getElementById('roomNumber')); return false}else document.getElementById('roomErr').style.display='none';
  }else{
    const din=document.getElementById('diningDate').value;
    if(!din){ showErrorCard(t('labelDiningDate')); shake(document.getElementById('diningDate')); return false; }
  }
  return true;
}
function toStep6(){
  if (!validateStep5()) return;
  document.getElementById('cf_direction').value = selectedDirection;
  document.getElementById('cf_date').value = selectedDateRaw;
  const pick = (selectedDirection === '回程') ? selectedStationRaw : '福泰大飯店 Forte Hotel';
  const drop = (selectedDirection === '回程') ? '福泰大飯店 Forte Hotel' : selectedStationRaw;
  document.getElementById('cf_pick').value = pick;
  document.getElementById('cf_drop').value = drop;
  document.getElementById('cf_time').value = selectedScheduleTime;
  document.getElementById('cf_name').value = (document.getElementById('guestName').value || '').trim();
  const sel = document.getElementById('passengers');
  sel.innerHTML = '';
  const maxPassengers = Math.min(4, Math.max(0, selectedAvailableSeats));
  if (maxPassengers <= 0){
    const opt = document.createElement('option');
    opt.value = ''; opt.textContent = '0';
    sel.appendChild(opt);
    sel.disabled = true;
  } else {
    sel.disabled = false;
    for (let i = 1; i <= maxPassengers; i++){
      const opt = document.createElement('option');
      opt.value = String(i);
      opt.textContent = String(i);
      sel.appendChild(opt);
    }
    sel.value = '1';
  }
  document.getElementById('passengersHint').textContent = `此班次可預約：${selectedAvailableSeats} 人；單筆最多 4 人`;
  ['step1','step2','step3','step4','step5'].forEach(id=>{ const el = document.getElementById(id); if (el) el.style.display = 'none'; });
  document.getElementById('step6').style.display = '';
  window.scrollTo({ top: 0, behavior: 'smooth' });
  const errEl = document.getElementById('passengersErr'); if (errEl) errEl.style.display = 'none';
}

// === 友善錯誤提示（所有班次失效 / 調整額滿 / 不存在）===
function showFriendlyCapacityError() {
  showErrorCard(t("overPaxOrMissing"));
}

/* ====== 成功動畫 ====== */
function showSuccessAnimation() {
  const el = document.getElementById('successAnimation');
  el.style.display = 'flex';
  el.classList.add('show');
  setTimeout(() => {
    el.classList.remove('show');
    el.style.display = 'none';
  }, 3000);
}

/* ====== 送出預約 ====== */
let bookingSubmitting = false;
async function submitBooking(){
  if (bookingSubmitting) return;

  // 人數驗證
  const pSel = document.getElementById('passengers');
  const p = Number(pSel?.value || 0);
  if (!p || p < 1 || p > 4) {
    const errEl = document.getElementById('passengersErr');
    if (errEl) errEl.style.display = 'block';
    return;
  }
  const errEl = document.getElementById('passengersErr'); 
  if (errEl) errEl.style.display = 'none';

  // 準備資料
  const identity = document.getElementById('identitySelect').value;
  const payload = {
    direction: selectedDirection,
    date: selectedDateRaw,
    station: selectedStationRaw,
    time: selectedScheduleTime,
    identity,
    checkIn: identity === 'hotel' ? (document.getElementById('checkInDate').value || null) : null,
    checkOut: identity === 'hotel' ? (document.getElementById('checkOutDate').value || null) : null,
    diningDate: identity === 'dining' ? (document.getElementById('diningDate').value || null) : null,
    roomNumber: identity === 'hotel' ? (document.getElementById('roomNumber').value || null) : null,
    name: (document.getElementById('guestName').value || '').trim(),
    phone: (document.getElementById('guestPhone').value || '').trim(),
    email: (document.getElementById('guestEmail').value || '').trim(),
    passengers: p,
    dropLocation: selectedDirection === '回程' ? '福泰大飯店 Forte Hotel' : selectedStationRaw,
    pickLocation: selectedDirection === '回程' ? selectedStationRaw : '福泰大飯店 Forte Hotel',
  };

  bookingSubmitting = true;
  const step6 = document.getElementById('step6');
  if (step6) step6.style.display = 'none';
  showVerifyLoading(true);

  try {
    const res = await fetch(OPS_URL, {
      method: 'POST',
      mode: 'cors',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ action: 'book', data: payload }),
    });

    // 嘗試解析後端回傳 JSON（成功或失敗都試著吃）
    let result = null;
    try {
      result = await res.json();
    } catch (e) {
      result = null;
    }

    const backendMsg = result && (result.error || result.code || result.detail || result.message || '');
    const isCapacityError =
      res.status === 409 ||
      backendMsg === 'capacity_not_found' ||
      String(backendMsg || '').includes('capacity_not_found');

    // HTTP 非 2xx：統一處理
    if (!res.ok) {
      if (isCapacityError) {
        // 班次失效 / 人數超過 / 找不到班次 → 友善提示（多語系）
        showErrorCard(t('overPaxOrMissing'));
      } else {
        // 其他 HTTP 錯誤
        showErrorCard(t('submitFailedPrefix') + `HTTP ${res.status}`);
      }
      if (step6) step6.style.display = '';
      return;
    }

    // res.ok 但結果不是 success
    if (!result || result.status !== 'success') {
      if (isCapacityError) {
        showErrorCard(t('overPaxOrMissing'));
      } else {
        showErrorCard(
          (result && (result.detail || result.message)) || t('errorGeneric')
        );
      }
      if (step6) step6.style.display = '';
      return;
    }

    // ✅ 成功 → 顯示車票
    const qrPath = result.qr_content 
      ? (`${QR_ORIGIN}/api/qr/${encodeURIComponent(result.qr_content)}`) 
      : (result.qr_url || '');

    currentBookingData = {
      bookingId: result.booking_id || '',
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

    // ✅ 寄信（背景）
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 4000);
      const dataUrl = await domtoimage.toPng(
        document.getElementById('ticketCard'),
        { bgcolor: '#fff', pixelRatio: 2 }
      );
      fetch(OPS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          action: 'mail',
          data: {
            booking_id: currentBookingData.bookingId,
            lang: currentLang,
            kind: 'book',
            ticket_png_base64: dataUrl
          }
        }),
        signal: controller.signal
      }).catch(()=>{}).finally(()=>clearTimeout(timer));
    } catch (e) {
      console.warn('寄信未完成或超時', e);
    }

  } catch(err){
    // fetch 本身錯誤（例如網路問題）
    const maybeCapacity =
      err && (err.error === 'capacity_not_found' || String(err.message || '').includes('capacity_not_found'));
    if (maybeCapacity) {
      showErrorCard(t('overPaxOrMissing'));
    } else {
      showErrorCard(t('submitFailedPrefix') + (err.message || ''));
    }
    if (step6) step6.style.display = '';
  } finally {
    showVerifyLoading(false);
    bookingSubmitting = false;
  }
}


function mountTicketAndShow(ticket){
  document.getElementById('ticketQrImg').src = ticket.qrUrl;
  document.getElementById('ticketBookingId').textContent = ticket.bookingId;
  document.getElementById('ticketSchedule').textContent = ticket.time;
  document.getElementById('ticketDirection').textContent = ticket.direction;
  document.getElementById('ticketPick').textContent = ticket.pickLocation;
  document.getElementById('ticketDrop').textContent = ticket.dropLocation;
  document.getElementById('ticketName').textContent = ticket.name;
  document.getElementById('ticketPhone').textContent = ticket.phone;
  document.getElementById('ticketEmail').textContent = ticket.email;
  document.getElementById('ticketPassengers').textContent = ticket.passengers + ' ' + t('labelPassengersShort');
  const card = document.getElementById('successCard');
  if (card) card.style.display = '';
  window.scrollTo({ top: 0, behavior: 'smooth' });
  showSuccessAnimation();
}
function closeTicketToHome(){
  const card = document.getElementById('successCard');
  if (card) card.style.display = 'none';
  document.getElementById('homeHero').style.display = '';
  ['step1','step2','step3','step4','step5','step6'].forEach(id=>{
    const el=document.getElementById(id); if(el) el.style.display='none';
  });
  window.scrollTo({top:0,behavior:'smooth'});
}
async function downloadTicket() {
  const card = document.getElementById('ticketCard');
  if (!card) { showErrorCard('找不到票卡'); return; }
  try {
    const rect = card.getBoundingClientRect();
    const dpr = Math.max(window.devicePixelRatio || 1, 1);
    const width = Math.round(rect.width);
    const height = Math.round(rect.height);
    const dataUrl = await domtoimage.toPng(card, {
      width, height, bgcolor: '#ffffff', pixelRatio: dpr,
      style: { margin: '0', transform: 'none', boxShadow: 'none', overflow: 'visible' }
    });
    const a = document.createElement('a');
    const bid = (document.getElementById('ticketBookingId')?.textContent || 'ticket').trim();
    a.href = dataUrl; a.download = `ticket_${bid}.png`; a.click();
  } catch (e) { showErrorCard('下載失敗：' + (e?.message || e)); }
}

/* ====== 查詢我的預約 ====== */
function showCheckQueryForm(){
  document.getElementById('queryForm').style.display='flex';
  document.getElementById('checkDateStep').style.display='none';
  document.getElementById('checkTicketStep').style.display='none';
  window.scrollTo({top:0,behavior:'smooth'});
}
function showCheckDateStep(){
  document.getElementById('queryForm').style.display='none';
  document.getElementById('checkDateStep').style.display='block';
  document.getElementById('checkTicketStep').style.display='none';
  window.scrollTo({top:0,behavior:'smooth'});
}
function showCheckTicketStep(){
  document.getElementById('queryForm').style.display='none';
  document.getElementById('checkDateStep').style.display='none';
  document.getElementById('checkTicketStep').style.display='block';
  window.scrollTo({top:0,behavior:'smooth'});
}
function closeCheckTicket(){ showCheckDateStep(); }
function withinOneMonth(dateIso){
  try{ 
    const d = new Date((fmtDateLabel(dateIso)||todayISO())+'T00:00:00'); 
    const now=new Date(); 
    const pastLimit = new Date(now); 
    pastLimit.setMonth(now.getMonth()-1); 
    return d >= pastLimit; 
  }catch(e){ 
    return true; 
  }
}
function getStatusCode(row){
  const s = String(row["預約狀態"]||row["訂單狀態"]||'').toLowerCase();
  const audited = String(row["櫃台審核"]||'').trim().toUpperCase();
  const boarded = String(row["乘車狀態"]||'').includes('已上車');
  if(boarded) return 'boarded';
  if(audited==='N') return 'rejected';
  if(s.includes('取消')) return 'cancelled';
  if(s.includes('預約')) return 'booked';
  return 'booked';
}
function maskName(name){
  const s = String(name||'').trim();
  if(!s) return "";
  if(/[\u4e00-\u9fa5]/.test(s)){ return s.charAt(0) + '*'.repeat(Math.max(0, s.length-1)); }
  const prefix = s.slice(0,3);
  return prefix + '*'.repeat(Math.max(0, s.length-3));
}
function maskPhone(phone){ const p = String(phone||''); return p.slice(-4); }
function maskEmail(email){
  const e = String(email||'').trim();
  const at = e.indexOf('@');
  if(at <= 0) return e ? e[0] + '***' : '';
  const name = e.slice(0, at);
  const prefix = name.slice(0,3);
  const stars = '*'.repeat(Math.max(0, name.length - 3));
  const domain = e.slice(at+1).toLowerCase();
  return `${prefix}${stars}@${domain}`;
}
function buildTicketCard(row, {mask=false}={}){
  const carDateTime = String(row["車次-日期時間"] || "");
  const dateIso = getDateFromCarDateTime(carDateTime);
  const time = getTimeFromCarDateTime(carDateTime);
  const expired = isExpiredByCarDateTime(carDateTime);

  const statusCode = getStatusCode(row);
  const name = mask ? maskName(String(row["姓名"]||'')) : String(row["姓名"]||'');
  const phone = mask ? maskPhone(String(row["手機"]||'')) : String(row["手機"]||'');
  const email = mask ? maskEmail(String(row["信箱"]||'')) : String(row["信箱"]||'');
  const rb = String(row["往返"]||row["往返方向"]||'');
  const pick = String(row["上車地點"]||'');
  const drop = String(row["下車地點"]||'');
  const bookingId = String(row["預約編號"]||'');
  const pax = Number(row["確認人數"] || row["預約人數"] || '1') || 1;
  const qrCodeContent = String(row["QRCode編碼"]||'');
  const qrUrl = qrCodeContent ? (QR_ORIGIN + '/api/qr/' + encodeURIComponent(qrCodeContent)) : '';

  const card = document.createElement('div');
  card.className = 'ticket-card' + (expired ? ' expired' : '');
  const pill = document.createElement('div');
  pill.className = 'status-pill ' + (expired ? 'status-expired' : ('status-'+statusCode));
  pill.textContent = expired ? ts('expired') : ts(statusCode);
  card.appendChild(pill);

  if(statusCode==='rejected'){
    const tip = document.createElement('button');
    tip.className='badge-alert';
    tip.title = t('rejectedTip');
    tip.textContent='!';
    tip.onclick = ()=> showErrorCard(t('rejectedTip'));
    card.appendChild(tip);
  }

  const header = document.createElement('div');
  header.className='ticket-header';
  header.innerHTML=`<h2>${sanitize(carDateTime)}</h2>`;
  card.appendChild(header);

  const content = document.createElement('div'); 
  content.className='ticket-content';
  const qr = document.createElement('div'); 
  qr.className='ticket-qr';
  qr.innerHTML = (statusCode==='cancelled')
    ? `<img src="/images/qr-placeholder.png" alt="QR placeholder" />`
    : `<img src="${qrUrl}" alt="QR" />`;

  const info = document.createElement('div'); 
  info.className='ticket-info';
  info.innerHTML = `
    <div class="ticket-field"><span class="ticket-label">${t('labelBookingId')}</span><span class="ticket-value">${sanitize(bookingId)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelDirection')}</span><span class="ticket-value">${sanitize(rb)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelPick')}</span><span class="ticket-value">${sanitize(pick)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelDrop')}</span><span class="ticket-value">${sanitize(drop)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelName')}</span><span class="ticket-value">${sanitize(name)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelPhone')}</span><span class="ticket-value">${sanitize(phone)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelEmail')}</span><span class="ticket-value">${sanitize(email)}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelPassengersShort')}</span><span class="ticket-value">${sanitize(String(pax))}</span></div>
  `;
  content.appendChild(qr); 
  content.appendChild(info); 
  card.appendChild(content);

  const actions = document.createElement('div'); 
  actions.className='ticket-actions';
  if(statusCode!=='cancelled' && statusCode!=='rejected'){
    const dlBtn = document.createElement('button'); 
    dlBtn.className='button'; 
    dlBtn.textContent=ts('download');
    dlBtn.onclick = ()=>{ 
      domtoimage.toPng(card,{bgcolor:'#fff', pixelRatio:2}).then((dataUrl)=>{ 
        const a=document.createElement('a'); 
        a.href=dataUrl; 
        a.download=`ticket_${sanitize(bookingId)}.png`; 
        a.click(); 
      }); 
    };
    actions.appendChild(dlBtn);
  }
  if(!expired && statusCode!=='cancelled' && statusCode!=='rejected' && statusCode!=='boarded'){
    const mdBtn = document.createElement('button'); 
    mdBtn.className='button btn-ghost'; 
    mdBtn.textContent=ts('modify');
    mdBtn.onclick = ()=> openModifyPage({ row, bookingId, rb, date: dateIso, pick, drop, time, pax });
    actions.appendChild(mdBtn);
    
    const delBtn = document.createElement('button'); 
    delBtn.className='button btn-ghost'; 
    delBtn.textContent=ts('remove');
    delBtn.onclick = ()=> deleteOrder(bookingId);
    actions.appendChild(delBtn);
  }
  card.appendChild(actions);
  return card;
}

/* ====== 查詢/刪改 ====== */
async function queryOrders(){
  const id=(document.getElementById('qBookId').value||'').trim();
  const phone=(document.getElementById('qPhone').value||'').trim();
  const email=(document.getElementById('qEmail').value||'').trim();
  const queryHint = document.getElementById('queryHint');
  if(!id && !phone && !email){ shake(queryHint); return; }
  showLoading(true);
  try{
    const res = await fetch(OPS_URL, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'query', data:{booking_id:id, phone, email}})});
    const data = await res.json();
    const arr = Array.isArray(data) ? data : (data.results || []);
    lastQueryResults = arr;
    buildDateListFromResults(arr);
    showCheckDateStep();
  }catch(e){ showErrorCard(t('queryFailedPrefix') + (e?.message||'')); }
  finally{ showLoading(false); }
}
function buildDateListFromResults(rows){
  const dateMap = new Map();
  rows.forEach(r => {
    const carDateTime = String(r["車次-日期時間"] || "");
    const dateIso = getDateFromCarDateTime(carDateTime);
    if (withinOneMonth(dateIso)) dateMap.set(dateIso, (dateMap.get(dateIso) || 0) + 1);
  });
  queryDateList = Array.from(dateMap.entries()).sort((a, b) => new Date(a[0]) - new Date(b[0]));
  const wrap = document.getElementById('dateChoices');
  wrap.innerHTML = '';
  if (!queryDateList.length) {
    const empty = document.createElement('div'); 
    empty.className = 'card'; 
    empty.style.textAlign = 'center'; 
    empty.style.color = '#666'; 
    empty.textContent = (I18N_STATUS[currentLang] || I18N_STATUS.zh).noRecords;
    wrap.appendChild(empty); 
    return;
  }
  queryDateList.forEach(([date, count]) => {
    const btn = document.createElement('button'); 
    btn.type = 'button'; 
    btn.className = 'opt-btn';
    btn.innerHTML = `${date} <span style="color:#777;font-size:13px">(有：${count} 筆預約)</span>`;
    btn.onclick = () => openTicketsForDate(date);
    wrap.appendChild(btn);
  });
}
function openTicketsForDate(dateIso) {
  currentQueryDate = dateIso;
  const dateRows = lastQueryResults.filter(r => {
    const carDateTime = String(r["車次-日期時間"] || "");
    const rowDateIso = getDateFromCarDateTime(carDateTime);
    return rowDateIso === dateIso;
  });
  currentDateRows = dateRows.sort((a, b) => {
    const statusA = getStatusCode(a);
    const statusB = getStatusCode(b);
    const carDateTimeA = String(a["車次-日期時間"] || "");
    const carDateTimeB = String(b["車次-日期時間"] || "");
    const isValidA = (statusA === 'booked' || statusA === 'boarded') && !isExpiredByCarDateTime(carDateTimeA);
    const isValidB = (statusB === 'booked' || statusB === 'boarded') && !isExpiredByCarDateTime(carDateTimeB);
    if (isValidA && !isValidB) return -1;
    if (!isValidA && isValidB) return 1;
    if (isValidA && isValidB) {
      const timeA = getTimeFromCarDateTime(carDateTimeA);
      const timeB = getTimeFromCarDateTime(carDateTimeB);
      return timeA.localeCompare(timeB);
    }
    const order = { 'cancelled': 1, 'rejected': 2, 'expired': 3, 'booked': 4, 'boarded': 5 };
    return (order[statusA] || 6) - (order[statusB] || 6);
  });
  const mount = document.getElementById('checkTicketMount');
  mount.innerHTML = '';
  currentDateRows.forEach(row => mount.appendChild(buildTicketCard(row, { mask: true })));
  showCheckTicketStep();
}
function rerenderQueryPages(){
  if(document.getElementById('checkDateStep').style.display!=='none'){ buildDateListFromResults(lastQueryResults); }
  if(document.getElementById('checkTicketStep').style.display!=='none'){ openTicketsForDate(currentQueryDate); }
}

/* 刪除（卡片確認 + 倒數5秒） */
async function deleteOrder(bookingId){
  showConfirmDelete(bookingId, async ()=>{
    showLoading(true);
    try{
      const r = await fetch(OPS_URL, {
        method: 'POST', 
        headers: {'Content-Type':'application/json'}, 
        body: JSON.stringify({action:'delete', data:{booking_id:bookingId}})
      });
      const j = await r.json();
      if(j.status==='success'){
        showSuccessAnimation();
        setTimeout(async () => {
          // 重新查詢
          const id = document.getElementById('qBookId').value.trim();
          const phone = document.getElementById('qPhone').value.trim();
          const email = document.getElementById('qEmail').value.trim();
          const queryRes = await fetch(OPS_URL, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ action: 'query', data: { booking_id: id, phone, email } })
          });
          const queryData = await queryRes.json();
          lastQueryResults = Array.isArray(queryData) ? queryData : (queryData.results || []);
          buildDateListFromResults(lastQueryResults);
          if (currentQueryDate) openTicketsForDate(currentQueryDate); else showCheckDateStep();
        }, 3000);
      } else {
        showErrorCard(j.detail || t('errorGeneric'));
      }
    } catch(e) { showErrorCard(t('deleteFailedPrefix') + (e?.message||'')); }
    finally { showLoading(false); }
  });
}

/* ====== 修改：新頁面（人數動態受班次可預約限制，且<=4） ====== */
async function openModifyPage({row, bookingId, rb, date, pick, drop, time, pax}){
  await refreshData();
  showPage('check');
  document.getElementById('queryForm').style.display='none';
  document.getElementById('checkDateStep').style.display='none';

  const holderId = 'editHolder';
  let holder = document.getElementById(holderId);
  if(!holder){
    holder = document.createElement('div');
    holder.id = holderId;
    holder.className = 'card wizard-fixed';
    document.getElementById('check').appendChild(holder);
  }

  holder.innerHTML = `
    <h2>${t('editBookingTitle') || '修改預約'} ${sanitize(bookingId)}</h2>
    <div class="field"><label class="label">${t('labelDirection')}</label>
      <select id="md_dir" class="select">
        <option value="去程" ${rb==='去程'?'selected':''}>${t('dirOutLabel')}</option>
        <option value="回程" ${rb==='回程'?'selected':''}>${t('dirInLabel')}</option>
      </select>
    </div>
    <div class="field"><label class="label">${t('labelDate')}</label><div id="md_dates" class="options"></div></div>
    <div class="field"><label class="label">${t('labelStation')}</label><div id="md_stations" class="options"></div></div>
    <div class="field"><label class="label">${t('labelSchedule')}</label><div id="md_schedules" class="options"></div></div>
    <div class="field"><label class="label">${t('labelPassengersShort')}</label><select id="md_pax" class="select"></select><div id="md_hint" class="hint"></div></div>
    <div class="field"><label class="label">${t('labelPhone')}</label><input id="md_phone" class="input" value="${sanitize(String(row["手機"]||''))}" /></div>
    <div class="field"><label class="label">${t('labelEmail')}</label><input id="md_email" class="input" value="${sanitize(String(row["信箱"]||''))}" /></div>
    <div class="actions row" style="justify-content:flex-end">
      <button class="button btn-ghost" id="md_cancel">${t('back')}</button>
      <button class="button" id="md_save">${ts('modify')}</button>
    </div>
  `;

  document.getElementById('checkTicketStep').style.display='none';
  holder.style.display='block';

  let mdDirection = rb;
  let mdDate = fmtDateLabel(date);
  let mdStation = (rb==='回程') ? pick : drop;
  let mdTime = fmtTimeLabel(time);
  let mdAvail = 0;

  function buildDateOptions(){
    const dateSet = new Set(
      allRows
        .filter(r => String(r["去程 / 回程"]).trim() === mdDirection)
        .map(r => fmtDateLabel(r["日期"]))
    );
    const sorted = [...dateSet].sort((a,b)=>new Date(a)-new Date(b));
    const list = holder.querySelector('#md_dates'); 
    list.innerHTML = '';
    sorted.forEach(dateStr => {
      const btn = document.createElement('button'); 
      btn.type='button'; 
      btn.className='opt-btn'; 
      btn.textContent = dateStr; 
      if(dateStr === mdDate) btn.classList.add('active');
      btn.onclick = () => { 
        mdDate = dateStr; 
        list.querySelectorAll('.opt-btn').forEach(b=>b.classList.remove('active')); 
        btn.classList.add('active'); 
        buildStationOptions(); 
      }; 
      list.appendChild(btn); 
    });
  }

  function buildStationOptions() {
    const stations = new Set(
      allRows
        .filter(r =>
          String(r["去程 / 回程"]).trim() === mdDirection &&
          fmtDateLabel(r["日期"]) === mdDate
        )
        .map(r => String(r["站點"]).trim())
    );

    const list = holder.querySelector('#md_stations');
    list.innerHTML = '';

    [...stations].forEach(st => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'opt-btn';
      btn.textContent = st;
      if (st === mdStation) btn.classList.add('active');

      btn.onclick = () => {
        mdStation = st;
        list.querySelectorAll('.opt-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        buildScheduleOptions();
      };

      list.appendChild(btn);
    });

    // 如果目前選的站點不在列表裡，預設選第一個並重建班次
    if (!stations.has(mdStation) && stations.size > 0) {
      mdStation = [...stations][0];
      buildScheduleOptions();
    }
  }

  function buildScheduleOptions() {
    const list = holder.querySelector('#md_schedules');
    list.innerHTML = '';

    const entries = allRows
      .filter(r =>
        String(r["去程 / 回程"]).trim() === mdDirection &&
        fmtDateLabel(r["日期"]) === mdDate &&
        String(r["站點"]).trim() === mdStation
      )
      .sort((a, b) =>
        fmtTimeLabel(a["班次"]).localeCompare(fmtTimeLabel(b["班次"]))
      );

    entries.forEach(r => {
      const timeVal   = fmtTimeLabel(r["班次"] || r["車次"]);
      const availText = String(
        r["可預約人數"] || r["可約人數 / Available"] || ''
      ).trim();

      const baseAvail = Number(onlyDigits(availText)) || 0;

      const sameAsOriginal =
        (rb === mdDirection) &&
        (fmtDateLabel(date) === mdDate) &&
        (mdStation === ((rb === '回程') ? pick : drop)) &&
        (fmtTimeLabel(time) === timeVal);

      const availPlusSelf = baseAvail + (sameAsOriginal ? pax : 0);

      const btn = document.createElement('button');
      btn.type  = 'button';
      btn.className = 'opt-btn';
      if (timeVal === mdTime) btn.classList.add('active');

      const texts        = TEXTS[currentLang] || TEXTS.zh;
      const prefix       = texts.paxHintPrefix || '';
      const suffixRaw    = texts.paxHintSuffix || '';
      const suffixShort  = suffixRaw.split(/[；;]/)[0] || suffixRaw;
      const includeSelfText = sameAsOriginal
        ? (I18N_STATUS[currentLang] || I18N_STATUS.zh).includeSelf
        : '';

      const paxInfo = `(${prefix}${availPlusSelf}${suffixShort}${includeSelfText})`;

      btn.innerHTML = `
        <span style="color:var(--primary);font-weight:700">${timeVal}</span>
        <span style="color:#777;font-size:13px">
          ${paxInfo}
        </span>
      `;

      btn.onclick = () => {
        mdTime  = timeVal;
        mdAvail = availPlusSelf;
        list.querySelectorAll('.opt-btn').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        buildPax();
      };

      list.appendChild(btn);
    });

    buildPax();
  }




  function buildPax(){
    const sel = holder.querySelector('#md_pax'); 
    sel.innerHTML = '';
    const maxPassengers = Math.min(4, Math.max(0, mdAvail || pax || 4));
    for(let i=1;i<=maxPassengers;i++){
      const opt = document.createElement('option');
      opt.value = String(i);
      opt.textContent = String(i);
      sel.appendChild(opt);
    }
    sel.value = String(Math.min(pax, maxPassengers));
    const hint = holder.querySelector('#md_hint'); 
    hint.textContent = t('paxHintPrefix') + `${mdAvail || 0}` + t('paxHintSuffix');
  }

  holder.querySelector('#md_dir').addEventListener('change', (e)=>{
    mdDirection = e.target.value; 
    mdStation = (mdDirection === '回程') ? pick : drop; 
    buildDateOptions(); 
  });

  holder.querySelector('#md_cancel').onclick = ()=>{
    holder.style.display='none'; 
    showCheckDateStep(); 
  };

  holder.querySelector('#md_save').onclick = async ()=>{
    const passengers = Number(holder.querySelector('#md_pax').value || '1');
    const newPhone = (holder.querySelector('#md_phone').value || '').trim();
    const newEmail = (holder.querySelector('#md_email').value || '').trim();

    if(!phoneRegex.test(newPhone)){ 
      showErrorCard(t('errPhone')); 
      return; 
    }
    if(!emailRegex.test(newEmail)){ 
      showErrorCard(t('errEmail')); 
      return; 
    }

    try{
      showVerifyLoading(true);
      // 關閉編輯面板避免重複送出
      holder.style.display='none';

      const payload = {
        booking_id: bookingId,
        direction: mdDirection,
        date: mdDate,
        time: mdTime,
        passengers,
        pickLocation: mdDirection === '回程' ? mdStation : '福泰大飯店 Forte Hotel',
        dropLocation: mdDirection === '回程' ? '福泰大飯店 Forte Hotel' : mdStation,
        phone: newPhone,
        email: newEmail,
        station: mdStation
      };

      const r = await fetch(OPS_URL, {
        method:'POST',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({action:'modify', data: payload})
      });

      let j = null;
      try {
        j = await r.json();
      } catch (e) {
        j = null;
      }

      const backendMsg = j && (j.error || j.code || j.detail || j.message || '');
      const isCapacityError =
        r.status === 409 ||
        backendMsg === 'capacity_not_found' ||
        String(backendMsg || '').includes('capacity_not_found');

      // HTTP 錯誤
      if (!r.ok) {
        if (isCapacityError) {
          showErrorCard(t('overPaxOrMissing'));
        } else {
          showErrorCard(t('updateFailedPrefix') + `HTTP ${r.status}`);
        }
        holder.style.display='block';
        return;
      }

      // 回傳內容錯誤
      if (!j || j.status !== 'success') {
        if (isCapacityError) {
          showErrorCard(t('overPaxOrMissing'));
        } else {
          showErrorCard(
            (j && (j.detail || j.message)) || t('errorGeneric')
          );
        }
        holder.style.display='block';
        return;
      }

      // ✅ 修改成功：先重新查詢 + 顯示車票，再播成功動畫
      const qId    = document.getElementById('qBookId').value.trim();
      const qPhone = document.getElementById('qPhone').value.trim();
      const qEmail = document.getElementById('qEmail').value.trim();

      // 重新查詢目前條件
      const queryRes = await fetch(OPS_URL, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'query', data: { booking_id: qId, phone: qPhone, email: qEmail } })
      });
      const queryData = await queryRes.json();
      lastQueryResults = Array.isArray(queryData) ? queryData : (queryData.results || []);

      // 這筆訂單修改後的日期就是 mdDate，比較直覺就直接打開那一天
      currentQueryDate = mdDate;
      buildDateListFromResults(lastQueryResults);
      openTicketsForDate(mdDate);   // 直接顯示該日期所有票卡（含剛改好的那張）

      // 此時畫面上已經可以看到新票 → 播「成功」動畫
      showSuccessAnimation();


    }catch(e){
      showErrorCard(t('updateFailedPrefix') + (e?.message || ''));
      holder.style.display='block';
    }finally{
      showVerifyLoading(false);
    }
  };

  buildDateOptions();
  window.scrollTo({top:0,behavior:'smooth'});
}

/* ====== 系統與資料 ====== */
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
async function refreshData(){
  showLoading(true);
  try{
    const res = await fetch(API_URL);
    const raw = await res.json();
    const headers = raw[0];
    const rows = raw.slice(1);
    allRows = rows.map(r=>{const o={}; headers.forEach((h,i)=>o[h]=r[i]); return o;})
                  .filter(r=>r["去程 / 回程"]&&r["日期"]&&r["班次"]&&r["站點"]);
    return true;
  }catch(e){
    showErrorCard(t('refreshFailedPrefix') + (e?.message || ''));
    return false;
  }finally{
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
  const resultsEl = document.getElementById('scheduleResults');
  resultsEl.innerHTML = `<div class="loading-text">${t('loading')}</div>`;
  try {
    const res = await fetch(API_URL + '?sheet=可預約班次(web)');
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const data = await res.json();
    const headers = data[0];
    const rows = data.slice(1);
    const directionIndex = headers.indexOf('去程 / 回程');
    const dateIndex = headers.indexOf('日期');
    const timeIndex = headers.indexOf('班次');
    const stationIndex = headers.indexOf('站點');
    const capacityIndex = headers.indexOf('可預約人數');
    scheduleData.rows = rows.map(row => ({
      direction: String(row[directionIndex] || '').trim(),
      date: String(row[dateIndex] || '').trim(),
      time: String(row[timeIndex] || '').trim(),
      station: String(row[stationIndex] || '').trim(),
      capacity: String(row[capacityIndex] || '').trim()
    })).filter(row => row.direction && row.date && row.time && row.station);

    scheduleData.directions = new Set(scheduleData.rows.map(r => r.direction));
    scheduleData.dates = new Set(scheduleData.rows.map(r => r.date));
    scheduleData.stations = new Set(scheduleData.rows.map(r => r.station));
    renderScheduleFilters();
    renderScheduleResults();
  } catch (error) {
    resultsEl.innerHTML = `<div class="empty-state">${t('queryFailedPrefix')}${sanitize(error.message)}</div>`;
  }
}
function renderScheduleFilters() {
  // 單一 ALL 清除鈕
  const allWrap = document.getElementById('allFilter');
  allWrap.innerHTML = '';
  const allBtn = document.createElement('button');
  allBtn.type='button'; allBtn.className='filter-pill';
  allBtn.textContent = t('all');
  allBtn.onclick = () => {
    scheduleData.selectedDirection = null;
    scheduleData.selectedDate = null;
    scheduleData.selectedStation = null;
    renderScheduleFilters();
    renderScheduleResults();
  };
  allWrap.appendChild(allBtn);

  renderFilterPills('directionFilter', [...scheduleData.directions], scheduleData.selectedDirection, (dir) => {
    scheduleData.selectedDirection = scheduleData.selectedDirection === dir ? null : dir;
    renderScheduleFilters();
    renderScheduleResults();
  });
  renderFilterPills('dateFilter', [...scheduleData.dates], scheduleData.selectedDate, (date) => {
    scheduleData.selectedDate = scheduleData.selectedDate === date ? null : date;
    renderScheduleFilters();
    renderScheduleResults();
  });
  renderFilterPills('stationFilter', [...scheduleData.stations], scheduleData.selectedStation, (station) => {
    scheduleData.selectedStation = scheduleData.selectedStation === station ? null : station;
    renderScheduleFilters();
    renderScheduleResults();
  });
}
function renderFilterPills(containerId, items, selectedItem, onClick) {
  const container = document.getElementById(containerId);
  container.innerHTML = '';
  items.sort().forEach(item => {
    const value = String(item).trim();
    const pill = document.createElement('button');
    pill.type = 'button';
    pill.className = 'filter-pill' + (selectedItem === item ? ' active' : '');

    if (containerId === 'directionFilter') {
      if (value === '去程') {
        pill.textContent = t('dirOutLabel');
      } else if (value === '回程') {
        pill.textContent = t('dirInLabel');
      } else {
        pill.textContent = value;
      }
    } else {
      pill.textContent = value;
    }

    pill.onclick = () => onClick(item);
    container.appendChild(pill);
  });
}



function renderScheduleResults() {
  const container = document.getElementById('scheduleResults');
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
  container.innerHTML = filtered.map(row => `
    <div class="schedule-card">
      <div class="schedule-line">
        <span class="schedule-direction">${sanitize(row.direction)}</span>
        <span class="schedule-date">${sanitize(row.date)}</span>
        <span class="schedule-time">${sanitize(row.time)}</span>
      </div>
      <div class="schedule-line">
        <span class="schedule-station">${sanitize(row.station)}</span>
        <span class="schedule-capacity">${sanitize(row.capacity)}</span>
      </div>
    </div>
  `).join('');
}

/* ====== 系統設定載入（跑馬燈 + 圖片牆） ====== */
// 修改 loadSystemConfig 函數
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
      const text = row[3] || "";   // D 欄
      const flag = row[4] || "";   // E 欄

      if (/^(是|Y|1|TRUE)$/i.test(String(flag).trim()) && String(text).trim()) {
        marqueeText += String(text).trim() + "　　";
      }
    }

    // 保存跑馬燈數據
    marqueeData.text = marqueeText.trim();
    marqueeData.isLoaded = true;

    // 立即顯示跑馬燈（呼叫全域版本）
    showMarquee();

    // ========= 圖片牆處理 =========
    const gallery = document.getElementById("imageGallery");
    if (gallery) {
      gallery.innerHTML = "";
      for (let i = 7; i <= 11; i++) {
        const row = data[i] || [];
        const imgUrl = row[3] || "";
        const flag = row[4] || "";
        if (/^(是|Y|1|TRUE)$/i.test(String(flag).trim()) && String(imgUrl).trim()) {
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
function parseTripDateTime(dateStr, timeStr){
  const iso = fmtDateLabel(dateStr);
  let y, m, d;
  if (/^\d{4}-\d{2}-\d{2}$/.test(iso)) {
    const parts = iso.split('-').map(n => parseInt(n, 10));
    y = parts[0]; m = parts[1]; d = parts[2];
  } else {
    const now = new Date();
    y = now.getFullYear(); m = now.getMonth() + 1; d = now.getDate();
  }
  let H = 0, M = 0;
  if (timeStr) {
    const t = String(timeStr).trim().replace('：', ':');
    if (/^\d{1,2}\/\d{1,2}/.test(t)) {
      const [, hmPart] = t.split(' ');
      const hm = (hmPart || '00:00').slice(0, 5);
      const hhmm = hm.split(':');
      H = parseInt(hhmm[0] || '0', 10);
      M = parseInt(hhmm[1] || '0', 10);
    } else if (/^\d{1,2}:\d{1,2}/.test(t)) {
      const hm = t.slice(0, 5);
      const hhmm = hm.split(':');
      H = parseInt(hhmm[0] || '0', 10);
      M = parseInt(hhmm[1] || '0', 10);
    }
  }
  return new Date(y, m - 1, d, H, M, 0);
}

/* ====== 初始化 ====== */
function resetQuery(){ document.getElementById('qBookId').value=''; document.getElementById('qPhone').value=''; document.getElementById('qEmail').value=''; }
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.actions').forEach(a => {
    const btns = a.querySelectorAll('button');
    if (btns.length === 3) a.classList.add('has-three');
  });
  document.querySelectorAll('.ticket-actions').forEach(a => {
    const btns = a.querySelectorAll('button');
    if (btns.length === 3) a.classList.add('has-three');
  });
  // 預設折疊站點區塊
  ['stopHotel','stopMRT','stopTrain','stopLala'].forEach(id => {
    const el = document.getElementById(id);
    if (el) el.classList.remove('open');
  });
  init();
});
window.addEventListener('scroll', handleScroll, {passive:true});
window.addEventListener('resize', handleScroll, {passive:true});

// === 功能開關（快速開關） ===
const FEATURE_TOGGLE = {
  LIVE_LOCATION: true,
};

// === 即時位置渲染 ===
function renderLiveLocationPlaceholder() {
  const sec = document.querySelector('[data-feature="liveLocation"]');
  if (!sec) return;

  sec.style.display = FEATURE_TOGGLE.LIVE_LOCATION ? '' : 'none';

  const mount = document.getElementById('realtimeMount');
  if (!mount) return;

  if (FEATURE_TOGGLE.LIVE_LOCATION) {
    mount.innerHTML =
      '<iframe src="/realtime.html" width="100%" height="420" style="border:0;border-radius:12px" loading="lazy" referrerpolicy="no-referrer"></iframe>';
  } else {
    mount.innerHTML = '';
  }
}

async function init() {
  const tday = todayISO();
  const ci = document.getElementById('checkInDate');
  const co = document.getElementById('checkOutDate');
  const dining = document.getElementById('diningDate');
  if(ci) ci.value = tday;
  if(co) co.value = tday;
  if(dining) dining.value = tday;
  hardResetOverlays();
  showPage('reservation');
  applyI18N();
  handleScroll();
  await loadSystemConfig();
  renderLiveLocationPlaceholder();
}


