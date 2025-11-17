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

// 查詢分頁狀態
let queryDateList = [];
let currentQueryDate = "";
let currentDateRows = [];

/* ====== 事件/工具 ====== */
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
  handleScroll();
}
function showLoading(s=true){document.getElementById('loading').classList.toggle('show',s)}
function showVerifyLoading(s=true){document.getElementById('loadingConfirm').classList.toggle('show',s)}
function showExpiredOverlay(s=true){document.getElementById('expiredOverlay').classList.toggle('show',s)}
function overlayRestart(){ showExpiredOverlay(false); restart(); }
function shake(el){ if(!el) return; el.classList.add('shake'); setTimeout(()=>el.classList.remove('shake'),500); }
function closeMarquee() {
  const marqueeContainer = document.getElementById('marqueeContainer');
  marqueeContainer.style.display = 'none';
  localStorage.setItem('marqueeClosed','1');
}
function toggleCollapse(id){
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.toggle('open');
}

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
  if(!selectedDirection){ alert(t('labelDirection')); return; }
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
  if(!selectedDateRaw){ alert(t('labelDate')); return; }
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
  if(!selectedStationRaw){ alert(t('labelStation')); return; }
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
  if(!selectedScheduleTime){ alert(t('labelSchedule')); return; }
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
    if(!cin||!cout){ alert(t('labelCheckIn')+'/'+t('labelCheckOut')); shake(document.getElementById('checkInDate')); shake(document.getElementById('checkOutDate')); return false; }
    const room=(document.getElementById('roomNumber').value||'').trim();
    if(!roomRegex.test(room)){document.getElementById('roomErr').style.display='block'; shake(document.getElementById('roomNumber')); return false}else document.getElementById('roomErr').style.display='none';
  }else{
    const din=document.getElementById('diningDate').value;
    if(!din){ alert(t('labelDiningDate')); shake(document.getElementById('diningDate')); return false; }
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
  document.getElementById('passengersHint').textContent =
    `此班次可預約：${selectedAvailableSeats} 人；單筆最多 4 人`;
  ['step1','step2','step3','step4','step5'].forEach(id=>{ const el = document.getElementById(id); if (el) el.style.display = 'none'; });
  document.getElementById('step6').style.display = '';
  window.scrollTo({ top: 0, behavior: 'smooth' });
  const errEl = document.getElementById('passengersErr'); if (errEl) errEl.style.display = 'none';
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
  const pSel = document.getElementById('passengers');
  const p = Number(pSel?.value || 0);
  if (!p || p < 1 || p > 4) {
    const errEl = document.getElementById('passengersErr');
    if (errEl) errEl.style.display = 'block';
    return;
  }
  const errEl = document.getElementById('passengersErr'); if (errEl) errEl.style.display = 'none';

  // 依你要求：不再重拉資料；完全交由後端檢查
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
  // 送出前先關閉 Step6，避免誤觸
  document.getElementById('step6').style.display='none';
  showVerifyLoading(true);

  try {
    const res = await fetch(OPS_URL, {
      method: 'POST',
      mode: 'cors',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ action: 'book', data: payload }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const result = await res.json();

    if (result.status === 'success') {
      const qrPath = result.qr_content ? (`${QR_ORIGIN}/api/qr/${encodeURIComponent(result.qr_content)}`) : (result.qr_url || '');
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

      // 先顯示車票，再播成功動畫
      mountTicketAndShow(currentBookingData);

      // 背景寄信（4s 超時，不阻塞）
      try {
        const controller = new AbortController();
        const timer = setTimeout(() => controller.abort(), 4000);
        const dataUrl = await domtoimage.toPng(document.getElementById('ticketCard'), { bgcolor: '#fff', pixelRatio: 2 });
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
      } catch (e) { console.warn('寄信未完成或超時', e); }

    } else {
      alert(result.detail || result.message || '預約失敗，請稍後再試');
      // 回到 Step6 讓使用者修正
      document.getElementById('step6').style.display='';
    }
  } catch (e) {
    console.error('submitBooking error', e);
    alert('提交失敗：' + (e?.message || e));
    document.getElementById('step6').style.display='';
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
  document.getElementById('ticketPassengers').textContent = ticket.passengers + ' 人';
  const card = document.getElementById('successCard');
  if (card) card.style.display = '';
  window.scrollTo({ top: 0, behavior: 'smooth' });
  // 顯示成功動畫
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
  if (!card) { alert('找不到票卡'); return; }
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
  } catch (e) { alert('下載失敗：' + (e?.message || e)); }
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
  let dateIso = getDateFromCarDateTime(carDateTime);
  let time = getTimeFromCarDateTime(carDateTime);
  const expired = isExpiredByCarDateTime(carDateTime);
  const statusCode = getStatusCode(row);
  const name = mask ? maskName(String(row["姓名"]||'')) : String(row["姓名"]||'');
  const phone = mask ? maskPhone(String(row["手機"]||'')) : String(row["手機"]||'');
  const email = mask ? maskEmail(String(row["信箱"]||'')) : String(row["信箱"]||'');
  const rb = String(row["往返"]||row["往返方向"]||'');
  const pick = String(row["上車地點"]||'');
  const drop = String(row["下車地點"]||'');
  const bookingId = String(row["預約編號"]||'');
  const pax = Number(row["預約人數"]||'1')||1;
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
    tip.onclick = ()=> alert(t('rejectedTip'));
    card.appendChild(tip);
  }

  const header = document.createElement('div');
  header.className='ticket-header';
  header.innerHTML=`<h2>${carDateTime}</h2>`;
  card.appendChild(header);

  const content = document.createElement('div'); 
  content.className='ticket-content';
  const qr = document.createElement('div'); 
  qr.className='ticket-qr';
  if(statusCode==='cancelled'){
    qr.innerHTML = `<img src="/images/QR placeholder.png" alt="QR placeholder" />`;
  }else{
    qr.innerHTML = `<img src="${qrUrl}" alt="QR" />`;
  }
  const info = document.createElement('div'); 
  info.className='ticket-info';
  info.innerHTML = `
    <div class="ticket-field"><span class="ticket-label">${t('labelBookingId')}</span><span class="ticket-value">${bookingId}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelDirection')}</span><span class="ticket-value">${rb}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelPick')}</span><span class="ticket-value">${pick}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelDrop')}</span><span class="ticket-value">${drop}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelName')}</span><span class="ticket-value">${name}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelPhone')}</span><span class="ticket-value">${phone}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelEmail')}</span><span class="ticket-value">${email}</span></div>
    <div class="ticket-field"><span class="ticket-label">${t('labelPassengersShort')}</span><span class="ticket-value">${pax}</span></div>
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
        a.download=`ticket_${bookingId}.png`; 
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

function getDateFromCarDateTime(carDateTime) {
  if (!carDateTime) return "";
  const parts = carDateTime.split(' ');
  if (parts.length < 1) return "";
  const datePart = parts[0];
  return datePart.replace(/\//g, '-');
}
function getTimeFromCarDateTime(carDateTime) {
  if (!carDateTime) return "00:00";
  const parts = carDateTime.split(' ');
  return parts.length > 1 ? parts[1] : "00:00";
}
function isExpiredByCarDateTime(carDateTime) {
  if (!carDateTime) return true;
  try {
    const [datePart, timePart] = carDateTime.split(' ');
    const [year, month, day] = datePart.split('/').map(Number);
    const [hour, minute] = timePart.split(':').map(Number);
    const tripTime = new Date(year, month - 1, day, hour, minute, 0).getTime();
    return tripTime < Date.now();
  } catch (e) { return true; }
}

/* ====== 查詢 ====== */
async function queryOrders(){
  const id=(document.getElementById('qBookId').value||'').trim();
  const phone=(document.getElementById('qPhone').value||'').trim();
  const email=(document.getElementById('qEmail').value||'').trim();
  const queryHint = document.getElementById('queryHint');
  if(!id && !phone && !email){ shake(queryHint); return; }
  showLoading(true);
  try{
    const res = await fetch(OPS_URL, {method:'POST', mode:'cors', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'query', data:{booking_id:id, phone, email}})});
    const data = await res.json();
    const arr = Array.isArray(data) ? data : (data.results || []);
    lastQueryResults = arr;
    buildDateListFromResults(arr);
    showCheckDateStep();
  }catch(e){ alert('查詢失敗：' + (e?.message || e)); }
  finally{ showLoading(false); }
}
function buildDateListFromResults(rows){
  const dateMap = new Map();
  rows.forEach(r => {
    const carDateTime = String(r["車次-日期時間"] || "");
    let dateIso = getDateFromCarDateTime(carDateTime);
    if (withinOneMonth(dateIso)) { dateMap.set(dateIso, (dateMap.get(dateIso) || 0) + 1); }
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
    let rowDateIso = getDateFromCarDateTime(carDateTime);
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
    const statusOrder = { 'cancelled': 1, 'rejected': 2, 'expired': 3, 'booked': 4, 'boarded': 5 };
    return (statusOrder[statusA] || 6) - (statusOrder[statusB] || 6);
  });
  const mount = document.getElementById('checkTicketMount');
  mount.innerHTML = '';
  currentDateRows.forEach(row => mount.appendChild(buildTicketCard(row, { mask: true })));
  showCheckTicketStep();
}
window.rerenderQueryPages = function rerenderQueryPages(){
  if(document.getElementById('checkDateStep').style.display!=='none'){
    buildDateListFromResults(lastQueryResults);
  }
  if(document.getElementById('checkTicketStep').style.display!=='none'){
    openTicketsForDate(currentQueryDate);
  }
}

/* ====== 刪除 ====== */
async function deleteOrder(bookingId){
  if(!confirm(`刪除預約 ${bookingId} ？`)) return;
  // 送出後先回到日期頁（避免誤點）
  showCheckDateStep();
  showLoading(true);
  try{
    const r = await fetch(OPS_URL, {
      method: 'POST', mode:'cors',
      headers: {'Content-Type':'application/json'}, 
      body: JSON.stringify({action:'delete', data:{booking_id:bookingId}})
    });
    const j = await r.json();
    if(j.status==='success'){
      showSuccessAnimation();
      // 重新查詢目前的條件
      const id = document.getElementById('qBookId').value.trim();
      const phone = document.getElementById('qPhone').value.trim();
      const email = document.getElementById('qEmail').value.trim();
      try{
        const queryRes = await fetch(OPS_URL, {
          method: 'POST', mode:'cors',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action: 'query', data: { booking_id: id, phone, email } })
        });
        const queryData = await queryRes.json();
        lastQueryResults = Array.isArray(queryData) ? queryData : (queryData.results || []);
        buildDateListFromResults(lastQueryResults);
        if (currentQueryDate) openTicketsForDate(currentQueryDate);
      }catch{}
    } else {
      alert(j.detail || '刪除失敗');
    }
  } catch(e) { 
    alert('刪除失敗：'+(e?.message||e)); 
  } finally { showLoading(false); }
}

/* ====== 修改頁 ====== */
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
    <h2>修改預約 ${bookingId}</h2>
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
    <div class="field"><label class="label">${t('labelPhone')}</label><input id="md_phone" class="input" value="${String(row["手機"]||'')}" /></div>
    <div class="field"><label class="label">${t('labelEmail')}</label><input id="md_email" class="input" value="${String(row["信箱"]||'')}" /></div>
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
    const dateSet = new Set(allRows.filter(r=>String(r["去程 / 回程"]).trim()===mdDirection).map(r=>fmtDateLabel(r["日期"])));
    const sorted=[...dateSet].sort((a,b)=>new Date(a)-new Date(b));
    const list = holder.querySelector('#md_dates'); list.innerHTML='';
    sorted.forEach(dateStr=>{ const btn=document.createElement('button'); btn.type='button'; btn.className='opt-btn'; btn.textContent=dateStr; if(dateStr===mdDate) btn.classList.add('active');
      btn.onclick=()=>{ mdDate=dateStr; list.querySelectorAll('.opt-btn').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); buildStationOptions(); }; list.appendChild(btn); });
  }
  function buildStationOptions(){
    const stations = new Set(allRows.filter(r=>String(r["去程 / 回程"]).trim()===mdDirection && fmtDateLabel(r["日期"])===mdDate).map(r=>String(r["站點"]).trim()));
    const list = holder.querySelector('#md_stations'); list.innerHTML='';
    [...stations].forEach(st=>{ const btn=document.createElement('button'); btn.type='button'; btn.className='opt-btn'; btn.textContent=st; if(st===mdStation) btn.classList.add('active');
      btn.onclick=()=>{ mdStation=st; list.querySelectorAll('.opt-btn').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); buildScheduleOptions(); }; list.appendChild(btn); });
    buildScheduleOptions();
  }
  function buildScheduleOptions(){
    const list=holder.querySelector('#md_schedules'); list.innerHTML='';
    const entries = allRows.filter(r=>String(r["去程 / 回程"]).trim()===mdDirection && fmtDateLabel(r["日期"])===mdDate && String(r["站點"]).trim()===mdStation).sort((a,b)=>fmtTimeLabel(a["班次"]).localeCompare(fmtTimeLabel(b["班次"])));
    entries.forEach(r=>{
      const timeVal=fmtTimeLabel(r["班次"]||r["車次"]);
      const availText=String(r["可預約人數"]||r["可約人數 / Available"]||'').trim();
      const baseAvail=Number(onlyDigits(availText))||0;
      const sameAsOriginal = (rb===mdDirection) && (fmtDateLabel(date)===mdDate) && (mdStation===((rb==='回程')?pick:drop)) && (fmtTimeLabel(time)===timeVal);
      const availPlusSelf = baseAvail + (sameAsOriginal ? pax : 0);
      const btn=document.createElement('button'); btn.type='button'; btn.className='opt-btn'; if(timeVal===mdTime) btn.classList.add('active');
      btn.innerHTML = `<span style="color:var(--primary);font-weight:700">${timeVal}</span> <span style="color:#777;font-size:13px">(可預約：${availPlusSelf} 人${sameAsOriginal ? (I18N_STATUS[currentLang]||I18N_STATUS.zh).includeSelf : ''})</span>`;
      btn.onclick=()=>{ mdTime=timeVal; mdAvail=availPlusSelf; list.querySelectorAll('.opt-btn').forEach(b=>b.classList.remove('active')); btn.classList.add('active'); buildPax(); };
      list.appendChild(btn);
    });
    buildPax();
  }
  function buildPax(){
    const sel=holder.querySelector('#md_pax'); sel.innerHTML='';
    const maxPassengers = Math.min(4, Math.max(0, mdAvail||pax||4));
    for(let i=1;i<=maxPassengers;i++){const opt=document.createElement('option');opt.value=String(i);opt.textContent=String(i);sel.appendChild(opt);} 
    sel.value = String(Math.min(pax, maxPassengers));
    const hint = holder.querySelector('#md_hint'); 
    hint.textContent = `此班次可預約：${mdAvail || 0} 人；單筆最多 4 人`;
  }
  holder.querySelector('#md_dir').addEventListener('change', (e)=>{ mdDirection = e.target.value; mdStation = (mdDirection==='回程') ? pick : drop; buildDateOptions(); });
  holder.querySelector('#md_cancel').onclick = ()=>{ holder.style.display='none'; showCheckDateStep(); };
  holder.querySelector('#md_save').onclick = async ()=>{
    // 送出前關閉修改視圖，避免重複點擊
    holder.style.display='none';
    showVerifyLoading(true);
    const passengers = Number(holder.querySelector('#md_pax').value||'1');
    const newPhone = (holder.querySelector('#md_phone').value||'').trim();
    const newEmail = (holder.querySelector('#md_email').value||'').trim();
    if(!phoneRegex.test(newPhone)){ alert(t('errPhone')); showVerifyLoading(false); holder.style.display='block'; return; }
    if(!emailRegex.test(newEmail)){ alert(t('errEmail')); showVerifyLoading(false); holder.style.display='block'; return; }
    // 不再重拉資料；依後端檢查即可
    const payload = {
      booking_id: bookingId, direction: mdDirection, date: mdDate, time: mdTime, passengers,
      pickLocation: mdDirection==='回程' ? mdStation : '福泰大飯店 Forte Hotel',
      dropLocation: mdDirection==='回程' ? '福泰大飯店 Forte Hotel' : mdStation,
      phone: newPhone, email: newEmail, station: mdStation
    };
    try{
      const r = await fetch(OPS_URL, {method:'POST', mode:'cors', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:'modify', data:payload})});
      const j = await r.json();
      if(j.status==='success'){
        try{
          const temp = document.createElement('div');
          temp.style.position='absolute'; temp.style.left='-99999px'; temp.style.top='-99999px';
          temp.innerHTML = `
            <div class="ticket-card">
              <div class="status-pill status-booked">${ts('booked')}</div>
              <div class="ticket-header"><h2>${t('ticketTitle')}</h2></div>
              <div class="ticket-content">
                <div class="ticket-qr"><img src="${await buildQrUrl(j.booking_id || bookingId, newEmail)}" alt="QR"/></div>
                <div class="ticket-info">
                  <div class="ticket-field"><span class="ticket-label">${t('labelBookingId')}</span><span class="ticket-value">${j.booking_id || bookingId}</span></div>
                  <div class="ticket-field"><span class="ticket-label">${t('labelScheduleDate')}</span><span class="ticket-value">${mdTime}</span></div>
                  <div class="ticket-field"><span class="ticket-label">${t('labelDirection')}</span><span class="ticket-value">${mdDirection}</span></div>
                  <div class="ticket-field"><span class="ticket-label">${t('labelPick')}</span><span class="ticket-value">${payload.pickLocation}</span></div>
                  <div class="ticket-field"><span class="ticket-label">${t('labelDrop')}</span><span class="ticket-value">${payload.dropLocation}</span></div>
                  <div class="ticket-field"><span class="ticket-label">${t('labelName')}</span><span class="ticket-value">${(row['姓名']||'')}</span></div>
                  <div class="ticket-field"><span class="ticket-label">${t('labelPhone')}</span><span class="ticket-value">${newPhone}</span></div>
                  <div class="ticket-field"><span class="ticket-label">${t('labelEmail')}</span><span class="ticket-value">${newEmail}</span></div>
                  <div class="ticket-field"><span class="ticket-label">${t('labelPassengersShort')}</span><span class="ticket-value">${passengers}</span></div>
                </div>
              </div>
            </div>`;
          document.body.appendChild(temp);
          const png = await domtoimage.toPng(temp.querySelector('.ticket-card'), {bgcolor:'#fff', pixelRatio:2});
          document.body.removeChild(temp);
          fetch(OPS_URL, {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({action:'mail', data:{ booking_id: j.booking_id || bookingId, lang: currentLang, kind:'modify', ticket_png_base64: png }})}).catch(()=>{});
        }catch(e){ console.warn('修改寄信失敗', e); }
        // 成功動畫（在日期頁/票卡頁視圖上）
        showSuccessAnimation();
        // 重新查
        const id = document.getElementById('qBookId').value.trim();
        const phone = document.getElementById('qPhone').value.trim();
        const email = document.getElementById('qEmail').value.trim();
        const queryRes = await fetch(OPS_URL, { method: 'POST', mode:'cors', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ action: 'query', data: { booking_id: id, phone, email } })});
        const queryData = await queryRes.json();
        lastQueryResults = Array.isArray(queryData) ? queryData : (queryData.results || []);
        buildDateListFromResults(lastQueryResults);
        if (currentQueryDate) openTicketsForDate(currentQueryDate); else showCheckDateStep();
      } else {
        alert(j.detail || '更新失敗');
        holder.style.display='block';
      }
    }catch(e){ alert('更新失敗：'+(e?.message||e)); holder.style.display='block'; }
    finally{ showVerifyLoading(false); }
  };
  buildDateOptions();
  window.scrollTo({top:0,behavior:'smooth'});
}

/* ====== 工具 ====== */
async function sha256Hex(s){
  const data = new TextEncoder().encode(String(s||''));
  const hash = await crypto.subtle.digest('SHA-256', data);
  const arr = Array.from(new Uint8Array(hash));
  return arr.map(b => b.toString(16).padStart(2, '0')).join('');
}
async function buildQrUrl(bookingId, email){
  const hex = await sha256Hex(String(email||''));
  const em6 = hex.slice(0,6);
  const content = `FT:${bookingId}:${em6}`;
  return `${QR_ORIGIN}/api/qr/${encodeURIComponent(content)}`;
}

/* ====== 資料處理 ====== */
async function refreshData(){
  showLoading(true);
  try{
    const res = await fetch(API_URL, {mode:'cors', cache:'no-store'});
    const raw = await res.json();
    const headers = raw[0];
    const rows = raw.slice(1);
    allRows = rows.map(r=>{const o={}; headers.forEach((h,i)=>o[h]=r[i]); return o;})
                  .filter(r=>r["去程 / 回程"]&&r["日期"]&&r["班次"]&&r["站點"]);
    return true;
  }catch(e){
    alert("資料更新失敗，請稍後再試");
    return false;
  }finally{
    showLoading(false);
  }
}

/* ====== 查詢班次功能（含 ALL 快速重置） ====== */
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
  resultsEl.innerHTML = '<div class="loading-text" data-i18n="loading">'+t('loading')+'</div>';
  try {
    const res = await fetch(API_URL + '?sheet=' + encodeURIComponent('可預約班次(web)'), {mode:'cors', cache:'no-store'});
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
      direction: row[directionIndex] || '',
      date: row[dateIndex] || '',
      time: row[timeIndex] || '',
      station: row[stationIndex] || '',
      capacity: row[capacityIndex] || ''
    })).filter(row => row.direction && row.date && row.time && row.station);
    scheduleData.directions = new Set(scheduleData.rows.map(r => r.direction));
    scheduleData.dates = new Set(scheduleData.rows.map(r => r.date));
    scheduleData.stations = new Set(scheduleData.rows.map(r => r.station));
    renderScheduleFilters();
    renderScheduleResults();
  } catch (error) {
    resultsEl.innerHTML = `<div class="empty-state">查詢失敗: ${error.message}</div>`;
  }
}
function renderScheduleFilters() {
  // 綁定 ALL 快速清空
  const allBtn = document.getElementById('filterAll');
  if (allBtn) {
    allBtn.onclick = () => {
      scheduleData.selectedDirection = null;
      scheduleData.selectedDate = null;
      scheduleData.selectedStation = null;
      renderScheduleFilters();
      renderScheduleResults();
    };
  }
  // Direction: 將 '去程/回程' 顯示為語系文字，但 value 仍使用中文原值
  const dirContainer = document.getElementById('directionFilter');
  dirContainer.innerHTML = '';
  Array.from(scheduleData.directions).sort().forEach(dir => {
    const pill = document.createElement('button');
    pill.type='button'; pill.className='filter-pill' + (scheduleData.selectedDirection===dir ? ' active' : '');
    const label = dir === '去程' ? t('dirOutLabel') : dir === '回程' ? t('dirInLabel') : dir;
    pill.textContent = label;
    pill.onclick = () => { scheduleData.selectedDirection = dir; renderScheduleFilters(); renderScheduleResults(); };
    dirContainer.appendChild(pill);
  });
  // Dates
  const dateContainer = document.getElementById('dateFilter');
  dateContainer.innerHTML = '';
  Array.from(scheduleData.dates).sort((a,b)=>new Date(a)-new Date(b)).forEach(date => {
    const pill = document.createElement('button');
    pill.type='button'; pill.className='filter-pill' + (scheduleData.selectedDate===date ? ' active' : '');
    pill.textContent = date;
    pill.onclick = () => { scheduleData.selectedDate = date; renderScheduleFilters(); renderScheduleResults(); };
    dateContainer.appendChild(pill);
  });
  // Stations
  const stationContainer = document.getElementById('stationFilter');
  stationContainer.innerHTML = '';
  Array.from(scheduleData.stations).sort().forEach(st => {
    const pill = document.createElement('button');
    pill.type='button'; pill.className='filter-pill' + (scheduleData.selectedStation===st ? ' active' : '');
    pill.textContent = st;
    pill.onclick = () => { scheduleData.selectedStation = st; renderScheduleFilters(); renderScheduleResults(); };
    stationContainer.appendChild(pill);
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
    container.innerHTML = `<div class="empty-state" data-i18n="noSchedules">${t('noSchedules')}</div>`;
    return;
  }
  container.innerHTML = filtered.map(row => `
    <div class="schedule-card">
      <div class="schedule-line">
        <span class="schedule-direction">${row.direction === '去程' ? t('dirOutLabel') : t('dirInLabel')}</span>
        <span class="schedule-date">${row.date}</span>
        <span class="schedule-time">${row.time}</span>
      </div>
      <div class="schedule-line">
        <span class="schedule-station">${row.station}</span>
        <span class="schedule-capacity">${row.capacity}</span>
      </div>
    </div>
  `).join('');
}

/* ====== 系統設定（跑馬燈與圖片） ====== */
async function loadSystemConfig() {
  // 兼容不同後端參數名稱：?sheet=系統 / ?ws=系統 / ?name=系統
  async function tryFetch(urls) {
    for (const u of urls) {
      try{
        const r = await fetch(u, {mode:'cors', cache:'no-store'});
        if (r.ok) return await r.json();
      }catch(e){}
    }
    throw new Error('all variants failed');
  }
  try {
    const base = API_URL;
    const data = await tryFetch([
      `${base}?sheet=${encodeURIComponent('系統')}`,
      `${base}?ws=${encodeURIComponent('系統')}`,
      `${base}?name=${encodeURIComponent('系統')}`
    ]);
    const marqueeTexts = [];
    for (let i = 1; i <= 5; i++) {
      const row = data[i] || [];
      const text = row[3] || '';
      const flag = row[4] || '';
      if (String(flag).trim() === '是' && text) marqueeTexts.push(text);
    }
    if (marqueeTexts.length > 0 && !localStorage.getItem('marqueeClosed')) {
      const marqueeContainer = document.getElementById('marqueeContainer');
      const marqueeContent = document.getElementById('marqueeContent');
      marqueeContent.innerHTML = marqueeTexts.join(' | ');
      marqueeContainer.style.display = 'block';
    }
    const galleryImages = [];
    for (let i = 7; i <= 11; i++) {
      const row = data[i] || [];
      const url = row[3] || '';
      const flag = row[4] || '';
      if (String(flag).trim() === '是' && url) galleryImages.push(url);
    }
    if (galleryImages.length > 0) {
      const imageGallery = document.getElementById('imageGallery');
      imageGallery.innerHTML = galleryImages.map(u => `<img src="${u}" class="gallery-image" alt="宣傳圖片" />`).join('');
    }
  } catch (error) {
    console.warn('載入系統設定失敗:', error);
  }
}

/* ====== 其他 ====== */
function hardResetOverlays(){
  ['loading','loadingConfirm','expiredOverlay','successAnimation'].forEach(id=>{
    const el = document.getElementById(id);
    if(!el) return;
    el.classList.remove('show');
    el.style.display = (id==='successAnimation') ? 'none' : el.style.display;
  });
}
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
window.__DISABLE_CLIENT_REFRESH__ = true;

/* ====== 初始化 ====== */
function init() {
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
  loadSystemConfig();
  // 預設將可收合區塊設為收合
  ['blk-mrt','blk-train','blk-lala'].forEach(id=>{
    const el = document.getElementById(id);
    if (el) el.classList.remove('open');
  });
}
function resetQuery(){
  document.getElementById('qBookId').value='';
  document.getElementById('qPhone').value='';
  document.getElementById('qEmail').value='';
}
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.actions').forEach(a => {
    const btns = a.querySelectorAll('button');
    if (btns.length === 3) a.classList.add('has-three');
  });
  document.querySelectorAll('.ticket-actions').forEach(a => {
    const btns = a.querySelectorAll('button');
    if (btns.length === 3) a.classList.add('has-three');
  });
  init();
});
