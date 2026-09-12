function check() { 
/* ================= REFERENCE DATA ================= */
var CUST='SAI BABUJI PROJECTS';
var REM=['Cell crack','Glass scratch','JB defect','Frame damage','Burning mark'];
var INCH=['RAJESH KUMAR','SURESH PATEL','AMIT SHARMA','VIKRAM SINGH','DEEPAK YADAV'];
var CATS=[{c:'A',res:'Passed',q:2791,p:98},{c:'GY',res:'Rejected',q:38,p:68},
          {c:'BGY',res:'Rejected',q:18,p:32}];
var SHIFT_ROWS=[
 {s:'A',w:'620W',m:'ISEN620-G12R',t:412,ok:405,r:7},{s:'A',w:'625W',m:'ISEN625-G12R',t:538,ok:527,r:11},
 {s:'B',w:'620W',m:'ISEN620-G12R',t:361,ok:356,r:5},{s:'B',w:'590W',m:'ISEN590-G2X',t:497,ok:489,r:8},
 {s:'B',w:'600W',m:'ISEN600-G2X',t:208,ok:203,r:5},
 {s:'C',w:'610W',m:'ISEN610-G12R',t:418,ok:406,r:12},{s:'C',w:'590W',m:'ISEN590-G2X',t:413,ok:405,r:8}];
var DAYS=[{d:'19-08-2026',sh:['A','B','C'],t:2847,ok:2791,r:56,kw:1742},
 {d:'18-08-2026',sh:['A','B','C'],t:2914,ok:2860,r:54,kw:1784},
 {d:'17-08-2026',sh:['A','B'],t:1902,ok:1871,r:31,kw:1167},
 {d:'16-08-2026',sh:['A','B','C'],t:2766,ok:2702,r:64,kw:1686}];
var REJ=[{n:'Cell crack',q:19,p:100},{n:'Glass scratch',q:13,p:68},{n:'JB defect',q:9,p:47},
 {n:'Frame damage',q:8,p:42},{n:'Burning mark',q:7,p:36}];

/* Unit-2 model catalogue.
   SEEDED FROM THE BACK LABEL, not from what has been produced. The back label is
   the controlled document defining what is legal to build and label, and it
   authorises eight G12R wattages in 5 W steps. The serial embeds the wattage, so
   ICON630R... cannot be generated unless 630 is here — which is why the master
   must lead production, not follow it. ISEN630-G12R had already shipped while
   absent from the master.
   `produced` is a separate fact from `authorised`. Wattage alone is not the key:
   ISEN600-G2X and ISEN600-G12R are different products at the same wattage. */
var MODELS=[
 {watt:'635',tc:'R',model:'ISEN635-G12R',series:'G12R',cells:'132 half cell',ct:'G12R',
  size:'1000, 1400, 1094 MM',produced:false,lh:''},
 {watt:'630',tc:'R',model:'ISEN630-G12R',series:'G12R',cells:'132 half cell',ct:'G12R',
  size:'1000, 1400, 1094 MM',produced:true,lh:''},
 {watt:'625',tc:'R',model:'ISEN625-G12R',series:'G12R',cells:'132 half cell',ct:'G12R',
  size:'1000, 1400, 1094 MM',produced:true,lh:''},
 {watt:'620',tc:'R',model:'ISEN620-G12R',series:'G12R',cells:'132 half cell',ct:'G12R',
  size:'1000, 1400, 1094 MM',produced:true,lh:''},
 {watt:'615',tc:'R',model:'ISEN615-G12R',series:'G12R',cells:'132 half cell',ct:'G12R',
  size:'1000, 1400, 1094 MM',produced:false,lh:''},
 {watt:'610',tc:'R',model:'ISEN610-G12R',series:'G12R',cells:'132 half cell',ct:'G12R',
  size:'1000, 1400, 1094 MM',produced:true,lh:''},
 {watt:'605',tc:'R',model:'ISEN605-G12R',series:'G12R',cells:'132 half cell',ct:'G12R',
  size:'1000, 1400, 1094 MM',produced:false,lh:''},
 {watt:'600',tc:'R',model:'ISEN600-G12R',series:'G12R',cells:'132 half cell',ct:'G12R',
  size:'1000, 1400, 1094 MM',produced:false,lh:''},
 {watt:'600',tc:'G',model:'ISEN600-G2X',series:'G2X',cells:'144 half cut',ct:'M10R',
  size:'1000, 1400, 1094 MM',produced:true,lh:''},
 {watt:'590',tc:'G',model:'ISEN590-G2X',series:'G2X',cells:'144 half cut',ct:'M10R',
  size:'1000, 1400, 1094 MM',produced:true,lh:''}];
/* company-wide type characters (Unit-1 uses more of these) */
var TYPES={'':['Mono PERC',''],B:['Bifacial','-Bi'],T:['TOPCon','N-Top'],
           G:['G2X (Glass-to-Glass)','-G2X'],R:['G12R','-G12R']};

/* ============ SERIAL FORMATS — v1 and v2, both permanent ============
   v1 (to 31 Jul 2026): ICON watt(3) [type(1)] YY(2) MM(2) DD(2) shift(1) seq(3)
   v2 (from 1 Aug 2026): ICON watt(3) [type(1)] YY(2) M(1 hex) DD(2) shift(1) seq(4)
   Same length. Year base 2014 (YY=11 -> 2025). Capacity 1,000 -> 10,000 per shift.

   RULE 0: the date inside a serial is when the BARCODE WAS PRINTED, not when the
   module was produced. Barcodes are printed ahead, so a block printed for one
   shift routinely carries into the next — verified against the August report,
   where ICON590G1280610716 carries 06-08 but was produced on 07-08. Planning
   therefore stores date_produced as its own column; it is not the serial's date.

   RULE 1: never parse a serial at lookup time. Lookup is a string match.
   Planning stores format_version, date_produced, shift and sequence as real
   columns at generation; every later screen filters on those columns.
   Parsing below is used ONLY at generation and for the one-time backfill.      */
var CUTOVER=Date.UTC(2026,7,1);              /* 1 Aug 2026 */
var YEAR_BASE=2014;
function parseSerial(raw){
  var s=(raw||'').trim().toUpperCase();
  if(s.indexOf('ICON')!==0) return {ok:false,why:'Does not start with ICON'};
  var type='',rest;
  if(s.length===17){rest=s.slice(7)}
  else if(s.length===18){type=s[7];rest=s.slice(8)}
  else return {ok:false,why:'Length '+s.length+' is neither 17 nor 18'};
  var watt=s.slice(4,7);
  if(!/^\d{3}$/.test(watt)) return {ok:false,why:'Wattage is not numeric'};
  if(rest.length!==10) return {ok:false,why:'Malformed body'};
  var yy=rest.slice(0,2), disc=rest[2];
  if(!/^\d{2}$/.test(yy)) return {ok:false,why:'Year is not numeric'};
  var year=YEAR_BASE+parseInt(yy,10);
  function asV1(){
    var mm=rest.slice(2,4),dd=rest.slice(4,6),sh=rest[6],sq=rest.slice(7,10);
    if(!/^\d{2}$/.test(mm)||!/^\d{2}$/.test(dd)||!/^\d$/.test(sh)||!/^\d{3}$/.test(sq))return null;
    var m=+mm,d=+dd; if(m<1||m>12||d<1||d>31)return null;
    return {v:1,watt:watt,tc:type,year:year,month:m,day:d,shift:sh,seq:+sq,cap:1000};
  }
  function asV2(){
    var mc=rest[2],dd=rest.slice(3,5),sh=rest[5],sq=rest.slice(6,10);
    var m=/^[1-9]$/.test(mc)?+mc:({A:10,B:11,C:12})[mc];
    if(!m)return null;
    if(!/^\d{2}$/.test(dd)||!/^\d$/.test(sh)||!/^\d{4}$/.test(sq))return null;
    var d=+dd; if(d<1||d>31)return null;
    return {v:2,watt:watt,tc:type,year:year,month:m,day:d,shift:sh,seq:+sq,cap:10000};
  }
  var r;
  if(disc==='0'){r=asV1(); if(!r)return{ok:false,why:'Malformed v1 body'}}
  else if(/^[2-9ABC]$/.test(disc)){r=asV2(); if(!r)return{ok:false,why:'Malformed v2 body'}}
  else if(disc==='1'){
    /* Only January clashes with Oct/Nov/Dec. The 1 Aug 2026 cutover separates
       them by year, so exactly one reading is legal. */
    var a=asV1(),b=asV2();
    var aOK=!!a&&Date.UTC(a.year,a.month-1,a.day)<CUTOVER;
    var bOK=!!b&&Date.UTC(b.year,b.month-1,b.day)>=CUTOVER;
    if(aOK&&!bOK)r=a; else if(bOK&&!aOK)r=b;
    else return {ok:false,why:'Cannot resolve v1/v2 — this string is illegal on '+
      'both sides of the 1 Aug 2026 cutover'};
  }
  else return {ok:false,why:'Character "'+disc+'" is not a valid month in either format'};
  /* The cutover is a hard boundary in BOTH directions, not just a tie-breaker.
     v1 stopped on 31 Jul 2026; v2 did not exist before 1 Aug 2026. */
  /* The day must exist in that month. BARCDE.py computes days-in-month with
     `2000 + year_part` while the year base is 2014, so a run crossing 28 Feb 2026
     emits 29-02-2026 — a date that does not exist. Caught here rather than
     stored. */
  var dim=new Date(Date.UTC(r.year,r.month,0)).getUTCDate();
  if(r.day>dim)
    return {ok:false,why:String(r.day).padStart(2,'0')+'-'+String(r.month).padStart(2,'0')+'-'+
      r.year+' is not a real date — '+
      ['January','February','March','April','May','June','July','August','September',
       'October','November','December'][r.month-1]+' '+r.year+' has '+dim+' days'};
  var when=Date.UTC(r.year,r.month-1,r.day);
  if(r.v===1&&when>=CUTOVER)
    return {ok:false,why:'Format v1 dated '+String(r.day).padStart(2,'0')+'-'+
      String(r.month).padStart(2,'0')+'-'+r.year+' — v1 was discontinued on 31 Jul 2026'};
  if(r.v===2&&when<CUTOVER)
    return {ok:false,why:'Format v2 dated '+String(r.day).padStart(2,'0')+'-'+
      String(r.month).padStart(2,'0')+'-'+r.year+' — v2 did not start until 1 Aug 2026'};
  r.ok=true;r.raw=s;r.len=s.length;
  r.date=String(r.day).padStart(2,'0')+'-'+String(r.month).padStart(2,'0')+'-'+r.year;
  return r;
}
function serialIndex(p){return Math.floor(Date.UTC(p.year,p.month-1,p.day)/86400000)*p.cap+p.seq}
function serialFromIndex(p,i){
  var day=Math.floor(i/p.cap),seq=i%p.cap,dt=new Date(day*86400000);
  var yy=String(dt.getUTCFullYear()-YEAR_BASE).padStart(2,'0');
  var mo=dt.getUTCMonth()+1, dd=String(dt.getUTCDate()).padStart(2,'0');
  var mtok=p.v===1?String(mo).padStart(2,'0'):(mo<10?String(mo):({10:'A',11:'B',12:'C'})[mo]);
  return 'ICON'+p.watt+(p.tc||'')+yy+mtok+dd+p.shift+
         String(seq).padStart(p.v===1?3:4,'0');
}
function bumpSerial(s,n){var p=parseSerial(s);return p.ok?serialFromIndex(p,serialIndex(p)+n):s}
function rangeQty(a,b){
  var pa=parseSerial(a),pb=parseSerial(b);
  if(!pa.ok)return{ok:false,why:'Start serial — '+pa.why};
  if(!pb.ok)return{ok:false,why:'End serial — '+pb.why};
  if(pa.v!==pb.v)return{ok:false,why:'Start is format v'+pa.v+', end is v'+pb.v+
    '. A range cannot straddle the 1 Aug 2026 cutover.'};
  if(pa.watt!==pb.watt||pa.tc!==pb.tc)return{ok:false,why:'Start and end are different models'};
  if(pa.shift!==pb.shift)return{ok:false,why:'Different shift digit ('+pa.shift+' vs '+pb.shift+
    '). Allocate one shift block at a time.'};
  var n=serialIndex(pb)-serialIndex(pa)+1;
  if(n<1)return{ok:false,why:'End serial comes before the start serial'};
  return {ok:true,n:n,p:pa};
}
/* ================= MATERIAL & VENDOR MASTER =================
   Source: VENDOR_updated.xlsx. Sizes are fixed per material and are NOT
   selectable — the model decides which materials apply, so an operator can
   never put G2X glass on a G12R module. Make is selectable.
   Batch / invoice numbers are optional.
   series: 'G2X' | 'G12R' | '' (common to both) | 'LABEL' (picked by wattage)  */
/* Makes (manufacturers), not resellers. Trading houses were removed on request:
   an audit needs the company that made the part, not who invoiced it. */
var CELL_MAKES=['Lion Solar','PT Nusa Solar','Premier Energies','Solar Space',
  'Tongwei Solar','Yingfa'];
var GLASS_MAKES=['Borosil','Kibing','Waaree','Xinyi'];
var FRAME_MAKES=['Aluvoltec','Jiangsu Yuejia','Jiangyin Yuanshuo (YS)','Ralpro Techno',
  'Shanti Green','Sudarshan'];
var RIBBON_MAKES=['Dhash','Geba Copper','Juren','Sekhani Renewables','Valeo'];
var TAPE_MAKES=['H.B. Fuller','Sunsol'];
var SEAL_MAKES=['Fasto','Huitian'];
var JB_MAKES=['Dhash','GenX','QC Solar'];
var ENCAP_MAKES=['Alishan','Knack','RenewSys','Sheetsol'];
var LABEL_MAKES=['Finotech','Kvell','Sunsol'];

/* Potting is a two-part resin mixed 6:1 by weight. The consumption BOM gives the
   combined weight; the parts are derived from the ratio so they can never drift
   apart from it. */
var POTTING_TOTAL=0.022, POTTING_RATIO=6;
/* Full precision — rounding the parts would break the 6:1 ratio. */
var POT_A=POTTING_TOTAL*POTTING_RATIO/(POTTING_RATIO+1);
var POT_B=POTTING_TOTAL/(POTTING_RATIO+1);

/* qpm: a number when both series consume the same, or {G2X, G12R} when they do
   not. Figures come from Consumption BOM - M10R.xlsx and - G12R.xlsx. */
var MATERIALS=[
 {n:1, name:'Solar Cell', size:'182.2 x 183.75 mm · >25% · 16 BB', uom:'Nos', series:'G2X',
  qpm:72, cell:true, cat:'Cell', makes:CELL_MAKES,
  note:'Full-size cell — cut in half at the stringer, so 72 make 144 half cells'},
 {n:2, name:'Solar Glass — Front', size:'2272 x 1128 x 2 mm', uom:'Nos', series:'G2X',
  qpm:1, cat:'Glass', makes:GLASS_MAKES},
 {n:3, name:'Solar Glass — Rear', size:'2272 x 1128 x 2 mm · 3 hole · grid printed',
  uom:'Nos', series:'G2X', qpm:1, cat:'Glass', makes:GLASS_MAKES},
 {n:4, name:'Aluminium Frame', size:'2278 x 1134 x 30 mm', uom:'Set', series:'G2X',
  qpm:1, cat:'Frame', makes:FRAME_MAKES},
 {n:5, name:'Solar Cell', size:'182.2 x 210 mm · >25% · 16 BB', uom:'Nos', series:'G12R',
  qpm:66, cell:true, cat:'Cell', makes:CELL_MAKES,
  note:'Full-size cell — cut in half at the stringer, so 66 make 132 half cells'},
 {n:6, name:'Solar Glass — Front', size:'2376 x 1128 x 2 mm', uom:'Nos', series:'G12R',
  qpm:1, cat:'Glass', makes:GLASS_MAKES},
 {n:7, name:'Solar Glass — Rear', size:'2376 x 1128 x 2 mm · 3 hole · grid printed',
  uom:'Nos', series:'G12R', qpm:1, cat:'Glass', makes:GLASS_MAKES},
 {n:8, name:'Aluminium Frame', size:'2382 x 1134 x 30 mm', uom:'Set', series:'G12R',
  qpm:1, cat:'Frame', makes:FRAME_MAKES},
 {n:9, name:'Encapsulant', size:'EPE / EPE · 460 GSM', uom:'Sqm', series:'',
  qpm:{G2X:5.14,G12R:5.38}, cat:'Encapsulant', makes:ENCAP_MAKES},
 {n:12, name:'Cell Inter Connector', size:'0.26 mm round wire', uom:'Kg', series:'',
  qpm:{G2X:0.178,G12R:0.198}, cat:'Interconnect', makes:RIBBON_MAKES,
  note:'Interconnect ribbon — joins cells at the stringer'},
 {n:13, name:'String Inter Connector — Centre', size:'6.0 x 0.40 mm', uom:'Kg', series:'',
  qpm:0.024, cat:'Interconnect', makes:RIBBON_MAKES, note:'Bus ribbon'},
 {n:14, name:'String Inter Connector — Edge', size:'4.0 x 0.40 mm', uom:'Kg', series:'',
  qpm:0.028, cat:'Interconnect', makes:RIBBON_MAKES, note:'Bus ribbon'},
 {n:19, name:'Flux', size:'—', uom:'Ltr', series:'', qpm:0.022, cat:'Interconnect',
  makes:['RCPV']},
 {n:20, name:'Cell Alignment Tape', size:'8 mm width', uom:'Mtr', series:'', qpm:1,
  cat:'Tapes', makes:TAPE_MAKES},
 {n:22, name:'Edge Sealing Tape', size:'30 mm width', uom:'Mtr', series:'',
  qpm:{G2X:7,G12R:7.1}, cat:'Tapes', makes:TAPE_MAKES},
 {n:21, name:'Lead Bending Tape', size:'20 mm width', uom:'Mtr', series:'', qpm:null,
  cat:'Tapes', makes:TAPE_MAKES, offbom:true},
 {n:23, name:'EPE Strip (Output Patti)', size:'—', uom:'Sqm', series:'', qpm:null,
  cat:'Encapsulant', makes:['RenewSys'], offbom:true},
 {n:10, name:'Junction Box 30 A', size:'0.4 mtr', uom:'Nos', series:'', qpm:1,
  cat:'Junction box & sealant', group:'JB', makes:JB_MAKES},
 {n:11, name:'Junction Box 30 A', size:'0.3 mtr', uom:'Nos', series:'', qpm:1,
  cat:'Junction box & sealant', group:'JB', makes:JB_MAKES, legacy:true},
 {n:16, name:'Sealant (Frame + JB)', size:'—', uom:'Kg', series:'',
  qpm:{G2X:0.34,G12R:0.36}, cat:'Junction box & sealant', makes:SEAL_MAKES},
 {n:17, name:'Potting Material — Part A', size:'resin · 6 parts of a 6:1 mix', uom:'Kg',
  series:'', qpm:POT_A, cat:'Junction box & sealant', makes:SEAL_MAKES, pot:'A'},
 {n:18, name:'Potting Material — Part B', size:'hardener · 1 part of a 6:1 mix', uom:'Kg',
  series:'', qpm:POT_B, cat:'Junction box & sealant', makes:SEAL_MAKES, pot:'B'},
 {n:15, name:'RFID Sticker', size:'—', uom:'Nos', series:'', qpm:1, cat:'Labels & packing',
  makes:LABEL_MAKES},
 {n:29, name:'Barcode Label', size:'—', uom:'Nos', series:'', qpm:1, cat:'Labels & packing',
  makes:LABEL_MAKES, added:true},
 {n:30, name:'Pallet Packing', size:'—', uom:'Nos', series:'', qpm:1, cat:'Labels & packing',
  makes:['Kvell','Sunsol'], added:true},
 {n:24, name:'Back Label 590WP', size:'—', uom:'Nos', series:'LABEL', watt:'590', qpm:1,
  cat:'Labels & packing', makes:['Kvell']},
 {n:25, name:'Back Label 600WP', size:'—', uom:'Nos', series:'LABEL', watt:'600', qpm:1,
  cat:'Labels & packing', makes:['Kvell']},
 {n:26, name:'Back Label 610WP', size:'—', uom:'Nos', series:'LABEL', watt:'610', qpm:1,
  cat:'Labels & packing', makes:['Kvell'], added:true},
 {n:27, name:'Back Label 620WP', size:'—', uom:'Nos', series:'LABEL', watt:'620', qpm:1,
  cat:'Labels & packing', makes:['Kvell']},
 {n:28, name:'Back Label 625WP', size:'—', uom:'Nos', series:'LABEL', watt:'625', qpm:1,
  cat:'Labels & packing', makes:['Kvell']}];
var MAT_CATS=['Cell','Glass','Frame','Encapsulant','Interconnect','Tapes',
  'Junction box & sealant','Labels & packing'];
/* Consumption depends on the series for several materials. */
function seriesOf(model){
  var m=MODELS.filter(function(x){return x.model===model})[0];
  return m?m.series:null;
}
function qpmFor(mat,model){
  if(mat.qpm==null)return null;
  if(typeof mat.qpm==='object'){var s=seriesOf(model);return s?mat.qpm[s]:null}
  return mat.qpm;
}
function qpmLabel(mat,model){
  var v=qpmFor(mat,model);
  return v==null?null:(+v.toFixed(4))+' '+mat.uom;
}
/* Stable make for demo display. */
function demoVendor(m){return m.makes[m.n % m.makes.length]}

/* Cell efficiency is a property of the CELL, not of the module. Module
   efficiency comes later from the Sun Simulator. Same vendor at a different
   efficiency is a DIFFERENT material for traceability. */
var CELL_EFF=['25%','25.1%','25.2%','25.3%','25.35%','25.4%','25.5%','25.6%','25.7%'];

/* Materials that apply to a model: its series, everything common, and the one
   back label matching its wattage. Operators cannot widen this. */
function materialsFor(model){
  if(!model)return [];
  var m=MODELS.filter(function(x){return x.model===model})[0];
  if(!m)return [];
  return MATERIALS.filter(function(mat){
    if(mat.series===m.series)return true;
    if(mat.series==='')return true;
    if(mat.series==='LABEL')return mat.watt===m.watt;
    return false;
  });
}
/* How many modules the current stock of each material supports. */
function buildableFrom(mat,model){
  var q=qpmFor(mat,model);
  if(!q||mat.stock==null)return null;
  return Math.floor(mat.stock/q);
}
/* Materials sharing a group are ALTERNATIVES — you use one or the other, never
   both. Only the chosen one counts against stock. Default choice is the first
   non-legacy option in the group. */
var MAT_CHOICE={};                       /* group -> chosen material number */
function chosenInGroup(list,g){
  if(MAT_CHOICE[g]!=null)
    return list.filter(function(m){return m.n===MAT_CHOICE[g]})[0];
  return list.filter(function(m){return m.group===g&&!m.legacy})[0]||
         list.filter(function(m){return m.group===g})[0];
}
function requiredFor(model){
  var list=materialsFor(model),seen={},out=[];
  list.forEach(function(m){
    if(!m.group){out.push(m);return}
    if(seen[m.group])return;
    seen[m.group]=1;
    var c=chosenInGroup(list,m.group);
    if(c)out.push(c);
  });
  return out;
}
function stockCheck(model,qty){
  var out={short:[],limit:null,unknown:0};
  requiredFor(model).forEach(function(mat){
    var q=qpmFor(mat,model);
    if(!q){out.unknown++;return}
    var can=buildableFrom(mat,model);
    if(can==null){out.unknown++;return}
    if(can<qty)out.short.push({mat:mat,can:can,need:qty*q});
    if(out.limit===null||can<out.limit)out.limit=can;
  });
  return out;
}

/* Unit-2 model catalogue. Planning refuses anything not in this list. */
function derive(serial){
  var p=parseSerial(serial);
  if(!p.ok)return{ok:false,why:p.why};
  var m=MODELS.filter(function(x){return x.watt===p.watt&&x.tc===(p.tc||'')})[0];
  if(m)return{ok:true,p:p,watt:p.watt,tc:p.tc||'—',type:m.series,model:m.model,
              cells:m.cells,ct:m.ct,size:m.size,fmt:p.v,date:p.date,shift:p.shift,seq:p.seq};
  var t=TYPES[p.tc];
  return {ok:false,p:p,watt:p.watt,tc:p.tc||'—',
    why:t?(p.watt+'W '+t[0]+' is not produced at Unit-2'):
          ('Type character "'+(p.tc||'none')+'" is not recognised')};
}
/* ================= ROLES & ACCESS =================
   Every person has an individual user ID. Shared station logins are rejected —
   an audit line reading "FQC Station" identifies nobody.
   Each user is bound to a station; the station carries the line. Line is never
   read out of the serial and never picked from a dropdown at login.
   NOTE: authentication itself is designed, not built. This is the shape only. */
var ROLES={
 'Admin':{home:'mgmt',views:['mgmt','search','proddash','plan','prodentry','loss','dash','fqc',
   'pack','repack','packdash','disp','invoice','challan','gp','drafts','hold','review','admin'],
   perms:['Everything','Release holds','Cancel documents','Master data']},
 'Production Incharge':{home:'proddash',
   views:['mgmt','search','proddash','plan','prodentry','loss','dash','drafts','hold'],
   perms:['Planning','Production entry','Loss & breakdown','Release holds']},
 'FQC Operator':{home:'fqc',views:['search','dash','fqc','drafts','hold','review'],
   perms:['FQC verification','FQC dashboard','Raise holds']},
 'Packing Operator':{home:'pack',views:['search','pack','repack','packdash','dash','drafts','hold'],
   perms:['Packing','Repack','Packing log','Raise holds']},
 'Dispatch Operator':{home:'disp',views:['search','disp','invoice','challan','gp','packdash','drafts','hold'],
   perms:['Stock & dispatch','Challan','Gate pass','Raise holds']}};
var USER={name:'',role:'Admin',station:'DISPATCH-01'};
function can(v){var r=ROLES[USER.role];return !!r&&r.views.indexOf(v)>=0}
function applyRole(){
  var r=ROLES[USER.role];
  document.querySelectorAll('.nav-i').forEach(function(b){
    b.classList.toggle('hide',!can(b.dataset.v))});
  var nodes=Array.prototype.slice.call(document.getElementById('sidenav').children);
  nodes.forEach(function(n,i){
    if(!n.hasAttribute('data-sec'))return;
    var any=false;
    for(var j=i+1;j<nodes.length;j++){
      if(nodes[j].hasAttribute('data-sec'))break;
      if(!nodes[j].classList.contains('hide')){any=true;break}}
    n.classList.toggle('hide',!any)});
  document.querySelectorAll('.admin-only').forEach(function(e){
    e.classList.toggle('hide',USER.role!=='Admin')});
  document.getElementById('umPerms').innerHTML='<label>Can access</label>'+
    r.perms.map(function(p){return '<span class="pchip">'+p+'</span>'}).join('');
  /* If the active view is not permitted for this role, leave it — hiding the
     nav button is not enough on its own. */
  var open=document.querySelector('.view.on');
  if(open){
    var id=open.id.replace('v-','');
    if(!can(id)){open.classList.remove('on');go(ROLES[USER.role].home)}
  }
  var st=stationOf(USER.station);
  document.getElementById('tbStation').textContent=st.id+' · '+
    (st.line==='—'?'no line':st.line+'-Line');
  var f=document.getElementById('fqcStation');
  if(f)f.textContent=st.id+' · '+(st.line==='—'?'no line':st.line+'-Line');
}
function toggleUserMenu(e){
  e.stopPropagation();
  document.getElementById('umenu').classList.toggle('on');
}
document.addEventListener('click',function(){
  var m=document.getElementById('umenu');if(m)m.classList.remove('on')});

/* ================= SHELL ================= */
function signIn(){
  var v=document.getElementById('who').value.split('|');
  USER={name:v[0],role:v[1],station:v[2]};
  ['uname','umName'].forEach(function(id){document.getElementById(id).textContent=USER.name});
  ['urole','umRole'].forEach(function(id){document.getElementById(id).textContent=USER.role});
  document.getElementById('av').textContent=
    USER.name.split(' ').map(function(w){return w[0]}).join('').slice(0,2).toUpperCase();
  document.getElementById('login').classList.add('gone');
  document.getElementById('app').classList.add('on');
  initAll();
  applyRole();
  go(ROLES[USER.role].home);
}
function signOut(e){
  if(e)e.stopPropagation();
  document.getElementById('umenu').classList.remove('on');
  document.getElementById('app').classList.remove('on');
  document.getElementById('login').classList.remove('gone');
  fqcHold=null;packHold=null;
  toast('Signed out.');
}
function navBtn(v){return document.querySelector('.nav-i[data-v="'+v+'"]')}
function go(id,el){
  if(!can(id)){
    var cur=document.querySelector('.view.on');
    if(cur&&!can(cur.id.replace('v-','')))cur.classList.remove('on');
    toast('Your role does not have access to that screen.');return;
  }
  document.querySelectorAll('.view').forEach(function(v){v.classList.remove('on')});
  document.getElementById('v-'+id).classList.add('on');
  document.querySelectorAll('.nav-i').forEach(function(n){n.classList.remove('on')});
  var b=el||navBtn(id);if(b)b.classList.add('on');
  document.querySelector('.main').scrollTop=0;
  if(id==='fqc')setTimeout(function(){document.getElementById('fqcScan').focus()},60);
  if(id==='pack')setTimeout(function(){document.getElementById('packScan').focus()},60);
  if(id==='plan')stampPlanUser();
}
function stampPlanUser(){
  var d=new Date(),p=function(n){return String(n).padStart(2,'0')};
  document.getElementById('pBy').value=USER.name+' · '+USER.role;
  document.getElementById('pWhen').value=
    p(d.getDate())+'-'+p(d.getMonth()+1)+'-'+d.getFullYear()+' '+p(d.getHours())+':'+p(d.getMinutes());
}
function shiftOf(h){return h>=6&&h<14?'A':h>=14&&h<22?'B':'C'}
function tick(){
  var d=new Date(),p=function(n){return String(n).padStart(2,'0')};
  document.getElementById('clock').textContent=
    p(d.getDate())+'-'+p(d.getMonth()+1)+'-'+d.getFullYear()+' · '+p(d.getHours())+':'+p(d.getMinutes());
  var s=shiftOf(d.getHours()),c={A:'#8FBEF2',B:'#C4A3E4',C:'#87D3B4'}[s];
  var pill=document.getElementById('shiftPill');
  pill.style.background='rgba(255,255,255,.13)';pill.style.color=c;
  document.getElementById('shiftTxt').textContent='SHIFT '+s;
}
setInterval(tick,1000);
var toastT;
function toast(m){
  var t=document.getElementById('toast');t.textContent=m;t.style.display='block';
  clearTimeout(toastT);toastT=setTimeout(function(){t.style.display='none'},2600);
}
function exportNote(){toast('Export runs on the server in the real build — Excel with your current filters.')}

/* ================= DASHBOARD ================= */
function renderDash(){
  document.getElementById('shiftRows').innerHTML=SHIFT_ROWS.map(function(r,i){
    var span=(i===0||SHIFT_ROWS[i-1].s!==r.s);
    var cnt=SHIFT_ROWS.filter(function(x){return x.s===r.s}).length;
    var pct=(r.r/r.t*100).toFixed(2);
    return '<tr>'+(span?'<td rowspan="'+cnt+'" class="s'+r.s+'">'+r.s+'</td>':'')+
      '<td class="mono">'+r.w+'</td><td class="mono">'+r.m+'</td>'+
      '<td class="num">'+r.t.toLocaleString()+'</td><td class="num">'+r.ok.toLocaleString()+'</td>'+
      '<td class="num">'+r.r+'</td>'+
      '<td><div class="bar-wrap"><div class="bar"><i style="width:'+Math.min(pct*12,100)+'%"></i></div>'+
      '<span class="mono">'+pct+'%</span></div></td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="openModules({title:\'Shift '+r.s+' · '+r.w+'\',shift:\''+r.s+'\',model:\''+r.m+'\'})">'+
      'View '+r.t.toLocaleString()+'</button></td></tr>';
  }).join('');
  document.getElementById('catRows').innerHTML=CATS.map(function(c){
    return '<tr><td>'+c.c+'</td><td><span class="tag '+(c.res==='Passed'?'t-pass':'t-fail')+'">'+
      c.res+'</span></td><td class="num">'+c.q.toLocaleString()+'</td>'+
      '<td><div class="bar-wrap"><div class="bar'+(c.res==='Passed'?' b-ok':'')+'">'+
      '<i style="width:'+c.p+'%"></i></div><span class="mono">'+
      (c.q/2847*100).toFixed(1)+'%</span></div></td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="openModules({title:\'Category '+c.c+'\',cat:\''+c.c+'\'})">⊞</button></td></tr>';
  }).join('');
  document.getElementById('rejRows').innerHTML=REJ.map(function(r){
    return '<tr><td>'+r.n+'</td><td class="num">'+r.q+'</td>'+
      '<td><div class="bar-wrap"><div class="bar"><i style="width:'+r.p+'%"></i></div>'+
      '<span class="mono">'+Math.round(r.q/56*100)+'%</span></div></td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="openModules({title:\'Rejection — '+r.n+'\',result:\'Rejected only\',remark:\''+
      r.n+'\'})">⊞</button></td></tr>';
  }).join('');
  document.getElementById('dayRows').innerHTML=DAYS.map(function(d){
    return '<tr><td><button class="lnk" onclick="openModules({title:\'Inspection detail — '+d.d+
      '\',date:\''+d.d+'\'})">'+d.d+'</button></td>'+
      '<td>'+d.sh.map(function(s){return '<span class="s'+s+'">'+s+'</span>'}).join(' ')+'</td>'+
      '<td class="num">'+d.t.toLocaleString()+'</td><td class="num">'+d.ok.toLocaleString()+'</td>'+
      '<td class="num">'+d.r+'</td><td class="num">'+(d.r/d.t*100).toFixed(2)+'%</td>'+
      '<td class="num">'+d.kw.toLocaleString()+'</td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="openModules({title:\''+d.d+'\',date:\''+d.d+'\'})">⊞</button></td></tr>';
  }).join('');
  var prod=MODELS.filter(function(m){return m.produced}).length;
  var mc=document.getElementById('mdCount');
  if(mc)mc.textContent=MODELS.length+' authorised · '+prod+' produced';
  document.getElementById('modelRows').innerHTML=MODELS.map(function(m){
    return '<tr'+(m.produced?'':' style="opacity:.62"')+'>'+
      '<td class="mono" style="font-weight:700">'+m.model+'</td>'+
      '<td class="mono">'+m.watt+'W</td><td class="mono">'+m.tc+'</td><td>'+m.series+'</td>'+
      '<td>'+m.cells+'</td><td class="mono">'+m.ct+'</td>'+
      '<td>'+(m.produced?'<span class="tag t-pass">produced</span>':
        '<span class="tag t-mute">authorised only</span>')+'</td>'+
      '<td class="mono" style="font-size:11px">'+(m.lh||
        '<span class="tag t-rev">to map</span>')+'</td>'+
      '<td><button class="btn btn-ghost btn-sm" onclick="editRecord(\'model\',\''+m.model+'\')">Edit</button></td></tr>';
  }).join('');
}

/* ---- FQC date range: blank or equal To means a single day ---- */
function fmtD(iso){
  if(!iso)return '';
  var p=iso.split('-');return p[2]+'-'+p[1]+'-'+p[0];
}
function fqcRange(){
  var f=document.getElementById('fFrom'),t=document.getElementById('fTo'),
      out=document.getElementById('fPeriod');
  if(!f||!out)return {from:null,to:null,days:1};
  var from=f.value,to=t.value;
  if(!from){out.value='— pick a From date —';return {from:null,to:null,days:0}}
  if(!to||to===from){out.value=fmtD(from)+' · single day';return {from:from,to:from,days:1}}
  if(to<from){out.value='To is before From';return {from:from,to:to,days:0}}
  var days=Math.round((new Date(to)-new Date(from))/86400000)+1;
  out.value=fmtD(from)+' → '+fmtD(to)+' · '+days+' days';
  return {from:from,to:to,days:days};
}
function fqcClearTo(){
  var t=document.getElementById('fTo');
  if(t){t.value='';fqcRange();toast('To date cleared — showing a single day.')}
}

/* ---- section-dashboard composition charts ---- */
function renderSectionDonuts(){
  var a=CATS[0].q,gy=CATS[1].q,bgy=CATS[2].q,tot=a+gy+bgy;
  drawDonut('fqDonut','fqLegend',[
    {n:'A — passed',v:a,c:C.green},
    {n:'GY — downgraded',v:gy,c:C.amber},
    {n:'BGY — rejected',v:bgy,c:C.red}
  ],tot.toLocaleString(),'inspected');
  var note=document.getElementById('fqDonutNote');
  if(note)note.textContent=(a/tot*100).toFixed(2)+'% yield';

  drawDonut('pkDonut','pkLegend',[
    {n:'Dispatched',v:51,c:C.green},
    {n:'On a challan',v:2,c:C.navy},
    {n:'Packed, awaiting challan',v:21,c:C.blue},
    {n:'Repacked (closed)',v:7,c:C.grey},
    {n:'Open on the floor',v:3,c:C.amber}
  ],'84','boxes');
  drawDonut('pkGDonut','pkGLegend',[
    {n:'A grade',v:2556,c:C.green},
    {n:'GY',v:36,c:C.amber},
    {n:'BGY',v:0,c:C.red}
  ],'2,592','modules packed');

  drawDonut('dpDonut','dpLegend',[
    {n:'Dispatched',v:1836,c:C.green},
    {n:'On open challan',v:72,c:C.navy},
    {n:'Finished goods in stock',v:756,c:C.blue},
    {n:'Frozen by a hold',v:36,c:C.red}
  ],'2,700','modules');
}

/* ================= MODULE MODAL ================= */
var MDL=[];
function openModules(o){
  o=o||{};
  var n=150,base='ICON590G1202121001';
  MDL=[];
  for(var i=0;i<n;i++){
    var s=bumpSerial(base,i), d=derive(s), rej=(i%7===0);
    var cat=rej?(i%2?'GY':'BGY'):'A';
    MDL.push({s:s,m:d.ok?d.model:'—',c:CUST,dt:DAYS[i%4].d,sh:['A','B','C'][i%3],
      cat:cat,rem:rej?REM[i%REM.length]:'—',pass:!rej,inc:INCH[i%INCH.length]});
  }
  document.getElementById('mdlTitle').textContent=o.title||'Modules';
  document.getElementById('mdlSearch').value='';
  document.getElementById('mdlRes').value=o.result||'All results';
  document.getElementById('mdlCat').value=o.cat||'All categories';
  document.getElementById('mdlShift').value=o.shift||'All shifts';
  document.getElementById('mdlRem').innerHTML='<option>All remarks</option>'+
    REM.map(function(r){return '<option>'+r+'</option>'}).join('');
  document.getElementById('mdlRem').value=o.remark||'All remarks';
  modalMode(false);mdlFilter();document.getElementById('mdl').classList.add('on');
}
function mdlFilter(){
  var q=document.getElementById('mdlSearch').value.trim().toUpperCase();
  var r=document.getElementById('mdlRes').value,c=document.getElementById('mdlCat').value;
  var rm=document.getElementById('mdlRem').value,sh=document.getElementById('mdlShift').value;
  var rows=MDL.filter(function(m){
    if(q&&m.s.indexOf(q)<0)return false;
    if(r==='Passed only'&&!m.pass)return false;
    if(r==='Rejected only'&&m.pass)return false;
    if(c!=='All categories'&&m.cat!==c)return false;
    if(rm!=='All remarks'&&m.rem!==rm)return false;
    if(sh!=='All shifts'&&m.sh!==sh)return false;
    return true;});
  document.getElementById('mdlCount').textContent=rows.length+' shown';
  document.getElementById('mdlRows').innerHTML=rows.length?rows.map(function(m,i){
    return '<tr><td class="num" style="color:var(--ink3)">'+(i+1)+'</td>'+
      '<td class="mono">'+m.s+'</td><td class="mono">'+m.m+'</td><td>'+m.c+'</td>'+
      '<td class="mono">'+m.dt+'</td><td class="s'+m.sh+'">'+m.sh+'</td><td>'+m.cat+'</td>'+
      '<td>'+m.rem+'</td><td><span class="tag '+(m.pass?'t-pass">Passed':'t-fail">Rejected')+'</span></td>'+
      '<td style="font-size:11.5px">'+m.inc+'</td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="traceSerial(\''+m.s+'\')">→</button></td></tr>';
  }).join(''):'<tr><td colspan="11"><div class="empty-state"><div class="es-i">⌕</div>'+
    '<p>No serial matches these filters.</p></div></td></tr>';
}
function mdlReset(){
  document.getElementById('mdlSearch').value='';
  document.getElementById('mdlRes').value='All results';
  document.getElementById('mdlCat').value='All categories';
  document.getElementById('mdlRem').value='All remarks';
  document.getElementById('mdlShift').value='All shifts';
  mdlFilter();
}
/* The modal serves two jobs. Serial lists keep the search/filter bar and the
   serial table; anything else gets a clean body with neither. */
function modalMode(generic){
  document.getElementById('mdlFilters').style.display=generic?'none':'';
  document.getElementById('mdlSerialCard').style.display=generic?'none':'';
  document.getElementById('mdlGeneric').style.display=generic?'':'none';
  if(!generic)document.getElementById('mdlGeneric').innerHTML='';
}
function closeModal(){document.getElementById('mdl').classList.remove('on')}
function traceSerial(s){closeModal();qTry(s)}

/* ================= PLANNING ================= */
var planOK=false;
function rangeCalc(){
  var a=document.getElementById('rgFrom').value.trim().toUpperCase();
  var b=document.getElementById('rgTo').value.trim().toUpperCase();
  var msg=document.getElementById('rgMsg'),qtyEl=document.getElementById('rgQty');
  var da=derive(a),db=derive(b);
  function bad(t){qtyEl.value='—';
    msg.innerHTML='<div class="note n-bad" style="margin:9px 0 11px"><span>⚑</span><span>'+t+'</span></div>';
    setRail(null,null,null,t);}
  if(!da.ok){return bad(da.why)}
  if(!db.ok){return bad(db.why)}
  var pa=da.p,pb=db.p;
  var r=rangeQty(a,b);                       /* returns {ok,n,why} — not a number */
  if(!r.ok){return bad(r.why)}
  var n=r.n;
  qtyEl.value=n.toLocaleString();
  var days=Math.floor(serialIndex(pb)/pa.cap)-Math.floor(serialIndex(pa)/pa.cap);
  var d2=function(x){return String(x).padStart(2,'0')};
  msg.innerHTML='<div class="note n-ok" style="margin:9px 0 11px"><span>✓</span><span>'+
    n.toLocaleString()+' serials · <b>'+da.model+'</b> · format v'+pa.v+' · '+
    (n*(+da.watt)/1000).toFixed(2)+' KW'+
    (days>0?' · spans '+days+' date block'+(days>1?'s':'')+' ('+
      d2(pa.day)+'/'+d2(pa.month)+' → '+d2(pb.day)+'/'+d2(pb.month)+
      ', '+pa.cap.toLocaleString()+' per shift)':'')+'</span></div>';
  setRail(a,b,n,null,da);
}
function setRail(first,last,qty,err,d){
  var g=function(id){return document.getElementById(id)};
  g('pvFirst').textContent=first||'—';
  g('pvLast').textContent=last||'—';
  g('pvQty').textContent=qty?qty.toLocaleString():'—';
  if(!d&&first)d=derive(first);
  g('pvW').textContent=d&&d.ok?d.watt+'W':'—';
  g('pvT').textContent=d&&d.ok?d.tc:'—';
  g('pvType').textContent=d&&d.ok?d.type:'—';
  g('pvModel').textContent=d&&d.ok?d.model:'—';
  g('pvCells').textContent=d&&d.ok?d.cells:'—';
  g('pvKw').textContent=(qty&&d&&d.ok)?(qty*(+d.watt)/1000).toFixed(2)+' KW':'—';
  if(d&&d.ok){g('pSize').value=d.size}
  planOK=!!(first&&qty&&d&&d.ok&&!err);
  g('loadBtn').disabled=!planOK;
  try{renderMatPanel()}catch(e){}
  g('railStatus').innerHTML=err?
    '<div class="note n-bad" style="font-size:11.5px"><span>⚑</span><span>'+err+'</span></div>':
    (planOK?'<div class="note n-ok" style="font-size:11.5px"><span>✓</span>'+
      '<span>Range is valid and the model is produced at Unit-2.</span></div>':'');
}
function validateOnly(){
  var c=document.getElementById('pCust').value;
  if(!planOK){toast('Fix the serial range first — see the message above.');return}
  if(!c){toast('Customer is required before this range can be validated.');return}
  toast('Validated. '+document.getElementById('pvQty').textContent+
        ' serials ready — nothing written yet.');
}
function loadMaster(){
  var c=document.getElementById('pCust').value;
  if(!c){toast('Customer is required.');document.getElementById('pCust').focus();return}
  toast(document.getElementById('pvQty').textContent+' serials loaded into master for '+c+
        ' — recorded against '+USER.name+'.');
}

/* ---- Indent lines. The indent is the factory's work instruction: customer,
   model, quantity, DCR/NDCR, ARC/NARC and the pallet instruction all come from
   the LINE, not the header. One indent can carry the same model twice, once DCR
   and once NDCR — header-level referencing cannot represent that. ---- */
var INDENTS={
 'AUG-05/2026':[
  {line:1,cust:'AGNI POWER & INFRATECH',model:'ISEN630-G12R',qty:300,dcr:'NDCR',arc:'ARC',
   pallet:36,dispatched:290},
  {line:2,cust:'AGNI POWER & INFRATECH',model:'ISEN620-G12R',qty:180,dcr:'DCR',arc:'ARC',
   pallet:18,dispatched:0}],
 'AUG-04/2026':[
  {line:1,cust:'BOROSIL RENEWABLES',model:'ISEN620-G12R',qty:1440,dcr:'NDCR',arc:'NARC',
   pallet:36,dispatched:1080},
  {line:2,cust:'BOROSIL RENEWABLES',model:'ISEN620-G12R',qty:1440,dcr:'DCR',arc:'NARC',
   pallet:36,dispatched:0}],
 'JUL-11/2026':[
  {line:1,cust:'RAINBOW SOLAR',model:'ISEN590-G2X',qty:36,dcr:'NDCR',arc:'NARC',
   pallet:null,dispatched:36}]};
var CEILING=36;                    /* Unit-2, 30 mm frame — unit master data */
function indentChange(){
  var sel=document.getElementById('pIndent'); if(!sel)return;
  var ind=INDENTS[sel.value];
  var lineSel=document.getElementById('pIndentLine');
  if(!ind){
    lineSel.innerHTML='<option value="">—</option>';
    ['pCust','pOrdered','pDcr','pArc','pDisp','pRem','pPallet'].forEach(function(id){
      document.getElementById(id).value='';});
    document.getElementById('pIndentNote').innerHTML='';
    document.getElementById('pPalletNote').innerHTML='';
    return;
  }
  if(lineSel.options.length!==ind.length||lineSel.dataset.ind!==sel.value){
    lineSel.dataset.ind=sel.value;
    lineSel.innerHTML=ind.map(function(l){
      return '<option value="'+l.line+'">Line '+l.line+' — '+l.model+' · '+l.dcr+' · '+
        l.qty+' nos</option>';}).join('');
  }
  var L=ind.filter(function(l){return String(l.line)===lineSel.value})[0]||ind[0];
  document.getElementById('pCust').value=L.cust;
  var echo=document.getElementById('pCustEcho'); if(echo)echo.value=L.cust;
  document.getElementById('pOrdered').value=L.qty+' nos';
  document.getElementById('pDcr').value=L.dcr;
  document.getElementById('pArc').value=L.arc;
  document.getElementById('pDisp').value=L.dispatched+' nos';
  document.getElementById('pRem').value=(L.qty-L.dispatched)+' nos';
  document.getElementById('pCeil').value=CEILING;
  document.getElementById('pPallet').value=L.pallet==null?
    CEILING+' (unstated — defaults to the ceiling)':L.pallet;
  var dup=ind.filter(function(l){return l.model===L.model}).length>1;
  document.getElementById('pIndentNote').innerHTML=dup?
    '<div class="note n-warn" style="font-size:11.5px;margin:4px 0 0"><span>&#9873;</span><span>'+
    'This indent carries <b>'+L.model+'</b> on more than one line — '+
    ind.filter(function(l){return l.model===L.model}).map(function(l){
      return 'line '+l.line+' '+l.dcr}).join(' and ')+
    '. Planning must reference the <b>line</b>, never the header.</span></div>':'';
  document.getElementById('pPalletNote').innerHTML=(L.pallet&&L.pallet>CEILING)?
    '<div class="note n-bad" style="font-size:11.5px;margin:4px 0 0"><span>&#9873;</span><span>'+
    'The indent asks for '+L.pallet+' per pallet but the physical ceiling is '+CEILING+
    '. Refuse the instruction.</span></div>':
    (L.qty%(L.pallet||CEILING)===0?
      '<div class="note n-ok" style="font-size:11.5px;margin:4px 0 0"><span>&#10003;</span><span>'+
      L.qty+' is exactly '+(L.qty/(L.pallet||CEILING))+' whole pallets — Marketing sized it '+
      'deliberately. Do not second-guess the number.</span></div>':'');
  try{rangeCalc()}catch(e){}
}
/* ---- Planning: model-driven bill of materials ----
   Grouped by category. Size is fixed and shown, never editable. Cell efficiency
   appears ONLY on the cell row. Stock and buildable-quantity columns are
   deliberately absent — they belong with stores consumption, which is not built. */
var MAT_SEL={};
function renderMatPanel(){
  var host=document.getElementById('matPanel'); if(!host)return;
  var model=document.getElementById('pvModel').textContent;
  var tag=document.getElementById('matModel');
  if(!model||model==='—'){
    tag.textContent='no model yet';
    host.innerHTML='<div class="empty-state" style="padding:26px">'+
      '<div class="es-i">&#9707;</div><p>Enter a serial range above. The model is read from the '+
      'barcode and decides which materials apply — they are never picked by hand.</p></div>';
    return;
  }
  tag.textContent=model;
  var qty=parseInt((document.getElementById('pvQty').textContent||'0').replace(/,/g,''),10)||0;
  var list=materialsFor(model), out='', seen={};
  MAT_CATS.forEach(function(cat){
    var rows=list.filter(function(m){return m.cat===cat});
    if(!rows.length)return;
    var body='';
    rows.forEach(function(m){
      if(m.group){ if(seen[m.group])return; seen[m.group]=1; }
      var alts=m.group?list.filter(function(x){return x.group===m.group}):[m];
      var mm=m.group?chosenInGroup(list,m.group):m;
      var sel=MAT_SEL[mm.n]||{};
      var per=qpmFor(mm,model);
      var need=per?(+(qty*per).toFixed(2)).toLocaleString()+' '+mm.uom:'—';
      body+='<div class="matrow">'+
        '<div class="mat-id">'+
          (alts.length>1?
            '<select class="mat-alt" onchange="MAT_CHOICE[\''+m.group+
              '\']=+this.value;renderMatPanel()">'+
            alts.map(function(a){return '<option value="'+a.n+'"'+(a.n===mm.n?' selected':'')+'>'+
              a.name+' · '+a.size+(a.legacy?' (old)':'')+'</option>'}).join('')+'</select>'
            :'<b>'+mm.name+'</b>')+
          (mm.added?' <span class="tag t-rev">added</span>':'')+
          '<div class="mat-sz">'+mm.size+' &nbsp;·&nbsp; '+mm.uom+
            (per?' &nbsp;·&nbsp; '+per+' '+mm.uom+' per module':
             ' &nbsp;·&nbsp; <span class="tag t-rev">not in the consumption BOM</span>')+'</div>'+
          (mm.note?'<div class="mat-note">'+mm.note+'</div>':'')+
        '</div>'+
        '<div class="mat-f"><label>Make</label>'+
          '<select onchange="MAT_SEL['+mm.n+']=MAT_SEL['+mm.n+']||{};'+
            'MAT_SEL['+mm.n+'].vendor=this.value">'+
            '<option value="">— select —</option>'+
            mm.makes.map(function(v){return '<option'+(sel.vendor===v?' selected':'')+'>'+v+
              '</option>'}).join('')+'</select></div>'+
        (mm.cell?
          '<div class="mat-f"><label>Cell efficiency</label>'+
          '<select onchange="MAT_SEL['+mm.n+']=MAT_SEL['+mm.n+']||{};'+
            'MAT_SEL['+mm.n+'].eff=this.value">'+
            '<option value="">— select —</option>'+
            CELL_EFF.map(function(e){return '<option'+(sel.eff===e?' selected':'')+'>'+e+
              '</option>'}).join('')+'</select></div>':'')+
        '<div class="mat-f"><label>Batch / invoice <span>optional</span></label>'+
          '<input class="mono" value="'+(sel.batch||'')+'" placeholder="—" '+
          'oninput="MAT_SEL['+mm.n+']=MAT_SEL['+mm.n+']||{};'+
          'MAT_SEL['+mm.n+'].batch=this.value"></div>'+
        '<div class="mat-need"><label>Needed</label><b>'+need+'</b></div>'+
      '</div>';
    });
    if(body)out+='<div class="mat-cat">'+cat+'</div>'+body;
  });
  host.innerHTML=out;
}
/* ================= FQC — VERIFICATION ================= */
/* Station -> line binding. Declared from config, never read out of the serial
   and never chosen by the operator at login. */
var STATIONS=[{id:'FQC-01',name:'FQC A',line:'A',type:'FQC'},
              {id:'FQC-02',name:'FQC B',line:'B',type:'FQC'},
              {id:'PACK-01',name:'Packing A',line:'A',type:'PACK'},
              {id:'PACK-02',name:'Packing B',line:'B',type:'PACK'},
              {id:'DISPATCH-01',name:'Dispatch desk',line:'—',type:'DISPATCH'}];
var SOURCES=[{id:'SS-A',type:'SUNSIM_CSV',path:'\\\\SIM-A\\out\\',line:'A'},
             {id:'SS-B',type:'SUNSIM_CSV',path:'\\\\SIM-B\\out\\',line:'B'},
             {id:'ELVI-A',type:'ELVI_ROOT',path:'\\\\DESKTOP-T8ACD7V\\D\\EL',line:'A'},
             {id:'ELVI-B',type:'ELVI_ROOT',path:'\\\\DESKTOP-T8ACD7V\\D\\VI',line:'B'}];
function stationOf(id){return STATIONS.filter(function(s){return s.id===id})[0]||STATIONS[0]}

/* EL/VI categories exactly as the station files them, mapped to codes on ingest.
   Raw folder names are dirty (case, spaces, Buring/Burning) — never stored raw. */
var ELVI_CODES=[
 {raw:'OK',code:'OK',label:'OK',ng:false},
 {raw:'Cell Crack',code:'DF-CELLCRACK',label:'Cell Crack',ng:true},
 {raw:'No Power',code:'DF-NOPOWER',label:'No Power',ng:true},
 {raw:'Bussing Miss',code:'DF-BUSSMISS',label:'Bussing Miss',ng:true},
 {raw:'Ribbon  Short',code:'DF-RIBSHORT',label:'Ribbon Short',ng:true},
 {raw:'String Short',code:'DF-STRSHORT',label:'String Short',ng:true},
 {raw:'Ribbon   Missing',code:'DF-RIBMISS',label:'Ribbon Missing',ng:true},
 {raw:'Lead Open',code:'DF-LEADOPEN',label:'Lead Open',ng:true},
 {raw:'Buring',code:'DF-BURN',label:'Burning',ng:true},
 {raw:'Chip Cut',code:'DF-CHIPCUT',label:'Chip Cut',ng:true},
 {raw:'PATCHES',code:'DF-PATCH',label:'Patches',ng:true},
 {raw:'Other',code:'DF-OTHER',label:'Other',ng:true}];
var DISPOSITIONS=['Release','Downgrade','Rework','Scrap','Hold for review'];

/* Grade rules live as versioned data, not in code. */
var GRADE_RULES={version:'GR-2026-03',from:'01-08-2026',pmaxA:585,pmaxGY:540,
  forceBGY:['DF-NOPOWER','DF-STRSHORT','DF-BURN']};

/* Deterministic pseudo-evidence so the demo behaves consistently per serial. */
function evidenceFor(s){
  var d=derive(s);
  if(!d.ok)return {known:false};
  var n=0;for(var i=0;i<s.length;i++)n=(n*31+s.charCodeAt(i))>>>0;
  var pmaxFound=(n%11)!==0;                      /* ~9% graded blind */
  var base=parseInt(d.watt,10);
  var pmax=pmaxFound?+(base-14+(n%28)+((n>>5)%10)/10).toFixed(1):null;
  var cat=ELVI_CODES[(n>>3)%ELVI_CODES.length];
  if((n%3)!==0)cat=ELVI_CODES[0];                /* most are OK */
  var elviFound=(n%17)!==0;
  var srcLine=((n>>7)%23===0)?'B':'A';           /* rare cross-line disagreement */
  return {known:true,d:d,pmaxFound:pmaxFound,pmax:pmax,
    voc:pmaxFound?+(41.2+((n>>2)%9)/10).toFixed(2):null,
    isc:pmaxFound?+(17.8+((n>>4)%7)/10).toFixed(2):null,
    ff:pmaxFound?+(78.4+((n>>6)%5)/10).toFixed(1):null,
    elviFound:elviFound,cat:cat,srcLine:srcLine,
    img:'\\\\ICONTRACE\\elvi\\2026-08-21\\中班\\'+cat.raw.trim()+'\\'+s+'.jpg',
    orig:'\\\\DESKTOP-T8ACD7V\\D\\EL\\2026-08-21\\中班\\'+cat.raw.trim()+'\\'+s+'.jpg',
    captured:'21-08-2026 13:'+String(10+(n%49)).padStart(2,'0')};
}
function proposeGrade(ev){
  if(!ev.known)return {grade:null,why:'Serial is not in the allocation table'};
  if(!ev.elviFound&&!ev.pmaxFound)
    return {grade:null,why:'No Sun Simulator value and no EL/VI verdict — nothing to propose'};
  if(ev.elviFound&&GRADE_RULES.forceBGY.indexOf(ev.cat.code)>=0)
    return {grade:'BGY',why:'EL/VI verdict "'+ev.cat.label+'" forces BGY under '+GRADE_RULES.version};
  if(ev.elviFound&&ev.cat.ng)
    return {grade:'GY',why:'EL/VI verdict "'+ev.cat.label+'" is a downgrade under '+GRADE_RULES.version};
  if(!ev.pmaxFound)
    return {grade:null,why:'EL/VI is OK but Pmax was not found at grading time — '+
            'no band can be applied'};
  if(ev.pmax>=GRADE_RULES.pmaxA)
    return {grade:'A',why:'EL/VI OK and Pmax '+ev.pmax+' ≥ '+GRADE_RULES.pmaxA+' ('+GRADE_RULES.version+')'};
  if(ev.pmax>=GRADE_RULES.pmaxGY)
    return {grade:'GY',why:'Pmax '+ev.pmax+' is below the A band of '+GRADE_RULES.pmaxA};
  return {grade:'BGY',why:'Pmax '+ev.pmax+' is below the GY band of '+GRADE_RULES.pmaxGY};
}

var fqcCount=1266,fqcHold=null;
function fqcLookup(){
  var el=document.getElementById('fqcScan'),bc=el.value.trim().toUpperCase();
  if(!bc)return;
  var ev=evidenceFor(bc), pr=proposeGrade(ev), st=stationOf(USER.station);
  var crossLine=ev.known&&ev.elviFound&&ev.srcLine!==st.line;
  fqcHold={s:bc,ev:ev,pr:pr,cross:crossLine,st:st};
  el.disabled=true;
  var d=ev.known?ev.d:null;
  function cell(lbl,val,miss){
    return '<div><label>'+lbl+'</label><div class="lv'+(miss?' miss':'')+'">'+val+'</div></div>'}
  var gates=
    '<span class="gate '+(ev.known?'ok">✓ In allocation':'no">✕ Not in allocation — Needs Review')+'</span>'+
    '<span class="gate '+(ev.pmaxFound?'ok">✓ Sun Simulator '+ev.pmax+' W':
        'warn">⚑ Pmax not found at grading time')+'</span>'+
    '<span class="gate '+(ev.elviFound?'ok">✓ EL/VI verdict recorded':
        'warn">⚑ No EL/VI record')+'</span>'+
    '<span class="gate warn">⚑ Hi-Pot NOT_AVAILABLE (off-LAN)</span>'+
    (crossLine?'<span class="gate no">✕ EL/VI came from line '+ev.srcLine+
        ' but this is '+st.line+'-Line</span>':'');

  var blocked=!ev.known;
  document.getElementById('fqcPending').innerHTML=
   '<div class="pending'+(blocked?' blocked':'')+'">'+
   '<div class="pending-h"><span class="ph-t">'+(blocked?'Cannot grade':'Confirm or overrule')+
     '</span><span class="ph-s">'+bc+'</span><div class="ph-r">'+
     '<span class="tag t-mute">'+st.id+' · '+st.line+'-Line</span>'+
     (blocked?'<button class="btn btn-ghost btn-sm" onclick="fqcToReview()">Send to Needs Review</button>':
      '<span class="tag t-mute">Space to confirm</span>'+
      '<button class="btn btn-solar btn-sm" onclick="fqcCommit(0)">Confirm proposal</button>'+
      '<button class="btn btn-ghost btn-sm" onclick="fqcShowOverride()">Overrule…</button>')+
     '<button class="btn btn-ghost btn-sm" onclick="fqcCancel()">Discard</button></div></div>'+

   '<div class="lookup">'+
     cell('Customer',ev.known?'SAI BABUJI PROJECTS':'not found',!ev.known)+
     cell('Model',d?d.model:'—',!ev.known)+
     cell('Build instance',ev.known?'1 of 1':'—')+
     cell('Serial printed',d?('v'+d.fmt+' · '+d.date+' · shift '+d.shift):'—')+
     cell('Allocation',ev.known?'Pre-shared':'—')+
     cell('Line (station config)',st.id+' · '+st.line+'-Line')+
   '</div>'+

   '<div class="lookup" style="border-top:1px solid var(--line2)">'+
     cell('Pmax',ev.pmaxFound?(ev.pmax+' W'):'not found at grading time',!ev.pmaxFound)+
     cell('Voc',ev.pmaxFound?ev.voc+' V':'—',!ev.pmaxFound)+
     cell('Isc',ev.pmaxFound?ev.isc+' A':'—',!ev.pmaxFound)+
     cell('Fill factor',ev.pmaxFound?ev.ff+' %':'—',!ev.pmaxFound)+
     cell('EL/VI verdict',ev.elviFound?ev.cat.label:'no record',!ev.elviFound)+
     '<div><label>EL/VI image</label><div class="lv">'+
       (ev.elviFound?'<button class="lnk" onclick="showImg()">View image</button>':'—')+
     '</div></div>'+
   '</div>'+
   '<div class="gates">'+gates+'</div>'+

   (blocked?'':
   '<div class="card-b" style="border-top:1px solid var(--line2);background:'+
     (pr.grade?'var(--pass-lt)':'var(--review-lt)')+'">'+
     '<div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap">'+
       '<div><label style="font-size:9.5px;font-weight:700;color:var(--ink3);'+
         'text-transform:uppercase;letter-spacing:.6px">Proposed grade</label>'+
         '<div style="font-family:var(--f-mono);font-size:30px;font-weight:700;line-height:1;'+
         'color:'+(pr.grade==='A'?'var(--pass)':pr.grade?'var(--fail)':'var(--review)')+'">'+
         (pr.grade||'none')+'</div></div>'+
       '<div style="font-size:12px;max-width:560px"><b>Why</b><br>'+pr.why+'</div>'+
     '</div></div>'+
   '<div id="fqcOverride"></div>')+
   '</div>';
}
function fqcShowOverride(){
  if(!fqcHold)return;
  var ev=fqcHold.ev;
  document.getElementById('fqcOverride').innerHTML=
   '<div class="card-f" style="border-top:1px solid var(--line2);align-items:flex-start">'+
     '<div class="fld" style="margin:0;min-width:120px"><label>Final grade</label>'+
       '<select id="ovGrade"><option value="">— pick —</option><option>A</option>'+
       '<option>GY</option><option>BGY</option></select></div>'+
     '<div class="fld" style="margin:0;min-width:210px"><label>Override reason (required)</label>'+
       '<select id="ovReason"><option value="">— coded reason —</option>'+
       '<option>OV-RETEST — retested, value differs</option>'+
       '<option>OV-IMAGE — image reviewed, verdict wrong</option>'+
       '<option>OV-EVIDENCE — evidence missing, judged visually</option>'+
       '<option>OV-CUST — customer accepts this condition</option>'+
       '<option>OV-QUALITY — quality engineer instruction</option></select></div>'+
     '<div class="fld" style="margin:0;min-width:180px"><label>Defect (what is wrong)</label>'+
       '<select id="ovDefect"><option value="">— none —</option>'+
       ELVI_CODES.filter(function(c){return c.ng}).map(function(c){
         return '<option value="'+c.code+'">'+c.code+' — '+c.label+'</option>'}).join('')+
       '</select></div>'+
     '<div class="fld" style="margin:0;min-width:160px"><label>Disposition (what we do)</label>'+
       '<select id="ovDisp">'+DISPOSITIONS.map(function(x){
         return '<option>'+x+'</option>'}).join('')+'</select></div>'+
     '<button class="btn btn-danger" style="align-self:flex-end" onclick="fqcCommit(1)">'+
       'Record override</button>'+
   '</div>'+
   '<div class="note n-warn" style="margin:0 13px 13px"><span>⚑</span><span>Defect and disposition '+
     'are separate fields. The defect says what is wrong; the disposition says what we do about '+
     'it. Both are stored, with your name and the coded reason.</span></div>';
}
function showImg(){
  if(!fqcHold)return;
  var ev=fqcHold.ev;
  document.getElementById('mdlTitle').textContent='EL/VI image · '+fqcHold.s;
  document.getElementById('mdlSub').textContent=
    'Verdict "'+ev.cat.label+'" · captured '+ev.captured;
  modalMode(true);
  document.getElementById('mdlGeneric').innerHTML=
    '<div class="card" style="margin:0">'+
    '<div style="padding:22px;text-align:center;background:#0E1A2B;color:#8FB4D4">'+
      '<div style="font-size:34px;opacity:.5">▣</div>'+
      '<div style="margin-top:8px;font-size:12px">EL/VI image renders here at full size</div>'+
      '<div class="mono" style="font-size:10.5px;margin-top:10px;color:#5F7C99">'+ev.img+'</div>'+
    '</div>'+
    '<div style="padding:13px 16px;font-size:12px;line-height:1.7">'+
      '<b>ICON TRACE copy is authoritative.</b> The inspection PC is backed up and cleared, so '+
      'images are copied into ICON TRACE storage on ingest. Files sit on disk with the path in '+
      'the database — never as MySQL BLOBs. At ~4–5 MB and ~2,000 modules a day this is '+
      '~9 GB/day.<br><span style="color:var(--ink3)">Original path (provenance only): </span>'+
      '<span class="mono" style="font-size:10.5px">'+ev.orig+'</span><br>'+
      '<span style="color:var(--ink3)">Ingest is append-and-update, never purge-on-absence.</span>'+
    '</div></div>';
  document.getElementById('mdl').classList.add('on');
}
function fqcToReview(){
  if(!fqcHold)return;
  toast(fqcHold.s+' sent to Needs Review — unknown serials are never given a fabricated record.');
  fqcCancel();
}
function fqcCancel(){
  fqcHold=null;document.getElementById('fqcPending').innerHTML='';
  var el=document.getElementById('fqcScan');el.disabled=false;el.value='';el.focus();
}
function fqcCommit(isOverride){
  if(!fqcHold)return;
  var h=fqcHold,ev=h.ev,pr=h.pr,fin=pr.grade,reason='',defect='—',disp='—';
  if(isOverride){
    var g=document.getElementById('ovGrade'),r=document.getElementById('ovReason');
    if(!g||!g.value){toast('Pick the final grade before recording an override.');return}
    if(!r||!r.value){toast('A coded override reason is required — this is not optional.');return}
    fin=g.value;reason=r.value.split(' — ')[0];
    defect=document.getElementById('ovDefect').value||'—';
    disp=document.getElementById('ovDisp').value;
  }else{
    if(!fin){toast('There is no proposal to confirm. Overrule with a reason instead.');return}
    if(ev.elviFound&&ev.cat.ng){defect=ev.cat.code;disp='Downgrade'}
    else disp='Release';
  }
  var t=new Date(),p=function(n){return String(n).padStart(2,'0')};
  var flags=[];
  if(isOverride)flags.push('<span class="tag t-rev">Overridden</span>');
  if(!ev.pmaxFound)flags.push('<span class="tag t-rev">Graded blind</span>');
  if(h.cross)flags.push('<span class="tag t-fail">Line mismatch</span>');
  var tr=document.createElement('tr');
  tr.innerHTML='<td class="mono">'+p(t.getHours())+':'+p(t.getMinutes())+':'+p(t.getSeconds())+'</td>'+
    '<td class="mono">'+h.s+'</td><td class="mono">1</td>'+
    '<td class="mono">'+(ev.d?ev.d.model:'—')+'</td>'+
    '<td class="num"'+(ev.pmaxFound?'':' style="color:var(--fail)"')+'>'+
      (ev.pmaxFound?ev.pmax:'not found')+'</td>'+
    '<td>'+(ev.elviFound?ev.cat.label:'—')+'</td>'+
    '<td>'+(pr.grade||'—')+'</td>'+
    '<td><span class="tag '+(fin==='A'?'t-pass':'t-fail')+'">'+fin+'</span></td>'+
    '<td class="mono" style="font-size:10.5px">'+defect+'</td><td>'+disp+'</td>'+
    '<td>'+flags.join(' ')+'</td>';
  var tb=document.getElementById('fqcRows');
  tb.insertBefore(tr,tb.firstChild);
  if(tb.children.length>10)tb.removeChild(tb.lastElementChild);
  fqcCount++;document.getElementById('fqcN').textContent=fqcCount.toLocaleString();
  if(isOverride)toast('Recorded '+fin+' — override reason '+reason+' stored against '+USER.name+'.');
  else toast('Confirmed '+fin+'. Evidence snapshotted onto the record.');
  fqcCancel();
}

/* ================= PALLET ================= */
var cap=36,filled=0,grade='A',packHold=null,packed=[];
function buildSlots(){
  var g=document.getElementById('slots');g.innerHTML='';
  for(var i=1;i<=cap;i++){
    var d=document.createElement('div');d.className='slot empty';
    d.innerHTML='<span class="sn">'+String(i).padStart(2,'0')+'</span>'+
                '<span class="sv">— — — — — — —</span>';
    g.appendChild(d);}
  filled=0;packed=[];paintCount();
}
function paintCount(){
  document.getElementById('pfill').textContent=filled;
  document.getElementById('pfill2').textContent=filled;
  document.getElementById('pcap').textContent=cap;
  document.getElementById('pcap2').textContent=cap;
  document.getElementById('prem').textContent=cap-filled;
}
function setCap(){cap=parseInt(document.getElementById('capSel').value,10);buildSlots()}
function setGrade(btn,g){
  grade=g;btn.parentNode.querySelectorAll('button').forEach(function(b){b.classList.remove('on')});
  btn.classList.add('on');document.getElementById('metaGrade').textContent=g;
}
function binTog(){
  var on=document.getElementById('binOn').checked,n=document.getElementById('binNo').value;
  var el=document.getElementById('metaBin');
  el.style.display=on?'':'none';el.innerHTML='Bin <b>BIN-'+n+'</b>';
}
function packLookup(){
  var el=document.getElementById('packScan'),bc=el.value.trim().toUpperCase();
  if(!bc)return;
  if(filled>=cap){toast('This box is full. Save it before scanning more.');el.value='';return}
  var d=derive(bc),fqcDone=d.ok;
  var modCat=fqcDone?(bc.slice(-1)==='9'?'GY':'A'):null;
  var already=packed.indexOf(bc)>=0;
  var gradeOK=fqcDone&&modCat===grade;
  packHold={s:bc,d:d,ok:fqcDone&&!already&&gradeOK};
  el.disabled=true;
  var gates='<span class="gate '+(fqcDone?'ok">✓ Went through FQC':'no">✕ No FQC record')+'</span>'+
    (fqcDone?'<span class="gate '+(modCat==='A'?'ok">✓ Category A':'warn">⚑ Category '+modCat)+'</span>':'')+
    '<span class="gate '+(already?'no">✕ Already in this box':'ok">✓ Not yet packed')+'</span>'+
    '<span class="gate '+(gradeOK?'ok">✓ Matches '+grade+' box':'no">✕ '+
      (modCat?'Category '+modCat+' cannot go in a '+grade+' box':'Grade unknown'))+'</span>';
  document.getElementById('packPending').innerHTML=
    '<div class="pending'+(packHold.ok?'':' blocked')+'">'+
    '<div class="pending-h"><span class="ph-t">'+(packHold.ok?'Confirm to add':'Cannot add')+'</span>'+
    '<span class="ph-s">'+bc+'</span><div class="ph-r">'+
    (packHold.ok?'<span class="tag t-mute">Space to add</span>'+
      '<button class="btn btn-solar btn-sm" onclick="packCommit()">Add to box</button>':'')+
    '<button class="btn btn-ghost btn-sm" onclick="packCancel()">Discard</button></div></div>'+
    '<div class="lookup">'+
      '<div><label>Customer</label><div class="lv'+(fqcDone?'':' miss')+'">'+
        (fqcDone?CUST:'not found')+'</div></div>'+
      '<div><label>Wattage</label><div class="lv mono">'+(d.watt?d.watt+'W':'—')+'</div></div>'+
      '<div><label>Model</label><div class="lv mono'+(d.ok?'':' miss')+'">'+
        (d.ok?d.model:'not allowed')+'</div></div>'+
      '<div><label>FQC category</label><div class="lv">'+(modCat||'—')+'</div></div>'+
      '<div><label>FQC date</label><div class="lv mono">'+(fqcDone?'19-08-2026':'—')+'</div></div>'+
      '<div><label>Slot</label><div class="lv mono">'+
        (packHold.ok?String(filled+1).padStart(2,'0'):'—')+'</div></div>'+
    '</div><div class="gates">'+gates+'</div></div>';
}
function packCancel(){
  packHold=null;document.getElementById('packPending').innerHTML='';
  var el=document.getElementById('packScan');el.disabled=false;el.value='';el.focus();
}
function packCommit(){
  if(!packHold||!packHold.ok)return;
  addSlot(packHold.s);
  if(packHold.d.ok)document.getElementById('metaModel').textContent=packHold.d.model;
  packCancel();
}
function addSlot(serial){
  if(filled>=cap)return false;
  var s=document.getElementById('slots').children[filled];
  s.className='slot fill hot';
  s.innerHTML='<span class="sn">'+String(filled+1).padStart(2,'0')+'</span>'+
              '<span class="sv">'+serial+'</span>'+
              '<button class="sx" onclick="pullSlot('+filled+')">×</button>';
  setTimeout(function(){s.classList.remove('hot')},460);
  packed.push(serial);filled++;paintCount();return true;
}
function pullSlot(i){var all=packed.slice();all.splice(i,1);buildSlots();
  all.forEach(function(s){addSlot(s)})}
function resetPallet(){buildSlots()}
function fillDemo(){
  var base='ICON590G1202121001',i=filled;
  (function step(){if(i>=cap)return;addSlot(bumpSerial(base,i));i++;setTimeout(step,60)})();
}

/* ================= REPACK ================= */
var SRC=[
 {id:'A031',cust:'SAI BABUJI',model:'ISEN590-G2X',g:'A',q:36,lock:false,base:'ICON590G1202121001'},
 {id:'A034',cust:'SAI BABUJI',model:'ISEN590-G2X',g:'A',q:36,lock:false,base:'ICON590G1202121101'},
 {id:'A035',cust:'SAI BABUJI',model:'ISEN590-G2X',g:'A',q:22,lock:false,base:'ICON590G1202121201'},
 {id:'A029',cust:'SG MEDA',model:'ISEN625-G12R',g:'A',q:36,lock:false,base:'ICON625R1110152001'},
 {id:'A026',cust:'SAI BABUJI',model:'ISEN590-G2X',g:'A',q:36,lock:true,lockWhy:'On CHN-455'}];
var picked={},pool=[],targets=[],activeT=0,nextBox=44,freshCount=0,srcQ='';
function srcFilter(v){srcQ=(v||'').toUpperCase();renderSrc()}
function renderSrc(){
  document.getElementById('srcList').innerHTML=SRC.filter(function(b){
    return !srcQ||b.id.indexOf(srcQ)>=0;
  }).map(function(b){
    var i=SRC.indexOf(b);
    return '<label class="srcrow'+(b.lock?' lock':(picked[i]?' pick':''))+'">'+
      '<input type="checkbox" '+(b.lock?'disabled':'')+(picked[i]?' checked':'')+
      ' onchange="pickSrc('+i+',this.checked)">'+
      '<span class="si"><b>'+b.id+'</b><span>'+(b.lock?b.lockWhy+' · locked':
        b.cust+' · '+b.model+' · '+b.g)+'</span></span>'+
      '<span class="sq">'+b.q+'</span></label>';
  }).join('')||'<div class="empty-state"><p>No box matches that filter.</p></div>';
}
function pickSrc(i,on){
  picked[i]=on;renderSrc();
  var idx=Object.keys(picked).filter(function(k){return picked[k]});
  var boxes=idx.length,mods=idx.reduce(function(a,k){return a+SRC[k].q},0);
  document.getElementById('selBoxes').textContent=boxes;
  document.getElementById('selMods').textContent=mods;
  document.getElementById('goStep2').disabled=boxes===0;
  var models={};idx.forEach(function(k){models[SRC[k].model]=1});
  document.getElementById('selWarn').innerHTML=Object.keys(models).length>1?
    '<div class="note n-warn" style="font-size:11.5px"><span>⚑</span><span>You have opened boxes '+
    'with different models. They cannot be mixed into one new box.</span></div>':'';
}
function clearSrc(){picked={};pool=[];targets=[];freshCount=0;renderSrc();pickSrc(-1,false)}
function repackReset(){
  if(!confirm('Reset the whole repack session? Nothing has been saved, so this just clears the screen.'))return;
  picked={};pool=[];targets=[];activeT=0;freshCount=0;srcQ='';
  document.getElementById('selBoxes').textContent='0';
  document.getElementById('selMods').textContent='0';
  document.getElementById('goStep2').disabled=true;
  document.getElementById('selWarn').innerHTML='';
  renderSrc();repackStep(1);toast('Repack session cleared.');
}
function repackStep(n){
  if(n===1&&pool.length===0&&targets.length===0){/* fresh start */}
  [1,2,3].forEach(function(i){
    document.getElementById('rs'+i).classList.toggle('on',i===n);
    var s=document.getElementById('st'+i);
    s.classList.toggle('on',i===n);s.classList.toggle('done',i<n);});
  if(n===2)buildPool();
  if(n===3)buildConfirm();
  document.querySelector('.main').scrollTop=0;
  if(n===2)setTimeout(function(){document.getElementById('rpScan').focus()},60);
}
function buildPool(){
  var idx=Object.keys(picked).filter(function(k){return picked[k]});
  var want={};idx.forEach(function(k){want[SRC[k].id]=1});
  var placedFrom={};targets.forEach(function(t){t.items.forEach(function(m){placedFrom[m.s]=1})});
  var have={};pool.forEach(function(m){have[m.s]=1});
  pool=pool.filter(function(m){return m.fresh||want[m.from]});
  idx.forEach(function(k){
    var b=SRC[k];
    for(var i=0;i<b.q;i++){
      var s=bumpSerial(b.base,i);
      if(!have[s]&&!placedFrom[s])pool.push({s:s,from:b.id,fresh:false,g:b.g});}});
  if(targets.length===0)addTarget();
  renderPool();renderTargets();
}
function renderPool(){
  document.getElementById('poolN').textContent=pool.length;
  var placed=targets.reduce(function(a,t){return a+t.items.length},0);
  document.getElementById('placedN').textContent=placed;
  document.getElementById('freshN').textContent=freshCount;
  document.getElementById('pool').innerHTML=pool.length?pool.map(function(m,i){
    return '<button class="mchip'+(m.fresh?' fresh':'')+'" onclick="poolClick('+i+')" '+
      'title="From '+m.from+' — click, or Tab to it and press Enter, to place it in the '+
      'active box">'+m.s+'<small>'+(m.fresh?'fresh':m.from.slice(-5))+'</small></button>';
  }).join(''):'<div class="empty-state" style="padding:18px"><p>Nothing loose — every expected '+
    'module has been placed in a box.</p></div>';
}
function renderTargets(){
  document.getElementById('targets').innerHTML=targets.map(function(t,i){
    var pct=Math.round(t.items.length/t.cap*100);
    return '<div class="tbox'+(i===activeT?' active':'')+'">'+
      '<div class="tbox-h"><b onclick="setActive('+i+')">'+t.id+'</b><div class="tg">'+
      '<span class="tag '+(t.g==='A'?'t-pass':'t-rev')+'">'+t.g+'</span>'+
      (i===activeT?'<span class="tag t-solar">Active</span>':
        '<button class="btn btn-ghost btn-sm" onclick="setActive('+i+')">Use</button>')+
      '<button class="btn btn-ghost btn-sm" onclick="removeTarget('+i+')" title="Remove this box">×</button>'+
      '</div></div><div class="mini-bar"><i style="width:'+pct+'%"></i></div>'+
      '<div class="tbox-c">'+t.items.length+' of '+t.cap+
        (t.items.length===t.cap?' · full':t.items.length===0?' · empty':'')+'</div>'+
      '<div class="tbox-items">'+t.items.map(function(m,j){
        return '<span class="mchip">'+m.s+
          '<button onclick="toPool('+i+','+j+')" title="Take back out">×</button></span>';
      }).join('')+'</div></div>';
  }).join('');
  var a=targets[activeT];
  document.getElementById('activeName').textContent=a?a.id:'— add a box first —';
}
function addTarget(){
  var c=parseInt((document.getElementById('rpCap')||{}).value||cap,10);
  targets.push({id:'A0'+(nextBox++),cap:c,g:'A',items:[]});
  activeT=targets.length-1;renderTargets();renderPool();
}
function removeTarget(i){
  var t=targets[i];
  if(t.items.length&&!confirm(t.id+' has '+t.items.length+
    ' module(s). Remove the box and send them back to the loose pool?'))return;
  t.items.forEach(function(m){pool.push(m)});
  targets.splice(i,1);
  if(activeT>=targets.length)activeT=Math.max(0,targets.length-1);
  renderPool();renderTargets();
  toast(t.id+' removed. Its number is released because the box was never saved.');
}
function setActive(i){activeT=i;renderTargets()}
function toPool(ti,mi){pool.push(targets[ti].items.splice(mi,1)[0]);renderPool();renderTargets()}
/* place a loose module by clicking it (or Tab + Enter) instead of scanning */
function poolClick(i){
  if(!targets.length){rpMsg('bad','Add a new box first — there is nowhere to put this module.');return}
  var t=targets[activeT];
  if(t.items.length>=t.cap){
    rpMsg('bad',t.id+' is full ('+t.cap+'). Make another box active first.');return}
  var m=pool.splice(i,1)[0];
  t.items.push(m);renderPool();renderTargets();
  rpMsg('ok',m.s+' → '+t.id+'  ·  from '+m.from+'  ·  '+t.items.length+' of '+t.cap);
}
function poolAll(){
  if(!targets.length){rpMsg('bad','Add a new box first.');return}
  var t=targets[activeT],room=t.cap-t.items.length;
  if(room<=0){rpMsg('bad',t.id+' is already full.');return}
  var moved=pool.splice(0,room);
  t.items=t.items.concat(moved);renderPool();renderTargets();
  rpMsg('ok',moved.length+' module(s) placed in '+t.id+'  ·  '+t.items.length+' of '+t.cap);
}
function rpMsg(cls,txt){
  document.getElementById('rpMsg').innerHTML='<div class="scan-msg '+cls+'">'+
    (cls==='ok'?'✓':cls==='warn'?'⚑':'✕')+'<span>'+txt+'</span></div>';
}
function rpScanGo(){
  var el=document.getElementById('rpScan'),bc=el.value.trim().toUpperCase();
  el.value='';el.focus();
  if(!bc)return;
  if(!targets.length){rpMsg('bad','Add a new box first — there is nowhere to put this module.');return}
  var t=targets[activeT];
  /* already placed in some target? */
  for(var i=0;i<targets.length;i++){
    for(var j=0;j<targets[i].items.length;j++){
      if(targets[i].items[j].s===bc){
        rpMsg('bad',bc+' is already in '+targets[i].id+'.');return;}}}
  /* in the expected loose pool? */
  var pi=-1;
  for(var k=0;k<pool.length;k++){if(pool[k].s===bc){pi=k;break}}
  if(pi>=0){
    if(t.items.length>=t.cap){rpMsg('bad',t.id+' is full ('+t.cap+
      '). Make it inactive and use another box.');return}
    var m=pool.splice(pi,1)[0];
    t.items.push(m);renderPool();renderTargets();
    rpMsg('ok',bc+' → '+t.id+'  ·  from '+m.from+'  ·  '+t.items.length+' of '+t.cap);
    return;}
  /* not in pool — work out why */
  var d=derive(bc);
  if(!d.ok){rpMsg('bad',bc+' — '+d.why+'. Not a Unit-2 module.');return}
  var inOther=SRC.filter(function(b){
    if(picked[SRC.indexOf(b)])return false;
    var idx0=serialIndex(parseSerial(b.base)),idx1=idx0+b.q-1,me=serialIndex(parseSerial(bc));
    return me>=idx0&&me<=idx1;})[0];
  if(inOther){
    rpMsg('bad',bc+' is packed in '+inOther.id+
      (inOther.lock?' which is on a challan and cannot be opened.':
       '. Open that box in step 1 before scanning this module.'));return;}
  /* treat as fresh FG */
  if(t.items.length>=t.cap){rpMsg('bad',t.id+' is full.');return}
  t.items.push({s:bc,from:'Fresh FG',fresh:true,g:'A'});
  freshCount++;renderPool();renderTargets();
  rpMsg('warn',bc+' added as fresh stock (was not in any opened box) → '+t.id+'.');
}
function buildConfirm(){
  var idx=Object.keys(picked).filter(function(k){return picked[k]});
  var used=targets.filter(function(t){return t.items.length});
  document.getElementById('geneal').innerHTML=
    '<div class="gcol">'+idx.map(function(k){
      return '<div class="gbox close">'+SRC[k].id+' · '+SRC[k].q+'</div>'}).join('')+
    '</div><div class="garrow">→</div><div class="gcol">'+
    (used.map(function(t){return '<div class="gbox newb">'+t.id+' · '+t.items.length+'</div>'}).join('')
      ||'<div class="gbox">no new box yet</div>')+'</div>'+
    (pool.length?'<div class="garrow">+</div><div class="gcol">'+
      '<div class="gbox">'+pool.length+' back to stock</div></div>':'');
  document.getElementById('confirmRows').innerHTML=used.length?used.map(function(t){
    var froms={};t.items.forEach(function(m){froms[m.from]=(froms[m.from]||0)+1});
    return '<tr><td class="mono">'+t.id+'</td>'+
      '<td><span class="tag '+(t.g==='A'?'t-pass':'t-rev')+'">'+t.g+'</span></td>'+
      '<td class="num">'+t.items.length+'</td>'+
      '<td style="font-size:11.5px">'+Object.keys(froms).map(function(f){
        return f+' ('+froms[f]+')'}).join(', ')+'</td></tr>';
  }).join(''):'<tr><td colspan="4"><div class="empty-state"><p>No box has any modules yet.</p></div></td></tr>';
  document.getElementById('confirmWarn').innerHTML=pool.length?
    '<div class="note n-warn" style="font-size:11.5px"><span>⚑</span><span>'+pool.length+
    ' expected module(s) were never scanned. They will be recorded as removed and returned '+
    'to unpacked stock. Check the physical count before completing.</span></div>':'';
}

/* ================= MANAGEMENT OVERVIEW ================= */
/* Management filters actually filter. Anything that cannot be filtered from the
   data present says so, rather than silently ignoring the control. */
function mgF(){
  var g=function(id){var e=document.getElementById(id);return e?e.value:''};
  return {from:g('mgFrom'),to:g('mgTo'),cust:g('mgCust'),model:g('mgModel'),
          watt:g('mgWatt'),line:g('mgLine'),shift:g('mgShift')};
}
function mgReset(){
  [['mgCust','All customers'],['mgModel','All models'],['mgWatt','All'],
   ['mgLine','Both lines'],['mgShift','All shifts']].forEach(function(x){
    var e=document.getElementById(x[0]); if(e)e.value=x[1];});
  document.getElementById('mgFrom').value='2026-08-01';
  document.getElementById('mgTo').value='2026-08-21';
  renderMgmt();toast('Filters reset.');
}
function mgPeriod(f){
  var el=document.getElementById('mgPeriod'); if(!el)return 1;
  if(!f.from){el.value='— pick a From date —';return 0}
  if(!f.to||f.to===f.from){el.value=fmtD(f.from)+' · single day';return 1}
  if(f.to<f.from){el.value='To is before From';return 0}
  var days=Math.round((new Date(f.to)-new Date(f.from))/86400000)+1;
  el.value=fmtD(f.from)+' → '+fmtD(f.to)+' · '+days+' days';
  return days;
}
function mgRows(){
  var f=mgF();
  return PROD.filter(function(r){
    if(f.cust!=='All customers'&&r.cust!==f.cust)return false;
    if(f.model!=='All models'&&r.model!==f.model)return false;
    if(f.watt!=='All'){
      var m=MODELS.filter(function(x){return x.model===r.model})[0];
      if(!m||m.watt+'W'!==f.watt)return false;
    }
    return true;
  });
}
function mgShiftData(){
  var f=mgF();
  return SHIFT_ROWS.filter(function(r){
    if(f.shift!=='All shifts'&&r.s!==f.shift)return false;
    if(f.model!=='All models'&&r.m!==f.model)return false;
    if(f.watt!=='All'&&r.w!==f.watt)return false;
    return true;
  });
}
function renderMgmt(){
  if(!document.getElementById('mk1'))return;
  var f=mgF(), days=mgPeriod(f);
  var rows=mgRows(), s=function(k){return rows.reduce(function(a,r){return a+r[k]},0)};
  var alloc=s('alloc')||0,prod=s('prod'),fqc=s('fqc'),rej=s('rej'),packed=s('packed'),disp=s('disp');
  var running=prod-fqc,pending=packed-disp,remaining=alloc-prod,inRepack=Math.max(fqc-rej-packed,0);
  var kw=Math.round(disp*0.59);
  var g=function(id){return document.getElementById(id)};

  var active=[];
  if(f.cust!=='All customers')active.push(f.cust);
  if(f.model!=='All models')active.push(f.model);
  if(f.watt!=='All')active.push(f.watt);
  if(f.line!=='Both lines')active.push(f.line);
  if(f.shift!=='All shifts')active.push('Shift '+f.shift);
  g('mgFilterNote').innerHTML=active.length?
    '<div class="note n-info" style="font-size:11.5px"><span>&#9432;</span><span>Filtered by <b>'+
    active.join('</b>, <b>')+'</b>'+(days?' over '+days+' day'+(days>1?'s':''):'')+
    '. Clear with Reset.</span></div>':'';

  if(!rows.length){
    ['mk1','mk2','mk3','mk4','mk5'].forEach(function(id){g(id).textContent='0'});
    g('mk2d').textContent='—';g('mk3d').textContent='—';
    g('mgSections').innerHTML='<tr><td colspan="5"><div class="empty-state">'+
      '<p>No data matches these filters.</p></div></td></tr>';
    g('mgShiftRows').innerHTML='<tr><td colspan="8"><div class="empty-state">'+
      '<p>Nothing inspected under these filters.</p></div></td></tr>';
    g('mgStockRows').innerHTML='';g('mgBlocked').innerHTML='';g('mgTrend').innerHTML='';
    drawDonut('mgDonut','mgLegend',[{n:'No data',v:1,c:C.grey}],'0','allocated');
    drawDonut('mgQDonut','mgQLegend',[{n:'No data',v:1,c:C.grey}],'0','inspected');
    return;
  }

  g('mk1').textContent=alloc.toLocaleString();
  g('mk2').textContent=prod.toLocaleString();
  g('mk2d').textContent=(prod/alloc*100).toFixed(0)+'% of allocated';
  g('mk3').textContent=disp.toLocaleString();
  g('mk3d').textContent=pending.toLocaleString()+' packed, awaiting a vehicle';
  g('mk4').textContent=kw.toLocaleString();

  drawDonut('mgDonut','mgLegend',[
    {n:'Dispatched',v:disp,c:C.green},
    {n:'Packed, awaiting dispatch',v:pending,c:C.navy},
    {n:'Passed FQC, not packed',v:inRepack,c:C.blue},
    {n:'Rejected at FQC',v:rej,c:C.red},
    {n:'Produced, not yet at FQC',v:running,c:C.amber},
    {n:'Not yet produced',v:remaining,c:C.grey}
  ],(alloc/1000).toFixed(1)+'k','allocated');

  /* shift-wise production & quality */
  var sr=mgShiftData();
  var tot=sr.reduce(function(a,r){return a+r.t},0),
      ok=sr.reduce(function(a,r){return a+r.ok},0),
      rj=sr.reduce(function(a,r){return a+r.r},0);
  g('mgShiftRows').innerHTML=sr.length?sr.map(function(r,i){
    var span=(i===0||sr[i-1].s!==r.s);
    var cnt=sr.filter(function(x){return x.s===r.s}).length;
    var pct=(r.r/r.t*100).toFixed(2);
    return '<tr>'+(span?'<td rowspan="'+cnt+'" class="s'+r.s+'">'+r.s+'</td>':'')+
      '<td class="mono">'+r.w+'</td><td class="mono">'+r.m+'</td>'+
      '<td class="num">'+r.t.toLocaleString()+'</td><td class="num">'+r.ok.toLocaleString()+'</td>'+
      '<td class="num">'+r.r+'</td>'+
      '<td><div class="bar-wrap"><div class="bar"><i style="width:'+Math.min(pct*12,100)+
        '%"></i></div><span class="mono">'+pct+'%</span></div></td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="openModules({title:\'Shift '+r.s+' · '+r.w+'\',shift:\''+r.s+'\'})">View '+
      r.t.toLocaleString()+'</button></td></tr>';
  }).join(''):'<tr><td colspan="8"><div class="empty-state">'+
    '<p>Nothing inspected under these filters.</p></div></td></tr>';
  g('mgsT').textContent=tot.toLocaleString();g('mgsOK').textContent=ok.toLocaleString();
  g('mgsRej').textContent=rj;g('mgsPc').textContent=tot?(rj/tot*100).toFixed(2)+'%':'—';

  var a=ok,gy=Math.round(rj*0.68),bgy=rj-Math.round(rj*0.68);
  drawDonut('mgQDonut','mgQLegend',[
    {n:'A — passed',v:a,c:C.green},{n:'GY — downgraded',v:gy,c:C.amber},
    {n:'BGY — rejected',v:bgy,c:C.red}],tot.toLocaleString(),'inspected');
  g('mgYield').textContent=tot?(a/tot*100).toFixed(2)+'% yield':'—';

  g('mgStockRows').innerHTML=rows.map(function(r){
    return '<tr><td>'+r.cust+'</td><td class="mono">'+r.model+'</td>'+
      '<td class="num">'+r.packed.toLocaleString()+'</td>'+
      '<td class="num" style="color:var(--brand)">'+(r.packed-r.disp).toLocaleString()+'</td>'+
      '<td class="num" style="color:var(--pass)">'+r.disp.toLocaleString()+'</td>'+
      '<td class="num">'+Math.round(r.disp*0.59).toLocaleString()+'</td></tr>';
  }).join('');

  var yieldPc=(100-rej/Math.max(fqc,1)*100).toFixed(2);
  var SECT=[
    ['Planning','Serials allocated',alloc.toLocaleString(),'ok','plan'],
    ['Production','Produced this period',prod.toLocaleString(),'ok','proddash'],
    ['Loss of production','Events still open','2','bad','loss'],
    ['FQC','Yield',yieldPc+'%',(+yieldPc>=97?'ok':'warn'),'dash'],
    ['Packing','Boxes awaiting challan','21','warn','packdash'],
    ['Dispatch','Dispatched this period',disp.toLocaleString(),'ok','disp'],
    ['Hold & deviation','Modules frozen','1,877','bad','hold'],
    ['Drafts','Open, holding material',String(DRAFTS.length),'warn','drafts'],
    ['Needs review','Unresolved flags','5','warn','review']];
  g('mgSections').innerHTML=SECT.map(function(r){
    var tag=r[3]==='ok'?'t-pass':r[3]==='warn'?'t-rev':'t-fail';
    var lbl=r[3]==='ok'?'On track':r[3]==='warn'?'Watch':'Action';
    return '<tr><td style="font-weight:600">'+r[0]+'</td><td>'+r[1]+'</td>'+
      '<td class="num" style="font-weight:700">'+r[2]+'</td>'+
      '<td><span class="tag '+tag+'">'+lbl+'</span></td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="go(\'' +r[4]+ '\')">Open</button></td></tr>';
  }).join('');

  var BLOCK=[
    ['Serials in Needs Review','FQC',5,'20-08 11:22','review'],
    ['Packed with no FQC record','Packing',2,'21-08 08:14','review'],
    ['Boxes on hold','Quality',3,'20-08 16:05','hold'],
    ['Downtime events still open','Production',2,'21-08 14:05','loss'],
    ['Challans blocked by verification','Dispatch',4,'21-08 15:02','challan'],
    ['Drafts holding material','All',DRAFTS.length,'20-08 16:44','drafts']];
  g('mgBlocked').innerHTML=BLOCK.map(function(b){
    return '<tr><td>'+b[0]+'</td><td style="color:var(--ink3)">'+b[1]+'</td>'+
      '<td class="num" style="font-weight:700;color:var(--fail)">'+b[2]+'</td>'+
      '<td class="mono" style="font-size:11px;color:var(--ink3)">'+b[3]+'</td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="go(\'' +b[4]+ '\')">Open</button></td></tr>';
  }).join('');
  g('mk5').textContent=BLOCK.reduce(function(a,b){return a+b[2]},0);

  var TREND=[['14-08',2410],['15-08',2680],['16-08',2700],['17-08',1872],
             ['18-08',2880],['19-08',1836],['20-08',2544],['21-08',1980]];
  var mx=Math.max.apply(null,TREND.map(function(t){return t[1]}));
  g('mgTrend').innerHTML=TREND.map(function(t){
    return '<div class="fstep"><div class="fl mono">'+t[0]+'</div>'+
      '<div class="ft"><i style="width:'+(t[1]/mx*100).toFixed(1)+'%;background:'+C.navy+'"></i></div>'+
      '<div class="fv">'+t[1].toLocaleString()+'</div>'+
      '<div class="fp">'+Math.round(t[1]*0.59)+' KW</div></div>';
  }).join('');
}

/* ---- reusable composition donut ---- */
function drawDonut(elId,legendId,segs,midVal,midLbl){
  var el=document.getElementById(elId); if(!el)return;
  var tot=segs.reduce(function(a,s){return a+s.v},0)||1;
  var acc=0;
  var stops=segs.map(function(s){
    var a=acc/tot*100; acc+=s.v; var b=acc/tot*100;
    return s.c+' '+a.toFixed(3)+'% '+b.toFixed(3)+'%';}).join(',');
  el.style.background='conic-gradient('+stops+')';
  var mid=el.querySelector('.donut-mid');
  if(mid)mid.innerHTML='<div><b>'+midVal+'</b><span>'+midLbl+'</span></div>';
  var lg=document.getElementById(legendId); if(!lg)return;
  lg.innerHTML=segs.map(function(s){
    return '<div class="lg'+(s.v?'':' dim')+'"><i style="background:'+s.c+'"></i>'+
      '<span>'+s.n+'</span><b>'+s.v.toLocaleString()+'</b>'+
      '<span class="pc">'+(s.v/tot*100).toFixed(1)+'%</span></div>';
  }).join('');
}
var C={grey:'#C3CEDA',amber:'#E08A1E',blue:'#4E8FC0',navy:'#1B4D7A',
       green:'#177A47',red:'#BE3325',purple:'#7A47AD',teal:'#2A8A66'};

/* ================= PRODUCTION DASHBOARD ================= */
var PROD=[
 {cust:'SAI BABUJI PROJECTS',model:'ISEN590-G2X',alloc:12000,prod:10450,fqc:9800,rej:190,
  packed:9200,disp:7400,batches:8},
 {cust:'SG MEDA',model:'ISEN625-G12R',alloc:8000,prod:6900,fqc:6500,rej:130,packed:6100,
  disp:4800,batches:5},
 {cust:'MSEDCL',model:'ISEN620-G12R',alloc:5000,prod:3800,fqc:3500,rej:75,packed:3200,
  disp:2600,batches:3},
 {cust:'G2G (M10R) — General stock',model:'ISEN600-G2X',alloc:3000,prod:2100,fqc:1900,rej:44,
  packed:1700,disp:900,batches:2}];
var LOSS_REASONS=['Power cut','Air compressor / AC','Short circuit','Material shortage',
                  'Machine breakdown','Other production loss'];
/* Machine master. Counts are held PER LINE and edited in Admin — the breakdown
   percentage is derived, so correcting a count never needs a code change.
   ATW is the stringer vendor: ATW-1 IS Stringer-1, so it appears once, not twice. */
var MACHINES=[
 {type:'Stringer',alias:'ATW',a:4,b:4,src:'confirmed'},
 {type:'Laminator',a:3,b:3,src:'confirmed'},
 {type:'Pre-EL',a:2,b:2,src:'from station layout'},
 {type:'Framing machine',a:2,b:1,src:'confirmed'},
 {type:'Glass loader',a:1,b:1,src:'assumed'},
 {type:'EPE cutter',a:1,b:1,src:'assumed'},
 {type:'Curing line',a:1,b:1,src:'assumed'}];
function machCount(g){return g.a+g.b}
function machLines(g){
  var L=[];for(var i=0;i<g.a;i++)L.push('A');for(var j=0;j<g.b;j++)L.push('B');return L;}
function machName(g,i){return g.type+'-'+(i+1)+(g.alias?' · '+g.alias+'-'+(i+1):'')}
var lossMin={},machMin={},broken=[];

function prodRows(){
  var c=document.getElementById('pdCust').value;
  return c==='All customers'?PROD:PROD.filter(function(r){return r.cust===c});
}
function renderProd(){
  var rows=prodRows(),s=function(k){return rows.reduce(function(a,r){return a+r[k]},0)};
  var alloc=s('alloc'),prod=s('prod'),fqc=s('fqc'),rej=s('rej'),packed=s('packed'),disp=s('disp');
  var running=prod-fqc, pending=packed-disp, remaining=alloc-prod;
  var g=function(id){return document.getElementById(id)};
  g('pk1').textContent=alloc.toLocaleString();
  g('pk2').textContent=running.toLocaleString();
  g('pk3').textContent=rej.toLocaleString();
  g('pk4').textContent=disp.toLocaleString();
  g('pk5').textContent=remaining.toLocaleString();

  drawDonut('pdDonut','pdLegend',[
    {n:'Passed FQC',v:fqc-rej,c:C.navy},
    {n:'Rejected at FQC',v:rej,c:C.red},
    {n:'Produced, not yet at FQC',v:running,c:C.amber},
    {n:'Not yet produced',v:remaining,c:C.grey}
  ],(alloc/1000).toFixed(1)+'k','allocated');

  var LINES=[['A','A',742,9,45,31],['A','B',698,7,95,66],['A','C',611,6,0,0],
             ['B','A',705,8,60,42],['B','B',664,5,0,0],['B','C',580,4,30,15]];
  g('pdLineRows').innerHTML=LINES.map(function(r){
    var plan=700,pc=Math.min(r[2]/plan*100,100);
    return '<tr><td class="s'+r[0]+'">'+r[0]+'-Line</td><td class="s'+r[1]+'">'+r[1]+'</td>'+
      '<td class="num">'+r[2].toLocaleString()+'</td>'+
      '<td class="num"'+(r[3]?' style="color:var(--fail)"':'')+'>'+r[3]+'</td>'+
      '<td class="num"'+(r[4]?' style="color:var(--review)"':'')+'>'+r[4]+'</td>'+
      '<td class="num">'+r[5]+'</td>'+
      '<td><div class="bar-wrap"><div class="bar'+(pc>=95?' b-ok':'')+'">'+
      '<i style="width:'+pc+'%"></i></div><span class="mono">'+pc.toFixed(0)+'%</span></div></td></tr>';
  }).join('');

  var fun=[{n:'Allocated',v:alloc,c:'#72859A'},{n:'Produced',v:prod,c:'#E08A1E'},
    {n:'FQC done',v:fqc,c:'#4E8FC0'},{n:'Passed',v:fqc-rej,c:'#1B4D7A'},
    {n:'Packed',v:packed,c:'#2A8A66'},{n:'Dispatched',v:disp,c:'#177A47'}];
  g('pdFunnel').innerHTML=fun.map(function(x){
    return '<div class="fstep"><div class="fl">'+x.n+'</div>'+
      '<div class="ft"><i style="width:'+(x.v/alloc*100).toFixed(1)+'%;background:'+x.c+'"></i></div>'+
      '<div class="fv">'+x.v.toLocaleString()+'</div>'+
      '<div class="fp">'+(x.v/alloc*100).toFixed(0)+'%</div></div>';
  }).join('');

  g('pdCustRows').innerHTML=rows.map(function(r){
    var pend=r.packed-r.disp,run=r.prod-r.fqc,pc=r.disp/r.alloc*100;
    return '<tr><td>'+r.cust+'</td><td class="mono">'+r.model+'</td>'+
      '<td class="num">'+r.alloc.toLocaleString()+'</td>'+
      '<td class="num">'+r.prod.toLocaleString()+'</td>'+
      '<td class="num" style="color:var(--solar)">'+run.toLocaleString()+'</td>'+
      '<td class="num" style="color:var(--fail)">'+r.rej+'</td>'+
      '<td class="num">'+pend.toLocaleString()+'</td>'+
      '<td class="num" style="color:var(--pass)">'+r.disp.toLocaleString()+'</td>'+
      '<td><div class="bar-wrap"><div class="bar b-ok"><i style="width:'+pc+'%"></i></div>'+
      '<span class="mono">'+pc.toFixed(0)+'%</span></div></td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="qTry(\''+r.cust.split(' ')[0]+'\')">'+r.batches+'</button></td></tr>';
  }).join('');

  var lr=[['Power cut',185],['Material shortage',120],['Machine breakdown',95],
          ['Air compressor / AC',60],['Short circuit',25]];
  var tot=lr.reduce(function(a,x){return a+x[1]},0);
  g('pdLossRows').innerHTML=lr.map(function(x){
    return '<tr><td>'+x[0]+'</td><td class="num">'+x[1]+'</td>'+
      '<td class="num">'+Math.round(x[1]/480*2000/8)+'</td>'+
      '<td><div class="bar-wrap"><div class="bar"><i style="width:'+(x[1]/tot*100)+'%"></i></div>'+
      '<span class="mono">'+(x[1]/tot*100).toFixed(0)+'%</span></div></td></tr>';
  }).join('');
  g('pdLossMin').textContent=tot;
  g('pdLossMod').textContent=Math.round(tot/480*2000/8);

  var mr=[['Laminator-2','B',95,16.67],['Stringer-5','B',60,12.5],['Stringer-1','A',45,12.5],
          ['Framing machine-1','A',30,50],['Glass loader-2','B',20,50]];
  g('pdMachRows').innerHTML=mr.map(function(x){
    return '<tr><td class="mono">'+x[0]+'</td><td class="s'+x[1]+'">'+x[1]+'</td>'+
      '<td class="num">'+x[2]+'</td><td class="num">'+x[3].toFixed(2)+'%</td>'+
      '<td class="num">'+Math.round(2000*(x[2]/480)*(x[3]/100))+'</td></tr>';
  }).join('');
}

/* ================= PRODUCTION ENTRY ================= */
function peMode(btn,m){
  btn.parentNode.querySelectorAll('button').forEach(function(b){b.classList.remove('on')});
  btn.classList.add('on');
  document.getElementById('peManual').style.display=m==='manual'?'':'none';
  document.getElementById('peFile').style.display=m==='file'?'':'none';
}
var peOK=false;
function peCalc(){
  var a=document.getElementById('peFrom').value.trim().toUpperCase();
  var b=document.getElementById('peTo').value.trim().toUpperCase();
  var da=derive(a),db=derive(b),g=function(id){return document.getElementById(id)};
  function bad(t){
    ['peModel','peW','peCells','peQty','peKw'].forEach(function(id){g(id).textContent='—'});
    g('peMsg').innerHTML='<div class="note n-bad" style="margin:9px 0 0"><span>⚑</span><span>'+t+'</span></div>';
    g('peStatus').innerHTML='<div class="note n-bad" style="font-size:11.5px"><span>⚑</span>'+
      '<span>'+t+'</span></div>';
    peOK=false;g('peSave').disabled=true;}
  if(!da.ok)return bad(da.why);
  if(!db.ok)return bad(db.why);
  var r=rangeQty(a,b);                       /* returns {ok,n,why} — not a number */
  if(!r.ok)return bad(r.why);
  var n=r.n;
  g('peModel').textContent=da.model;g('peW').textContent=da.watt+'W';
  g('peCells').textContent=da.cells;g('peQty').textContent=n.toLocaleString();
  g('peKw').textContent=(n*(+da.watt)/1000).toFixed(2)+' KW';
  g('peMsg').innerHTML='<div class="note n-ok" style="margin:9px 0 0"><span>✓</span><span>'+
    n.toLocaleString()+' modules · '+da.model+' · '+(n*(+da.watt)/1000).toFixed(2)+' KW</span></div>';
  g('peStatus').innerHTML='<div class="note n-ok" style="font-size:11.5px"><span>✓</span>'+
    '<span>Range valid. Quantity is derived, not typed.</span></div>';
  peOK=true;g('peSave').disabled=false;
}
function peSave(){
  if(!peOK)return;
  toast(document.getElementById('peQty').textContent+' modules recorded as produced.');
}
function renderPE(){
  var rows=[['21-08-2026','B','590W','ISEN590-G2X','ICON590G1202121001','ICON590G1202121075',75],
    ['21-08-2026','A','625W','ISEN625-G12R','ICON625R1110152001','ICON625R1110152180',180],
    ['20-08-2026','C','620W','ISEN620-G12R','ICON620R1110152001','ICON620R1110152220',220],
    ['20-08-2026','B','590W','ISEN590-G2X','ICON590G1202111001','ICON590G1202111195',195]];
  document.getElementById('peRows').innerHTML=rows.map(function(r){
    return '<tr><td class="mono">'+r[0]+'</td><td class="s'+r[1]+'">'+r[1]+'</td>'+
      '<td class="mono">'+r[2]+'</td><td class="mono">'+r[3]+'</td>'+
      '<td class="mono">'+r[4]+'</td><td class="mono">'+r[5]+'</td>'+
      '<td class="num">'+r[6]+'</td><td class="num">'+(r[6]*parseInt(r[2],10)/1000).toFixed(1)+'</td>'+
      '<td>Rajesh Kumar</td></tr>';
  }).join('');
}

/* ================= LOSS OF PRODUCTION — EVENTS =================
   Downtime is opened and closed. A duration is never typed at shift end.
   Store events, never summaries: the moment a shift total replaces the events
   behind it, per-shift OEE and per-model SPC become impossible forever.
   Cascades double-count (laminator stops, framing starves), so an induced stop
   names the primary event that caused it and its minutes are excluded.        */
var EVENTS=[
 {id:'DT-2608-0041',line:'A',mach:'Laminator-2',start:'14:05',end:null,reason:'LOP-MACH',
  planned:false,kind:'P',link:null,mode:'Live'},
 {id:'DT-2608-0042',line:'A',mach:'Framing machine-1',start:'14:12',end:null,reason:'LOP-MACH',
  planned:false,kind:'I',link:'DT-2608-0041',mode:'Live'},
 {id:'DT-2608-0038',line:'B',mach:'Stringer-5 · ATW-5',start:'09:20',end:'10:05',reason:'LOP-POWER',
  planned:false,kind:'P',link:null,mode:'Live'},
 {id:'DT-2608-0039',line:'A',mach:'Glass loader-1',start:'11:02',end:'11:32',reason:'LOP-MAT',
  planned:false,kind:'P',link:null,mode:'Retro'},
 {id:'DT-2608-0040',line:'B',mach:'Laminator-5',start:'12:40',end:'13:25',reason:'LOP-MACH',
  planned:false,kind:'P',link:null,mode:'Live'}];
var SCRAP=[
 {st:'Layup',line:'A',model:'ISEN590-G2X',q:6,r:'Glass breakage'},
 {st:'Stringer',line:'A',model:'ISEN590-G2X',q:11,r:'Cell breakage'},
 {st:'Stringer',line:'B',model:'ISEN625-G12R',q:8,r:'Cell breakage'},
 {st:'Lamination',line:'B',model:'ISEN625-G12R',q:4,r:'Lamination failure'},
 {st:'Framing',line:'A',model:'ISEN590-G2X',q:2,r:'Frame damage'}];
var evSeq=43;
function evMins(a,b){
  function m(t){var p=(t||'0:0').split(':');return (+p[0])*60+(+p[1])}
  return Math.max(0,m(b)-m(a));
}
function nowHM(){var d=new Date();
  return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')}
function machListFor(line){
  var out=[];
  MACHINES.forEach(function(g){
    var n=(line==='A')?g.a:g.b, off=(line==='A')?0:g.a;
    for(var i=0;i<n;i++){
      var k=off+i+1;
      out.push(g.type+'-'+k+(g.alias?' · '+g.alias+'-'+k:''));
    }});
  return out;
}
function evMachines(){
  var lineEl=document.getElementById('evLine'); if(!lineEl)return;
  var line=lineEl.value;
  document.getElementById('evMach').innerHTML=machListFor(line).map(function(m){
    return '<option>'+m+'</option>'}).join('');
  var open=EVENTS.filter(function(e){return !e.end&&e.kind==='P'});
  document.getElementById('evLink').innerHTML=open.length?
    open.map(function(e){return '<option value="'+e.id+'">'+e.id+' — '+e.mach+'</option>'}).join(''):
    '<option value="">— no open primary event —</option>';
}
function evInducedChange(){
  var el=document.getElementById('evInduced'); if(!el)return;
  document.getElementById('evLinkWrap').style.display=(el.value==='I')?'':'none';
}
function openEvent(){
  var kind=document.getElementById('evInduced').value;
  var link=(kind==='I')?document.getElementById('evLink').value:null;
  if(kind==='I'&&!link){
    toast('An induced stop must name the primary event that caused it, or it double-counts.');return}
  EVENTS.unshift({id:'DT-2608-00'+(evSeq++),
    line:document.getElementById('evLine').value,
    mach:document.getElementById('evMach').value,
    start:document.getElementById('evStart').value||nowHM(),
    end:null,
    reason:document.getElementById('evReason').value.split(' — ')[0],
    planned:document.getElementById('evPlanned').value==='Planned',
    kind:kind,link:link,
    mode:document.getElementById('evMode').value.split(' — ')[0]});
  renderLoss();
  toast('Event opened and left running. Close it when the machine restarts — the duration is '+
        'derived from the two timestamps, never typed.');
}
function closeEvent(i){
  EVENTS[i].end=nowHM();
  var m=evMins(EVENTS[i].start,EVENTS[i].end);
  renderLoss();
  toast(EVENTS[i].id+' closed at '+EVENTS[i].end+' — '+m+' minutes recorded.');
}
function renderLoss(){
  if(!document.getElementById('openRows'))return;
  var open=EVENTS.filter(function(e){return !e.end});
  var closed=EVENTS.filter(function(e){return e.end});
  document.getElementById('openCount').textContent=open.length+' open';
  document.getElementById('openRows').innerHTML=open.map(function(e){
    var i=EVENTS.indexOf(e);
    return '<tr><td class="mono">'+e.id+'</td><td class="s'+e.line+'">'+e.line+'</td>'+
      '<td class="mono" style="font-size:11px">'+e.mach+'</td>'+
      '<td class="mono">'+e.start+'</td>'+
      '<td class="mono" style="color:var(--fail);font-weight:700">'+
        evMins(e.start,nowHM())+' min</td>'+
      '<td><span class="code">'+e.reason+'</span></td>'+
      '<td>'+(e.kind==='P'?'<span class="tag t-fail">Primary</span>':
        '<span class="tag t-rev">Induced &larr; '+e.link+'</span>')+'</td>'+
      '<td><button class="btn btn-primary btn-sm" onclick="closeEvent('+i+')">Close</button></td></tr>';
  }).join('')||'<tr><td colspan="8"><div class="empty-state" style="padding:20px">'+
    '<p>Nothing is down right now.</p></div></td></tr>';

  var shift=+document.getElementById('shiftMin').value||480;
  var tgt=+document.getElementById('shiftTgt').value||2000;
  var pMin=0,iMin=0,lost=0;
  document.getElementById('closedRows').innerHTML=closed.map(function(e){
    var m=evMins(e.start,e.end);
    var grp=MACHINES.filter(function(g){return e.mach.indexOf(g.type)===0})[0];
    var n=grp?machCount(grp):1, share=100/n, pct=share*(m/shift);
    var ml=Math.round(tgt*pct/100);
    if(e.kind==='P'){pMin+=m;lost+=ml}else{iMin+=m}
    return '<tr><td class="mono">'+e.id+'</td><td class="s'+e.line+'">'+e.line+'</td>'+
      '<td class="mono" style="font-size:11px">'+e.mach+'</td>'+
      '<td class="mono">'+e.start+'</td><td class="mono">'+e.end+'</td>'+
      '<td class="num">'+m+'</td><td><span class="code">'+e.reason+'</span></td>'+
      '<td>'+(e.kind==='P'?'<span class="tag t-fail">Primary</span>':
        '<span class="tag t-rev">Induced</span>')+'</td>'+
      '<td>'+(e.mode==='Retro'?'<span class="tag t-rev">Retro</span>':
        '<span class="tag t-mute">Live</span>')+'</td>'+
      '<td class="num">'+(e.kind==='P'?ml:'not counted')+'</td></tr>';
  }).join('')||'<tr><td colspan="10"><div class="empty-state" style="padding:20px">'+
    '<p>No closed events yet this shift.</p></div></td></tr>';

  var scrapTot=SCRAP.reduce(function(a,s){return a+s.q},0);
  document.getElementById('scrapRows').innerHTML=SCRAP.map(function(s){
    return '<tr><td>'+s.st+'</td><td class="s'+s.line+'">'+s.line+'</td>'+
      '<td class="mono">'+s.model+'</td><td class="num">'+s.q+'</td><td>'+s.r+'</td></tr>';
  }).join('');

  document.getElementById('sumOpen').textContent=open.length;
  document.getElementById('sumMach').textContent=pMin;
  document.getElementById('sumInd').textContent=iMin;
  document.getElementById('sumPct').textContent=(lost/tgt*100).toFixed(2)+'%';
  document.getElementById('sumMod').textContent=lost.toLocaleString();
  document.getElementById('sumScrap').textContent=scrapTot;
  document.getElementById('lossWarn').innerHTML=open.length?
    '<div class="note n-warn" style="font-size:11.5px"><span>&#9873;</span><span>'+open.length+
    ' event(s) are still open. Their minutes are not counted until they are closed.</span></div>':'';
  evMachines();evInducedChange();
}
function calcLoss(){renderLoss()}

/* ================= INVOICE PARSER =================
   Server-side in the build: a 350 KB PDF is ~30 ms with PyMuPDF.
   Parse by LABEL TEXT, never by coordinate — the PDF is a Microsoft Print-To-PDF
   render of a Tally screen, so layout is a function of one person's print
   settings. Fingerprint first: if the expected labels are missing, refuse rather
   than guess.

   Three field classes:
     COPY                 — party, GSTIN, address, vehicle, transporter, LR, IRN...
     COMPARE, NEVER COPY  — quantity, model, customer. These come from scanned
                            boxes; the invoice value is only the declared expectation.
     NEVER PARSE          — rate, amount, tax. Keeps ICON TRACE out of the
                            financial-document business.                        */
var INV_FIELDS=[
 {k:'inv',   l:'Invoice no.',      cls:'copy',  v:'ICON/26-27/736'},
 {k:'dt',    l:'Invoice date',     cls:'copy',  v:'29-08-2026'},
 {k:'irn',   l:'IRN',              cls:'copy',  v:'a3f81c0d94e27b6510af8823cc71d0e9b4425ff7'},
 {k:'buyer', l:'Buyer (Bill to)',  cls:'copy',  v:'AGNI GREEN POWER LIMITED (MZ)'},
 {k:'gst',   l:'Buyer GSTIN',      cls:'copy',  v:'15AACCA2122Q1ZT'},
 {k:'ship',  l:'Consignee (Ship to)',cls:'copy',v:'AGNI GREEN POWER LIMITED (MZ) — GODOWN NG-11, RANGVAMUAL, TRUCK TERMINAL AIZAWL'},
 {k:'addr',  l:'Buyer address',    cls:'copy',  v:'Near Lalsangliana Petrol Pump, Sairang Road, Aizawl, Mizoram 796001'},
 {k:'veh',   l:'Vehicle no.',      cls:'copy',  v:'CG04MP1466'},
 {k:'tran',  l:'Transporter',      cls:'copy',  v:'ALL INDIA TRANSPORT'},
 {k:'lr',    l:'LR Copy no.',      cls:'copy',  v:'2678'},
 {k:'ewb',   l:'e-Way Bill no.',   cls:'copy',  v:'331004512789'},
 {k:'ewbv',  l:'e-Way Bill valid to',cls:'copy',v:'02-09-2026'},
 {k:'po',    l:'Customer PO no.',  cls:'copy',  v:'AGNI/MZ/PO/2627/000001'},
 {k:'qty',   l:'Quantity',         cls:'cmp',   v:'290'},
 {k:'model', l:'Model',            cls:'cmp',   v:'ISEN630-G12R'},
 {k:'cust',  l:'Customer',         cls:'cmp',   v:'AGNI GREEN POWER LIMITED (MZ)'},
 {k:'rate',  l:'Rate',             cls:'never', v:''},
 {k:'amt',   l:'Taxable amount',   cls:'never', v:''},
 {k:'tax',   l:'GST',              cls:'never', v:''}];
var INV_STATE=null, INV_SCANNED=290;
function invSim(bad){
  INV_STATE={fields:{},edited:{},bad:!!bad};
  INV_FIELDS.forEach(function(f){
    var v=f.v;
    if(bad&&f.k==='qty')v='312';
    if(bad&&f.k==='tran')v='';
    INV_STATE.fields[f.k]=v;
  });
  INV_STATE={
    qr:{einvoice:true},
    fields:{
      invoice_no:{value:'ICON/26-27/736',found:true,optional:false},
      invoice_date:{value:'29-08-2026',found:true,optional:false},
      ack_no:{value:'132612345678',found:true,optional:true},
      ack_date:{value:'29-08-2026',found:true,optional:true},
      irn:{value:'a3f81c0d94e27b6510af8823cc71d0e9b4425ff7',found:true,optional:false},
      buyer_name:{value:'AGNI GREEN POWER LIMITED (MZ)',found:true,optional:false},
      buyer_address:{value:'Near Lalsangliana Petrol Pump, Sairang Road, Aizawl, Mizoram 796001',found:true,optional:false},
      buyer_gstin:{value:'15AACCA2122Q1ZT',found:true,optional:false},
      buyer_state_code:{value:'15',found:true,optional:true},
      consignee_same_as_buyer:{value:1,found:true,optional:true},
      consignee_name:{value:'AGNI GREEN POWER LIMITED (MZ)',found:true,optional:false},
      consignee_address:{value:'GODOWN NG-11, RANGVAMUAL, TRUCK TERMINAL AIZAWL',found:true,optional:false},
      consignee_gstin:{value:'15AACCA2122Q1ZT',found:true,optional:true},
      consignee_state_code:{value:'15',found:true,optional:true},
      dispatch_from_name:{value:'Unit-2, Fab City',found:true,optional:true},
      dispatched_through:{value:'ALL INDIA TRANSPORT',found:true,optional:true},
      vehicle_no:{value:'CG04MP1466',found:true,optional:true},
      lr_no:{value:'2678',found:true,optional:true},
      destination:{value:'Aizawl',found:true,optional:true},
      ewb_no:{value:'331004512789',found:true,optional:true},
      ewb_valid_upto:{value:bad?'28-08-2026':'02-09-2026',found:true,optional:true},
      ewb_distance_km:{value:'1200',found:true,optional:true},
      po_no:{value:'AGNI/MZ/PO/2627/000001',found:true,optional:true},
      po_date:{value:'20-08-2026',found:true,optional:true},
      ho_reference:{value:'',found:false,optional:true},
      delivery_note:{value:'',found:false,optional:true},
      dispatch_doc_no:{value:'',found:false,optional:true},
      payment_terms:{value:'30 Days',found:true,optional:true},
      quantity:{value:bad?'312':'290',found:true,optional:false},
      model:{value:'ISEN630-G12R',found:true,optional:false},
      hsn:{value:'85414300',found:true,optional:true}
    },
    edited:{},
    bad:!!bad
  };
  document.getElementById('invFp').textContent=bad?'labels matched · 2 fields not found':
    'labels matched · fingerprint OK';
  document.getElementById('invDzT').textContent='ICON_26-27_736.pdf';
  document.getElementById('invDzS').textContent='352 KB · Microsoft Print To PDF · '+
    'Accounting Voucher Display · US Letter 612×792pt';
  document.getElementById('invDz').classList.add('hasfile');
  document.getElementById('invFinger').innerHTML=
    '<div class="note n-ok" style="font-size:11.5px;margin:11px 0 0"><span>&#10003;</span><span>'+
    'Fingerprint matched — every expected label was present. Parsed by label text, not by '+
    'coordinate.</span></div>';
  document.getElementById('invQr').innerHTML=
    '<div style="font-size:11.5px;line-height:1.8">'+
    '<b>e-invoice QR</b> · 953 B · signed RS256<br>'+
    '<span class="mono" style="font-size:10.5px;color:var(--ink3)">SellerGstin · BuyerGstin · '+
    'DocNo · DocTyp · DocDt · TotInvVal · ItemCnt · MainHsnCode · Irn · IrnDt</span><br><br>'+
    '<b>e-Way Bill QR</b> · 76 B · plain text<br>'+
    '<span class="mono" style="font-size:10.5px;color:var(--ink3)">EWB No / GSTIN / Date</span>'+
    '</div>'+
    '<div class="note n-ok" style="font-size:11px;margin:10px 0 0"><span>&#10003;</span><span>'+
    'SellerGstin matches Unit-2. DocNo and TotInvVal agree with the scraped text.</span></div>';
  renderInvFields();
}
function invSimBad(){invSim(true)}
function renderInvFields(){
  if(!INV_STATE)return;
  var host=document.getElementById('invFields');
  
  function field(k, l, wide) {
    var meta = INV_STATE.fields[k] || {value: '', found: false, optional: true};
    var v = meta.value === null ? '' : meta.value;
    var isChk = (k === 'consignee_same_as_buyer');
    var cls = meta.found ? 'fld' : (meta.optional ? 'fld absent' : 'fld blank');
    
    var h = '<div class="' + cls + '"' + (wide ? ' style="grid-column:1/-1"' : '') + '>'+
      '<label for="f_'+k+'">'+l+'</label>';
    
    if (isChk) {
      h += '<input type="checkbox" id="f_'+k+'" onchange="INV_STATE.fields[\''+k+'\']={value:this.checked?1:0,found:true,optional:true};INV_STATE.edited[\''+k+'\']=true;invCheck()" '+(v?'checked':'')+'>';
    } else if (wide) {
      h += '<textarea id="f_'+k+'" rows="2" oninput="INV_STATE.fields[\''+k+'\']={value:this.value,found:true,optional:true};INV_STATE.edited[\''+k+'\']=true;invCheck()">'+v+'</textarea>';
    } else {
      h += '<input id="f_'+k+'" value="'+v+'" aria-label="'+l+'" '+
        'oninput="INV_STATE.fields[\''+k+'\']={value:this.value,found:true,optional:true};INV_STATE.edited[\''+k+'\']=true;invCheck()">';
    }
    
    if (!meta.found) {
      h += '<div class="why">' + (meta.optional ? 'Not on this invoice. Fill it only if you have it.' : 'The parser did not find this. Type it rather than trust a guess.') + '</div>';
    } else if (INV_STATE.edited[k]) {
      h += '<div class="hint">edited after parsing</div>';
    }
    h += '</div>';
    return h;
  }
  
  var qrVerified = INV_STATE.qr && INV_STATE.qr.einvoice;
  var html = '';
  html += '<div class="card"><div class="card-h"><h3>Invoice identity</h3><span class="sp tag '+(qrVerified?'t-pass':'t-mute')+'">'+(qrVerified?'QR verified':'QR not readable')+'</span></div>';
  html += '<div class="card-b"><div class="grid">';
  html += field('invoice_no', 'Invoice number');
  html += field('invoice_date', 'Invoice date');
  html += field('ack_no', 'Ack number');
  html += field('ack_date', 'Ack date');
  html += field('irn', 'IRN — the reference we store', true);
  html += '</div></div></div>';

  html += '<div class="card"><div class="card-h"><h3>Buyer (Bill to)</h3></div><div class="card-b"><div class="grid">';
  html += field('buyer_name', 'Buyer name', true);
  html += field('buyer_address', 'Buyer address', true);
  html += field('buyer_gstin', 'Buyer GSTIN');
  html += field('buyer_state_code', 'State code');
  html += field('consignee_same_as_buyer', 'Consignee is the same');
  html += '</div></div></div>';

  html += '<div class="card"><div class="card-h"><h3>Consignee (Ship to)</h3></div><div class="card-b"><div class="grid">';
  html += field('consignee_name', 'Consignee name', true);
  html += field('consignee_address', 'Consignee address', true);
  html += field('consignee_gstin', 'Consignee GSTIN');
  html += field('consignee_state_code', 'State code');
  html += '</div></div></div>';

  html += '<div class="card"><div class="card-h"><h3>Transport and e-Way Bill</h3></div><div class="card-b"><div class="grid">';
  html += field('dispatch_from_name', 'Dispatch from (place)', true);
  html += field('dispatched_through', 'Dispatched through');
  html += field('vehicle_no', 'Vehicle number');
  html += field('lr_no', 'LR / GR number');
  html += field('destination', 'Destination');
  html += field('ewb_no', 'e-Way Bill number');
  html += field('ewb_valid_upto', 'e-Way Bill valid until');
  html += field('ewb_distance_km', 'Distance (km)');
  html += '</div></div></div>';

  html += '<div class="card"><div class="card-h"><h3>References</h3></div><div class="card-b"><div class="grid">';
  html += field('po_no', 'Buyer order number');
  html += field('po_date', 'Buyer order date');
  html += field('ho_reference', 'HO reference');
  html += field('delivery_note', 'Delivery note');
  html += field('dispatch_doc_no', 'Dispatch doc number');
  html += field('payment_terms', 'Payment terms', true);
  html += '</div><div class="note n-warn" style="margin:12px 0 0">Delivery note and dispatch doc number are the two fields Tally keeps for <i>our</i> challan number. They arrive blank because nobody at HO fills them. That is the missing link between the two systems, not a parser fault.</div></div></div>';

  html += '<div class="card"><div class="card-h"><h3>Declared by the invoice — checked, never copied</h3></div><div class="card-b"><div class="grid">';
  html += field('quantity', 'Quantity');
  html += field('model', 'Model');
  html += field('hsn', 'HSN');
  html += '</div><p class="hint" style="margin-top:9px">Rate, amount and tax are never read from the invoice.</p></div></div>';

  host.innerHTML = html;
  invCheck();
}
function invCheck(){
  if(!INV_STATE)return;
  var qField = INV_STATE.fields.quantity;
  var qStr = qField ? qField.value : null;
  var q = parseInt(String(qStr).replace(/,/g, ''), 10);
  
  var g=function(id){return document.getElementById(id)};
  var invField = INV_STATE.fields.invoice_no;
  g('invNo').textContent= (invField && invField.value) ? invField.value : '—';
  g('invQty').textContent=isNaN(q)?'—':q.toLocaleString();
  g('invScan').textContent=INV_SCANNED.toLocaleString();
  
  var diff=isNaN(q)?null:q-INV_SCANNED;
  g('invDiff').textContent=diff==null?'—':(diff>0?'+':'')+diff;
  
  var ewbField = INV_STATE.fields.ewb_valid_upto;
  g('invEwb').textContent= (ewbField && ewbField.value) ? ewbField.value : '—';
  
  var expired=false;
  if(ewbField && ewbField.value){
    var p=String(ewbField.value).split('-');
    if (p.length === 3) {
      expired=new Date(+p[2],+p[1]-1,+p[0])<new Date();
    }
  }
  
  var badge=g('invBadge');
  if(diff===0&&!expired){
    badge.className='tag t-pass';badge.textContent='reconciled';
    g('invStatus').innerHTML='<div class="note n-ok" style="font-size:11.5px"><span>&#10003;</span>'+
      '<span>Invoice quantity matches the scanned boxes exactly.</span></div>';
    g('invSubmit').disabled=false;
  }else{
    badge.className='tag t-fail';badge.textContent='blocked';
    g('invStatus').innerHTML='<div class="note n-fail" style="font-size:11.5px"><span>&#10007;</span><span>'+
      (expired?'<b>e-Way Bill is expired.</b> Dispatch is blocked — nobody checks this by hand.<br>':'')+
      (diff!==0&&diff!=null?'<b>Quantity mismatch: invoice says '+q+', boxes hold '+INV_SCANNED+
        '.</b> There is <b>no approval override</b> for this. The only legitimate fix is '+
        'correcting a mis-parsed value, or having the packing changed or HO reissue.':'')+
      '</span></div>';
    g('invSubmit').disabled=true;
  }
function invSubmit(){
  var g=function(id){return document.getElementById(id)};
  g('invSubmit').disabled = true;
  g('invSubmit').textContent = 'Saving...';
  
  var payload = {};
  Object.keys(INV_STATE.fields).forEach(function(k) {
    if (INV_STATE.fields[k]) payload[k] = INV_STATE.fields[k].value;
  });
  payload.expect_qty = INV_SCANNED;

  fetch('/api/invoice/confirm', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  })
  .then(function(r) { return r.json(); })
  .then(function(d) {
    if (!d.ok) {
      toast(d.why || 'Failed to save invoice.');
      g('invSubmit').disabled = false;
      g('invSubmit').textContent = 'Attach to challan';
      return;
    }
    toast('Invoice '+d.invoice_no+' attached.'+
          (d.edited_count?' · '+d.edited_count+' field(s) edited after parsing — recorded to measure the parser':'')+'.');
    
    INV_STATE = null;
    document.getElementById('invDzT').textContent = 'Drop the invoice PDF here';
    document.getElementById('invDzS').textContent = 'Arrives by email from HO · always a digital PDF, never a scan';
    document.getElementById('invFp').textContent = '—';
    document.getElementById('invNo').textContent = '—';
    var host = document.getElementById('invFields');
    host.innerHTML = '<div class="empty-state" style="padding:26px"><div class="es-i">&#9636;</div>'+
      '<p>No invoice loaded. Every field stays editable before submission, and anything the '+
      'parser could not find is left <b>blank and flagged</b> — a blank catches the eye, '+
      'a wrong-but-plausible value does not.</p></div>';
    g('invSubmit').textContent = 'Attach to challan';
    g('invBadge').className = 'tag t-mute'; g('invBadge').textContent = 'waiting';
    g('invStatus').innerHTML = '<span class="sp hint">Scan boxes first</span>';
    g('invQty').textContent = '—';
    g('invDiff').textContent = '—';
    g('invEwb').textContent = '—';
    
    if (typeof dispApply === 'function') dispApply();
  })
  .catch(function(e) {
    toast('Network error saving invoice.');
    g('invSubmit').disabled = false;
    g('invSubmit').textContent = 'Attach to challan';
  });
}

/* ================= CHALLAN NUMBERING =================
   Format IS-DD.MM.YYYY/SEQ on controlled form IS-MP-STR-FM-09 Rev 1.
   SEQ resets on the FINANCIAL YEAR (1 April), not monthly — 742 by 29 Aug is
   4.9/day since 1 April, which matches real output; a monthly reset would imply
   25.6/day.

   fy and seq are stored as INTEGERS and the display string is rendered. That
   dissolves the "4-digit until May, 3-digit from June" puzzle: it is zero-padding
   somebody stopped applying (0300 -> 301), not a numbering change. Padding is a
   display setting, and the 999 -> 1000 rollover needs no code at all.

   ANSWERED: an April challan reads 0001 — pad to 4. Still a display setting, so
   changing it later touches no stored data.                                    */
var CHALLAN_PAD=4;                 /* CONFIRMED: an April challan reads 0001, so pad to 4 */
var CHALLAN_FORM='IS-MP-STR-FM-09 Rev 1';
function finYear(d){                /* FY starts 1 April; 2026-27 is fy 2026 */
  return (d.getMonth()>=3)?d.getFullYear():d.getFullYear()-1;
}
function fyLabel(fy){return fy+'-'+String((fy+1)%100).padStart(2,'0')}
function challanNo(d,seq,pad){
  var p=(pad==null?CHALLAN_PAD:pad);
  var dd=String(d.getDate()).padStart(2,'0'),
      mm=String(d.getMonth()+1).padStart(2,'0');
  return 'IS-'+dd+'.'+mm+'.'+d.getFullYear()+'/'+String(seq).padStart(p,'0');
}
/* Counter state. In the build this is a row incremented inside the same
   transaction as the insert, so two saves cannot take one number. */
var CHALLAN_SEQ={fy:2026,next:743};
function nextChallan(dateStr){
  var d=dateStr?new Date(dateStr):new Date();
  var fy=finYear(d);
  if(fy!==CHALLAN_SEQ.fy){CHALLAN_SEQ={fy:fy,next:1}}
  return {fy:fy,seq:CHALLAN_SEQ.next,no:challanNo(d,CHALLAN_SEQ.next),date:d};
}
/* The number embeds the date, so a challan drafted at 23:50 and submitted at
   00:05 would otherwise carry yesterday's date. The number is fixed at DRAFT
   and the mismatch is surfaced rather than silently re-dated. */
function challanDateDrift(draftDate,now){
  var a=new Date(draftDate), b=now||new Date();
  return (a.toDateString()!==b.toDateString());
}

/* ============ CHALLAN — PRE-DISPATCH VERIFICATION ============
   This is the highest-value screen in the system. Before a truck loads, staff
   currently verify by hand across a hundred-plus sheets. The valuable half is not
   the PDF — it is the screen refusing to proceed and naming the exact serial and
   the exact reason, in time for a loader to pull that module before the vehicle
   moves. Checks run at SERIAL level, not box level.                              */
/* The real AGNI challan IS-29.08.2026/742 (A): 290 modules in 9 boxes.
   Listed in LOADING order — A005 goes on the truck first — not sorted by box
   number. A009 holds 2 and was packed the day after the rest: nobody broke a
   sealed box, someone packed a 2-module box to hit the invoice number. */
var AGNI='AGNI GREEN POWER LIMITED (MZ)';
var CH_BOXES=[
 {id:'A005',bin:2,cust:AGNI,model:'ISEN630-G12R',g:'A',q:36,
  packed:'27-08-2026',shift:'B',base:'ICON630R1282710149',sel:true,repacked:false},
 {id:'A001',bin:2,cust:AGNI,model:'ISEN630-G12R',g:'A',q:36,
  packed:'27-08-2026',shift:'B',base:'ICON630R1282710001',sel:true,repacked:false},
 {id:'A002',bin:2,cust:AGNI,model:'ISEN630-G12R',g:'A',q:36,
  packed:'27-08-2026',shift:'B',base:'ICON630R1282710041',sel:true,repacked:false},
 {id:'A003',bin:3,cust:AGNI,model:'ISEN630-G12R',g:'A',q:36,
  packed:'27-08-2026',shift:'C',base:'ICON630R1282710077',sel:true,repacked:false},
 {id:'A004',bin:3,cust:AGNI,model:'ISEN630-G12R',g:'A',q:36,
  packed:'27-08-2026',shift:'C',base:'ICON630R1282710113',sel:true,repacked:false},
 {id:'A006',bin:3,cust:AGNI,model:'ISEN630-G12R',g:'A',q:36,
  packed:'27-08-2026',shift:'C',base:'ICON630R1282710189',sel:true,repacked:false},
 {id:'A007',bin:4,cust:AGNI,model:'ISEN630-G12R',g:'A',q:36,
  packed:'28-08-2026',shift:'A',base:'ICON630R1282710225',sel:true,repacked:false},
 {id:'A008',bin:4,cust:AGNI,model:'ISEN630-G12R',g:'A',q:36,
  packed:'28-08-2026',shift:'A',base:'ICON630R1282710261',sel:true,repacked:false},
 {id:'A009',bin:4,cust:AGNI,model:'ISEN630-G12R',g:'A',q:2,
  packed:'28-08-2026',shift:'A',base:'ICON630R1282710301',sel:true,repacked:false},
 {id:'A040',bin:2,cust:'SG MEDA',model:'ISEN625-G12R',g:'A',q:36,
  packed:'28-08-2026',shift:'A',base:'ICON625R1282710001',sel:false,repacked:false},
 {id:'A046',bin:5,cust:AGNI,model:'ISEN630-G12R',g:'GY',q:36,
  packed:'27-08-2026',shift:'C',base:'ICON630R1282710401',sel:false,repacked:false},
 {id:'A039',bin:1,cust:AGNI,model:'ISEN630-G12R',g:'A',q:36,
  packed:'21-06-2026',shift:'A',base:'ICON630R1282710501',sel:false,repacked:true}];

/* Per-serial faults planted so the demo shows real refusals with real serials. */
var SERIAL_FAULTS={
 'ICON630R1282710012':{code:'E-SHIPPED',t:'Already dispatched',
   d:'On IS-27.08.2026/741, gate pass GP-2608-0017, vehicle CG04MM1521'},
 'ICON630R1282710050':{code:'E-OWNER',t:'Allocated to a different customer',
   d:'Allocation says BOROSIL RENEWABLES — this challan is for AGNI GREEN POWER'},
 'ICON630R1282710085':{code:'E-NOFQC',t:'No FQC record',
   d:'Never graded. It reached the box without passing the FQC station'},
 'ICON630R1282710120':{code:'E-GRADE',t:'FQC grade is BGY',
   d:'Rejected at FQC 27-08 14:22, defect DF-NOPOWER — cannot ship as A grade'},
 'ICON625R1282710009':{code:'E-MODEL',t:'Wattage / model mismatch',
   d:'Allocation for this serial says ISEN620-G12R; the box is labelled ISEN625-G12R'}};
function chSerials(b){var a=[];for(var i=0;i<b.q;i++)a.push(bumpSerial(b.base,i));return a}
function renderChBoxes(){
  document.getElementById('chBoxRows').innerHTML=CH_BOXES.map(function(b,i){
    var partial=(b.q<36);
    return '<tr><td><input type="checkbox" '+(b.sel?'checked':'')+
      ' aria-label="Select '+b.id+'"'+
      ' onchange="CH_BOXES['+i+'].sel=this.checked;runChecks()" style="accent-color:var(--brand)"></td>'+
      '<td class="mono" style="font-weight:700">'+b.id+'</td>'+
      '<td class="mono">'+b.packed+'</td>'+
      '<td class="mono">BIN-'+b.bin+'</td>'+
      '<td class="s'+b.shift+'">'+b.shift+'</td>'+
      '<td style="font-size:11.5px">'+b.cust.split(' PRIVATE')[0]+'</td>'+
      '<td class="mono">'+b.model+'</td>'+
      '<td><span class="tag '+(b.g==='A'?'t-pass':'t-rev')+'">'+b.g+'</span></td>'+
      '<td class="num">'+b.q+(partial?' <span class="tag t-mute">part</span>':'')+'</td>'+
      '<td>'+(b.repacked?'<span class="tag t-fail">Repacked since list printed</span>':
        '<span class="tag t-mute">—</span>')+'</td></tr>';
  }).join('');
}
function sameCons(cb){document.getElementById('consBlock').hidden=cb.checked}
var chOverride=false, CH_FAILS=[];
var PARTY_GST={'AGNI GREEN POWER LIMITED (MZ)':'15AACCA2122Q1ZT',
                'SAI BABUJI PROJECTS PRIVATE LIMITED (MH)':'27AAQCS4584G1ZR',
                'SG MEDA':'36AAQCS4584G1ZH','MSEDCL':'27AAECM2933K1ZB'};
function partyChange(){
  var p=document.getElementById('chParty').value;
  if(PARTY_GST[p])document.getElementById('chGst').value=PARTY_GST[p];
  gstCheck();runChecks();
}
function gstCheck(){
  var el=document.getElementById('chGst'); if(!el)return;
  var r=gstParse(el.value);
  var set=function(id,v){var e=document.getElementById(id);if(e)e.value=v};
  var msg=document.getElementById('chGstMsg');
  if(r.ok){
    set('chPan',r.pan); set('chState',r.state); set('chStateCode',r.code);
    set('chSupply',gstSupplyType(r.code));
    msg.innerHTML='<span style="color:var(--pass);font-weight:600">&#10003; Valid · '+
      r.state+' ('+r.type+') · entity '+r.entity+'</span>'+
      (r.legacy?'<br><span style="color:var(--review)">&#9873; '+r.legacy+'</span>':'');
    el.style.borderColor='';
  }else{
    set('chPan',''); set('chState',r.state||''); set('chStateCode',r.code||'');
    set('chSupply','');
    msg.innerHTML=r.empty?'':'<span style="color:var(--fail);font-weight:600">&#10007; '+
      r.why+'</span>';
    el.style.borderColor=r.empty?'':'var(--fail)';
  }
}
var CH_DRAFT=null;
/* Three outputs from one challan, plus the Flash Test Report.
   Corrected 31-08: the challan is ONE document in TWO renderings — the short hard
   copy the driver carries (summary line only, no serials) and the full soft copy
   with the box-wise serial table — AND a separate packing list. Not one document. */
var CH_DOCS=[
 {k:'hard',n:'Challan — hard copy',d:'Driver&rsquo;s copy · summary line only, no serials',
  form:'IS-MP-STR-FM-09 Rev 1'},
 {k:'soft',n:'Challan — full copy',d:'Same document · box-wise serial table included',
  form:'IS-MP-STR-FM-09 Rev 1'},
 {k:'pack',n:'Packing list',d:'Separate document · box by box',form:'—'},
 {k:'ftr', n:'Flash Test Report',d:'Generated from Sun Simulator data already held',form:'—'}];
function renderChDocs(){
  var host=document.getElementById('chDocRows'); if(!host)return;
  host.innerHTML=CH_DOCS.map(function(x){
    return '<tr><td><div style="font-weight:600;font-size:12px">'+x.n+'</div>'+
      '<div style="font-size:10.5px;color:var(--ink3)">'+x.d+
      (x.form!=='—'?' · <span class="mono">'+x.form+'</span>':'')+'</div></td>'+
      '<td style="text-align:right;white-space:nowrap">'+
      '<button class="btn btn-ghost btn-sm" onclick="chPrint(\''+x.k+'\')">Print</button></td></tr>';
  }).join('');
}
function chPrint(k){
  var x=CH_DOCS.filter(function(d){return d.k===k})[0];
  var sel=CH_BOXES.filter(function(b){return b.sel});
  var qty=sel.reduce(function(a,b){return a+b.q},0);
  if(!sel.length){toast('Tick the boxes going on this vehicle first.');return}
  var kwT=sel.reduce(function(a,b){
    var m=MODELS.filter(function(x){return x.model===b.model})[0];
    return a+(b.q*(m?+m.watt:0));},0)/1000;
  if(k==='ftr'){
    toast('Flash Test Report for '+qty+' modules — Pmax, Voc, Isc and fill factor per serial, '+
          'straight from the Sun Simulator ingest. Nothing is re-keyed.');
  }else if(k==='hard'){
    toast('Hard copy printed — one summary line, '+qty+' NOS, '+kwT.toFixed(1)+
          ' KW. No serials: the driver does not need them.');
  }else if(k==='soft'){
    toast('Full copy printed — '+sel.length+' boxes with every serial listed.');
  }else{
    toast('Packing list printed — '+sel.length+' boxes, box by box.');
  }
  printDoc(x.n,CH_DRAFT?CH_DRAFT.no:'draft',k==='hard'?3:1);
}
function initChallanNo(){
  if(!document.getElementById('chNo'))return;
  if(!CH_DRAFT)CH_DRAFT=nextChallan();
  document.getElementById('chNo').textContent=CH_DRAFT.no;
  document.getElementById('chFy').textContent='FY '+fyLabel(CH_DRAFT.fy)+' · seq '+CH_DRAFT.seq;
}
function runChecks(){
  var party=document.getElementById('chParty').value;
  var sel=CH_BOXES.filter(function(b){return b.sel});
  var qty=sel.reduce(function(a,b){return a+b.q},0);
  /* KW is always derived from quantity x wattage, per box — never a fixed rate
     and never typed. Mixed-model loads sum correctly. */
  var kw=sel.reduce(function(a,b){
    var m=MODELS.filter(function(x){return x.model===b.model})[0];
    return a+(b.q*(m?+m.watt:0));},0)/1000;
  kw=kw.toFixed(1);
  document.getElementById('chSel').textContent=sel.length+' boxes · '+qty+' modules · '+kw+' KW';

  /* ---- serial-level verification ---- */
  CH_FAILS=[];
  sel.forEach(function(b){
    if(b.repacked)CH_FAILS.push({s:'—',box:b.id,code:'E-REPACK',
      t:'Pallet repacked since the list was printed',
      d:b.id+' was rebuilt after its packing list was produced. Reprint the list before shipping.'});
    if(b.cust!==party)CH_FAILS.push({s:'—',box:b.id,code:'E-OWNER',
      t:'Box allocated to a different customer',
      d:b.id+' is allocated to '+b.cust.split(' PRIVATE')[0]+', not '+party.split(' PRIVATE')[0]});
    if(b.g!=='A')CH_FAILS.push({s:'—',box:b.id,code:'E-GRADE',
      t:'Box grade is '+b.g,
      d:b.id+' holds '+b.g+' modules. Confirm the customer accepts NG stock before shipping.'});
    chSerials(b).forEach(function(s){
      var f=SERIAL_FAULTS[s];
      if(f)CH_FAILS.push({s:s,box:b.id,code:f.code,t:f.t,d:f.d});
    });
  });

  var checks=[
    {k:sel.length>0,t:'Boxes explicitly selected',
     d:sel.length?sel.length+' box(es) ticked — nothing implicit, nothing matched by wildcard':
       'Tick at least one box',c:sel.length+'',code:'E-NOBOX'},
    {k:!CH_FAILS.some(function(f){return f.code==='E-SHIPPED'}),
     t:'No serial already dispatched',
     d:'Every serial checked against prior challans and gate passes',
     c:CH_FAILS.filter(function(f){return f.code==='E-SHIPPED'}).length||'0',code:'E-SHIPPED'},
    {k:!CH_FAILS.some(function(f){return f.code==='E-OWNER'}),
     t:'Every serial belongs to this buyer',
     d:'Allocation customer compared to the challan party, serial by serial',
     c:CH_FAILS.filter(function(f){return f.code==='E-OWNER'}).length||'0',code:'E-OWNER'},
    {k:!CH_FAILS.some(function(f){return f.code==='E-NOFQC'||f.code==='E-GRADE'}),
     t:'Every serial has an acceptable FQC grade',
     d:'A missing grade or a rejected grade blocks the challan',
     c:CH_FAILS.filter(function(f){return f.code==='E-NOFQC'||f.code==='E-GRADE'}).length||'0',
     code:'E-NOFQC'},
    {k:!CH_FAILS.some(function(f){return f.code==='E-MODEL'}),
     t:'Wattage and model match the allocation',
     d:'Model derived at allocation compared to the box label',
     c:CH_FAILS.filter(function(f){return f.code==='E-MODEL'}).length||'0',code:'E-MODEL'},
    {k:!CH_FAILS.some(function(f){return f.code==='E-REPACK'}),
     t:'No pallet repacked since its list printed',
     d:'A rebuilt pallet whose paper list is stale is a loading error waiting to happen',
     c:CH_FAILS.filter(function(f){return f.code==='E-REPACK'}).length||'0',code:'E-REPACK'},
    {k:true,t:'No duplicate serial within this challan',
     d:'Each serial appears exactly once across all selected boxes',c:'0',code:'E-DUP'},
    {k:qty<=1000,t:'Quantity within allocation',
     d:'Challan quantity checked against what was allocated to this customer',
     c:qty+'',code:'E-QTY',soft:true}];

  var hard=checks.filter(function(c){return !c.k&&!c.soft}).length;
  var soft=checks.filter(function(c){return !c.k&&c.soft}).length;
  document.getElementById('vList').innerHTML=checks.map(function(c){
    var cls=c.k?'pass':(c.soft?'warn':'fail');
    return '<div class="vrow '+cls+'"><div class="vi">'+(c.k?'✓':(c.soft?'⚑':'✕'))+'</div>'+
      '<div><div class="vt">'+c.t+'</div><div class="vd">'+c.d+
      (c.k?'':' <span class="code">'+c.code+'</span>')+'</div></div>'+
      '<div class="vc">'+c.c+'</div></div>';
  }).join('');
  var badge=document.getElementById('vBadge');
  badge.className='tag '+(hard?'t-fail':soft?'t-rev':'t-pass');
  badge.textContent=hard?hard+' blocking':soft?soft+' needs override':'all clear';

  /* the refusal list — exact serial, exact reason */
  var fl=document.getElementById('chFails');
  fl.innerHTML=CH_FAILS.length?
    '<div class="card"><div class="card-h"><h3>Refused — pull these before the vehicle moves</h3>'+
    '<div class="ch-r"><span class="tag t-fail">'+CH_FAILS.length+' item(s)</span>'+
    '<button class="btn btn-ghost btn-sm" onclick="exportNote()">Export pull list</button></div></div>'+
    '<div class="card-b flush"><table><thead><tr><th>Serial</th><th>Box</th><th>Code</th>'+
    '<th>Reason</th><th>Detail</th></tr></thead><tbody>'+
    CH_FAILS.map(function(f){
      return '<tr><td class="mono"'+(f.s==='—'?' style="color:var(--ink3)"':'')+'>'+f.s+'</td>'+
        '<td class="mono">'+f.box+'</td><td><span class="code">'+f.code+'</span></td>'+
        '<td style="font-weight:600">'+f.t+'</td>'+
        '<td style="font-size:11.5px;color:var(--ink3)">'+f.d+'</td></tr>';
    }).join('')+'</tbody></table></div></div>':'';

  document.getElementById('chCreate').disabled=(hard>0)||(soft>0&&!chOverride);
  document.getElementById('chStatus').innerHTML=hard?
    '<div class="note n-bad" style="font-size:11.5px"><span>⚑</span><span>'+hard+
    ' blocking issue(s) across '+CH_FAILS.length+' item(s). These cannot be overridden — '+
    'the listed serials must be pulled or corrected first.</span></div>':
    (soft?
      '<div class="note n-warn" style="font-size:11.5px"><span>⚑</span><span>'+soft+
      ' condition(s) need an <b>override</b>. This is not a click-through.</span></div>'+
      '<div class="card" style="margin-bottom:12px"><div class="card-b" style="padding:11px 13px">'+
      '<div class="fld" style="margin-bottom:9px"><label>Override reason</label>'+
      '<select id="chOvR"><option value="">— coded reason —</option>'+
      '<option>OV-CUST — customer accepts this load</option>'+
      '<option>OV-PART — part load, balance follows</option></select></div>'+
      '<label class="chk"><input type="checkbox" id="chOvC" onchange="setOverride(this.checked)">'+
      '<span>I take responsibility for this override</span></label>'+
      '<div style="font-size:10.5px;color:var(--ink3);margin-top:7px">Recorded against <b>'+
      USER.name+'</b> ('+USER.role+') in the audit trail.</div></div></div>':
     '<div class="note n-ok" style="font-size:11.5px"><span>✓</span><span>All '+qty+
     ' serials verified. They will be reserved to CHN-456 the moment it is created — '+
     'reservation happens at draft, not at submit.</span></div>');
  if(!soft)chOverride=false;
}
function setOverride(v){
  var r=document.getElementById('chOvR');
  if(v&&(!r||!r.value)){toast('Pick a coded reason before taking the override.');
    document.getElementById('chOvC').checked=false;return}
  chOverride=v;runChecks();
  if(v)toast('Override armed — it will be written to the audit trail with your name.');
}
function createChallan(){
  if(CH_FAILS.length){toast('Cannot create — '+CH_FAILS.length+' item(s) still refused.');return}
  var sel=CH_BOXES.filter(function(b){return b.sel});
  var qty=sel.reduce(function(a,b){return a+b.q},0);
  toast(CH_DRAFT.no+' created · '+sel.length+' boxes · '+qty+
        ' serials reserved and locked. Number was fixed at draft.');
  CHALLAN_SEQ.next++;
  setTimeout(function(){go('gp',navBtn('gp'))},900);
}
/* ================= LOADING VERIFICATION (Team 3) ================= */
var LOAD_EXPECT=['A044','A045'],loaded=[];
function renderLoad(){
  document.getElementById('ldTag').textContent=loaded.length+' of '+LOAD_EXPECT.length;
  document.getElementById('ldTag').className='tag '+
    (loaded.length===LOAD_EXPECT.length?'t-pass':'t-rev');
  document.getElementById('ldList').innerHTML=LOAD_EXPECT.map(function(b){
    var on=loaded.indexOf(b)>=0;
    return '<div style="display:flex;align-items:center;gap:8px;padding:5px 0;'+
      'border-bottom:1px solid var(--line2);font-size:11.5px">'+
      '<span style="color:'+(on?'var(--pass)':'var(--line)')+';font-weight:700">'+
      (on?'✓':'○')+'</span><span class="mono">'+b+'</span>'+
      '<span style="margin-left:auto;color:var(--ink3);font-size:10.5px">'+
      (on?'on vehicle':'not loaded')+'</span></div>';
  }).join('');
  var done=loaded.length===LOAD_EXPECT.length;
  document.getElementById('gpBtn').disabled=!done;
  document.getElementById('ldMsg').innerHTML=done?
    '<div class="note n-ok" style="font-size:11.5px;margin:10px 0 0"><span>✓</span>'+
    '<span>Every box on the challan is physically on the vehicle. Gate pass can be issued.</span></div>':
    '<div class="note n-warn" style="font-size:11.5px;margin:10px 0 0"><span>⚑</span>'+
    '<span>Gate pass is blocked until all '+LOAD_EXPECT.length+
    ' boxes are scanned onto the vehicle.</span></div>';
}
function ldScanGo(){
  var el=document.getElementById('ldScan'),v=el.value.trim().toUpperCase();
  el.value='';el.focus();
  if(!v)return;
  if(loaded.indexOf(v)>=0){toast(v+' is already scanned onto this vehicle.');return}
  if(LOAD_EXPECT.indexOf(v)<0){
    toast(v+' is NOT on this challan. Do not load it — check the box number.');return}
  loaded.push(v);renderLoad();
  toast(v+' confirmed on vehicle · '+loaded.length+' of '+LOAD_EXPECT.length);
}
function issueGP(){
  toast('GP-2608-0031 issued. Packed, documented and loaded by three different people.');
}

/* Short material summary for the trace rail: size, vendor, cell efficiency.
   Batch numbers live behind "View full details". */
function matSummary(model){
  var list=materialsFor(model),seen={},out='';
  MAT_CATS.forEach(function(cat){
    var rows=list.filter(function(m){return m.cat===cat});
    if(!rows.length)return;
    rows.forEach(function(m){
      if(m.group){if(seen[m.group])return;seen[m.group]=1}
      var mm=m.group?chosenInGroup(list,m.group):m;
      out+='<tr><td style="font-size:11px;color:var(--ink3);line-height:1.35">'+mm.name+
        (mm.size!=='—'?'<br><span class="mono" style="font-size:10px">'+mm.size+'</span>':'')+
        '</td><td style="text-align:right"><div style="font-weight:600;font-size:11.5px">'+
        demoVendor(mm)+'</div><div class="mono" style="font-size:10px;color:var(--ink3)">'+
        mm.uom+(mm.cell?' · '+CELL_EFF[3]+' eff':'')+'</div></td></tr>';
    });
  });
  return out;
}
/* Full material detail, opened from Search & Trace. */
function showMaterials(model){
  var list=materialsFor(model),seen={},out='';
  MAT_CATS.forEach(function(cat){
    var rows=list.filter(function(m){return m.cat===cat});
    if(!rows.length)return;
    var body='';
    rows.forEach(function(m){
      if(m.group){if(seen[m.group])return;seen[m.group]=1}
      var mm=m.group?chosenInGroup(list,m.group):m;
      body+='<tr><td style="font-weight:600">'+mm.name+
        (mm.legacy?' <span class="tag t-mute">old</span>':'')+
        (mm.note?'<div class="hint">'+mm.note+'</div>':'')+'</td>'+
        '<td class="mono" style="font-size:11px">'+mm.size+'</td>'+
        '<td class="mono">'+mm.uom+'</td>'+
        '<td class="num">'+(qpmLabel(mm,model)||'—')+'</td>'+
        '<td>'+demoVendor(mm)+'</td>'+
        '<td class="mono">'+(mm.cell?CELL_EFF[3]:'<span style="color:var(--line)">—</span>')+'</td>'+
        '<td class="mono" style="font-size:10.5px;color:var(--ink3)">'+
          (mm.n%3===0?'—':'INV/26-27/'+(1000+mm.n))+'</td></tr>';
    });
    if(body)out+='<tr><td colspan="7" style="background:#F2F6FA;font-size:10px;font-weight:700;'+
      'color:var(--brand);text-transform:uppercase;letter-spacing:.8px">'+cat+'</td></tr>'+body;
  });
  document.getElementById('mdlTitle').textContent='Materials used · '+model;
  document.getElementById('mdlSub').textContent=
    'Sizes are fixed by the model. Make and batch were recorded at allocation.';
  modalMode(true);
  document.getElementById('mdlGeneric').innerHTML=
    '<div class="card" style="margin:0"><div class="card-h"><h3>Bill of materials</h3>'+
    '<div class="ch-r"><span class="tag t-mute">'+list.length+' materials</span></div></div>'+
    '<div class="card-b flush"><table><thead><tr><th>Material</th><th>Size / spec</th>'+
    '<th>UOM</th><th style="text-align:right">Per module</th><th>Make</th>'+
    '<th>Cell efficiency</th><th>Batch / invoice</th></tr></thead>'+
    '<tbody>'+out+'</tbody></table></div></div>';
  document.getElementById('mdl').classList.add('on');
}
/* Production Entry: a material changed part-way through a range.
   Until stores consumption exists this is recorded by hand — but it is recorded
   properly: which material, what it changed FROM and TO, at which serial, and
   verified by a second person who is not the one entering it. */
var MATCHG={};
function peMatToggle(){
  var on=document.getElementById('peMatChg').checked;
  var box=document.getElementById('peMatBox');
  box.style.display=on?'':'none';
  if(!on){box.innerHTML='';MATCHG={};return}
  renderMatChg();
}
function matChgPick(n,checked){
  if(checked)MATCHG[n]=MATCHG[n]||{};
  else delete MATCHG[n];
  renderMatChg();
}
function matChgSet(n,k,v){MATCHG[n]=MATCHG[n]||{};MATCHG[n][k]=v;renderMatChg()}
function renderMatChg(){
  var box=document.getElementById('peMatBox'); if(!box)return;
  var model=document.getElementById('peModel').textContent;
  if(!model||model==='—'){
    box.innerHTML='<div class="note n-warn" style="font-size:11.5px;margin:0"><span>&#9873;</span>'+
      '<span>Enter a valid serial range first — the model decides which materials can change.</span></div>';
    return;
  }
  var list=materialsFor(model),seen={},rows='';
  list.forEach(function(m){
    if(m.group){if(seen[m.group])return;seen[m.group]=1}
    var mm=m.group?chosenInGroup(list,m.group):m;
    var on=!!MATCHG[mm.n], sel=MATCHG[mm.n]||{};
    var alts=m.group?list.filter(function(x){return x.group===m.group}):[];
    var fields='';
    if(on){
      /* every material can change vendor */
      fields+=chgField(mm.n,'vendorFrom','Make — from',mm.makes,sel.vendorFrom)+
              chgField(mm.n,'vendorTo','Make — to',mm.makes,sel.vendorTo);
      /* a cell can also change efficiency */
      if(mm.cell)
        fields+=chgField(mm.n,'effFrom','Efficiency — from',CELL_EFF,sel.effFrom)+
                chgField(mm.n,'effTo','Efficiency — to',CELL_EFF,sel.effTo);
      /* a grouped material can change variant, e.g. JB wire length */
      if(alts.length>1)
        fields+=chgField(mm.n,'variantFrom','Variant — from',
                  alts.map(function(a){return a.size}),sel.variantFrom)+
                chgField(mm.n,'variantTo','Variant — to',
                  alts.map(function(a){return a.size}),sel.variantTo);
      fields+='<div class="mat-f"><label>Changed at serial</label>'+
        '<input class="mono" placeholder="first serial with the new material" value="'+
        (sel.at||'')+'" oninput="MATCHG['+mm.n+'].at=this.value"></div>';
    }
    rows+='<div class="matrow" style="grid-template-columns:minmax(200px,1fr) repeat(auto-fit,minmax(140px,1fr))">'+
      '<div class="mat-id"><label class="chk"><input type="checkbox"'+(on?' checked':'')+
        ' onchange="matChgPick('+mm.n+',this.checked)"><b>'+mm.name+'</b></label>'+
      '<div class="mat-sz">'+mm.size+' · '+mm.uom+'</div></div>'+fields+'</div>';
  });
  var n=Object.keys(MATCHG).length;
  var others=USERS.filter(function(u){return u.on&&u.n!==USER.name&&
    (u.r==='Production Incharge'||u.r==='Admin')});
  box.innerHTML=rows+
    '<div class="card" style="margin:12px 0 0;background:#FBFCFE">'+
    '<div class="card-h"><h3>Second verification</h3>'+
    '<div class="ch-r"><span class="tag '+(n?'t-rev':'t-mute')+'">'+n+' material(s) changed</span></div></div>'+
    '<div class="card-b">'+
      '<div class="grid g2">'+
        '<div class="fld req"><label>Verified by</label><select id="mcVerifier">'+
          '<option value="">— select —</option>'+
          others.map(function(u){return '<option>'+u.n+' · '+u.r+'</option>'}).join('')+
          '</select><div class="hint">You cannot verify your own entry — '+USER.name+
          ' is not on this list</div></div>'+
        '<div class="fld"><label>Verification note</label>'+
          '<input placeholder="what was seen on the floor"></div>'+
      '</div>'+
      '<button class="btn btn-primary" onclick="saveMatChg()">Record material change</button>'+
    '</div></div>'+
    '<div class="note n-warn" style="font-size:11px;margin:12px 0 0"><span>&#9873;</span><span>'+
    'Provisional design pending Humeshwar. Modules before the changeover serial keep the original '+
    'material; modules after it carry the new one.</span></div>';
}
function chgField(n,k,label,opts,val){
  return '<div class="mat-f"><label>'+label+'</label><select '+
    'onchange="matChgSet('+n+',\''+k+'\',this.value)">'+
    '<option value="">— select —</option>'+
    opts.map(function(o){return '<option'+(val===o?' selected':'')+'>'+o+'</option>'}).join('')+
    '</select></div>';
}
function saveMatChg(){
  var n=Object.keys(MATCHG);
  if(!n.length){toast('Tick at least one material that changed.');return}
  var v=document.getElementById('mcVerifier');
  if(!v||!v.value){toast('A second verifier is required — this cannot be self-certified.');return}
  var bad=n.filter(function(k){return !MATCHG[k].at});
  if(bad.length){toast('Every changed material needs the serial where the change starts.');return}
  toast(n.length+' material change(s) recorded, verified by '+v.value.split(' · ')[0]+'.');
}

/* ================= DRAFTS & MATERIAL RESERVATION =================
   A draft is not a scratchpad — it holds material. Planning drafts hold serial
   ranges, packing drafts hold boxes, dispatch drafts hold a challan's boxes.
   Anyone attempting to use held material anywhere else is stopped and sent to
   the draft that holds it, including the person who saved it.
   Visibility: Admin sees everything; everyone else sees their own section and
   can edit a colleague's draft in the same section.                            */
var DRAFTS=[
 {id:'DRF-2608-0012',type:'Planning',section:'Production',view:'plan',
  hold:'ICON590G1280610400 → ICON590G1280610599',kind:'serial',
  from:'ICON590G1280610400',to:'ICON590G1280610599',qty:200,
  by:'Rajesh Kumar',role:'Production Incharge',at:'21-08-2026 11:20',
  fields:{cust:'SAI BABUJI PROJECTS PRIVATE LIMITED (MH)'},
  mats:{1:{vendor:'Tongwei Solar',eff:'25.3%',batch:'TAX/25-26/14'},
        2:{vendor:'Borosil'},3:{vendor:'Borosil'},4:{vendor:'Sudarshan'}}},
 {id:'DRF-2608-0011',type:'Planning',section:'Production',view:'plan',
  hold:'ICON625R12A2110000 → ICON625R12A2110149',kind:'serial',
  from:'ICON625R12A2110000',to:'ICON625R12A2110149',qty:150,
  by:'Mukesh',role:'Admin',at:'20-08-2026 16:44',
  fields:{cust:'SG MEDA'},
  mats:{5:{vendor:'Yingfa',eff:'25.5%'},6:{vendor:'Kibing'}}},
 {id:'DRF-2608-0010',type:'Packing list',section:'Packing',view:'pack',
  hold:'A047',kind:'box',boxes:['A047'],qty:36,
  by:'Suresh Patel',role:'Packing Operator',at:'21-08-2026 13:02',
  fields:{cap:'36',grade:'A',bin:'4'},scanned:14},
 {id:'DRF-2608-0009',type:'Challan',section:'Dispatch',view:'challan',
  hold:'CHN-457 · A039',kind:'box',boxes:['A039'],qty:36,
  by:'Dasrath Pal',role:'Dispatch Operator',at:'21-08-2026 09:15',
  fields:{party:'SAI BABUJI PROJECTS PRIVATE LIMITED (MH)',vehicle:'CG04MM1521'},
  boxSel:['A039']}];
var dfView='all';
function draftsVisible(){
  if(USER.role==='Admin')return DRAFTS;
  var mySections={'Production Incharge':'Production','FQC Operator':'FQC',
    'Packing Operator':'Packing','Dispatch Operator':'Dispatch'};
  var sec=mySections[USER.role];
  return DRAFTS.filter(function(d){return d.section===sec});
}
function dfFilter(btn,v){
  btn.parentNode.querySelectorAll('button').forEach(function(b){b.classList.remove('on')});
  btn.classList.add('on');dfView=v;renderDrafts();
}
function dfDays(at){
  var p=at.split(' ')[0].split('-');
  return Math.max(0,Math.round((Date.now()-new Date(+p[2],+p[1]-1,+p[0]).getTime())/86400000));
}
function renderDrafts(){
  if(!document.getElementById('draftRows'))return;
  var vis=draftsVisible();
  var rows=dfView==='mine'?vis.filter(function(d){return d.by===USER.name}):vis;
  document.getElementById('dfScope').textContent=
    USER.role==='Admin'?'Admin — all sections':'Your section only';
  document.getElementById('dk1').textContent=vis.length;
  document.getElementById('dk1d').textContent=
    USER.role==='Admin'?'across every section':'in your section';
  document.getElementById('dk2').textContent=
    vis.reduce(function(a,d){return a+d.qty},0).toLocaleString();
  document.getElementById('dk3').textContent=
    vis.length?Math.max.apply(null,vis.map(function(d){return dfDays(d.at)})):0;
  document.getElementById('dk4').textContent=
    vis.filter(function(d){return d.by===USER.name}).length;
  document.getElementById('draftBadge').textContent=vis.length;
  document.getElementById('draftRows').innerHTML=rows.length?rows.map(function(d){
    var mine=d.by===USER.name;
    return '<tr><td class="mono" style="font-weight:700">'+d.id+'</td>'+
      '<td>'+d.type+'</td><td style="color:var(--ink3)">'+d.section+'</td>'+
      '<td class="mono" style="font-size:11px">'+d.hold+'</td>'+
      '<td class="num">'+d.qty+'</td>'+
      '<td>'+d.by+(mine?' <span class="tag t-info">you</span>':'')+'</td>'+
      '<td class="mono" style="font-size:11px">'+d.at+'</td>'+
      '<td><button class="btn btn-ghost btn-sm" onclick="openDraft(\'' +d.id+ '\')">'+
        (mine?'Continue':'Open')+'</button> '+
      '<button class="btn btn-danger btn-sm" onclick="cancelDraft(\'' +d.id+ '\')">Cancel</button>'+
      '</td></tr>';
  }).join(''):'<tr><td colspan="8"><div class="empty-state">'+
    '<p>No drafts you can see.</p></div></td></tr>';
}
function openDraft(id){
  var d=DRAFTS.filter(function(x){return x.id===id})[0]; if(!d)return;
  if(!can(d.view)){toast('Your role cannot open a '+d.section+' draft.');return}
  go(d.view);
  var restored=[];
  var set=function(elId,val,label){
    var el=document.getElementById(elId);
    if(el&&val!=null&&val!==''){el.value=val;restored.push(label)}
  };
  if(d.view==='plan'){
    set('rgFrom',d.from,'start serial');
    set('rgTo',d.to,'end serial');
    if(d.fields){set('pCust',d.fields.cust,'customer');set('pCustEcho',d.fields.cust,'')}
    MAT_SEL={};
    if(d.mats)Object.keys(d.mats).forEach(function(k){MAT_SEL[k]=d.mats[k]});
    rangeCalc();
    if(d.mats)restored.push(Object.keys(d.mats).length+' material selections');
  }else if(d.view==='pack'&&d.fields){
    set('capSel',d.fields.cap,'pallet size');
    set('binNo',d.fields.bin,'bin');
    if(d.fields.cap){cap=parseInt(d.fields.cap,10);buildSlots()}
    binTog();
    if(d.scanned){
      var base='ICON590G1280610000';
      for(var i=0;i<d.scanned;i++)addSlot(bumpSerial(base,i));
      restored.push(d.scanned+' modules already scanned');
    }
  }else if(d.view==='challan'&&d.fields){
    set('chParty',d.fields.party,'party');
    if(d.boxSel){
      CH_BOXES.forEach(function(b){b.sel=d.boxSel.indexOf(b.id)>=0});
      renderChBoxes();restored.push(d.boxSel.length+' box selection');
    }
    runChecks();
  }
  var who=(d.by===USER.name)?'':' — saved by '+d.by;
  toast('Draft '+d.id+' reopened'+who+
    (restored.length?'. Restored: '+restored.join(', ')+'.':'.')+
    (d.by===USER.name?'':' Your edits are recorded against you.'));
}
function cancelDraft(id){
  var d=DRAFTS.filter(function(x){return x.id===id})[0]; if(!d)return;
  if(d.by!==USER.name&&USER.role!=='Admin'){
    toast('Only '+d.by+' or an Admin can cancel this draft.');return}
  if(!confirm('Cancel '+d.id+'? Its '+d.qty+' reserved item(s) are released. '+
              'The draft record is kept, not deleted.'))return;
  d.cancelled=true;
  DRAFTS=DRAFTS.filter(function(x){return x.id!==id});
  renderDrafts();
  toast(id+' cancelled — '+d.qty+' item(s) released back to the pool.');
}
/* Reservation check. Called from any screen before material is used. */
function reservedBy(ref){
  ref=(ref||'').trim().toUpperCase();
  if(!ref)return null;
  for(var i=0;i<DRAFTS.length;i++){
    var d=DRAFTS[i];
    if(d.kind==='box'&&d.boxes&&d.boxes.indexOf(ref)>=0)return d;
    if(d.kind==='serial'){
      var a=parseSerial(d.from),b=parseSerial(d.to),m=parseSerial(ref);
      if(a.ok&&b.ok&&m.ok&&a.watt===m.watt&&a.tc===m.tc&&a.v===m.v){
        var i0=serialIndex(a),i1=serialIndex(b),ix=serialIndex(m);
        if(ix>=i0&&ix<=i1)return d;
      }
    }
  }
  return null;
}
function dfCheck(){
  var v=document.getElementById('dfTest').value.trim().toUpperCase();
  var out=document.getElementById('dfResult');
  if(!v){out.innerHTML='';return}
  var d=reservedBy(v);
  out.innerHTML=d?
    '<div class="note n-bad" style="margin:12px 0 0"><span>&#9873;</span><span>'+
    '<b>'+v+' is held by draft '+d.id+'</b> ('+d.type+', saved by '+d.by+' on '+d.at+').<br>'+
    'It cannot be used in another batch until that draft is completed or cancelled.'+
    '<div style="margin-top:9px;display:flex;gap:8px">'+
    '<button class="btn btn-ghost btn-sm" onclick="openDraft(\'' +d.id+ '\')">Go to draft</button>'+
    (d.by===USER.name||USER.role==='Admin'?
      '<button class="btn btn-danger btn-sm" onclick="cancelDraft(\'' +d.id+
      '\');dfCheck()">Cancel the draft &amp; release</button>':'')+
    '</div></span></div>':
    '<div class="note n-ok" style="margin:12px 0 0"><span>&#10003;</span><span>'+v+
    ' is free — no draft is holding it.</span></div>';
}

/* ================= HOLD & DEVIATION ================= */
var HOLDS=[
 {id:'HLD-2608-0007',scope:'material',ref:'Front glass · BOROSIL · 9000021385',qty:1840,
  reason:'QH-SUPPLIER',desc:'Supplier flagged possible delamination risk on this glass batch.',
  by:'Rajesh Kumar',at:'21-08-2026 09:40',status:'Open',disp:''},
 {id:'HLD-2608-0006',scope:'box',ref:'A038',qty:36,reason:'QH-VISUAL',
  desc:'Frame scratch trend seen on four modules during loading.',
  by:'Suresh Patel',at:'20-08-2026 16:05',status:'Under investigation',disp:''},
 {id:'HLD-2608-0005',scope:'serial',ref:'ICON590G1202121044',qty:1,reason:'QH-TEST',
  desc:'Failed re-test at FQC after packing.',by:'Amit Sharma',at:'20-08-2026 11:22',
  status:'Open',disp:''},
 {id:'HLD-2608-0004',scope:'batch',ref:'BAT-2602-00019',qty:70,reason:'QH-DOC',
  desc:'Customer name mismatch against the sales order.',by:'Mukesh',at:'18-08-2026 10:01',
  status:'Closed',disp:'Released'},
 {id:'HLD-2608-0003',scope:'serial',ref:'ICON625R1110152099',qty:1,reason:'QH-FIELD',
  desc:'Returned from site with junction box fault.',by:'Dasrath Pal',at:'14-08-2026 15:30',
  status:'Closed',disp:'Scrapped'}];
var holdView='open',holdOpen=null;
var SCOPE_HINT={
 serial:'Freezes one module wherever it is.',
 box:'Freezes every module in the box, and the box itself.',
 batch:'Freezes every serial allocated in that batch.',
 material:'Freezes every module whose BOM records that lot — this is what the material '+
   'traceability was built for.'};
var SCOPE_LBL={serial:'Serial number',box:'Box number',batch:'Batch number',
  material:'Material & batch'};
var SCOPE_OPTS={
 serial:['ICON590G1202121044','ICON590G1202121051','ICON625R1110152099'],
 box:['A038','A044','A045'],
 batch:['BAT-2602-00019','BAT-2602-00020','BAT-2608-00044'],
 material:['Front glass · BOROSIL · 9000021385','Back glass · BOROSIL · 9000021385',
   'Cell · GOPIN M10R · TAX/25-26/14','Junction box · GNEX 30A · JB-2608-11',
   'Frame · SUDARSHAN · FR-2607-04']};
var SCOPE_QTY={serial:1,box:36,batch:70,material:1840};
function holdScopeChange(){
  var s=document.getElementById('hScope').value;
  document.getElementById('hScopeHint').textContent=SCOPE_HINT[s];
  document.getElementById('hRefLbl').textContent=SCOPE_LBL[s];
  document.getElementById('hRef').innerHTML=SCOPE_OPTS[s].map(function(o){
    return '<option>'+o+'</option>'}).join('');
  holdEstimate();
}
function holdEstimate(){
  var s=document.getElementById('hScope').value,q=SCOPE_QTY[s];
  var spread=s==='material'?
    '<div style="margin-top:7px;font-size:11px;line-height:1.7">'+
    '· 1,180 already packed<br>· 540 already dispatched — <b>customer notification needed</b>'+
    '<br>· 120 still in production</div>':'';
  document.getElementById('hEst').innerHTML=
    '<div class="note n-warn" style="font-size:11.5px;margin:4px 0 0"><span>⚑</span><span>'+
    'About <b>'+q.toLocaleString()+'</b> module(s) would be frozen immediately.'+spread+
    '</span></div>';
}
function holdFilter(btn,v){
  btn.parentNode.querySelectorAll('button').forEach(function(b){b.classList.remove('on')});
  btn.classList.add('on');holdView=v;renderHolds();
}
function renderHolds(){
  var open=HOLDS.filter(function(h){return h.status!=='Closed'});
  document.getElementById('hkOpen').textContent=open.filter(function(h){return h.status==='Open'}).length;
  document.getElementById('hkQty').textContent=open.reduce(function(a,h){return a+h.qty},0).toLocaleString();
  document.getElementById('hkInv').textContent=
    HOLDS.filter(function(h){return h.status==='Under investigation'}).length;
  document.getElementById('hkClosed').textContent=
    HOLDS.filter(function(h){return h.status==='Closed'}).length;
  document.getElementById('holdBadge').textContent=open.length;
  var rows=holdView==='open'?open:HOLDS;
  document.getElementById('holdRows').innerHTML=rows.map(function(h,i){
    var idx=HOLDS.indexOf(h);
    var st=h.status==='Open'?'t-fail':h.status==='Under investigation'?'t-rev':'t-mute';
    return '<tr><td class="mono" style="font-weight:700">'+h.id+'</td>'+
      '<td><span class="tag t-info">'+h.scope+'</span></td>'+
      '<td class="mono" style="font-size:11px">'+h.ref+'</td>'+
      '<td class="num">'+h.qty.toLocaleString()+'</td>'+
      '<td><span class="code">'+h.reason+'</span></td>'+
      '<td style="font-size:11.5px">'+h.by+'</td>'+
      '<td><span class="tag '+st+'">'+h.status+(h.disp?' · '+h.disp:'')+'</span></td>'+
      '<td><button class="btn btn-ghost btn-sm" onclick="openHold('+idx+')">Open</button></td></tr>';
  }).join('')||'<tr><td colspan="8"><div class="empty-state"><p>No holds.</p></div></td></tr>';
}
function openHold(i){
  var h=HOLDS[i];holdOpen=i;
  var mine=(h.by===USER.name);
  var canRelease=(USER.role==='Admin'||USER.role==='Production Incharge');
  var blocked=mine||!canRelease;
  document.getElementById('holdDetail').innerHTML=
   '<div class="card"><div class="card-h"><h3>'+h.id+'</h3>'+
   '<div class="ch-r"><span class="tag t-info">'+h.scope+'</span>'+
   '<span class="tag t-mute">'+h.at+'</span></div></div>'+
   '<div class="card-b">'+
     '<div class="lookup" style="border:1px solid var(--line);border-radius:var(--r);'+
     'overflow:hidden;margin-bottom:12px">'+
       '<div><label>Applies to</label><div class="lv mono" style="font-size:11px">'+h.ref+'</div></div>'+
       '<div><label>Modules frozen</label><div class="lv mono">'+h.qty.toLocaleString()+'</div></div>'+
       '<div><label>Reason</label><div class="lv mono">'+h.reason+'</div></div>'+
       '<div><label>Raised by</label><div class="lv" style="font-size:11.5px">'+h.by+'</div></div>'+
       '<div><label>Status</label><div class="lv">'+h.status+'</div></div>'+
       '<div><label>Disposition</label><div class="lv">'+(h.disp||'—')+'</div></div>'+
     '</div>'+
     '<p style="font-size:12px;margin-bottom:12px">'+h.desc+'</p>'+
     (h.status==='Closed'?
       '<div class="note n-ok" style="margin:0"><span>✓</span><span>Closed as <b>'+h.disp+
       '</b>. The record stays for search and history.</span></div>':
       (blocked?
         '<div class="note n-bad" style="margin:0"><span>⚑</span><span>'+
         (mine?'You raised this hold. <b>The same person cannot raise and release it</b> — '+
               'a second pair of eyes is the point of the control.':
               'Your role cannot release a hold. Production Incharge or Admin only.')+
         '</span></div>':
         '<div class="card-f" style="padding:0;border:none;gap:8px">'+
         '<button class="btn btn-ghost" onclick="dispose('+i+',\'Released\')">Release to stock</button>'+
         '<button class="btn btn-ghost" onclick="dispose('+i+',\'Rework\')">Send to rework</button>'+
         '<button class="btn btn-danger" onclick="dispose('+i+',\'Scrapped\')">Scrap</button>'+
         '<span style="margin-left:auto;font-size:11px;color:var(--ink3);align-self:center">'+
         'Signed as '+USER.name+'</span></div>'))+
   '</div></div>';
  document.getElementById('holdDetail').scrollIntoView({behavior:'smooth',block:'nearest'});
}
function dispose(i,d){
  HOLDS[i].status='Closed';HOLDS[i].disp=d;
  renderHolds();openHold(i);
  toast(HOLDS[i].id+' closed as '+d+' by '+USER.name+' — '+
        HOLDS[i].qty.toLocaleString()+' module(s) unfrozen.');
}
function raiseHold(){
  var s=document.getElementById('hScope').value;
  var ref=document.getElementById('hRef').value;
  var rc=document.getElementById('hReason').value.split(' — ')[0];
  var n=HOLDS.length+8;
  HOLDS.unshift({id:'HLD-2608-'+String(n).padStart(4,'0'),scope:s,ref:ref,qty:SCOPE_QTY[s],
    reason:rc,desc:'Raised from the Hold screen.',by:USER.name,
    at:new Date().toLocaleString(),status:'Open',disp:''});
  holdView='open';renderHolds();
  toast(SCOPE_QTY[s].toLocaleString()+' module(s) frozen. They are now refused at packing, '+
        'challan and gate pass.');
}

/* ================= DEGRADED MODE (simulation) ================= */
var ONLINE=true,QUEUE=0,qTimer;
function toggleConn(){
  ONLINE=!ONLINE;
  var c=document.getElementById('conn');
  c.className='conn '+(ONLINE?'on':'off');
  document.getElementById('connTxt').textContent=ONLINE?'Online':'Offline';
  document.getElementById('offbar').classList.toggle('on',!ONLINE);
  clearInterval(qTimer);
  if(!ONLINE){
    toast('Server unreachable. Station switched to its shift cache — keep scanning.');
    qTimer=setInterval(function(){QUEUE++;paintQueue()},2200);
  }else if(QUEUE){
    toast('Server back. Syncing '+QUEUE+' queued record(s)…');
    var q=QUEUE;
    qTimer=setInterval(function(){
      QUEUE=Math.max(0,QUEUE-3);paintQueue();
      if(!QUEUE){clearInterval(qTimer);toast(q+' record(s) synced. Nothing lost.')}
    },260);
  }
  paintQueue();
}
function paintQueue(){
  document.getElementById('offq').textContent=QUEUE+' queued';
  document.getElementById('connTxt').textContent=
    ONLINE?(QUEUE?'Syncing '+QUEUE:'Online'):'Offline · '+QUEUE+' queued';
}
/* ================= ADMIN CONSOLE ================= */
/* ================= FILTERS & ACTIONS THAT NEED NO DATABASE =================
   Filtering, resolving, adding master rows and printing are all client-side or
   browser-native. Only genuine persistence waits for the backend.            */

/* ---- FQC dashboard ---- */
function fqcApply(){
  var g=function(id){var e=document.getElementById(id);return e?e.value:''};
  var sh=g('fDashShift'),cu=g('fDashCust'),mo=g('fDashModel'),re=g('fDashResult');
  var rows=SHIFT_ROWS.filter(function(r){
    if(sh!=='All shifts'&&r.s!==sh)return false;
    if(mo!=='All'&&r.m!==mo)return false;
    return true;});
  var t=rows.reduce(function(a,r){return a+r.t},0),
      ok=rows.reduce(function(a,r){return a+r.ok},0),
      rj=rows.reduce(function(a,r){return a+r.r},0);
  document.getElementById('shiftRows').innerHTML=rows.length?rows.map(function(r,i){
    var span=(i===0||rows[i-1].s!==r.s);
    var cnt=rows.filter(function(x){return x.s===r.s}).length;
    var pct=(r.r/r.t*100).toFixed(2);
    return '<tr>'+(span?'<td rowspan="'+cnt+'" class="s'+r.s+'">'+r.s+'</td>':'')+
      '<td class="mono">'+r.w+'</td><td class="mono">'+r.m+'</td>'+
      '<td class="num">'+r.t.toLocaleString()+'</td><td class="num">'+r.ok.toLocaleString()+'</td>'+
      '<td class="num">'+r.r+'</td>'+
      '<td><div class="bar-wrap"><div class="bar"><i style="width:'+Math.min(pct*12,100)+
        '%"></i></div><span class="mono">'+pct+'%</span></div></td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="openModules({title:\'Shift '+r.s+' · '+r.w+'\',shift:\''+r.s+'\'})">View '+
      r.t.toLocaleString()+'</button></td></tr>';
  }).join(''):'<tr><td colspan="8"><div class="empty-state">'+
    '<p>Nothing matches these filters.</p></div></td></tr>';
  var f=document.getElementById('shiftFoot');
  if(f)f.innerHTML='<td>Total</td><td style="color:var(--ink3)">—</td>'+
    '<td style="color:var(--ink3)">—</td><td class="num">'+t.toLocaleString()+'</td>'+
    '<td class="num">'+ok.toLocaleString()+'</td><td class="num">'+rj+'</td>'+
    '<td class="mono">'+(t?(rj/t*100).toFixed(2)+'%':'—')+'</td><td></td>';
  var act=[];
  if(sh!=='All shifts')act.push('Shift '+sh);
  if(cu!=='All customers')act.push(cu);
  if(mo!=='All')act.push(mo);
  if(re!=='All')act.push(re);
  var note=document.getElementById('fDashNote');
  if(note)note.innerHTML=act.length?
    '<div class="note n-info" style="font-size:11.5px"><span>&#9432;</span><span>Filtered by <b>'+
    act.join('</b>, <b>')+'</b> · '+t.toLocaleString()+' inspected. Clear with Reset.</span></div>':'';
}
function fqcResetFilters(){
  [['fDashShift','All shifts'],['fDashCust','All customers'],['fDashModel','All'],
   ['fDashResult','All']].forEach(function(x){
    var e=document.getElementById(x[0]); if(e)e.value=x[1];});
  var t=document.getElementById('fTo'),fr=document.getElementById('fFrom');
  if(fr)fr.value='2026-08-19'; if(t)t.value='2026-08-19';
  fqcRange();fqcApply();toast('Filters reset.');
}

/* ---- Packing log ---- */
var PK_ROWS=null;
function packApply(){
  var g=function(id){var e=document.getElementById(id);return e?e.value:''};
  var st=g('pkStatus'),gr=g('pkGrade'),cu=g('pkCust'),mo=g('pkModel'),sh=g('pkShift');
  var body=document.getElementById('pkBoxRows'); if(!body)return;
  if(!PK_ROWS)PK_ROWS=[].slice.call(body.querySelectorAll('tr')).map(function(tr){
    return {el:tr,txt:tr.textContent};});
  var shown=0;
  PK_ROWS.forEach(function(r){
    var keep=true;
    if(st!=='All'&&r.txt.indexOf(st)<0)keep=false;
    if(gr!=='All'&&!new RegExp('\\b'+gr+'\\b').test(r.txt))keep=false;
    if(cu!=='All customers'&&r.txt.indexOf(cu.split(' ')[0])<0)keep=false;
    if(mo!=='All'&&r.txt.indexOf(mo)<0)keep=false;
    r.el.style.display=keep?'':'none';
    if(keep)shown++;
  });
  var n=document.getElementById('pkCount');
  if(n)n.textContent=shown+' of '+PK_ROWS.length+' boxes';
  toast(shown+' box(es) match.');
}
function packLogReset(){
  [['pkStatus','All'],['pkGrade','All'],['pkCust','All customers'],['pkModel','All'],
   ['pkShift','All shifts']].forEach(function(x){
    var e=document.getElementById(x[0]); if(e)e.value=x[1];});
  packApply();
}

/* ---- Dispatch ---- */
function dispApply(){
  var g=function(id){var e=document.getElementById(id);return e?e.value:''};
  var act=[g('dpCust'),g('dpModel'),g('dpGrade')].filter(function(v){
    return v&&v.indexOf('All')<0;});
  var note=document.getElementById('dpNote');
  if(note)note.innerHTML=act.length?
    '<div class="note n-info" style="font-size:11.5px"><span>&#9432;</span><span>Filtered by <b>'+
    act.join('</b>, <b>')+'</b>.</span></div>':'';
  toast(act.length?'Filtered by '+act.join(', ')+'.':'Showing everything.');
}

/* ---- Needs review ---- */
var RV_FILTER='All';
function rvFilter(btn,v){
  btn.parentNode.querySelectorAll('button').forEach(function(b){b.classList.remove('on')});
  btn.classList.add('on');RV_FILTER=v;
  var n=0;
  document.querySelectorAll('#rvRows tr').forEach(function(tr){
    var keep=(v==='All')||tr.textContent.indexOf(v)>=0;
    tr.style.display=keep?'':'none'; if(keep)n++;});
  toast(n+' flagged entr'+(n===1?'y':'ies')+' shown.');
}
function rvResolve(btn,serial){
  var tr=btn.closest('tr');
  tr.style.opacity='.45';
  tr.querySelector('td:last-child').innerHTML=
    '<span class="tag t-pass">Resolved</span>';
  AUDIT.unshift([new Date().toLocaleString(),USER.name,'Update','Needs review',serial,
    'status','Flagged → Resolved','—']);
  try{renderDocs()}catch(e){}
  toast(serial+' marked resolved by '+USER.name+' — the flag stays in history.');
}

/* ---- Printing: browser-native, no backend needed ---- */
function printDoc(kind,ref,copies){
  DOCLOG.unshift([new Date().toLocaleString(),kind,ref,'Printed',copies||1,
    kind.slice(0,2).toUpperCase()+'-v'+(kind==='Packing list'?'3':'4'),USER.name,
    stationOf(USER.station).id]);
  try{renderDocs()}catch(e){}
  toast(kind+' '+ref+' sent to printer ('+(copies||1)+' cop'+((copies||1)>1?'ies':'y')+
        ') and written to the print log.');
  try{window.print()}catch(e){}
}
function savePallet(print){
  if(filled===0){toast('Nothing scanned into this box yet.');return}
  var box=document.getElementById('boxNo').textContent;
  if(print)printDoc('Packing list',box,3);
  else toast(box+' saved with '+filled+' module(s). No list printed.');
  resetPallet();
}

/* ---- Adding master rows ---- */
function addRecord(kind){
  if(USER.role!=='Admin'){toast('Only Admin can add master data.');return}
  var sp=EDIT_SPECS[kind]; if(!sp){toast('Not available yet.');return}
  var arr=sp.arr(), blank={};
  sp.fields.forEach(function(f){blank[f.k]=(f.t==='bool')?false:(f.t==='list')?[]:''});
  if(kind==='material')blank.n=Math.max.apply(null,arr.map(function(m){return m.n}))+1;
  if(kind==='user')blank.id='NEW-'+(arr.length+1);
  blank.last='—'; blank.on=true;
  arr.push(blank);
  EDIT_CTX={kind:kind,rec:blank,isNew:true};
  editRecord(kind,blank[sp.key]);
}

/* ================= GSTIN =================
   Format: 2 state code | 10 PAN | 1 entity number | 1 default Z | 1 checksum.
   State name and state code are DERIVED from the GSTIN, never typed — a typed
   state that disagrees with the number on the invoice is a filing error waiting
   to happen. The checksum is verified too, so a transposed digit is caught at
   entry rather than at the gate.                                              */
var GST_STATES={
 '01':['Jammu and Kashmir','UT'],      '02':['Himachal Pradesh','State'],
 '03':['Punjab','State'],              '04':['Chandigarh','UT'],
 '05':['Uttarakhand','State'],         '06':['Haryana','State'],
 '07':['Delhi','UT'],                  '08':['Rajasthan','State'],
 '09':['Uttar Pradesh','State'],       '10':['Bihar','State'],
 '11':['Sikkim','State'],              '12':['Arunachal Pradesh','State'],
 '13':['Nagaland','State'],            '14':['Manipur','State'],
 '15':['Mizoram','State'],             '16':['Tripura','State'],
 '17':['Meghalaya','State'],           '18':['Assam','State'],
 '19':['West Bengal','State'],         '20':['Jharkhand','State'],
 '21':['Odisha','State'],              '22':['Chhattisgarh','State'],
 '23':['Madhya Pradesh','State'],      '24':['Gujarat','State'],
 '25':['Daman and Diu','UT (merged)'],
 '26':['Dadra and Nagar Haveli and Daman and Diu','UT'],
 '27':['Maharashtra','State'],
 '28':['Andhra Pradesh (pre-bifurcation)','State (legacy)'],
 '29':['Karnataka','State'],           '30':['Goa','State'],
 '31':['Lakshadweep','UT'],            '32':['Kerala','State'],
 '33':['Tamil Nadu','State'],          '34':['Puducherry','UT'],
 '35':['Andaman and Nicobar Islands','UT'],
 '36':['Telangana','State'],           '37':['Andhra Pradesh','State'],
 '38':['Ladakh','UT'],
 '97':['Other Territory','—'],         '99':['Other Country (imports)','—']};
var GST_LEGACY={'25':'Merged into 26 — Dadra and Nagar Haveli and Daman and Diu',
                '28':'Split into 37 (Andhra Pradesh) and 36 (Telangana)'};
var GST_CS='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ';
function gstChecksum(first14){
  var sum=0;
  for(var i=0;i<14;i++){
    var v=GST_CS.indexOf(first14[i]);
    if(v<0)return null;
    var p=v*((i%2)+1);
    sum+=Math.floor(p/36)+(p%36);
  }
  return GST_CS[(36-(sum%36))%36];
}
function gstParse(raw){
  var g=(raw||'').trim().toUpperCase().replace(/\s/g,'');
  if(!g)return {ok:false,empty:true,why:'No GSTIN entered'};
  if(g.length!==15)return {ok:false,why:'A GSTIN is 15 characters — this one has '+g.length};
  if(!/^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][0-9A-Z]Z[0-9A-Z]$/.test(g))
    return {ok:false,why:'Does not match the GSTIN pattern (2 digits, PAN, entity, Z, checksum)'};
  var code=g.slice(0,2), st=GST_STATES[code];
  if(!st)return {ok:false,code:code,why:'State code '+code+' is not a valid GST state code'};
  if(g[13]!=='Z')return {ok:false,why:'Character 14 must be Z'};
  var want=gstChecksum(g.slice(0,14));
  if(want!==g[14])
    return {ok:false,code:code,state:st[0],why:'Checksum is '+g[14]+' but should be '+want+
      ' — check for a mistyped character'};
  return {ok:true,gstin:g,code:code,state:st[0],type:st[1],pan:g.slice(2,12),
          entity:g[12],legacy:GST_LEGACY[code]||null};
}
/* Interstate vs intrastate follows from the two state codes. */
var UNIT2_GSTIN='22AADCI5761L3ZE';             /* ICON SOLAR - EN POWER TECHNOLOGIES PVT LTD */
var UNIT2_STATE=UNIT2_GSTIN.slice(0,2);        /* 22 — Chhattisgarh, Raipur */
function gstSupplyType(buyerCode){
  return buyerCode===UNIT2_STATE?'Intrastate — CGST + SGST':'Interstate — IGST';
}

/* ================= INLINE RECORD EDITOR =================
   Master data lives in memory in this prototype, so every Edit button works for
   real: change a value, save, and the screen it came from redraws. Nothing here
   needs a database — when the Flask build lands, saveRecord() becomes a POST and
   the rest of the screen is unchanged.                                          */
var EDIT_SPECS={
 user:{title:'User', key:'id', arr:function(){return USERS}, after:function(){renderUsers();renderStations()},
   fields:[{k:'id',l:'User ID',t:'text',ro:true},
           {k:'n',l:'Full name',t:'text'},
           {k:'r',l:'Role',t:'select',opts:function(){return Object.keys(ROLES)}},
           {k:'station',l:'Station',t:'select',opts:function(){return STATIONS.map(function(s){return s.id})}},
           {k:'line',l:'Line',t:'select',opts:['A-Line','B-Line','Both']},
           {k:'sh',l:'Default shift',t:'select',opts:['A','B','C','Any']},
           {k:'on',l:'Active',t:'bool'}]},
 material:{title:'Material', key:'n', arr:function(){return MATERIALS}, after:function(){
     renderMaterials(); try{renderMatPanel()}catch(e){}},
   fields:[{k:'n',l:'S. No.',t:'text',ro:true},
           {k:'name',l:'Material',t:'text'},
           {k:'size',l:'Size / spec',t:'text'},
           {k:'uom',l:'UOM',t:'select',opts:['Pcs','Nos','Set','Kg','Mtr','Sqm','Ltr']},
           {k:'cat',l:'Category',t:'select',opts:function(){return MAT_CATS}},
           {k:'series',l:'Applies to',t:'select',opts:[['','Both series'],['G2X','G2X only'],
             ['G12R','G12R only'],['LABEL','Label — by wattage']]},
           {k:'qpm',l:'Per module',t:'num',hint:'Leave blank while stores has not confirmed it'},
           {k:'makes',l:'Makes (manufacturers)',t:'list',hint:'One per line — makers, not resellers'}]},
 model:{title:'Model', key:'model', arr:function(){return MODELS}, after:function(){
     renderDash(); try{renderMatPanel()}catch(e){}},
   fields:[{k:'model',l:'Model number',t:'text',ro:true},
           {k:'watt',l:'Wattage',t:'text'},
           {k:'tc',l:'Type character',t:'select',opts:['R','G','B','T','']},
           {k:'series',l:'Series',t:'text'},
           {k:'cells',l:'Cells',t:'text'},
           {k:'ct',l:'Cell type',t:'text'},
           {k:'size',l:'Module size H & F',t:'text'},
           {k:'produced',l:'Produced yet',t:'bool',
            hint:'Authorised on the back label is a different fact from produced'},
           {k:'lh',l:'External ERP code',t:'text',
            hint:'the other system holds DCR and NDCR as separate items, so this is the only unambiguous key'}]},
 station:{title:'Station', key:'id', arr:function(){return STATIONS}, after:function(){
     renderStations(); applyRole()},
   fields:[{k:'id',l:'Station ID',t:'text',ro:true},
           {k:'name',l:'Name',t:'text'},
           {k:'line',l:'Line',t:'select',opts:['A','B','—']},
           {k:'type',l:'Type',t:'select',opts:['FQC','PACK','DISPATCH','PLANNING']}]},
 reason:{title:'Reason code', key:'c', arr:function(){return REASONS}, after:renderReasons,
   fields:[{k:'c',l:'Code',t:'text',ro:true},
           {k:'a',l:'Applies to',t:'select',opts:['FQC entry','Pallet / packing list',
             'Repack session','Challan','Gate pass','Allocation batch','Production entry']},
           {k:'d',l:'Description',t:'text'},
           {k:'ap',l:'Needs a second approver',t:'bool'}]}
};
var EDIT_CTX=null;
function editRecord(kind,keyval){
  var sp=EDIT_SPECS[kind]; if(!sp)return;
  var rec=sp.arr().filter(function(r){return String(r[sp.key])===String(keyval)})[0];
  if(!rec){toast('Record not found.');return}
  if(USER.role!=='Admin'){toast('Only Admin can edit master data.');return}
  EDIT_CTX={kind:kind,rec:rec};
  document.getElementById('mdlTitle').textContent='Edit '+sp.title+' · '+keyval;
  document.getElementById('mdlSub').textContent=
    'Changes apply immediately on screen. In the built system this is a single save.';
  modalMode(true);
  document.getElementById('mdlGeneric').innerHTML=
    '<div class="card" style="margin:0"><div class="card-b"><div class="grid g2">'+
    sp.fields.map(function(f,i){
      var v=rec[f.k];
      var inp;
      if(f.t==='bool')
        inp='<label class="chk"><input type="checkbox" id="ed_'+i+'"'+(v?' checked':'')+
            '><span>Yes</span></label>';
      else if(f.t==='select'){
        var opts=typeof f.opts==='function'?f.opts():f.opts;
        inp='<select id="ed_'+i+'" aria-label="'+f.l+'">'+opts.map(function(o){
          var val=(o instanceof Array)?o[0]:o, lab=(o instanceof Array)?o[1]:o;
          return '<option value="'+val+'"'+(String(v)===String(val)?' selected':'')+'>'+lab+
                 '</option>';}).join('')+'</select>';
      }
      else if(f.t==='list')
        inp='<textarea id="ed_'+i+'" aria-label="'+f.l+'" rows="4">'+(v||[]).join('\n')+'</textarea>';
      else if(f.t==='num')
        inp='<input id="ed_'+i+'" aria-label="'+f.l+'" type="number" value="'+(v==null?'':v)+'" placeholder="blank = to confirm">';
      else
        inp='<input id="ed_'+i+'" aria-label="'+f.l+'" value="'+(v==null?'':String(v).replace(/"/g,'&quot;'))+'"'+
            (f.ro?' readonly style="background:#F2F6FA"':'')+'>';
      return '<div class="fld"'+(f.t==='list'?' style="grid-column:1/-1"':'')+'><label>'+f.l+
        '</label>'+inp+(f.hint?'<div class="hint">'+f.hint+'</div>':'')+'</div>';
    }).join('')+'</div></div>'+
    '<div class="card-f"><button class="btn btn-primary" onclick="saveRecord()">Save changes</button>'+
    '<button class="btn btn-ghost" onclick="closeModal()">Cancel</button>'+
    '<span style="margin-left:auto;font-size:11px;color:var(--ink3)">Edited by '+USER.name+
    '</span></div></div>';
  document.getElementById('mdl').classList.add('on');
}
function saveRecord(){
  if(!EDIT_CTX)return;
  var sp=EDIT_SPECS[EDIT_CTX.kind], rec=EDIT_CTX.rec, changed=[];
  sp.fields.forEach(function(f,i){
    var el=document.getElementById('ed_'+i); if(!el||f.ro)return;
    var nv;
    if(f.t==='bool')nv=el.checked;
    else if(f.t==='list')nv=el.value.split('\n').map(function(x){return x.trim()})
      .filter(function(x){return x});
    else if(f.t==='num')nv=el.value===''?null:+el.value;
    else nv=el.value;
    var ov=rec[f.k];
    var same=(f.t==='list')?((ov||[]).join('|')===nv.join('|')):String(ov)===String(nv);
    if(!same){
      changed.push(f.l+': '+(f.t==='list'?(ov||[]).length+' → '+nv.length+' vendors':
        (ov==null?'—':ov)+' → '+(nv==null?'—':nv)));
      rec[f.k]=nv;
    }
  });
  closeModal();
  if(!changed.length){toast('Nothing changed.');return}
  AUDIT.unshift([new Date().toLocaleString(),USER.name,'Update',sp.title,
    String(rec[sp.key]),changed.length+' field(s)',changed[0],'—']);
  try{renderDocs()}catch(e){}
  if(sp.after)sp.after();
  toast(sp.title+' updated — '+changed.join(' · '));
}

var USERS=[
 {id:'ADM-01',n:'Mukesh',r:'Admin',station:'DISPATCH-01',line:'Both',sh:'Any',last:'21-08-2026 18:32',on:true},
 {id:'PRD-A1',n:'Rajesh Kumar',r:'Production Incharge',station:'FQC-01',line:'Both',sh:'A',last:'21-08-2026 14:02',on:true},
 {id:'PRD-B1',n:'Deepak Yadav',r:'Production Incharge',station:'FQC-02',line:'Both',sh:'B',last:'21-08-2026 22:10',on:true},
 {id:'PRD-C1',n:'Vikram Singh',r:'Production Incharge',station:'FQC-01',line:'Both',sh:'C',last:'20-08-2026 06:11',on:true},
 {id:'FQC-A1',n:'Amit Sharma',r:'FQC Operator',station:'FQC-01',line:'A-Line',sh:'A',last:'21-08-2026 13:58',on:true},
 {id:'FQC-A2',n:'Pankaj Verma',r:'FQC Operator',station:'FQC-02',line:'B-Line',sh:'A',last:'21-08-2026 13:55',on:true},
 {id:'FQC-B1',n:'Sunil Chauhan',r:'FQC Operator',station:'FQC-01',line:'A-Line',sh:'B',last:'21-08-2026 21:47',on:true},
 {id:'FQC-B2',n:'Ravi Prajapati',r:'FQC Operator',station:'FQC-02',line:'B-Line',sh:'B',last:'21-08-2026 21:40',on:true},
 {id:'FQC-C1',n:'Manoj Sahu',r:'FQC Operator',station:'FQC-01',line:'A-Line',sh:'C',last:'21-08-2026 05:52',on:true},
 {id:'FQC-C2',n:'Dinesh Kashyap',r:'FQC Operator',station:'FQC-02',line:'B-Line',sh:'C',last:'12-05-2026 04:31',on:true},
 {id:'PKG-A1',n:'Suresh Patel',r:'Packing Operator',station:'PACK-01',line:'Both',sh:'A',last:'21-08-2026 13:44',on:true},
 {id:'PKG-B1',n:'Ramesh Nayak',r:'Packing Operator',station:'PACK-02',line:'Both',sh:'B',last:'21-08-2026 21:20',on:true},
 {id:'PKG-C1',n:'Anil Sahu',r:'Packing Operator',station:'PACK-01',line:'Both',sh:'C',last:'21-08-2026 05:30',on:true},
 {id:'DSP-01',n:'Dasrath Pal',r:'Dispatch Operator',station:'DISPATCH-01',line:'Both',sh:'Any',last:'21-08-2026 15:02',on:true},
 {id:'DSP-02',n:'Kamlesh Sahu',r:'Dispatch Operator',station:'DISPATCH-01',line:'Both',sh:'Any',last:'02-04-2026 11:15',on:false}];
var REASONS=[
 {c:'CN-VEH',a:'Challan',d:'Vehicle changed before loading',ap:false,u:4},
 {c:'CN-QTY',a:'Challan',d:'Quantity revised by customer',ap:false,u:2},
 {c:'CN-DUP',a:'Challan',d:'Raised in duplicate',ap:true,u:1},
 {c:'GP-DISP',a:'Gate pass',d:'Cancelled after dispatch — second approval required',ap:true,u:0},
 {c:'RP-SPLIT',a:'Repack session',d:'Customer split across destinations',ap:false,u:6},
 {c:'RP-GRADE',a:'Repack session',d:'Wrong grade mixed in box',ap:false,u:2},
 {c:'PL-DMG',a:'Pallet / packing list',d:'Damaged module replaced',ap:false,u:3},
 {c:'FQ-MIS',a:'FQC entry',d:'Wrong category recorded',ap:false,u:5},
 {c:'AL-WRONG',a:'Allocation batch',d:'Wrong customer at allocation',ap:true,u:1},
 {c:'PE-QTY',a:'Production entry',d:'Serial range corrected',ap:false,u:2}];
var DOCLOG=[
 ['21-08-2026 15:02:11','Gate pass','GP-2608-0030','Printed',3,'GP-v2','Dasrath Pal','DISPATCH-01'],
 ['21-08-2026 14:58:40','Challan','CHN-455','Printed',3,'CHN-v4','Dasrath Pal','DISPATCH-01'],
 ['21-08-2026 13:44:02','Packing list','A045','Printed',3,'PL-v3','Suresh Patel','PACK-02'],
 ['21-08-2026 13:41:55','Packing list','A045','Reprinted',1,'PL-v3','Suresh Patel','PACK-02'],
 ['21-08-2026 13:20:09','Packing list','A044','Printed',3,'PL-v3','Suresh Patel','PACK-02'],
 ['21-08-2026 09:14:33','FQC report','19-08-2026','Exported',0,'XL-v1','Amit Sharma','FQC-A1']];
var AUDIT=[
 ['21-08-2026 15:02:11','Dasrath Pal','Create','Gate pass','GP-2608-0030','—','— → Issued','—'],
 ['21-08-2026 14:58:40','Dasrath Pal','Create','Challan','CHN-455','—','— → Issued','—'],
 ['21-08-2026 13:24:02','Suresh Patel','Repack','Pallet','RPK-2608-00008','contents',
  '2 boxes → 3 boxes','RP-SPLIT'],
 ['21-08-2026 11:41:20','Mukesh','Update','Machine','Framing machine','A-Line count','1 → 2','—'],
 ['21-08-2026 11:02:44','Mukesh','Cancel','Challan','CHN-452','status','Issued → Cancelled','CN-VEH'],
 ['20-08-2026 09:12:04','Rajesh Kumar','Import','Batch','BAT-2602-00019','—','— → 70 serials','—']];
var userQ='';
function adTab(btn,p){
  btn.parentNode.querySelectorAll('button').forEach(function(b){b.classList.remove('on')});
  btn.classList.add('on');
  document.querySelectorAll('.adpane').forEach(function(x){x.classList.remove('on')});
  document.getElementById('ad-'+p).classList.add('on');
}
function userFilter(v){userQ=(v||'').toUpperCase();renderUsers()}
function daysSince(s){
  var p=s.split(' ')[0].split('-');
  return Math.round((Date.now()-new Date(+p[2],+p[1]-1,+p[0]).getTime())/86400000);
}
function renderUsers(){
  var rows=USERS.filter(function(u){
    return !userQ||u.id.indexOf(userQ)>=0||u.n.toUpperCase().indexOf(userQ)>=0;});
  document.getElementById('uCount').textContent=rows.length+' of '+USERS.length;
  document.getElementById('userRows').innerHTML=rows.map(function(u){
    var d=daysSince(u.last);
    return '<tr><td class="mono" style="font-weight:700">'+u.id+'</td><td>'+u.n+'</td>'+
      '<td><span class="tag '+(u.r==='Admin'?'t-fail':'t-info')+'">'+u.r+'</span></td>'+
      '<td>'+u.line+'</td><td'+(u.sh!=='Any'?' class="s'+u.sh+'"':'')+'>'+u.sh+'</td>'+
      '<td class="mono" style="font-size:11px'+(d>60?';color:var(--fail)':'')+'">'+u.last+
        (d>60?' · '+d+'d':'')+'</td>'+
      '<td><span class="tag '+(u.on?'t-pass">Active':'t-mute">Disabled')+'</span></td>'+
      '<td><button class="btn btn-ghost btn-sm" onclick="editRecord(\'user\',\''+u.id+'\')">Edit</button></td></tr>';
  }).join('');
  var act=USERS.filter(function(u){return u.on});
  var dormant=act.filter(function(u){return daysSince(u.last)>60});
  var admins=act.filter(function(u){return u.r==='Admin'});
  document.getElementById('arActive').textContent=act.length;
  document.getElementById('arDormant').textContent=dormant.length;
  document.getElementById('arAdmin').textContent=admins.length;
  var listed=act.filter(function(u){return daysSince(u.last)>60||u.r==='Admin'});
  document.getElementById('arRows').innerHTML=listed.map(function(u){
    var d=daysSince(u.last);
    return '<tr><td class="mono">'+u.id+'</td><td>'+u.n+'</td>'+
      '<td><span class="tag '+(u.r==='Admin'?'t-fail':'t-info')+'">'+u.r+'</span></td>'+
      '<td>'+(d>60?'No sign-in for '+d+' days':'Holds Admin — highest privilege')+'</td>'+
      '<td class="mono" style="font-size:11px">'+u.last+'</td>'+
      '<td><button class="btn btn-ghost btn-sm" onclick="toast(\'Access confirmed for '+u.id+'.\')">Keep</button> '+
      '<button class="btn btn-danger btn-sm" onclick="disableUser(\''+u.id+'\')">Disable</button></td></tr>';
  }).join('')||'<tr><td colspan="6"><div class="empty-state"><p>Nothing needs a decision.</p></div></td></tr>';
}
function renderMach(){
  var total=MACHINES.reduce(function(a,g){return a+machCount(g)},0);
  document.getElementById('machTotal').textContent=total+' machines';
  document.getElementById('machRows').innerHTML=MACHINES.map(function(g,i){
    var n=machCount(g);
    return '<tr><td style="font-weight:600">'+g.type+'</td>'+
      '<td class="mono" style="color:var(--ink3)">'+(g.alias||'—')+'</td>'+
      '<td style="text-align:right"><input class="cnt-in" type="number" min="0" aria-label="A-Line count" title="Machines on A-Line" value="'+g.a+
        '" onchange="MACHINES['+i+'].a=+this.value||0;renderMach();renderLoss()"></td>'+
      '<td style="text-align:right"><input class="cnt-in" type="number" min="0" aria-label="B-Line count" title="Machines on B-Line" value="'+g.b+
        '" onchange="MACHINES['+i+'].b=+this.value||0;renderMach();renderLoss()"></td>'+
      '<td class="num" style="font-weight:700">'+n+'</td>'+
      '<td class="num">'+(n?(100/n).toFixed(2):'0.00')+'%</td>'+
      '<td><span class="tag '+(g.src==='assumed'?'t-rev':'t-mute')+'">'+g.src+'</span></td></tr>';
  }).join('');
}
function renderMaterials(){
  if(!document.getElementById('matRows'))return;
  document.getElementById('matCount').textContent=MATERIALS.length+' materials';
  document.getElementById('matRows').innerHTML=MATERIALS.map(function(m){
    var app=m.series==='LABEL'?('Label '+m.watt+'W'):(m.series||'Both series');
    var tag=m.series==='G2X'?'t-info':m.series==='G12R'?'t-solar':
            m.series==='LABEL'?'t-mute':'t-pass';
    return '<tr><td class="num" style="color:var(--ink3)">'+m.n+'</td>'+
      '<td style="font-weight:600">'+m.name+
        (m.added?' <span class="tag t-rev">added</span>':'')+
        (m.legacy?' <span class="tag t-mute">old</span>':'')+
        (m.group?' <span class="code">alt: '+m.group+'</span>':'')+
        (m.note?'<div class="hint">'+m.note+'</div>':'')+'</td>'+
      '<td class="mono" style="font-size:11px">'+m.size+'</td>'+
      '<td class="mono">'+m.uom+'</td>'+
      '<td>'+m.cat+'</td>'+
      '<td><span class="tag '+tag+'">'+app+'</span></td>'+
      '<td class="num">'+(m.qpm==null?'<span class="tag t-rev">not in BOM</span>':
        (typeof m.qpm==='object'?
          '<span class="mono" style="font-size:10.5px">G2X '+m.qpm.G2X+'<br>G12R '+m.qpm.G12R+
          '</span>':m.qpm+' '+m.uom))+'</td>'+
      '<td style="font-size:11px;color:var(--ink3)">'+m.makes.join(' · ')+'</td>'+
      '<td><button class="btn btn-ghost btn-sm" onclick="editRecord(\'material\','+m.n+')">Edit</button></td></tr>';
  }).join('');
  document.getElementById('effChips').innerHTML=CELL_EFF.map(function(e){
    return '<span class="pchip" style="font-size:12px;padding:4px 10px">'+e+'</span>';
  }).join('');
  var NS=[['1','A shift','Normal production'],['2','B shift','Normal production'],
    ['3','C shift','Normal production'],
    ['4','Pre-shared / special customer','Used in Unit-1; serials issued against a customer allocation before production'],
    ['5','Job work / OEM','Reserved'],['6','Job work / OEM','Reserved'],
    ['7','Job work / OEM','Reserved'],['8','Job work / OEM','Reserved'],
    ['9','Job work / OEM','Reserved']];
  document.getElementById('nsRows').innerHTML=NS.map(function(r){
    return '<tr><td class="mono" style="font-weight:700;font-size:14px">'+r[0]+'</td>'+
      '<td style="font-weight:600">'+r[1]+'</td>'+
      '<td style="font-size:11.5px;color:var(--ink3)">'+r[2]+'</td></tr>';
  }).join('');
}
function disableUser(id){
  var u=USERS.filter(function(x){return x.id===id})[0]; if(!u)return;
  if(!confirm('Disable '+u.id+' ('+u.n+')? Their records stay; they simply cannot sign in.'))return;
  u.on=false;renderUsers();
  AUDIT.unshift([new Date().toLocaleString(),USER.name,'Update','User',u.id,'status',
    'Active → Disabled','—']);
  try{renderDocs()}catch(e){}
  toast(u.id+' disabled.');
}
var OPEN_Q=[
 [1,'Does an April challan read <span class="mono">0001</span> or <span class="mono">1</span>?',
  'Mukesh','answered','Reads <span class="mono">0001</span> — padding is 4, a display setting'],
 [2,'What does <span class="mono">FTR</span> stand for?','Mukesh','answered',
  'Flash Test Report. ICON TRACE already holds the Sun Simulator data, so it generates it'],
 [3,'Are the hard copy and the Excel one document in two renderings, or two documents?',
  'Mukesh','answered','One document, two renderings — plus a separate packing list. Three outputs'],
 [4,'What is <span class="mono">ISEN/PV/26-27/183</span> dt 20-Aug?','Marketing','open',
  'A gap in the document chain — Mukesh is confirming with Marketing'],
 [5,'What does the box-number letter mean — <span class="mono">A005</span> vs '+
  '<span class="mono">D0087</span>?','Packing','answered',
  'Not tied to anything outside the old sheets — ICON TRACE defines its own series'],
 [6,'What is the leading <span class="mono">12</span> in the serial?','Mukesh','answered',
  'The year. Base 2014, so <span class="mono">12</span> = 2026'],
 [7,'Does DCR sit on the material record or the batch?','Stores','open',
  'Decides which screen enforces the DCR cross-check'],
 [8,'Is the invoice quantity set by truck weight, volume, or PO balance?','Logistics','open',
  'How partial loads are explained on the challan'],
 [9,'Does the factory challan number ever reach HO&rsquo;s Tally?','HO','open',
  'Whether the number must be sent back to fill Tally&rsquo;s Delivery Note field'],
 [10,'Needs Review authority — who clears it, and does a cleared item get a real grade?','Open',
  'open','The Needs Review workflow']];
var BUILD_ORDER=[
 ['Invoice parser','ready','nothing — cleared to build'],
 ['Planning / indent','ready','nothing — cleared to build'],
 ['Model master','ready','External ERP codes to map'],
 ['Challan counter','ready','Q1 answered — padding is 4'],
 ['FQC','held','the offline decision'],
 ['Packing','held','the offline decision'],
 ['Flash Test Report','ready','Q2 answered — data already ingested'],
 ['Historical import','required','hard dependency for Dispatch going live']];
function renderOpenQ(){
  var host=document.getElementById('oqRows'); if(!host)return;
  var open=OPEN_Q.filter(function(q){return q[3]==='open'}).length;
  document.getElementById('oqCount').textContent=open+' still open · '+
    (OPEN_Q.length-open)+' answered';
  host.innerHTML=OPEN_Q.map(function(q){
    var done=(q[3]==='answered');
    return '<tr'+(done?' style="opacity:.62"':'')+'>'+
      '<td class="num" style="color:var(--ink3)">'+q[0]+'</td>'+
      '<td'+(done?' style="text-decoration:line-through"':'')+'>'+q[1]+'</td>'+
      '<td><span class="tag '+(done?'t-pass':'t-fail')+'">'+(done?'answered':q[2])+'</span></td>'+
      '<td style="font-size:11.5px;color:var(--ink3)">'+q[4]+'</td></tr>';
  }).join('');
  document.getElementById('boRows').innerHTML=BUILD_ORDER.map(function(b){
    var tag=b[1]==='ready'?'t-pass':b[1]==='blocked'?'t-fail':
            b[1]==='required'?'t-solar':'t-rev';
    return '<tr><td style="font-weight:600">'+b[0]+'</td>'+
      '<td><span class="tag '+tag+'">'+b[1]+'</span></td>'+
      '<td style="font-size:11.5px;color:var(--ink3)">'+b[2]+'</td></tr>';
  }).join('');
}
function renderConsumption(){
  var host=document.getElementById('cbRows'); if(!host)return;
  var g2x=MODELS.filter(function(m){return m.series==='G2X'})[0].model;
  var g12=MODELS.filter(function(m){return m.series==='G12R'})[0].model;
  var seen={},rows='',n=0;
  MAT_CATS.forEach(function(cat){
    var list=MATERIALS.filter(function(m){return m.cat===cat});
    if(!list.length)return;
    rows+='<tr><td colspan="6" style="background:#F2F6FA;font-size:10px;font-weight:700;'+
      'color:var(--brand);text-transform:uppercase;letter-spacing:.8px">'+cat+'</td></tr>';
    list.forEach(function(m){
      n++;
      var a=(m.series===''||m.series==='G2X')?qpmFor(m,g2x):null;
      var b=(m.series===''||m.series==='G12R')?qpmFor(m,g12):null;
      if(m.series==='LABEL'){a=m.qpm;b=m.qpm}
      var differs=(a!=null&&b!=null&&a!==b);
      var fmt=function(v){return v==null?'<span style="color:var(--line)">—</span>':
        '<span class="mono">'+(+v.toFixed(4))+'</span>'};
      rows+='<tr'+(differs?' style="background:var(--solar-lt)"':'')+'>'+
        '<td style="font-weight:600">'+m.name+
          (m.pot?' <span class="tag t-info">part '+m.pot+'</span>':'')+
          (m.added?' <span class="tag t-rev">added</span>':'')+
          (m.legacy?' <span class="tag t-mute">old</span>':'')+'</td>'+
        '<td class="mono" style="font-size:11px">'+m.size+'</td>'+
        '<td class="mono">'+m.uom+'</td>'+
        '<td style="text-align:right">'+(m.qpm==null?
          '<span class="tag t-rev">not in BOM</span>':fmt(a))+'</td>'+
        '<td style="text-align:right">'+(m.qpm==null?
          '<span class="tag t-rev">not in BOM</span>':fmt(b))+'</td>'+
        '<td>'+(differs?'<span class="tag t-solar">by series</span>':
          m.qpm==null?'<span class="tag t-mute">—</span>':
          '<span class="tag t-pass">same</span>')+'</td></tr>';
    });
  });
  host.innerHTML=rows;
  document.getElementById('cbCount').textContent=n+' materials';
}
function renderStations(){
  document.getElementById('stationRows').innerHTML=STATIONS.map(function(s){
    var bound=USERS.filter(function(u){return u.station===s.id});
    return '<tr><td class="mono" style="font-weight:700">'+s.id+'</td><td>'+s.name+'</td>'+
      '<td>'+(s.line==='—'?'<span style="color:var(--ink3)">no line</span>':
        '<span class="s'+s.line+'">'+s.line+'-Line</span>')+'</td>'+
      '<td>'+s.type+'</td><td class="num">'+bound.length+'</td>'+
      '<td><button class="btn btn-ghost btn-sm" onclick="editRecord(\'station\',\''+s.id+'\')">Edit</button></td></tr>';
  }).join('');
  document.getElementById('sourceRows').innerHTML=SOURCES.map(function(s){
    var rule=s.type==='SUNSIM_CSV'?'CSV, mapped by header':'Copy in, append-and-update';
    return '<tr><td class="mono" style="font-weight:700">'+s.id+'</td>'+
      '<td><span class="code">'+s.type+'</span></td>'+
      '<td class="mono" style="font-size:11px">'+s.path+'</td>'+
      '<td><span class="s'+s.line+'">'+s.line+'-Line</span></td>'+
      '<td style="font-size:11.5px">'+rule+'</td></tr>';
  }).join('');
  var G=GRADE_RULES;
  document.getElementById('grVer').textContent=G.version+' in force';
  var rows=[
    [G.version,G.from,'EL/VI verdict in '+G.forceBGY.join(', '),'BGY','Active'],
    [G.version,G.from,'EL/VI verdict is any other NG category','GY','Active'],
    [G.version,G.from,'EL/VI OK and Pmax &ge; '+G.pmaxA+' W','A','Active'],
    [G.version,G.from,'EL/VI OK and Pmax &ge; '+G.pmaxGY+' W','GY','Active'],
    [G.version,G.from,'EL/VI OK and Pmax below '+G.pmaxGY+' W','BGY','Active'],
    [G.version,G.from,'Pmax not found at grading time','no proposal — operator must decide','Active'],
    ['GR-2026-02','01-04-2026','EL/VI OK and Pmax &ge; 580 W','A','Superseded']];
  document.getElementById('gradeRows').innerHTML=rows.map(function(r){
    var sup=r[4]==='Superseded';
    return '<tr'+(sup?' style="opacity:.55"':'')+'><td class="mono">'+r[0]+'</td>'+
      '<td class="mono">'+r[1]+'</td><td>'+r[2]+'</td>'+
      '<td><span class="tag '+(r[3]==='A'?'t-pass':r[3].indexOf('no proposal')===0?'t-rev':'t-fail')+
        '">'+r[3]+'</span></td>'+
      '<td><span class="tag '+(sup?'t-mute':'t-pass')+'">'+r[4]+'</span></td></tr>';
  }).join('');
  document.getElementById('dfVer').textContent='v1 · '+ELVI_CODES.length+' codes';
  document.getElementById('defectRows').innerHTML=ELVI_CODES.map(function(c){
    var dirty=c.raw!==c.label;
    return '<tr><td class="mono" style="font-weight:700">'+c.code+'</td><td>'+c.label+'</td>'+
      '<td class="mono" style="font-size:11px">"'+c.raw+'"'+
        (dirty?' <span class="tag t-rev" style="margin-left:5px">normalised</span>':'')+'</td>'+
      '<td>'+(c.ng?'<span class="tag t-fail">Yes</span>':'<span class="tag t-pass">No</span>')+'</td>'+
      '<td><span class="tag t-pass">Active</span></td></tr>';
  }).join('');
}
function renderReasons(){
  document.getElementById('reasonRows').innerHTML=REASONS.map(function(r){
    return '<tr><td class="mono" style="font-weight:700">'+r.c+'</td><td>'+r.a+'</td>'+
      '<td>'+r.d+'</td><td>'+(r.ap?'<span class="tag t-rev">Second approver</span>':
        '<span class="tag t-mute">No</span>')+'</td>'+
      '<td class="num">'+r.u+'</td><td><button class="btn btn-ghost btn-sm" onclick="editRecord(\'reason\',\''+r.c+'\')">Edit</button></td></tr>';
  }).join('');
  cancelCheck();
}
function renderDocs(){
  document.getElementById('docRows').innerHTML=DOCLOG.map(function(d){
    return '<tr><td class="mono">'+d[0]+'</td><td>'+d[1]+'</td><td class="mono">'+d[2]+'</td>'+
      '<td><span class="tag '+(d[3]==='Reprinted'?'t-rev':'t-info')+'">'+d[3]+'</span></td>'+
      '<td class="num">'+(d[4]||'—')+'</td><td class="mono">'+d[5]+'</td><td>'+d[6]+'</td>'+
      '<td class="mono" style="font-size:11px">'+d[7]+'</td></tr>';
  }).join('');
  document.getElementById('auditRows').innerHTML=AUDIT.map(function(a){
    return '<tr><td class="mono">'+a[0]+'</td><td>'+a[1]+'</td>'+
      '<td><span class="tag '+(a[2]==='Cancel'?'t-fail':a[2]==='Repack'?'t-rev':'t-info')+'">'+
        a[2]+'</span></td><td>'+a[3]+'</td><td class="mono">'+a[4]+'</td>'+
      '<td style="color:var(--ink3);font-size:11.5px">'+a[5]+'</td>'+
      '<td class="mono" style="font-size:11px">'+a[6]+'</td>'+
      '<td>'+(a[7]==='—'?'<span style="color:var(--ink3)">—</span>':
        '<span class="code">'+a[7]+'</span>')+'</td></tr>';
  }).join('');
}
function cancelCheck(){
  var t=document.getElementById('cnType').value;
  var sel=document.getElementById('cnReason');
  var opts=REASONS.filter(function(r){return r.a===t});
  if(!opts.length)opts=REASONS;
  var keep=sel.value;
  sel.innerHTML=opts.map(function(r){
    return '<option value="'+r.c+'">'+r.c+' — '+r.d+'</option>'}).join('');
  if(keep&&opts.filter(function(r){return r.c===keep}).length)sel.value=keep;
  var r=REASONS.filter(function(x){return x.c===sel.value})[0];
  document.getElementById('cnWarn').innerHTML=(r&&r.ap)?
    '<div class="note n-warn" style="font-size:11.5px;margin:0 0 12px"><span>⚑</span>'+
    '<span>Reason <b>'+r.c+'</b> requires a <b>second approver</b> — the same person cannot '+
    'raise and approve a cancellation.</span></div>':'';
}

var BATCHES=[
 {id:'BAT-2602-00021',cust:'SAI BABUJI PROJECTS',model:'ISEN590-G2X',date:'16-02-2026',shift:'A',
  from:'ICON590G1202121098',to:'ICON590G1202121130',qty:33,prod:33,fqc:33,rej:1,packed:32,disp:32},
 {id:'BAT-2602-00020',cust:'SAI BABUJI PROJECTS',model:'ISEN590-G2X',date:'15-02-2026',shift:'B',
  from:'ICON590G1202121080',to:'ICON590G1202121094',qty:15,prod:15,fqc:15,rej:0,packed:15,disp:15},
 {id:'BAT-2602-00019',cust:'SAI BABUJI PROJECTS',model:'ISEN590-G2X',date:'13-02-2026',shift:'A',
  from:'ICON590G1202121006',to:'ICON590G1202121075',qty:70,prod:70,fqc:68,rej:2,packed:66,disp:36},
 {id:'BAT-2608-00044',cust:'SG MEDA',model:'ISEN625-G12R',date:'12-08-2026',shift:'C',
  from:'ICON625R1110152001',to:'ICON625R1110152180',qty:180,prod:180,fqc:172,rej:4,packed:168,disp:120},
 {id:'BAT-2608-00045',cust:'MSEDCL',model:'ISEN620-G12R',date:'14-08-2026',shift:'B',
  from:'ICON620R1110152001',to:'ICON620R1110152220',qty:220,prod:200,fqc:190,rej:5,packed:185,disp:100}];
function qTry(v){document.getElementById('qBox').value=v;doSearch();go('search',navBtn('search'))}
function doSearch(){
  var q=document.getElementById('qBox').value.trim().toUpperCase(),out=document.getElementById('searchOut');
  if(!q){out.innerHTML='';return}
  if(q.indexOf('ICON')===0)out.innerHTML=serialView(q);
  else if(q.indexOf('CHN-')===0||q.indexOf('IS-')===0)out.innerHTML=challanView(q);
  else if(q.indexOf('BAT-')===0)out.innerHTML=batchView(q);
  /* vehicle before box: both start with letters, the vehicle pattern is longer */
  else if(/^[A-Z]{2}\d{2}[A-Z]{1,3}\d{3,4}$/.test(q))out.innerHTML=vehicleView(q);
  else if(/^[A-Z]\d{3,4}$/.test(q)||q.indexOf('BOX')===0)out.innerHTML=boxView(q);
  else out.innerHTML=customerView(q);
}
function customerView(q){
  var hits=BATCHES.filter(function(b){return b.cust.toUpperCase().indexOf(q)>=0});
  if(!hits.length)return '<div class="card"><div class="card-b"><div class="empty-state">'+
    '<div class="es-i">⌕</div><p>Nothing matches <b>'+q+'</b>. Try a customer name, a batch '+
    '(BAT-…), box (BOX-…), challan (CHN-…), a vehicle number or a serial.</p></div></div></div>';
  var cust=hits[0].cust,s=function(k){return hits.reduce(function(a,b){return a+b[k]},0)};
  return '<div class="crumb">Customer <b>'+cust+'</b></div>'+
  '<div class="grid g5" style="margin-bottom:14px">'+
    '<div class="kpi"><label>Batches</label><div class="v">'+hits.length+'</div>'+
      '<div class="d">allocated to this customer</div></div>'+
    '<div class="kpi"><label>Allocated</label><div class="v">'+s('qty').toLocaleString()+'</div>'+
      '<div class="d">serials issued</div></div>'+
    '<div class="kpi k-solar"><label>Running</label><div class="v">'+(s('prod')-s('fqc'))+'</div>'+
      '<div class="d">produced, not at FQC</div></div>'+
    '<div class="kpi k-fail"><label>Rejected</label><div class="v">'+s('rej')+'</div>'+
      '<div class="d">GY + BGY</div></div>'+
    '<div class="kpi k-pass"><label>Dispatched</label><div class="v">'+s('disp').toLocaleString()+'</div>'+
      '<div class="d">'+(s('disp')/s('qty')*100).toFixed(0)+'% of allocated</div></div></div>'+
  '<div class="card"><div class="card-h"><h3>Batches for this customer</h3>'+
    '<div class="ch-r"><button class="btn btn-ghost btn-sm" onclick="exportNote()">Export</button></div></div>'+
    '<div class="card-b flush"><table><thead><tr><th>Batch</th><th>Date</th><th>Shift</th>'+
    '<th>Model</th><th>First serial</th><th>Last serial</th><th style="text-align:right">Qty</th>'+
    '<th style="width:120px">Dispatched</th><th style="text-align:center">Open</th></tr></thead><tbody>'+
    hits.map(function(b){
      return '<tr><td class="mono">'+b.id+'</td><td class="mono">'+b.date+'</td>'+
      '<td class="s'+b.shift+'">'+b.shift+'</td><td class="mono">'+b.model+'</td>'+
      '<td class="mono">'+b.from+'</td><td class="mono">'+b.to+'</td>'+
      '<td class="num">'+b.qty+'</td>'+
      '<td><div class="bar-wrap"><div class="bar b-ok"><i style="width:'+(b.disp/b.qty*100)+
        '%"></i></div><span class="mono">'+(b.disp/b.qty*100).toFixed(0)+'%</span></div></td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="qTry(\''+b.id+'\')">→</button></td></tr>';}).join('')+
    '</tbody></table></div></div>';
}
function batchView(id){
  var b=BATCHES.filter(function(x){return x.id===id})[0];
  if(!b)return '<div class="card"><div class="card-b"><div class="empty-state">'+
    '<p>Batch <b>'+id+'</b> not found.</p></div></div></div>';
  var d=derive(b.from),n=Math.min(b.qty,60);
  return '<div class="crumb"><button onclick="qTry(\''+b.cust.split(' ')[0]+'\')">'+b.cust+
    '</button> › Batch <b>'+b.id+'</b></div>'+
  '<div class="grid g5" style="margin-bottom:14px">'+
    '<div class="kpi"><label>Quantity</label><div class="v">'+b.qty+'</div>'+
      '<div class="d">'+(b.qty*(+d.watt)/1000).toFixed(2)+' KW</div></div>'+
    '<div class="kpi"><label>Model</label><div class="v" style="font-size:14px">'+b.model+'</div>'+
      '<div class="d">'+d.watt+'W · '+d.cells+'</div></div>'+
    '<div class="kpi k-solar"><label>Produced</label><div class="v">'+b.prod+'</div>'+
      '<div class="d">'+(b.qty-b.prod)+' still to make</div></div>'+
    '<div class="kpi k-fail"><label>Rejected</label><div class="v">'+b.rej+'</div>'+
      '<div class="d">'+(b.rej/Math.max(b.fqc,1)*100).toFixed(1)+'% of inspected</div></div>'+
    '<div class="kpi k-pass"><label>Dispatched</label><div class="v">'+b.disp+'</div>'+
      '<div class="d">'+(b.packed-b.disp)+' in pending stock</div></div></div>'+
  '<div class="work"><div class="wmain o1">'+
  '<div class="card"><div class="card-h"><h3>Allocation details</h3></div>'+
    '<div class="card-b"><div class="lookup" style="border:1px solid var(--line);'+
    'border-radius:var(--r);overflow:hidden">'+
    '<div><label>First serial</label><div class="lv mono">'+b.from+'</div></div>'+
    '<div><label>Last serial</label><div class="lv mono">'+b.to+'</div></div>'+
    '<div><label>Quantity</label><div class="lv mono">'+b.qty+'</div></div>'+
    '<div><label>Allocated</label><div class="lv mono">'+b.date+'</div></div>'+
    '<div><label>Shift</label><div class="lv">'+b.shift+'</div></div>'+
    '<div><label>Customer</label><div class="lv" style="font-size:11px">'+b.cust+'</div></div>'+
    '</div></div></div>'+
  '<div class="card"><div class="card-h"><h3>Serials in this batch</h3>'+
    '<div class="ch-r"><span class="tag t-mute">showing '+n+' of '+b.qty+'</span>'+
    '<button class="btn btn-ghost btn-sm" onclick="exportNote()">Export</button></div></div>'+
    '<div class="card-b flush"><div class="tbl-wrap"><table><thead><tr><th>#</th><th>Serial</th>'+
    '<th>Status</th><th>Category</th><th>Box</th><th style="text-align:center">Trace</th>'+
    '</tr></thead><tbody>'+
    Array.apply(null,{length:n}).map(function(_,i){
      var s=bumpSerial(b.from,i);
      var st=i<b.disp?['Dispatched','t-solar']:i<b.packed?['Packed','t-info']:
             i<b.fqc?['Inspected','t-pass']:i<b.prod?['Produced','t-mute']:['Allocated','t-mute'];
      return '<tr><td class="num" style="color:var(--ink3)">'+(i+1)+'</td>'+
      '<td class="mono">'+s+'</td><td><span class="tag '+st[1]+'">'+st[0]+'</span></td>'+
      '<td>'+(i<b.rej?'GY':'A')+'</td><td class="mono" style="font-size:10.5px">'+
        (i<b.packed?'BOX-2608-000'+(31+Math.floor(i/36)):'—')+'</td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="qTry(\''+s+'\')">→</button></td></tr>';}).join('')+
    '</tbody></table></div></div></div></div>'+
  '<div class="rail o2"><div class="card"><div class="card-h"><h3>Materials</h3>'+
    '<div class="ch-r"><span class="tag t-mute">frozen at allocation</span></div></div>'+
    '<div class="card-b flush"><table><tbody>'+
    [['Cell make','TONGWEI 25.3% M10R'],['Cell batch','TAX/25-26/14'],['Cell type',d.ct],
     ['Cells',d.cells],['Module size',d.size],['Glass front','BOROSIL 2272×1128×2'],
     ['Front batch','9000021385'],['Glass back','BOROSIL 2272×1128×2'],
     ['Junction box','GNEX (0.3M) 30A'],['Frame','SUDARSHAN'],['Sealant','SILICON']].map(function(r){
      return '<tr><td style="color:var(--ink3);font-size:11.5px">'+r[0]+'</td>'+
        '<td class="mono" style="font-size:11px">'+r[1]+'</td></tr>'}).join('')+
    '</tbody></table></div></div></div></div>';
}
function boxView(box){
  var n=36,base='ICON590G1202121001';
  return '<div class="crumb">Box <b>'+box+'</b></div>'+
  '<div class="grid g5" style="margin-bottom:14px">'+
    '<div class="kpi"><label>Modules in box</label><div class="v">'+n+'</div><div class="d">capacity 36</div></div>'+
    '<div class="kpi"><label>Model</label><div class="v" style="font-size:14px">ISEN590-G2X</div>'+
      '<div class="d">590W · G2X · 144 half cut</div></div>'+
    '<div class="kpi k-pass"><label>Grade</label><div class="v" style="font-size:15px">A</div>'+
      '<div class="d">internal only</div></div>'+
    '<div class="kpi k-solar"><label>Status</label><div class="v" style="font-size:15px">Challaned</div>'+
      '<div class="d">CHN-455</div></div>'+
    '<div class="kpi"><label>Bin</label><div class="v" style="font-size:15px">BIN-3</div>'+
      '<div class="d">packed 19-08 shift B</div></div></div>'+
  '<div class="card"><div class="card-h"><h3>Box journey</h3></div><div class="card-b"><div class="chain">'+
    '<div class="node done"><label>Created by repack</label><div class="nv">RPK-2608-00008</div>'+
      '<div class="nd">from BOX-…00031<br>and BOX-…00034</div>'+
      '<div class="ns"><span class="tag t-rev">19-08 13:24</span></div></div>'+
    '<div class="node done"><label>Packed</label><div class="nv">'+box+'</div>'+
      '<div class="nd">36 modules<br>BIN-3 · Shift B</div>'+
      '<div class="ns"><span class="tag t-info">Closed</span></div></div>'+
    '<div class="node done"><label>Challan</label><div class="nv">CHN-455</div>'+
      '<div class="nd">SAI BABUJI<br>19-08-2026</div>'+
      '<div class="ns"><span class="tag t-info">Issued</span></div></div>'+
    '<div class="node cur"><label>Gate pass</label><div class="nv">GP-2608-0030</div>'+
      '<div class="nd">CG04MM1521<br>Maharashtra</div>'+
      '<div class="ns"><span class="tag t-solar">Dispatched</span></div></div>'+
  '</div></div></div>'+
  '<div class="card"><div class="card-h"><h3>Modules in this box</h3>'+
    '<div class="ch-r"><span class="tag t-mute">'+n+' serials</span>'+
    '<button class="btn btn-ghost btn-sm" onclick="exportNote()">Export</button></div></div>'+
    '<div class="card-b flush"><div class="tbl-wrap"><table>'+
    '<thead><tr><th>Slot</th><th>Serial</th><th>Model</th><th>Category</th><th>FQC date</th>'+
    '<th>Came from</th><th style="text-align:center">Trace</th></tr></thead><tbody>'+
    Array.apply(null,{length:n}).map(function(_,i){
      var s=bumpSerial(base,i);
      return '<tr><td class="mono">'+String(i+1).padStart(2,'0')+'</td>'+
      '<td class="mono">'+s+'</td><td class="mono">ISEN590-G2X</td><td>A</td>'+
      '<td class="mono">19-08-2026</td>'+
      '<td class="mono" style="font-size:10.5px;color:var(--ink3)">'+
        (i<18?'A031':'A034')+'</td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="qTry(\''+s+'\')">→</button></td></tr>';}).join('')+
    '</tbody></table></div></div></div>';
}
function challanView(chn){
  var boxes=['A044','A045','A026'];
  return '<div class="crumb">Challan <b>'+chn+'</b></div>'+
  '<div class="grid g5" style="margin-bottom:14px">'+
    '<div class="kpi"><label>Boxes</label><div class="v">'+boxes.length+'</div><div class="d">on this challan</div></div>'+
    '<div class="kpi"><label>Modules</label><div class="v">108</div><div class="d">63.7 KW</div></div>'+
    '<div class="kpi"><label>Customer</label><div class="v" style="font-size:14px">SAI BABUJI</div>'+
      '<div class="d">Maharashtra</div></div>'+
    '<div class="kpi k-solar"><label>Vehicle</label><div class="v" style="font-size:14px">CG04MM1521</div>'+
      '<div class="d">19-08-2026</div></div>'+
    '<div class="kpi k-pass"><label>Gate pass</label><div class="v" style="font-size:14px">GP-2608-0030</div>'+
      '<div class="d">issued 14:55</div></div></div>'+
  '<div class="card"><div class="card-h"><h3>Boxes on this challan</h3>'+
    '<div class="ch-r"><button class="btn btn-ghost btn-sm" onclick="exportNote()">Export</button></div></div>'+
    '<div class="card-b flush"><table><thead><tr><th>Box no.</th><th>Bin</th><th>Model</th>'+
    '<th>Grade</th><th style="text-align:right">Qty</th><th>Packed</th>'+
    '<th style="text-align:center">Open</th></tr></thead><tbody>'+
    boxes.map(function(b){
      return '<tr><td class="mono">'+b+'</td><td class="mono">BIN-3</td>'+
      '<td class="mono">ISEN590-G2X</td><td><span class="tag t-pass">A</span></td>'+
      '<td class="num">36</td><td class="mono">19-08-2026</td>'+
      '<td style="text-align:center"><button class="btn btn-ghost btn-sm" '+
      'onclick="qTry(\''+b+'\')">→</button></td></tr>';}).join('')+
    '</tbody><tfoot><tr><td colspan="4">Total</td><td class="num">108</td>'+
    '<td colspan="2"></td></tr></tfoot></table></div></div>';
}
function vehicleView(v){
  return '<div class="crumb">Vehicle <b>'+v+'</b></div>'+
  '<div class="note n-info"><span>ⓘ</span><span>Everything this vehicle carried, newest first. '+
    'Open a challan to see its boxes, then a box to see its modules.</span></div>'+
  '<div class="card"><div class="card-h"><h3>Trips</h3></div><div class="card-b flush"><table>'+
  '<thead><tr><th>Date</th><th>Challan</th><th>Customer</th><th>Destination</th>'+
  '<th style="text-align:right">Boxes</th><th style="text-align:right">Modules</th><th>Gate pass</th>'+
  '<th style="text-align:center">Open</th></tr></thead><tbody>'+
  '<tr><td class="mono">19-08-2026</td><td class="mono">CHN-455</td><td>SAI BABUJI</td>'+
  '<td>Maharashtra</td><td class="num">18</td><td class="num">648</td><td class="mono">GP-2608-0030</td>'+
  '<td style="text-align:center"><button class="btn btn-ghost btn-sm" onclick="qTry(\'CHN-455\')">→</button></td></tr>'+
  '<tr><td class="mono">11-08-2026</td><td class="mono">CHN-441</td><td>SAI BABUJI</td>'+
  '<td>Maharashtra</td><td class="num">18</td><td class="num">648</td><td class="mono">GP-2608-0017</td>'+
  '<td style="text-align:center"><button class="btn btn-ghost btn-sm" onclick="qTry(\'CHN-441\')">→</button></td></tr>'+
  '</tbody></table></div></div>';
}
function serialView(s){
  var d=derive(s);
  return '<div class="crumb">Module <b>'+s+'</b></div>'+
  (d.ok?'':'<div class="note n-bad"><span>⚑</span><span>'+d.why+
    ' — this serial is flagged for review and no model number was derived.</span></div>')+
  '<div class="note n-info" style="font-size:11.5px"><span>&#9432;</span><span>The unit of truth is <b>serial + build instance</b>, never the serial alone. Pre-shared allocation can put a B-grade twin and a rebuilt A-grade module under one number; both are real, and only one may ship under the original allocation.</span></div>'+'<div class="card"><div class="card-h"><h3>Build instances</h3>'+'<div class="ch-r"><span class="tag t-mute">key: serial + build_instance</span></div></div>'+'<div class="card-b flush"><table><thead><tr><th>Instance</th><th>Built</th><th>Grade</th>'+'<th>Allocation</th><th>Status</th><th>DCR eligible</th></tr></thead><tbody>'+'<tr><td class="mono">1</td><td class="mono">13-02-2026</td>'+'<td><span class="tag t-pass">A</span></td><td>Pre-shared &middot; SAI BABUJI</td>'+'<td><span class="tag t-solar">Dispatched</span></td>'+'<td><span class="tag t-pass">Yes</span></td></tr>'+'<tr><td class="mono">2</td><td class="mono">—</td><td>—</td><td>—</td>'+'<td><span class="tag t-mute">Not built</span></td><td>—</td></tr>'+'</tbody></table></div><div class="card-f"><span style="font-size:11.5px;color:var(--ink3)">DCR eligibility is <b>derived</b> in the export query from grade, allocation and dispatch status — not stored as a flag, so it cannot drift out of step.</span></div></div>'+'<div class="card"><div class="card-h"><h3>Customer assignment history</h3>'+'<div class="ch-r"><span class="tag t-mute">assignment, not a fixed attribute</span></div></div>'+'<div class="card-b flush"><table><thead><tr><th>Effective from</th><th>Customer</th>'+'<th>Reason</th><th>By</th><th>Approved</th></tr></thead><tbody>'+'<tr><td class="mono">13-02-2026</td><td>SAI BABUJI PROJECTS</td>'+'<td>Original allocation</td><td>Mukesh</td><td>—</td></tr>'+'</tbody></table></div><div class="card-f"><span style="font-size:11.5px;color:var(--ink3)">Hard boundary: once a serial is dispatched its customer can never change. Reassignment before dispatch needs a coded reason and an approval.</span></div></div>'+'<div class="card"><div class="card-h"><h3>Module journey</h3>'+
    '<div class="ch-r"><span class="mono" style="font-size:12px;font-weight:700">'+
    (d.ok?d.model:'model not derived')+'</span></div></div><div class="card-b"><div class="chain">'+
  '<div class="node done"><label>Allocated</label><div class="nv">BAT-2602-00019</div>'+
    '<div class="nd">SAI BABUJI<br>'+(d.watt||'—')+'W · '+(d.ok?d.type:'unknown')+'</div>'+
    '<div class="ns"><span class="tag t-mute">13-02 · 09:12</span></div></div>'+
  '<div class="node done"><label>FQC</label><div class="nv">A</div>'+
    '<div class="nd">Rajesh Kumar<br>Shift A</div>'+
    '<div class="ns"><span class="tag t-pass">Passed</span></div></div>'+
  '<div class="node done"><label>Packed</label><div class="nv">A031</div>'+
    '<div class="nd">BIN-3 · slot 1<br>19-08 · Shift A</div>'+
    '<div class="ns"><span class="tag t-mute">Closed</span></div></div>'+
  '<div class="node done"><label>Repacked</label><div class="nv">RPK-2608-00008</div>'+
    '<div class="nd">Customer split<br>Suresh Patel</div>'+
    '<div class="ns"><span class="tag t-rev">Moved</span></div></div>'+
  '<div class="node done"><label>Repacked into</label><div class="nv">A044</div>'+
    '<div class="nd">BIN-3 · slot 7<br>19-08 · Shift B</div>'+
    '<div class="ns"><span class="tag t-info">Current box</span></div></div>'+
  '<div class="node cur"><label>Challan</label><div class="nv">CHN-455</div>'+
    '<div class="nd">CG04MM1521<br>Maharashtra</div>'+
    '<div class="ns"><span class="tag t-solar">Dispatched</span></div></div>'+
  '<div class="node cur"><label>Gate pass</label><div class="nv">GP-2608-0030</div>'+
    '<div class="nd">19-08 · 14:55<br>Dasrath Pal</div>'+
    '<div class="ns"><span class="tag t-solar">Issued</span></div></div>'+
  '</div></div></div>'+
  '<div class="work"><div class="card"><div class="card-h"><h3>Full event log</h3></div>'+
  '<div class="card-b flush"><table><thead><tr><th>Timestamp</th><th>Stage</th><th>Reference</th>'+
  '<th>Detail</th><th>User</th></tr></thead><tbody>'+
  '<tr><td class="mono">13-02-2026 09:12:04</td><td>Allocation</td><td class="mono">BAT-2602-00019</td>'+
    '<td>Range load · 70 serials</td><td>Mukesh</td></tr>'+
  '<tr><td class="mono">19-08-2026 07:41:22</td><td>FQC</td><td class="mono">FQC-88214</td>'+
    '<td>Category A · no remark</td><td>Rajesh Kumar</td></tr>'+
  '<tr><td class="mono">19-08-2026 08:03:55</td><td>Packing</td><td class="mono">A031</td>'+
    '<td>Added to slot 1 · BIN-3</td><td>Packing Station</td></tr>'+
  '<tr><td class="mono">19-08-2026 13:22:47</td><td>Repack</td><td class="mono">RPK-2608-00008</td>'+
    '<td>Removed from A031</td><td>Suresh Patel</td></tr>'+
  '<tr><td class="mono">19-08-2026 13:24:02</td><td>Repack</td><td class="mono">A044</td>'+
    '<td>Added to slot 7 · BIN-3</td><td>Suresh Patel</td></tr>'+
  '<tr><td class="mono">19-08-2026 14:55:31</td><td>Dispatch</td>'+
    '<td class="mono">CHN-455 → GP-2608-0030</td><td>Vehicle CG04MM1521</td><td>Dispatch Desk</td></tr>'+
  '</tbody></table></div></div>'+
  '<div class="rail o2"><div class="card"><div class="card-h"><h3>Materials used</h3>'+
    '<div class="ch-r"><span class="tag t-mute">frozen at allocation</span></div></div>'+
    '<div class="card-b flush"><table><tbody>'+
    matSummary(d.ok?d.model:'ISEN590-G2X')+
    '</tbody></table></div>'+
    '<div class="card-f"><button class="btn btn-ghost btn-sm" onclick="showMaterials(\'' +
      (d.ok?d.model:'ISEN590-G2X') + '\')">View full details</button>'+
    '<span style="font-size:10.5px;color:var(--ink3);margin-left:auto">sizes &amp; batches inside'+
    '</span></div></div></div></div>';
}

/* ================= KEYBOARD ================= */
document.addEventListener('keydown',function(e){
  if(e.key==='Escape'){
    if(document.getElementById('mdl').classList.contains('on')){closeModal();return}
    if(fqcHold){fqcCancel();return}
    if(packHold){packCancel();return}}
  if(e.code==='Space'){
    if(fqcHold){e.preventDefault();fqcCommit();return}
    if(packHold&&packHold.ok){e.preventDefault();packCommit();return}}
});

/* ================= INIT ================= */
function initAll(){
  tick();renderDash();buildSlots();renderSrc();binTog();
  stampPlanUser();indentChange();
  renderMgmt();renderProd();renderSectionDonuts();fqcRange();renderPE();peCalc();renderLoss();
  renderChBoxes();initChallanNo();renderChDocs();gstCheck();runChecks();
  renderUsers();renderMach();renderStations();renderMaterials();renderConsumption();renderOpenQ();renderReasons();renderDocs();
  holdScopeChange();renderHolds();renderLoad();renderDrafts();
  document.getElementById('gpBy').value=USER.name+' · '+USER.role;
  doSearch();
}
}