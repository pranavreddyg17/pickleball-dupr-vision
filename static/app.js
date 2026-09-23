const app = document.getElementById('app');
const state = {user:null, videos:[], scores:null, self:null, page:'home', selectedId:null,
  player:null, players:[], playerView:'discover', search:'', offset:0, hasMore:false,
  year:null, day:null, preview:1, point:null, consent:false, authMode:'login',
  busy:false, uploadProgress:0, error:'', notice:'', workerRunning:false, engine:'local', analysisConfigured:true, externalConsent:false};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num = value => value == null ? '--' : String(Math.round(Number(value)));
const reportCount = value => `${value} ${value===1?'report':'reports'}`;
const dateLabel = value => new Date(value.length === 10 ? `${value}T12:00:00` : value).toLocaleDateString(undefined, {month:'short',day:'numeric',year:'numeric'});
const duration = value => `${Math.floor(value / 60)}:${String(Math.round(value % 60)).padStart(2,'0')}`;
const timestamp = value => `${Math.floor(value / 60)}:${(value % 60).toFixed(1).padStart(4,'0')}`;
const icon = name => `<img class="icon" src="/icons/${name}.svg?v=7" alt="">`;
const button = (label, action, style='secondary') => `<button class="${style}" data-action="${action}">${label}</button>`;

async function api(path, options={}) {
  const response = await fetch(`/api${path}`, {credentials:'same-origin',...options});
  const data = await response.json().catch(() => ({}));
  if (!response.ok) { const error = new Error(typeof data.detail === 'string' ? data.detail : 'Request could not be completed'); error.status = response.status; throw error; }
  return data;
}
const jsonRequest = (method, body) => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});

async function refresh(draw=true) {
  try {
    const user = await api('/me');
    const [videos,scores,health,self] = await Promise.all([api('/videos'),api('/scores'),api('/health'),api(`/players/${user.id}`)]);
    Object.assign(state,{user,videos,scores,self,workerRunning:health.worker_running,engine:health.analysis_engine,analysisConfigured:health.analysis_configured});
  } catch (error) {
    if (error.status === 401) Object.assign(state,{user:null,videos:[],scores:null,self:null,selectedId:null,player:null});
    else state.error = error.message;
  }
  if (draw) render();
}
async function loadPlayers() {
  const result = await api(`/players?q=${encodeURIComponent(state.search)}&view=${state.playerView}&offset=${state.offset}`);
  state.players = result.players; state.hasMore = result.has_more;
}
function message() { return `${state.error ? `<div class="alert" role="alert">${esc(state.error)}</div>` : ''}${state.notice ? `<div class="notice" role="status">${esc(state.notice)}</div>` : ''}`; }
function avatar(name, large=false) { return `<span class="avatar ${large ? 'large' : ''}">${esc(name.trim().slice(0,1).toUpperCase())}</span>`; }

function authView() {
  const register = state.authMode === 'register';
  return `<main class="auth"><a class="brand" href="/">DUPRVision<span class="brand-dot"></span></a><div class="auth-form"><h1>${register ? 'Create account' : 'Welcome back'}</h1>${message()}<form id="auth-form">
    ${register ? '<label for="display-name">Name</label><input id="display-name" name="display_name" autocomplete="name" maxlength="80" required>' : ''}
    <label for="email">Email</label><input id="email" name="email" type="email" autocomplete="email" required>
    <label for="password">Password</label><input id="password" name="password" type="password" autocomplete="${register ? 'new-password' : 'current-password'}" minlength="10" maxlength="256" required>
    <button class="primary full" type="submit">${register ? 'Create account' : 'Sign in'}</button></form>
    <div class="auth-switch"><span>${register ? 'Already have an account?' : 'New to DUPRVision?'}</span>${button(register ? 'Sign in' : 'Create account','auth-toggle','text-button')}</div></div></main>`;
}

function shell(content) {
  const nav = [['home','Overview','house'],['analyze','Analyze','circle-plus'],['players','Players','users-round'],['profile','Account','user-round']]
    .map(([key,label,img]) => `<button class="nav-item ${state.page === key ? 'active' : ''}" data-page="${key}" ${state.page === key ? 'aria-current="page"' : ''}>${icon(img)}<span>${label}</span></button>`).join('');
  return `<header class="topbar"><div class="topbar-inner"><a class="brand" href="/">DUPRVision<span class="brand-dot"></span></a><nav aria-label="Main">${nav}</nav><button class="avatar-button" data-page="profile" title="Your account" aria-label="Your account">${avatar(state.user.display_name)}</button></div></header>
    <main class="main">${message()}${content}</main>`;
}

function stats(history) {
  const today = history.days.find(d => d.date === history.today);
  return `<div class="score-strip"><div class="score-primary"><span class="label">Vision score</span><div class="score-value">${num(history.average)}<small>/ 100</small></div><span class="muted small">${history.average == null ? 'No scored sessions' : 'Daily average · Clip performance'}</span><div class="dupr-equivalent"><span class="label">DUPR-scale equivalent</span><strong>${history.dupr_equivalent == null ? '--' : Number(history.dupr_equivalent).toFixed(1)}</strong><span class="fine">Uncalibrated estimate from Vision score</span></div></div><div><span class="label">Today</span><strong>${num(today?.score)}</strong><span class="muted small">${today ? reportCount(today.clips) : 'No analysis'}</span></div><div><span class="label">Active days</span><strong>${history.days.length}</strong><span class="muted small">${history.streak} day streak</span></div><div><span class="label">Reports</span><strong>${history.clips}</strong><span class="muted small">Completed analyses</span></div></div>`;
}

function calendar(history) {
  const currentYear = Number(history.today.slice(0,4));
  const earliest = history.days.length ? Number(history.days[0].date.slice(0,4)) : currentYear;
  const year = state.year || currentYear;
  const years = Array.from({length:currentYear-earliest+1},(_,i)=>currentYear-i);
  const first = new Date(Date.UTC(year,0,1)), last = new Date(Date.UTC(year,11,31));
  const start = new Date(first); start.setUTCDate(1-first.getUTCDay());
  const count = Math.ceil(((last-start)/86400000+1)/7)*7;
  const lookup = Object.fromEntries(history.days.map(d=>[d.date,d]));
  let cells = '', months = '', previousMonth = -1;
  for (let i=0;i<count;i++) {
    const date = new Date(start.getTime()+i*86400000), key=date.toISOString().slice(0,10), day=lookup[key];
    const inYear = date.getUTCFullYear() === year;
    if (i%7===0) {
      const anchor = new Date(Math.max(first.getTime(),date.getTime()+3*86400000)), month=anchor.getUTCMonth();
      months += `<span>${month !== previousMonth ? anchor.toLocaleDateString('en',{month:'short',timeZone:'UTC'}) : ''}</span>`; previousMonth=month;
    }
    const label = `${dateLabel(key)}: ${day ? `${day.score == null ? 'No score' : `${num(day.score)} Vision score`}, ${reportCount(day.clips)}` : 'No analysis'}`;
    const level = day ? day.score == null ? 1 : Math.min(4,Math.max(1,1+Math.floor(day.score/25))) : 0;
    cells += inYear && key <= history.today
      ? `<button class="day level-${level} ${state.day === key ? 'selected' : ''}" data-day="${key}" aria-label="${esc(label)}" title="${esc(label)}"></button>`
      : `<span class="day ${inYear?'future':'outside'}"></span>`;
  }
  const selected = lookup[state.day];
  const yearDays = history.days.filter(d=>d.date.startsWith(`${year}-`));
  return `<section class="section calendar-section"><div class="section-head"><h2>Daily activity</h2><select id="calendar-year" aria-label="Calendar year">${years.map(y=>`<option ${y===year?'selected':''}>${y}</option>`).join('')}</select></div>
    <div class="calendar-scroll"><div class="calendar-inner" style="--weeks:${count/7}"><div class="month-labels">${months}</div><div class="calendar-body"><div class="weekday-labels"><span>Mon</span><span>Wed</span><span>Fri</span></div><div class="heatmap">${cells}</div></div></div></div>
    <div class="calendar-meta"><span>${yearDays.length} recorded ${yearDays.length===1?'day':'days'} in ${year}</span><div class="legend"><span>0</span>${[1,2,3,4].map(l=>`<i class="day level-${l}"></i>`).join('')}<span>100</span></div></div>
    ${state.day ? `<div class="selected-day"><strong>${dateLabel(state.day)}</strong><span>${selected ? `${selected.score == null ? 'No score' : `${num(selected.score)} Vision score`} &middot; ${reportCount(selected.clips)}` : 'No analysis'}</span>${button('Clear','clear-day','text-button')}</div>` : ''}
    </section>`;
}

function homeView() {
  const videos = state.day ? state.videos.filter(v=>v.result?.score_date===state.day) : state.videos;
  return `<div class="page-head"><div><h1>${esc(state.user.display_name)}</h1><div class="social-links"><button data-people="followers">${state.self.followers} followers</button><button data-people="following">${state.self.following} following</button></div></div></div>
    ${stats(state.scores)}${calendar(state.scores)}<section class="section"><div class="section-head"><h2>${state.day ? 'Clips on this day' : 'Your clips'}</h2><span class="muted small">${state.user.remaining} uploads left today</span></div>${videos.length ? `<div class="session-list">${videos.map(sessionRow).join('')}</div>` : '<p class="empty">No clips yet.</p>'}</section>`;
}

function sessionRow(video) {
  const r = video.status==='COMPLETED'?video.result:null, score = r?.performance?.score;
  return `<button class="session-row" data-video="${video.id}"><div><strong>${esc(video.original_filename)}</strong><span class="muted small">${dateLabel(video.created_at)} &middot; ${duration(video.duration_seconds)}${r?' &middot; Report saved':''}</span></div><span class="session-status ${video.status==='FAILED'?'danger':''}">${score != null ? `<b>${num(score)}</b>` : esc(r ? 'View report' : video.status==='WAITING_FOR_PLAYER'?'Select player':video.stage)}</span><span aria-hidden="true">&rsaquo;</span></button>`;
}

function analyzeView() {
  return `<div class="page-head"><h1>Analyze</h1><span class="muted small">${state.user.remaining} of 5 uploads remaining</span></div>
    ${!state.workerRunning ? '<div class="alert">Analysis is temporarily unavailable. The local worker needs to restart.</div>' : ''}
    ${!state.analysisConfigured ? '<div class="alert">Video review is awaiting owner configuration.</div>' : ''}
    <section class="upload-zone">${icon('upload')}<h2>Gameplay video</h2><p class="muted">MP4, MOV &middot; Up to 3 minutes &middot; 100 MB max</p><input id="video-input" type="file" accept="video/mp4,video/quicktime,video/x-m4v,.mp4,.mov,.m4v" hidden><button class="primary" data-action="choose-video" ${state.busy || !state.workerRunning || !state.analysisConfigured || !state.user.remaining?'disabled':''}>Choose video</button>${state.busy?`<progress max="100" value="${state.uploadProgress}" aria-label="Upload progress"></progress><span id="upload-percent">${state.uploadProgress}%</span>`:''}</section>
    <p class="fine retention-note">Video files are deleted after the report is saved. Reports and daily activity remain.</p>`;
}

function followButton(player) {
  return player.id === state.user.id ? '' : `<button class="${player.is_following?'secondary':'primary'} follow-button" data-follow="${player.id}" data-following="${player.is_following}">${player.is_following?'Following':'Follow'}</button>`;
}
function playersView() {
  if (state.player) {
    const p=state.player;
    return `${button(`${icon('arrow-left')}Players`,'back-players','text-button')}<div class="page-head"><div class="player-identity">${avatar(p.display_name,true)}<div><h1>${esc(p.display_name)}</h1><p class="muted small">${p.followers} followers &middot; ${p.following} following</p></div></div>${followButton(p)}</div>${stats(p.history)}${calendar(p.history)}`;
  }
  return `<div class="page-head"><h1>Players</h1></div><div class="directory-tools"><div class="tabs" role="tablist" aria-label="Players">${['discover','following','followers'].map(view=>`<button role="tab" aria-selected="${state.playerView===view}" data-people="${view}" class="${state.playerView===view?'active':''}">${view[0].toUpperCase()+view.slice(1)}</button>`).join('')}</div><form id="search-form"><input name="q" aria-label="Search players" placeholder="Search players" maxlength="80" value="${esc(state.search)}"><button class="secondary search-button" type="submit" aria-label="Search" title="Search">${icon('search')}</button></form></div>
    <div class="player-list">${state.players.length ? state.players.map(p=>`<div class="player-row"><button class="player-identity" data-player="${p.id}">${avatar(p.display_name)}<span><strong>${esc(p.display_name)}</strong><span class="muted small">${p.latest ? `Last scored ${dateLabel(p.latest.date)}` : 'No scored clips'}</span></span></button><div class="player-score"><strong>${num(p.average)}</strong><span class="muted small">Vision score</span></div>${followButton(p)}</div>`).join('') : '<p class="empty">No players found.</p>'}</div>
    <div class="pagination">${state.offset ? button('Previous','previous-players') : ''}${state.hasMore ? button('Next','next-players') : ''}</div>${!state.user.discoverable?'<p class="fine">Your profile is private. Profile visibility can be changed in Account.</p>':''}`;
}

function profileView() {
  return `<div class="page-head"><h1>Account</h1></div><div class="account-layout"><div class="player-identity">${avatar(state.user.display_name,true)}<div><strong>${esc(state.user.display_name)}</strong><p class="muted small">${esc(state.user.email)}</p></div></div><form id="profile-form" class="profile-form"><label for="profile-name">Display name</label><input id="profile-name" name="display_name" value="${esc(state.user.display_name)}" required maxlength="80"><label class="checkbox"><input name="discoverable" type="checkbox" ${state.user.discoverable?'checked':''}><span>Visible in player directory</span></label><p class="fine">Shares your name, score calendar and follow counts with signed-in members. Videos and email stay private.</p><button class="primary" type="submit">Save changes</button></form><div class="account-bottom"><span class="muted small">${state.videos.length} reports and uploads &middot; ${state.user.remaining} uploads remaining today</span>${button('Sign out','logout')}</div></div>`;
}

function detailView() {
  const v=state.videos.find(video=>video.id===state.selectedId);
  if (!v) return homeView();
  const heading=`${button(`${icon('arrow-left')}Reports`,'back-clips','text-button')}<div class="page-head"><div><h1>${v.status==='WAITING_FOR_PLAYER'?'Select player':'Session review'}</h1><p class="muted small">${esc(v.original_filename)} &middot; ${dateLabel(v.created_at)} &middot; ${duration(v.duration_seconds)}</p></div>${v.status==='COMPLETED'?`<button class="icon-button report-delete" data-action="delete-video" aria-label="Delete report" title="Delete report">${icon('trash-2')}</button>`:''}</div>`;
  if (v.status==='WAITING_FOR_PLAYER') return heading+`<div class="tabs preview-tabs">${[1,2,3].map(n=>`<button class="${n===state.preview?'active':''}" data-preview="${n}">Frame ${n}</button>`).join('')}</div><div class="preview-wrap"><img id="preview-image" src="/api/videos/${v.id}/preview/${state.preview}" alt="Select your body in the video frame" tabindex="0">${state.point?`<span class="point" style="left:${state.point.x*100}%;top:${state.point.y*100}%" aria-hidden="true">+</span>`:''}</div><div class="selection-coordinates"><label>Player X <input id="point-x" type="number" min="0" max="100" step="1" value="${state.point?Math.round(state.point.x*100):50}" aria-label="Player horizontal position percent"></label><label>Player Y <input id="point-y" type="number" min="0" max="100" step="1" value="${state.point?Math.round(state.point.y*100):50}" aria-label="Player vertical position percent"></label><span class="muted small">${state.point?'Player selected':'Select yourself in the frame'}</span></div><label class="checkbox"><input id="consent" type="checkbox" ${state.consent?'checked':''}><span>I have permission to analyze this footage.</span></label>
    ${state.engine==='gemini'?`<label class="checkbox"><input id="external-consent" type="checkbox" ${state.externalConsent?'checked':''}><span>I agree to send this clip and its player-selection frame to Google Gemini for video analysis. Other players may be visible. Google's API data policy applies.</span></label>`:''}
    <div class="action-row"><button class="primary" data-action="start-analysis" ${canAnalyze()?'':'disabled'}>Analyze clip</button>${button('Delete clip','delete-video','text-button danger')}</div>`;
  if (v.status==='COMPLETED') {
    const r=v.result;
    if (!['pose_review_v1','video_review_v1','video_review_v2'].includes(r.kind)) return heading+`<p class="empty">Archived report. Not included in scores.</p>${button('Delete report','delete-video','text-button danger')}`;
    return heading+reportView(r);
  }
  if (v.status==='FAILED') return heading+`<div class="failure"><h2>Analysis incomplete</h2><p>${esc(v.error)}</p><div class="action-row">${button('Try again','retry-video','primary')}${button('Delete clip','delete-video','text-button danger')}</div></div>`;
  if (v.status==='EXPIRED') return heading+`<p class="empty">This upload expired before analysis.</p><button class="primary" data-page="analyze">Upload a new clip</button>`;
  return heading+`<div class="processing" role="status"><span class="spinner"></span><h2>${esc(v.stage)}</h2></div>`;
}

function canAnalyze() { return state.point && state.consent && state.analysisConfigured && (state.engine!=='gemini'||state.externalConsent); }

function reportView(r) {
  if(r.kind==='video_review_v2') return compactReport(r);
  const local=r.kind==='pose_review_v1';
  const events=local?(r.swing_candidates||[]):(r.shots||[]);
  const rallies=local?[]:(r.rallies||[]);
  const counts=Object.entries(r.shot_counts||{}).filter(([type,count])=>type!=='unknown'&&count>0).sort((a,b)=>b[1]-a[1]);
  const total=counts.reduce((sum,[,count])=>sum+count,0);
  const capitalize=value=>value.charAt(0).toUpperCase()+value.slice(1);
  const localSummary=`The selected player was visible in ${Math.round((r.metrics?.subject_visibility||0)*100)}% of sampled frames. ${events.length} stroke-like movements were recorded. This earlier report contains tracking observations only.`;
  return `<section class="review-overview"><span class="eyebrow">${local?'Tracking record':'Your game'}</span><p class="review-lead">${esc(local?localSummary:r.summary)}</p></section>
    ${!local?`<p class="fine">Earlier review${r.rating?` · ${Number(r.rating.estimate).toFixed(1)} unofficial level estimate`:''}. Not included in Vision scores.</p>`:''}
    ${!local&&((r.strengths||[]).length||(r.priorities||[]).length)?`<div class="coaching-columns">${(r.strengths||[]).length?`<section class="section"><h2>Working well</h2><ul class="coaching-list strengths">${r.strengths.map(p=>`<li>${esc(p)}</li>`).join('')}</ul></section>`:''}${(r.priorities||[]).length?`<section class="section"><h2>Next session</h2><ol class="coaching-list priorities">${r.priorities.map(p=>`<li>${esc(p)}</li>`).join('')}</ol></section>`:''}</div>`:''}
    ${counts.length?`<section class="section"><div class="section-head"><h2>Shot selection</h2><span class="muted small">${total} identified${r.uncertain_shots?` &middot; ${r.uncertain_shots} unclear`:''}</span></div><ul class="shot-mix">${counts.map(([type,count])=>`<li><span>${esc(capitalize(type))}</span><div class="shot-track"><span style="width:${Math.round(count/total*100)}%"></span></div><strong>${count}</strong></li>`).join('')}</ul></section>`:''}
    ${rallies.length?`<section class="section"><h2>Rally review</h2><ol class="event-list">${rallies.map(rally=>`<li><time>${timestamp(rally.start)} &ndash; ${timestamp(rally.end)}</time><span>${esc(rally.observation)}</span></li>`).join('')}</ol></section>`:''}
    ${events.length?`<details class="shot-log"><summary>${local?'Recorded movements':'Shot log'} &middot; ${events.length}</summary><ol class="event-list">${events.map(e=>`<li><time>${timestamp(e.timestamp)}</time><div><strong>${esc(capitalize(e.form||e.shot_type))}</strong>${e.confidence==='low'?'<span class="uncertain">Uncertain</span>':''}${e.observation?`<p>${esc(e.observation)}</p>`:''}</div></li>`).join('')}</ol></details>`:''}
    ${!local&&(r.limitations||[]).length?`<aside class="review-note"><strong>About this clip</strong><p>${r.limitations.map(esc).join(' ')}</p></aside>`:''}`;
}

function compactReport(r) {
  const p=r.performance, counts=Object.entries(r.shot_counts||{});
  return `<section class="performance-summary"><div class="performance-number"><span class="label">Vision score</span><strong>${num(p.score)}</strong><span class="muted"> / 100</span></div><div><p>${esc(r.summary)}</p>${r.priority?`<p class="next-focus"><strong>Next session</strong> ${esc(r.priority)}</p>`:''}<span class="fine">${esc(p.note)}</span></div></section>
    <dl class="performance-metrics">${p.components.map(c=>`<div><dt>${esc(c.name)} <span>${Math.round(c.weight*100)}%</span></dt><dd>${num(c.value)}<small>/ 100</small></dd><span class="fine">${c.observations} observations</span></div>`).join('')}</dl>
    <div class="clip-totals"><span>${p.observed_shots} assessed shots</span><span>${r.rallies.length} ${r.rallies.length===1?'rally':'rallies'}</span>${counts.map(([type,n])=>`<span>${n} ${esc(type)}${n===1?'':'s'}</span>`).join('')}</div>
    <details class="shot-log"><summary>Scoring details</summary><p class="fine">50% shot control + 25% balance + 25% recovery. Control: purposeful placement = 100, neutral = 50, visible error = 0. Unclear observations are excluded. First 40 visible contacts at most; saved scores stay fixed. AI observations can be wrong.</p>${r.recording_note?`<p class="fine">${esc(r.recording_note)}</p>`:''}<ol class="event-list">${r.shots.map(s=>`<li><time>${timestamp(s.timestamp)}</time><div><strong>${esc(s.shot_type)}</strong><p>${esc(s.control)} · Balance ${s.balanced==null?'unclear':s.balanced?'stable':'unstable'} · Recovery ${s.recovered==null?'unclear':s.recovered?'ready':'late'}${s.confidence==='low'?' · Low confidence':''}</p></div></li>`).join('')}</ol></details>`;
}

function render() {
  const previousScroll=document.querySelector('.calendar-scroll')?.scrollLeft;
  document.title=state.user?`${({home:'Overview',analyze:'Analyze',players:'Players',profile:'Account'})[state.page]} | DUPRVision`:'DUPRVision';
  app.innerHTML=state.user?shell(state.selectedId?detailView():({home:homeView,analyze:analyzeView,players:playersView,profile:profileView}[state.page])()):authView();
  const preview=document.getElementById('preview-image');
  if(preview) {
    const fitPreview=()=>{
      if(!preview.naturalWidth||!preview.naturalHeight)return;
      const scale=Math.min(900/preview.naturalWidth,(window.innerWidth-40)/preview.naturalWidth,Math.min(600,window.innerHeight*.65)/preview.naturalHeight);
      preview.parentElement.style.width=`${Math.round(preview.naturalWidth*scale)}px`;
      preview.style.visibility='visible';
    };
    if(preview.complete)fitPreview();
    else preview.addEventListener('load',fitPreview,{once:true});
  }
  const calendarScroll=document.querySelector('.calendar-scroll');
  if(calendarScroll) {
    const today=document.querySelector(`[data-day="${state.scores.today}"]`);
    calendarScroll.scrollLeft=previousScroll??(today?Math.max(0,today.getBoundingClientRect().left-calendarScroll.getBoundingClientRect().left-calendarScroll.clientWidth+30):0);
  }
}

app.addEventListener('click', async event=>{
  const target=event.target.closest('button, #preview-image');
  if (!target) return;
  if (target.type === 'submit' && target.closest('form')) return;
  state.error=''; state.notice='';
  try {
    if (target.dataset.page) {
      state.page=target.dataset.page; state.selectedId=null; state.player=null; state.year=null; state.day=null;
      if(state.page==='players') await loadPlayers();
      render(); window.scrollTo(0,0); return;
    }
    if (target.dataset.people) {
      Object.assign(state,{page:'players',playerView:target.dataset.people,offset:0,player:null,selectedId:null,search:''});
      await loadPlayers(); render(); return;
    }
    if (target.dataset.player) { state.player=await api(`/players/${target.dataset.player}`); state.year=null; state.day=null; render(); return; }
    if (target.dataset.follow) {
      target.disabled=true;
      await api(`/players/${target.dataset.follow}/follow`,{method:target.dataset.following==='true'?'DELETE':'POST'});
      if(state.player) state.player=await api(`/players/${state.player.id}`);
      await loadPlayers(); await refresh(); return;
    }
    if (target.dataset.day) { state.day=target.dataset.day; render(); return; }
    if (target.dataset.video) { Object.assign(state,{selectedId:target.dataset.video,preview:1,point:null,consent:false,externalConsent:false});render();window.scrollTo(0,0);return; }
    if (target.dataset.preview) {state.preview=Number(target.dataset.preview);state.point=null;render();return;}
    if (target.id==='preview-image') {const rect=target.getBoundingClientRect();state.point={x:(event.clientX-rect.left)/rect.width,y:(event.clientY-rect.top)/rect.height};render();return;}
    switch(target.dataset.action) {
      case 'auth-toggle':state.authMode=state.authMode==='login'?'register':'login';break;
      case 'choose-video':document.getElementById('video-input').click();return;
      case 'clear-day':state.day=null;break;
      case 'back-clips':state.selectedId=null;state.page='home';break;
      case 'back-players':state.player=null;state.day=null;state.year=null;await loadPlayers();break;
      case 'next-players':state.offset+=30;await loadPlayers();break;
      case 'previous-players':state.offset=Math.max(0,state.offset-30);await loadPlayers();break;
      case 'logout':await api('/logout',{method:'POST'});state.page='home';await refresh();return;
      case 'start-analysis': {
        const v=state.videos.find(v=>v.id===state.selectedId);target.disabled=true;
        await api(`/videos/${v.id}/select`,jsonRequest('POST',{timestamp_seconds:v.duration_seconds*[.1,.4,.7][state.preview-1],...state.point,consent:state.consent,external_consent:state.externalConsent}));
        await refresh();return;
      }
      case 'retry-video':
        if(!confirm('Reanalyze this clip? Its current result will be removed from your score history.')) return;
        await api(`/videos/${state.selectedId}/retry`,{method:'POST'});state.point=null;state.consent=false;state.externalConsent=false;await refresh();return;
      case 'delete-video':
        if(!confirm('Permanently delete this clip and its result? The daily score will be recalculated. Upload allowance will not reset.'))return;
        await api(`/videos/${state.selectedId}`,{method:'DELETE'});state.selectedId=null;state.page='home';await refresh();return;
    }
    render();
  } catch(error) {state.error=error.message;render();}
});

app.addEventListener('submit',async event=>{
  event.preventDefault(); const form=event.target, data=new FormData(form), submit=form.querySelector('[type="submit"]');
  if(submit)submit.disabled=true;
  state.error='';state.notice='';
  try {
    if(form.id==='auth-form') {await api(state.authMode==='register'?'/register':'/login',jsonRequest('POST',Object.fromEntries(data)));await refresh();}
    if(form.id==='profile-form') {await api('/me',jsonRequest('PUT',{display_name:data.get('display_name'),discoverable:data.has('discoverable')}));state.notice='Changes saved';await refresh();}
    if(form.id==='search-form') {state.search=data.get('q');state.offset=0;await loadPlayers();render();}
  } catch(error) {state.error=error.message;render();}
});

app.addEventListener('change',event=>{
  const target=event.target;
  if(target.id==='calendar-year') {state.year=Number(target.value);state.day=null;render();}
  if(target.id==='consent') {state.consent=target.checked;document.querySelector('[data-action="start-analysis"]').disabled=!canAnalyze();}
  if(target.id==='external-consent') {state.externalConsent=target.checked;document.querySelector('[data-action="start-analysis"]').disabled=!canAnalyze();}
  if(target.id==='video-input'&&target.files[0]) upload(target.files[0]);
});

app.addEventListener('input',event=>{
  if(!['point-x','point-y'].includes(event.target.id))return;
  state.point={x:Math.max(0,Math.min(100,Number(document.getElementById('point-x').value)))/100,y:Math.max(0,Math.min(100,Number(document.getElementById('point-y').value)))/100};
  let marker=document.querySelector('.point');
  if(!marker){marker=document.createElement('span');marker.className='point';marker.textContent='+';marker.setAttribute('aria-hidden','true');document.querySelector('.preview-wrap').append(marker);}
  marker.style.left=`${state.point.x*100}%`;marker.style.top=`${state.point.y*100}%`;
  document.querySelector('.selection-coordinates>span').textContent='Player selected';
  document.querySelector('[data-action="start-analysis"]').disabled=!canAnalyze();
});

function upload(file) {
  if(state.busy)return;
  if(file.size>100_000_000) {state.error='Video exceeds 100 MB.';render();return;}
  state.busy=true;state.uploadProgress=0;state.error='';render();
  const xhr=new XMLHttpRequest();xhr.open('POST','/api/videos');xhr.setRequestHeader('X-Filename',encodeURIComponent(file.name));
  xhr.upload.onprogress=event=>{if(event.lengthComputable){state.uploadProgress=Math.round(event.loaded/event.total*100);const progress=document.querySelector('progress');if(progress)progress.value=state.uploadProgress;const label=document.getElementById('upload-percent');if(label)label.textContent=`${state.uploadProgress}%`;}};
  xhr.onload=async()=>{state.busy=false;try{const result=JSON.parse(xhr.responseText);if(xhr.status>=400)throw new Error(result.detail||'Upload failed');state.selectedId=result.id;state.preview=1;state.point=null;state.consent=false;state.externalConsent=false;await refresh();}catch(error){state.error=error.message;render();}};
  xhr.onerror=()=>{state.busy=false;state.error='Connection lost during upload.';render();};xhr.send(file);
}

let polling=false;
setInterval(async()=>{
  if(polling||!state.user||state.busy||!state.videos.some(v=>['PROCESSING','PREPARING','QUEUED','ANALYZING'].includes(v.status)))return;
  polling=true;
  try {const active=document.activeElement;const editing=active&&['INPUT','SELECT','TEXTAREA'].includes(active.tagName);await refresh(!editing&&state.page!=='profile');}
  finally {polling=false;}
},3000);
refresh();
