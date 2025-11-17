/* ====== 多語文本與工具 ====== */
window.TEXTS = {
  zh: {
    title:"飯店服務-免費接駁車預約", brand:"飯店服務",
    navReservation:"立即預約", navCheck:"我的預約", navSchedule:"查詢班次", navStation:"停靠站點",
    heroTitle:"免費接駁", bookNow:"立即預約",
    step1Title:"選擇方向", step2Title:"選擇日期", step3Title:"選擇站點", step4Title:"選擇班次", step5Title:"旅客資料填寫", step6Title:"確認班次資訊",
    labelDirection:"請選擇方向", directionHint:"去程固定由飯店出發，回程終點為飯店",
    labelDate:"請選擇日期", labelFixedStation:"固定站點", labelStation:"請選擇站點",
    labelSchedule:"請選擇班次", scheduleHint:"點選班次以繼續", labelScheduleOnly:"班次",
    labelIdentity:"請選擇您的身分", idHotel:"住宿貴賓", idDining:"用餐貴賓",
    labelCheckIn:"入住日期", labelCheckOut:"退房日期", labelDiningDate:"用餐日期", labelRoom:"房號",
    labelName:"貴賓姓名", labelPhone:"手機", labelEmail:"信箱", labelPick:"上車站點", labelDrop:"下車站點",
    labelPassengers:"預約人數（請選擇）", labelPassengersShort:"人數",
    errIdentity:"請選擇您的身分", errRoom:"請填寫正確的房號", roomHint:"尚未 CHECK IN 請輸入0000",
    errName:"請填寫姓名", errPhone:"請輸入正確的手機號碼", errEmail:"請填寫正確的郵箱", errPassengers:"請選擇正確的人數（不可超過可預約人數或4人）",
    back:"返回", requery:"重新查詢", next:"下一步", submit:"提交預約",
    ticketTitle:"接駁車票", labelBookingId:"預約編號", labelScheduleDate:"班次",
    loading:"資料讀取中…", verifying:"資料確認中…",
    expiredTitle:"班次已過期或目前不可預約", expiredText:"請重新查詢可預約班次",
    successText:"已完成",
    queryTitle:"查詢訂單(已預約/取消/修改)",
    queryBookingId:"預約編號", queryPhone:"預約電話", queryEmail:"預約信箱", queryBtn:"查詢", clearBtn:"清除", queryHint:"*請擇一輸入",
    selectDateTitle:"選擇日期", backToQuery:"返回查詢",
    notice1:"※ 須於發車前一小時完成【預約／刪改】，座位有限，約滿為止。",
    notice2:"※ 房客、用餐客人可享免費預約搭乘。",
    download:"下載車票",
    rejectedTip:"如有疑問請聯繫櫃檯",
    scheduleTitle:"查詢可預約班次",
    noSchedules:"沒有符合條件的班次",
    dirOutLabel:"去程（飯店出發）",
    dirInLabel:"回程（前往飯店）",
    all:"全部",

    /* 停靠站點：內容（依語系切換） */
    stopsInfoText:
      "※房客、用餐客人可享免費預約接駁，非房客或用餐客人預約接駁須收費每位NT$200/單趟，每趟次可搭乘19名旅客，座位有限，約滿為止。<br/>" +
      "※本飯店保有彈性調整發車時段，發車與否及車輛型式之權利。<br/>" +
      "車種介紹：依預約人數安排白色20人中巴(車牌PAB-311)或鐵灰色福斯九人座(車牌BLD-0361)",

    stopMRTDesc:
      "捷運南港展覽館 3 號出口 - 汽機車臨停接送區。<br/>" +
      "停靠時間：08:35 / 10:05 / 12:05 / 14:35 / 17:05 / 18:35 / 21:05",

    stopTrainDesc:
      "南港火車站靠興中路一側上下客點（南港車站東側臨停接送區）。<br/>" +
      "停靠時間：08:40 / 10:10 / 12:10 / 14:40 / 17:10 / 18:40 / 21:10",

    stopLalaDesc:
      "南港展覽館1號出口大客車臨停區 / 小客車臨停區（視車種有不同停靠區）。<br/>" +
      "停靠時間：12:15 / 14:45 / 17:20 / 18:50 / 21:15",
  },
  en: {
    title:"Hotel Service - Free Shuttle Booking", brand:"Hotel Service",
    navReservation:"Book Now", navCheck:"My Bookings", navSchedule:"Find Schedules", navStation:"Stops",
    heroTitle:"Free Shuttle", bookNow:"Book Now",
    step1Title:"Select Direction", step2Title:"Select Date", step3Title:"Select Stop", step4Title:"Select Time", step5Title:"Passenger Details", step6Title:"Confirm Trip",
    labelDirection:"Select direction", directionHint:"Outbound departs hotel. Inbound ends at hotel.",
    labelDate:"Select date", labelFixedStation:"Fixed Stop", labelStation:"Select stop",
    labelSchedule:"Select time", scheduleHint:"Tap a time to continue", labelScheduleOnly:"Time",
    labelIdentity:"Your identity", idHotel:"Hotel guest", idDining:"Dining guest",
    labelCheckIn:"Check-in date", labelCheckOut:"Check-out date", labelDiningDate:"Dining date", labelRoom:"Room",
    labelName:"Name", labelPhone:"Phone", labelEmail:"Email", labelPick:"Pickup", labelDrop:"Dropoff",
    labelPassengers:"Passengers (choose)", labelPassengersShort:"Pax",
    errIdentity:"Please choose identity", errRoom:"Invalid room", roomHint:"Not checked-in yet? Enter 0000",
    errName:"Name required", errPhone:"Invalid phone", errEmail:"Invalid email", errPassengers:"Invalid passengers (max 4, must be available)",
    back:"Back", requery:"Re-query", next:"Next", submit:"Submit",
    ticketTitle:"Shuttle Ticket", labelBookingId:"Booking ID", labelScheduleDate:"Schedule",
    loading:"Loading…", verifying:"Verifying…",
    expiredTitle:"Trip expired or unavailable", expiredText:"Please re-query available trips",
    successText:"Completed",
    queryTitle:"Find Orders (Booked/Cancelled/Modify)",
    queryBookingId:"Booking ID", queryPhone:"Phone", queryEmail:"Email", queryBtn:"Search", clearBtn:"Clear", queryHint:"*Enter any one",
    selectDateTitle:"Select a date", backToQuery:"Back to search",
    notice1:"※ Please book/modify/cancel at least 1 hour before departure. Seats are limited.",
    notice2:"※ Hotel and dining guests ride free with reservation.",
    download:"Download Ticket",
    rejectedTip:"If you have questions please contact the front desk.",
    scheduleTitle:"Find Available Schedules",
    noSchedules:"No matching schedules",
    dirOutLabel:"Outbound (from hotel)",
    dirInLabel:"Inbound (to hotel)",
    all:"ALL",

    /* Stops */
    stopsInfoText:
      "※ Hotel and dining guests may ride for free with reservation; non-guests are charged NT$200 per person per one-way. Up to 19 passengers per trip; limited seats, first-come-first-served.<br/>" +
      "※ The hotel reserves the right to flexibly adjust departure times, operate trips, and vehicle type.<br/>" +
      "Vehicle types: depending on reservations, we arrange a 20-seat white minibus (PAB-311) or a 9-seat grey Volkswagen (BLD-0361).",

    stopMRTDesc:
      "MRT Nangang Exhibition Center Exit 3 – temporary pick-up/drop-off area for cars and motorcycles.<br/>" +
      "Stop times: 08:35 / 10:05 / 12:05 / 14:35 / 17:05 / 18:35 / 21:05",

    stopTrainDesc:
      "Nangang Train Station, pick-up/drop-off area on Xingzhong Road side (east-side temporary loading area).<br/>" +
      "Stop times: 08:40 / 10:10 / 12:10 / 14:40 / 17:10 / 18:40 / 21:10",

    stopLalaDesc:
      "Nangang Exhibition Center Exit 1 – coach temporary bay / passenger car bay (different zones depending on vehicle type).<br/>" +
      "Stop times: 12:15 / 14:45 / 17:20 / 18:50 / 21:15",
  },
  ja: {
    title:"ホテルサービス-無料シャトル予約", brand:"ホテルサービス",
    navReservation:"今すぐ予約", navCheck:"予約の確認", navSchedule:"便查询", navStation:"停留所",
    heroTitle:"無料シャトル", bookNow:"今すぐ予約",
    step1Title:"方向を選択", step2Title:"日付を選択", step3Title:"停留所を選択", step4Title:"便を選択", step5Title:"お客様情報", step6Title:"便情報の確認",
    labelDirection:"方向を選択", directionHint:"往路はホテル発。復路はホテル行き。",
    labelDate:"日付を選択", labelFixedStation:"固定停留所", labelStation:"停留所を選択",
    labelSchedule:"便を選択", scheduleHint:"便をタップして続行", labelScheduleOnly:"便",
    labelIdentity:"区分を選択", idHotel:"宿泊客", idDining:"レストラン客",
    labelCheckIn:"チェックイン日", labelCheckOut:"チェックアウト日", labelDiningDate:"食事日", labelRoom:"部屋番号",
    labelName:"氏名", labelPhone:"電話", labelEmail:"メール", labelPick:"乗車場所", labelDrop:"降車場所",
    labelPassengers:"人数（選択）", labelPassengersShort:"人数",
    errIdentity:"区分を選択してください", errRoom:"部屋番号が正しくありません", roomHint:"未チェックインの方は 0000",
    errName:"氏名を入力してください", errPhone:"電話番号が正しくありません", errEmail:"メールが正しくありません", errPassengers:"人数が不正です（最大4、空席数以内）",
    back:"戻る", requery:"再検索", next:"次へ", submit:"送信",
    ticketTitle:"シャトル乗車券", labelBookingId:"予約番号", labelScheduleDate:"便",
    loading:"読み込み中…", verifying:"確認中…",
    expiredTitle:"便は期限切れまたは予約不可", expiredText:"予約可能な便を再検索してください",
    successText:"完了",
    queryTitle:"注文検索（予約済/取消/変更）",
    queryBookingId:"予約番号", queryPhone:"電話", queryEmail:"メール", queryBtn:"検索", clearBtn:"クリア", queryHint:"※ いずれか一つを入力",
    selectDateTitle:"日付を選択", backToQuery:"検索に戻る",
    notice1:"※ 出発1時間前までに予約／変更／取消を行ってください。席数に限りがあります。",
    notice2:"※ 宿泊客・レストラン客は無料で予約できます。",
    download:"乗車券をダウンロード",
    rejectedTip:"不明点はフロントにお問い合わせください。",
    scheduleTitle:"予約可能な便查询",
    noSchedules:"条件に合う便がありません",
    dirOutLabel:"往路（ホテル発）",
    dirInLabel:"復路（ホテル行き）",
    all:"すべて",

    /* Stops */
    stopsInfoText:
      "※ 宿泊客およびレストラン利用客は予約により無料でご乗車いただけます。該当しない場合はお一人様片道 NT$200 を頂戴します。1 便あたり最大 19 名、席数限定、先着順です。<br/>" +
      "※ 当ホテルは発車時刻の柔軟な調整、運行の有無、車両タイプの決定権を有します。<br/>" +
      "車種のご案内：予約人数に応じて、白い 20 人乗りミニバス（PAB-311）または鉄灰色の 9 人乗りフォルクスワーゲン（BLD-0361）を手配します。",

    stopMRTDesc:
      "MRT 南港展覧館駅 3 番出口・車両臨時乗降エリア。<br/>" +
      "停車時刻：08:35 / 10:05 / 12:05 / 14:35 / 17:05 / 18:35 / 21:05",

    stopTrainDesc:
      "南港駅・興中路側の乗降ポイント（駅東側の臨時送迎エリア）。<br/>" +
      "停車時刻：08:40 / 10:10 / 12:10 / 14:40 / 17:10 / 18:40 / 21:10",

    stopLalaDesc:
      "南港展覧館 1 番出口・大型バス臨時乗降エリア／小型車臨時乗降エリア（車種により異なる区画）。<br/>" +
      "停車時刻：12:15 / 14:45 / 17:20 / 18:50 / 21:15",
  },
  ko: {
    title:"호텔 서비스-무료 셔틀 예약", brand:"호텔 서비스",
    navReservation:"바로 예약", navCheck:"내 예약", navSchedule:"일정 조회", navStation:"정차역",
    heroTitle:"무료 셔틀", bookNow:"바로 예약",
    step1Title:"방향 선택", step2Title:"날짜 선택", step3Title:"정차역 선택", step4Title:"시간 선택", step5Title:"탑승자 정보", step6Title:"정보 확인",
    labelDirection:"방향을 선택", directionHint:"가는편은 호텔 출발, 오는편은 호텔 도착.",
    labelDate:"날짜 선택", labelFixedStation:"고정 정차역", labelStation:"정차역 선택",
    labelSchedule:"시간 선택", scheduleHint:"시간을 눌러 진행", labelScheduleOnly:"시간",
    labelIdentity:"구분 선택", idHotel:"숙박객", idDining:"식사객",
    labelCheckIn:"체크인", labelCheckOut:"체크아웃", labelDiningDate:"식사일", labelRoom:"객실",
    labelName:"이름", labelPhone:"전화", labelEmail:"이메일", labelPick:"승차", labelDrop:"하차",
    labelPassengers:"인원수(선택)", labelPassengersShort:"인원",
    errIdentity:"구분을 선택하세요", errRoom:"객실번호가 올바르지 않습니다", roomHint:"체크인 전이면 0000",
    errName:"이름을 입력하세요", errPhone:"전화번호가 올바르지 않습니다", errEmail:"이메일이 올바르지 않습니다", errPassengers:"인원수가 올바르지 않습니다(최대 4, 잔여석 이내)",
    back:"뒤로", requery:"재검색", next:"다음", submit:"제출",
    ticketTitle:"셔틀 승차권", labelBookingId:"예약번호", labelScheduleDate:"편",
    loading:"로드 중…", verifying:"확인 중…",
    expiredTitle:"편이 만료되었거나 예약 불가", expiredText:"예약 가능한 편을 재검색하세요",
    successText:"완료",
    queryTitle:"주문 조회(예약/취소/수정)",
    queryBookingId:"예약번호", queryPhone:"전화", queryEmail:"이메일", queryBtn:"조회", clearBtn:"초기화", queryHint:"*하나 이상 입력",
    selectDateTitle:"날짜 선택", backToQuery:"조회로 돌아가기",
    notice1:"※ 출발 1시간 전까지 예약·변경·취소해 주세요. 좌석 한정.",
    notice2:"※ 숙박객 및 식사객은 예약 시 무료 탑승.",
    download:"티켓 다운로드",
    rejectedTip:"문의 사항은 프런트에 연락하세요.",
    scheduleTitle:"예약 가능한 일정 조회",
    noSchedules:"조건에 맞는 일정이 없습니다",
    dirOutLabel:"가는편(호텔 출발)",
    dirInLabel:"오는편(호텔 도착)",
    all:"전체",

    /* Stops */
    stopsInfoText:
      "※ 숙박객·식사객은 예약 시 무료로 이용할 수 있으며, 그 외 고객은 1인당 편도 NT$200가 부과됩니다. 한 회차 최대 19명 탑승, 좌석 한정 선착순입니다.<br/>" +
      "※ 호텔은 운행 시간, 운행 여부 및 차량 종류를 유연하게 조정할 권리를 보유합니다.<br/>" +
      "차량 안내: 예약 인원에 따라 20인승 흰색 미니버스(PAB-311) 또는 9인승 회색 폭스바겐(BLD-0361)을 배차합니다.",

    stopMRTDesc:
      "MRT 난강(南港) 전람관 3번 출구 차량 임시 승하차 구역.<br/>" +
      "정차 시각: 08:35 / 10:05 / 12:05 / 14:35 / 17:05 / 18:35 / 21:05",

    stopTrainDesc:
      "난강역 흥중로(興中路) 측 승하차 지점(역 동측 임시 승하차 구역).<br/>" +
      "정차 시각: 08:40 / 10:10 / 12:10 / 14:40 / 17:10 / 18:40 / 21:10",

    stopLalaDesc:
      "난강 전람관 1번 출구 대형버스 임시 정차 구역 / 소형차 임시 정차 구역(차종에 따라 상이).<br/>" +
      "정차 시각: 12:15 / 14:45 / 17:20 / 18:50 / 21:15",
  }
};

window.I18N_STATUS = {
  zh: { booked:"✔️ 已預約", cancelled:"❌ 已取消", rejected:"已拒絕", boarded:"已上車", expired:"已過期", download:"下載車票", modify:"修改", remove:"刪除", noRecords:"查無符合條件的紀錄（僅顯示近一個月）", includeSelf:"（含本人）" },
  en: { booked:"✔️ Booked", cancelled:"❌ Cancelled", rejected:"Rejected", boarded:"Boarded", expired:"Expired", download:"Download ticket", modify:"Edit", remove:"Delete", noRecords:"No matching records (last 30 days only)", includeSelf:" (incl. you)" },
  ja: { booked:"✔️ 予約済み", cancelled:"❌ キャンセル", rejected:"拒否", boarded:"乗車済み", expired:"期限切れ", download:"チケットをダウンロード", modify:"変更", remove:"削除", noRecords:"該当データがありません（直近30日）", includeSelf:"（本人含む）" },
  ko: { booked:"✔️ 예약됨", cancelled:"❌ 취소됨", rejected:"거절됨", boarded:"탑승완료", expired:"만료", download:"티켓 다운로드", modify:"수정", remove:"삭제", noRecords:"일치하는 기록 없음 (최근 30일)", includeSelf:"(본인 포함)" }
};

window.currentLang = "zh";
window.t = function t(key){ return (window.TEXTS[window.currentLang]||window.TEXTS.zh)[key] || key; }
window.ts = function ts(key){ return (window.I18N_STATUS[window.currentLang]||window.I18N_STATUS.zh)[key] || key; }

window.applyI18N = function applyI18N(){
  document.title = t('title');
  document.querySelectorAll('[data-i18n]').forEach(el=>{
    const k = el.getAttribute('data-i18n');
    const v = t(k);
    if(v!=null) {
      // 允許多行段落（含 <br/>），這裡用 innerHTML
      if (v.includes('<br/>')) el.innerHTML = v;
      else el.textContent = v;
    }
  });
  const pill = document.getElementById('successStatusPill');
  if(pill) pill.textContent = ts('booked');
}

window.onLanguageChange = function onLanguageChange(lang){
  window.currentLang = lang || "zh";
  applyI18N();
  // 以下兩個函式在 app.js 中，若尚未載入則略過
  if (typeof window.rerenderQueryPages === 'function') window.rerenderQueryPages();
  if (document.getElementById('step1') && document.getElementById('step1').style.display !== 'none') {
    if (typeof window.buildStep1 === 'function') window.buildStep1();
  }
}
