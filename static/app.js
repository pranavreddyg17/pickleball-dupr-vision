const app = document.getElementById('app');
const state = {user:null, videos:[], scores:null, self:null, page:'home', selectedId:null, allSessions:false,
  player:null, players:[], playerView:'discover', search:'', offset:0, hasMore:false,
  year:null, day:null, preview:1, point:null, consent:false, saveEvidence:true, authMode:'login',
  busy:false, uploadProgress:0, error:'', notice:'', workerRunning:false, engine:'local', analysisConfigured:true, externalConsent:false};
let replay = null, replayRequest = 0, pendingSeek = null;
let viewer=null, overlayAnimation=null, overlayResize=null;
let connectionDialog=null, connectionRequest=0;
const connections={view:'connections',offset:0,players:[],hasMore:false};
const noteDrafts = new Map();
const noteOpen = new Set(), noteTimers = new Map(), noteRequests = new Map();
const capital = value => value.charAt(0).toUpperCase()+value.slice(1);
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
    if (error.status === 401) {closeConnections();clearReplay();noteDrafts.clear();Object.assign(state,{user:null,videos:[],scores:null,self:null,selectedId:null,player:null});}
    else state.error = error.message;
  }
  if (draw) render();
}
async function loadPlayers() {
  const result = await api(`/players?q=${encodeURIComponent(state.search)}&view=${state.playerView}&offset=${state.offset}`);
  state.players = result.players; state.hasMore = result.has_more;
}

function closeConnections() {
  connectionRequest++;
  const dialog=connectionDialog;connectionDialog=null;
  if(dialog){dialog.close();dialog.remove();}
  document.querySelector('[data-action="open-connections"]')?.focus();
}

function drawConnections() {
  if(!connectionDialog)return;
  connectionDialog.innerHTML=`<div class="connection-heading"><h2 id="connections-title">Connections <span>${state.self.connections??0}</span></h2><button class="dialog-close" data-close aria-label="Close connections" title="Close">&times;</button></div>
    <div class="connection-filters" aria-label="Connection filter">${[['connections','All'],['following','Following'],['followers','Followers']].map(([key,label])=>`<button data-connection-view="${key}" aria-pressed="${connections.view===key}">${label}</button>`).join('')}</div>
    <p class="connection-error" role="alert"></p><div class="connection-list">${connections.players.length?connections.players.map(p=>`<div class="connection-row"><button data-connection-player="${p.id}" class="player-identity">${avatar(p.display_name)}<strong>${esc(p.display_name)}</strong></button><button class="text-button" data-connection-follow="${p.id}" data-following="${p.is_following}">${p.is_following?'Unfollow':'Follow'}</button></div>`).join(''):`<p class="connection-empty">${connections.view==='followers'?'No followers yet.':connections.view==='following'?'You aren\'t following anyone yet.':'No connections yet.'}</p>`}</div>
    ${connections.offset||connections.hasMore?`<div class="pagination">${connections.offset?'<button class="text-button" data-connection-page="-1">Previous</button>':''}${connections.hasMore?'<button class="text-button" data-connection-page="1">Next</button>':''}</div>`:''}`;
}

async function loadConnections() {
  const request=++connectionRequest, dialog=connectionDialog;
  dialog?.setAttribute('aria-busy','true');
  const empty=dialog?.querySelector('.connection-empty');if(empty)empty.textContent='Loading connections...';
  dialog?.querySelectorAll('button:not([data-close])').forEach(b=>b.disabled=true);
  try {
    const [result,self]=await Promise.all([api(`/players?view=${connections.view}&offset=${connections.offset}`),api(`/players/${state.user.id}`)]);
    if(request!==connectionRequest||!connectionDialog)return;
    state.self=self;Object.assign(connections,{players:result.players,hasMore:result.has_more});
    const count=document.querySelector('.connection-count');if(count)count.textContent=self.connections??0;
    drawConnections();connectionDialog.querySelector(`[data-connection-view="${connections.view}"]`).focus();
  } catch(error) {
    if(request===connectionRequest&&connectionDialog){drawConnections();connectionDialog.querySelector('.connection-error').textContent=error.message;}
  } finally {dialog?.removeAttribute('aria-busy');}
}

function openConnections() {
  if(connectionDialog)return;
  Object.assign(connections,{view:'connections',offset:0,players:[],hasMore:false});
  connectionDialog=document.createElement('dialog');connectionDialog.className='connections-dialog';
  connectionDialog.setAttribute('aria-labelledby','connections-title');
  document.body.append(connectionDialog);drawConnections();connectionDialog.showModal();
  connectionDialog.addEventListener('cancel',event=>{event.preventDefault();closeConnections();});
  connectionDialog.addEventListener('click',async event=>{
    const button=event.target.closest('button');if(!button)return;
    if(button.hasAttribute('data-close')){closeConnections();return;}
    try {
      if(button.dataset.connectionView){connections.view=button.dataset.connectionView;connections.offset=0;await loadConnections();}
      if(button.dataset.connectionPage){connections.offset+=Number(button.dataset.connectionPage)*30;await loadConnections();}
      if(button.dataset.connectionFollow){
        button.disabled=true;
        await api(`/players/${button.dataset.connectionFollow}/follow`,{method:button.dataset.following==='true'?'DELETE':'POST'});
        if(connectionDialog)await loadConnections();
      }
      if(button.dataset.connectionPlayer){
        button.disabled=true;const player=await api(`/players/${button.dataset.connectionPlayer}`);
        if(!connectionDialog)return;
        closeConnections();Object.assign(state,{page:'players',player,selectedId:null,year:null,day:null});render();
      }
    } catch(error){if(connectionDialog){button.disabled=false;connectionDialog.querySelector('.connection-error').textContent=error.message;}}
  });
  loadConnections();
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
  const nav = [['home','Overview'],['analyze','Analyze'],['players','Players'],['profile','Account']]
    .map(([key,label]) => `<button class="nav-item ${state.page === key ? 'active' : ''}" data-page="${key}" ${state.page === key ? 'aria-current="page"' : ''}>${label}</button>`).join('');
  return `<header class="topbar"><div class="topbar-inner"><a class="brand" href="/">DUPRVision<span class="brand-dot"></span></a><nav aria-label="Main">${nav}</nav></div></header>
    <main class="main">${message()}${content}</main>`;
}

function stats(history) {
  return `<section class="score-summary" aria-label="Average performance"><span class="label">Average Vision score</span><div class="average-value">${num(history.average)}<span>/ 100</span></div><p class="fine">${history.average == null ? 'No scored sessions yet' : 'Clip performance · Daily average'}</p><div class="level-estimate"><div><span class="label">DUPR-scale equivalent</span><p class="fine">Uncalibrated estimate</p></div><strong>${history.dupr_equivalent == null ? '--' : Number(history.dupr_equivalent).toFixed(1)}</strong></div></section>`;
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
  return `<section class="section calendar-section"><div class="section-head"><h2>Daily activity</h2><select id="calendar-year" aria-label="Calendar year">${years.map(y=>`<option ${y===year?'selected':''}>${y}</option>`).join('')}</select></div>
    <div class="calendar-scroll"><div class="calendar-inner" style="--weeks:${count/7}"><div class="month-labels">${months}</div><div class="calendar-body"><div class="weekday-labels"><span>Mon</span><span>Wed</span><span>Fri</span></div><div class="heatmap">${cells}</div></div></div></div>
    <div class="calendar-meta"><div class="legend"><span>Lower score</span>${[1,2,3,4].map(l=>`<i class="day level-${l}"></i>`).join('')}<span>Higher score</span></div></div>
    ${state.day ? `<div class="selected-day"><strong>${dateLabel(state.day)}</strong><span>${selected ? `${selected.score == null ? 'No score' : `${num(selected.score)} Vision score`} &middot; ${reportCount(selected.clips)}` : 'No analysis'}</span>${button('Clear','clear-day','text-button')}</div>` : ''}
    </section>`;
}

function homeView() {
  const filtered = state.day ? state.videos.filter(v=>v.result?.score_date===state.day) : state.videos;
  const active = v=>['PROCESSING','PREPARING','QUEUED','ANALYZING','RETRY_WAIT','WAITING_FOR_PLAYER'].includes(v.status);
  const ordered = state.day ? filtered : [...filtered.filter(active),...filtered.filter(v=>!active(v))];
  const videos = state.allSessions || state.day ? ordered : ordered.slice(0,6);
  return `<div class="page-head overview-heading"><div><span class="label">Overview</span><h1>${esc(state.user.display_name)}</h1></div><button class="text-button connections-link" data-action="open-connections" aria-haspopup="dialog">Connections <span class="connection-count">${state.self.connections??0}</span></button></div>
    <div class="overview-summary">${stats(state.scores)}${sessionFocus()}</div>${calendar(state.scores)}<section class="section sessions-section"><div class="section-head"><h2>${state.day ? 'Sessions on this day' : state.allSessions?'All sessions':'Recent sessions'}</h2>${!state.day&&filtered.length>6?button(state.allSessions?'Show recent':'View all','toggle-sessions','text-button'):''}</div>${videos.length ? `<div class="session-list">${videos.map(sessionRow).join('')}</div>` : `<p class="empty">${state.day?'No sessions on this day.':'Your completed sessions will appear here.'}</p>`}</section>`;
}

function sessionFocus() {
  const latest=state.videos.find(v=>v.status==='COMPLETED'&&v.result?.kind==='video_review_v2');
  if(!latest)return '';
  const note=latest.notes?.note?.trim(), priority=latest.result.priority?.trim();
  if(!note&&latest.notes?.feedback==='inaccurate')return '';
  if(!note&&!priority)return '';
  return `<section class="session-focus"><span class="label">${note?'Your practice note':'Next session'}</span><p>${esc(note||priority)}</p><button class="text-button" data-video="${latest.id}">Review last session <span aria-hidden="true">&rarr;</span></button></section>`;
}

function sessionRow(video) {
  const r = video.status==='COMPLETED'?video.result:null, score = r?.performance?.score;
  return `<button class="session-row" data-video="${video.id}"><div><strong>${esc(video.original_filename)}</strong><span class="muted small">${dateLabel(video.created_at)} &middot; ${duration(video.duration_seconds)}</span></div><span class="session-status ${video.status==='FAILED'?'danger':''}">${score != null ? `<b>${num(score)}</b><small>Vision</small>` : esc(r ? 'View report' : video.status==='WAITING_FOR_PLAYER'?'Select player':video.stage)}</span><span aria-hidden="true">&rsaquo;</span></button>`;
}

function analyzeView() {
  return `<div class="page-head"><h1>Analyze</h1><span class="muted small">${state.user.remaining} of 5 uploads remaining</span></div>
    ${!state.workerRunning ? '<div class="alert">Analysis is temporarily unavailable. The local worker needs to restart.</div>' : ''}
    ${!state.analysisConfigured ? '<div class="alert">Video review is awaiting owner configuration.</div>' : ''}
    <section class="upload-zone"><h2>Gameplay video</h2><p class="muted">MP4, MOV &middot; Up to 3 minutes &middot; 100 MB max</p><input id="video-input" type="file" accept="video/mp4,video/quicktime,video/x-m4v,.mp4,.mov,.m4v" hidden><button class="primary" data-action="choose-video" ${state.busy || !state.workerRunning || !state.analysisConfigured || !state.user.remaining?'disabled':''}>Choose video</button>${state.busy?`<progress max="100" value="${state.uploadProgress}" aria-label="Upload progress"></progress><span id="upload-percent">${state.uploadProgress}%</span>`:''}</section>
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
    <label class="checkbox"><input id="save-evidence" type="checkbox" ${state.saveEvidence?'checked':''}><span>Keep up to three private replay clips and tracked frames with my report. The full upload is deleted.</span></label>
    <div class="action-row"><button class="primary" data-action="start-analysis" ${canAnalyze()?'':'disabled'}>Analyze clip</button>${button('Delete clip','delete-video','text-button danger')}</div>`;
  if (v.status==='COMPLETED') {
    const r=v.result;
    if (!['pose_review_v1','video_review_v1','video_review_v2'].includes(r.kind)) return heading+`<p class="empty">Archived report. Not included in scores.</p>${button('Delete report','delete-video','text-button danger')}`;
    return heading+reportView(r)+sessionNotes(v);
  }
  if (v.status==='FAILED') return heading+`<div class="failure"><h2>Analysis paused</h2><p>${esc(v.error)}</p><div class="action-row">${button('Try again','retry-video','primary')}${v.media_available?button('Choose player again','reselect-video','text-button'):''}${button('Delete clip','delete-video','text-button danger')}</div></div>`;
  if (v.status==='RETRY_WAIT') return heading+`<div class="failure"><h2>Waiting for video service</h2><p>Your clip is saved. Another attempt is scheduled${v.recovery?.next_attempt_at?' after '+esc(new Date(v.recovery.next_attempt_at).toLocaleTimeString([], {hour:'numeric',minute:'2-digit'})):''}.</p>${button('Cancel and delete clip','delete-video','text-button danger')}</div>`;
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
  const recordingIssue=r.recording_note&&/blur|unclear|occlu|obstruct|limit|miss|hidden|poor|low.resolution|shak|cut off|out.of.frame|not visible|cannot|can't|hard to|distant/i.test(r.recording_note);
  return `<section class="performance-summary"><div class="performance-number"><span class="label">Vision score</span><strong>${num(p.score)}</strong><span class="muted"> / 100</span></div><div><p>${esc(r.summary)}</p>${r.priority?`<p class="next-focus"><strong>Next session</strong> ${esc(r.priority)}</p>`:''}${p.score==null?`<span class="fine">${esc(p.note)}</span>`:''}</div></section>
    <dl class="performance-metrics">${p.components.map(c=>`<div><dt>${esc(c.name)} <span>${Math.round(c.weight*100)}%</span></dt><dd>${num(c.value)}<small>/ 100</small></dd><span class="fine">${c.observations} observations</span></div>`).join('')}</dl>
    <div class="clip-totals"><span>${p.observed_shots} assessed shots</span><span>${r.rallies.length} ${r.rallies.length===1?'rally':'rallies'}</span>${counts.map(([type,n])=>`<span>${n} ${esc(type)}${n===1?'':'s'}</span>`).join('')}</div>
    ${replayView(r)}
    ${recordingIssue?`<p class="recording-note">${esc(r.recording_note)}</p>`:''}
    <button class="text-button score-method-button" data-action="score-method">About this score</button>
    <dialog id="score-method-dialog" class="report-dialog" aria-labelledby="score-method-title"><div class="report-dialog-head"><h2 id="score-method-title">About this score</h2><button type="button" class="dialog-close" data-action="close-dialog" aria-label="Close">&times;</button></div><p>Vision score combines observed shot control (50%), balance (25%), and recovery (25%). Clear, purposeful placement scores highest; neutral play scores midway; visible errors score lowest. Unclear observations are excluded.</p><p>The score uses up to 40 visible contacts and is based on this clip. Saved scores stay fixed when the scoring method changes.</p></dialog>`;
}

function evidenceView(r) {
  const moments=r.evidence||[];
  if(!moments.length)return '';
  return `<div class="review-moments"><h3>Key moments</h3><div class="evidence-grid">${moments.map(m=>`<button class="evidence-item" data-moment="${Number(m.number)}" aria-pressed="${viewer?.source!=='original'&&viewer?.moment===m.number}" title="Open ${esc(m.label)} at ${timestamp(m.timestamp)}"><img loading="lazy" src="/api/videos/${encodeURIComponent(state.selectedId)}/evidence/${Number(m.number)}" alt="Tracked ${esc(m.label)} frame"><span><strong>${esc(capital(m.label))}</strong><time>${timestamp(m.timestamp)}</time><small>${m.clip?'Replay':'Tracked frame'}</small></span></button>`).join('')}</div></div>`;
}

function reviewViewer(r) {
  if(viewer?.id!==state.selectedId) {
    const moment=(r.evidence||[]).find(m=>m.clip)||(r.evidence||[])[0];
    viewer={id:state.selectedId,source:moment?'moment':'original',moment:moment?.number,tracked:true,speed:1,loop:true,filter:'all',focus:moment?.timestamp??null};
  }
  return viewer;
}

function reviewMedia(r) {
  const v=reviewViewer(r);
  if(v.source==='original'&&replay?.id===state.selectedId)return {url:replay.url,video:true,offset:0,end:Infinity,fps:30};
  const moment=(r.evidence||[]).find(m=>m.number===v.moment);
  if(v.source==='moment'&&moment) {
    const url=`/api/videos/${encodeURIComponent(state.selectedId)}/evidence/${moment.number}`;
    return moment.clip?{url:`${url}/clip`,video:true,offset:moment.clip.start,end:moment.clip.end,fps:moment.clip.fps||30}:
      {url,video:false,offset:moment.timestamp,end:moment.timestamp};
  }
  return null;
}

function shotAssessment(shot) {
  if(!shot)return '';
  if(shot.confidence==='low')return '<p class="fine">This moment is too unclear for a reliable assessment.</p>';
  const control={controlled:'Purposeful placement',neutral:'Neutral play',error:'Visible error',unknown:'Not assessed'};
  return `<dl class="moment-assessment"><div><dt>Shot control</dt><dd>${control[shot.control]||'Not assessed'}</dd></div><div><dt>Balance</dt><dd>${shot.balanced==null?'Not assessed':shot.balanced?'Stable':'Off balance'}</dd></div><div><dt>Recovery</dt><dd>${shot.recovered==null?'Not assessed':shot.recovered?'Ready':'Late'}</dd></div></dl>`;
}

function replayView(r) {
  const v=reviewViewer(r), media=reviewMedia(r), attached=replay?.id===state.selectedId;
  const canTrack=media?.video&&r.player_track?.samples?.length;
  const shots=r.shots||[], types=[...new Set(shots.map(s=>s.shot_type))];
  const filtered=shots.filter(s=>v.filter==='all'||s.shot_type===v.filter);
  const selected=shots.find(s=>v.focus!=null&&Math.abs(s.timestamp-v.focus)<.4);
  return `<section class="section replay-section"><div class="section-head"><h2>Video review</h2><div class="replay-tools"><input type="file" id="replay-input" accept="video/*,.mp4,.mov" hidden>${attached&&v.source!=='original'?'<button class="text-button" data-action="full-replay">Full video</button>':''}<button class="text-button" data-action="open-replay">${icon('upload')}${attached?'Change full video':'Open full video'}</button></div></div>
    <div class="review-toolbar">${canTrack?`<div class="review-modes" role="group" aria-label="Video overlay"><button data-overlay="tracked" aria-pressed="${v.tracked}">Tracked</button><button data-overlay="original" aria-pressed="${!v.tracked}">Original</button></div>`:''}${media?.video?`<div class="frame-controls"><button class="icon-button" data-frame-step="-1" aria-label="Previous frame" title="Previous frame">${icon('arrow-left')}</button><button class="icon-button next-frame" data-frame-step="1" aria-label="Next frame" title="Next frame">${icon('arrow-left')}</button></div><label class="speed-label">Speed <select id="replay-speed">${[.25,.5,.75,1].map(s=>`<option value="${s}" ${s===v.speed?'selected':''}>${s}&times;</option>`).join('')}</select></label>${v.source==='moment'?`<label class="review-loop"><input id="review-loop" type="checkbox" ${v.loop?'checked':''}> Loop</label>`:''}`:''}</div>
    <div class="review-workspace"><div class="review-main"><div class="review-stage">${media?media.video?`<div class="review-media"><video id="replay-video" data-video-id="${esc(state.selectedId)}" src="${esc(media.url)}" controls controlslist="nofullscreen nodownload noremoteplayback" disablepictureinpicture playsinline preload="auto" aria-label="Gameplay review"></video><canvas id="tracking-overlay" aria-hidden="true"></canvas></div>`:`<img class="tracked-still" src="${esc(media.url)}" alt="Selected player highlighted in the saved report frame">`:'<div class="review-empty">Open your video to review this session.</div>'}</div>
    <div class="review-context"><span id="tracking-status">${media?.video?canTrack?'Selected player':'Original video':media?'Tracked frame':''}</span><time id="review-clock">${media?timestamp(media.offset):''}</time>${media?.video?'<button class="text-button" data-action="review-fullscreen" title="Expand video">Expand</button>':''}</div>
    <div id="moment-assessment">${shotAssessment(selected)}</div><p id="replay-status" class="fine" role="status"></p>${evidenceView(r)}</div>
    <aside class="review-index"><label for="shot-filter">Shots</label><select id="shot-filter"><option value="all">All shots (${shots.length})</option>${types.map(type=>`<option value="${esc(type)}" ${v.filter===type?'selected':''}>${esc(capital(type))} (${shots.filter(s=>s.shot_type===type).length})</option>`).join('')}</select><ol class="event-list review-events">${filtered.map(s=>`<li class="${selected===s?'selected':''}"><button class="shot-event" data-seek="${s.timestamp}"><time>${timestamp(s.timestamp)}</time><span><strong>${esc(capital(s.shot_type))}</strong><small>${s.confidence==='low'?'Uncertain observation':s.control==='error'?'Visible error':s.recovered===false?'Late recovery':s.balanced===false?'Off balance':'Review shot'}</small></span></button></li>`).join('')}</ol>${!filtered.length?'<p class="fine">No shots in this view.</p>':''}
    ${(r.rallies||[]).length?`<div class="rally-jumps">${r.rallies.map((r,i)=>`<button class="text-button" data-seek="${r.start}" title="Review rally ${i+1}">Rally ${i+1} <time>${timestamp(r.start)} &ndash; ${timestamp(r.end)}</time></button>`).join('')}</div>`:''}</aside></div></section>`;
}

function sessionNotes(v) {
  const notes=noteDrafts.get(v.id)||v.notes||{note:'',feedback:null};
  const editing=noteOpen.has(v.id);
  return `<section class="section session-notes"><div class="section-head"><h2>My notes</h2>${!editing?`<button class="text-button" data-action="edit-note">${notes.note?'Edit':'Add a note'}</button>`:''}</div>
    ${editing?`<div class="note-editor"><label for="session-note" class="sr-only">My note</label><textarea id="session-note" rows="3" maxlength="1000" placeholder="What would you practice next?">${esc(notes.note)}</textarea><div class="notes-actions"><span id="notes-status" class="fine" role="status">${noteDrafts.has(v.id)?'Saving changes':'Saved'}</span><button class="text-button" data-action="save-note">Save now</button><button class="text-button" data-action="close-note">Done</button></div></div>`:notes.note?`<p class="saved-note">${esc(notes.note)}</p>`:''}
    <div class="report-feedback-line"><button class="text-button" data-action="report-issue">${v.issue?'Edit reported issue':'Report an issue'}</button>${v.issue?'<span class="fine">Issue recorded</span>':''}</div>
    <dialog id="issue-dialog" class="report-dialog" aria-labelledby="issue-title"><div class="report-dialog-head"><h2 id="issue-title">Report an issue</h2><button type="button" class="dialog-close" data-action="close-dialog" aria-label="Close">&times;</button></div><form id="issue-form"><label for="issue-reason">What needs correction?</label><select id="issue-reason" name="reason" required><option value="player" ${v.issue?.reason==='player'?'selected':''}>Wrong player</option><option value="shot" ${v.issue?.reason==='shot'?'selected':''}>Shot or assessment</option><option value="missed" ${v.issue?.reason==='missed'?'selected':''}>Missed moment</option><option value="other" ${v.issue?.reason==='other'?'selected':''}>Something else</option></select><label for="issue-time">Time in video (optional, seconds)</label><input id="issue-time" name="timestamp_seconds" type="number" min="0" max="${v.duration_seconds}" step="0.1" value="${v.issue?.timestamp_seconds??''}"><label for="issue-detail">Details (optional)</label><textarea id="issue-detail" name="detail" maxlength="500" rows="3">${esc(v.issue?.detail||'')}</textarea><div class="dialog-actions"><button class="primary" type="submit">Send feedback</button></div></form></dialog></section>`;
}

function clearReplay() {
  replayRequest++;
  if(replay)URL.revokeObjectURL(replay.url);
  replay=null;pendingSeek=null;
  viewer=null;
}

function useReplay(file, id, verified) {
  clearReplay();
  replay={id,url:URL.createObjectURL(file),verified,speed:1};
}

async function attachReplay(file) {
  const id=state.selectedId, user=state.user?.id, token=++replayRequest;
  const v=state.videos.find(v=>v.id===id), status=document.getElementById('replay-status');
  if(!v)return;
  try {
    if(file.size>100_000_000)throw Error('Video exceeds 100 MB.');
    if(status)status.textContent='Checking video...';
    if(v.sha256) {
      if(!crypto.subtle)throw Error('Secure playback verification is unavailable in this browser.');
      const digest=await crypto.subtle.digest('SHA-256',await file.arrayBuffer());
      const hash=Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('');
      if(hash!==v.sha256)throw Error('This file does not match the analyzed clip. Choose the original video.');
    }
    if(token!==replayRequest||state.selectedId!==id||state.user?.id!==user)return;
    const seek=pendingSeek;
    useReplay(file,id,!!v.sha256);pendingSeek=seek;
    reviewViewer(v.result).source='original';
    render();
  } catch(error) {if(token===replayRequest&&state.selectedId===id&&status)status.textContent=error.message;}
}

function seekReplay(time) {
  const r=state.videos.find(v=>v.id===state.selectedId)?.result;
  if(!r)return;
  const v=reviewViewer(r), media=reviewMedia(r);
  v.focus=time;
  if(!media?.video||time<media.offset||time>=media.end) {
    const moment=(r.evidence||[]).find(m=>m.clip&&time>=m.clip.start&&time<m.clip.end);
    if(moment){v.source='moment';v.moment=moment.number;pendingSeek=time;render();return;}
    if(replay?.id===state.selectedId){v.source='original';pendingSeek=time;render();return;}
    const still=(r.evidence||[]).find(m=>Math.abs(m.timestamp-time)<.4);
    if(still){v.source='moment';v.moment=still.number;pendingSeek=null;render();return;}
    pendingSeek=time;document.getElementById('replay-input')?.click();return;
  }
  const video=document.getElementById('replay-video');
  if(!video)return;
  if(video.readyState<1){pendingSeek=time;return;}
  video.currentTime=Math.max(0,Math.min(time-media.offset,video.duration));
  const selected=(r.shots||[]).find(s=>Math.abs(s.timestamp-time)<.4);
  document.getElementById('moment-assessment').innerHTML=shotAssessment(selected);
  document.querySelectorAll('.shot-event').forEach(b=>b.closest('li').classList.toggle('selected',Math.abs(Number(b.dataset.seek)-time)<.4));
  video.scrollIntoView({block:'nearest'});
  video.play().catch(()=>{document.getElementById('replay-status').textContent='Press play to review this moment.';});
}

function trackingBox(samples, time, maxGap=.3) {
  if(!samples?.length)return null;
  let low=0,high=samples.length;
  while(low<high){const middle=(low+high)>>1;if(samples[middle][0]<time)low=middle+1;else high=middle;}
  const after=samples[low],before=samples[low-1];
  if(after&&Math.abs(after[0]-time)<.001)return after.slice(1);
  if(!before)return after&&after[0]-time<=.07?after.slice(1):null;
  if(!after)return time-before[0]<=.07?before.slice(1):null;
  const gap=after[0]-before[0];
  if(gap<=0||gap>maxGap)return null;
  const fraction=(time-before[0])/gap;
  return before.slice(1).map((n,i)=>n+(after[i+1]-n)*fraction);
}

function setupReview(video) {
  const r=state.videos.find(v=>v.id===state.selectedId)?.result;
  if(!r)return;
  const v=reviewViewer(r),media=reviewMedia(r),frame=video.closest('.review-media');
  const canvas=document.getElementById('tracking-overlay'),ctx=canvas.getContext('2d');
  const paint=()=>{
    if(!canvas.isConnected)return;
    const bounds=frame.getBoundingClientRect(),ratio=window.devicePixelRatio||1;
    const width=Math.round(bounds.width*ratio),height=Math.round(bounds.height*ratio);
    if(canvas.width!==width||canvas.height!==height){canvas.width=width;canvas.height=height;}
    ctx.clearRect(0,0,width,height);
    const time=media.offset+video.currentTime, track=r.player_track;
    const box=v.tracked?trackingBox(track?.samples,time,track?.max_gap||.3):null;
    const status=document.getElementById('tracking-status'),clock=document.getElementById('review-clock');
    if(clock)clock.textContent=timestamp(time);
    if(status){status.textContent=v.tracked&&track?.samples?.length?(box?'Selected player':'Tracking gap'):'Original video';status.classList.toggle('tracking-visible',!!box);}
    canvas.dataset.tracked=String(!!box);
    if(!box)return;
    const [x1,y1,x2,y2]=box.map((n,i)=>n*(i%2?height:width));
    const corner=Math.min((x2-x1)/3,(y2-y1)/4,18*ratio);
    const brackets=()=>{
      ctx.beginPath();
      for(const [x,y,dx,dy] of [[x1,y1,1,1],[x2,y1,-1,1],[x1,y2,1,-1],[x2,y2,-1,-1]]){
        ctx.moveTo(x+dx*corner,y);ctx.lineTo(x,y);ctx.lineTo(x,y+dy*corner);
      }
      ctx.stroke();
    };
    ctx.lineWidth=5*ratio;ctx.strokeStyle='rgba(0,0,0,.65)';brackets();
    ctx.lineWidth=2.5*ratio;ctx.strokeStyle='#78efb1';brackets();
    ctx.fillStyle='rgba(120,239,177,.06)';ctx.fillRect(x1,y1,x2-x1,y2-y1);
  };
  const animate=()=>{paint();if(!video.paused&&video.isConnected)overlayAnimation=requestAnimationFrame(animate);};
  const ready=()=>{
    if(video.videoWidth&&video.videoHeight){const ratio=video.videoWidth/video.videoHeight;frame.style.aspectRatio=String(ratio);frame.style.width=`${480*ratio}px`;frame.style.setProperty('--video-ratio',ratio);}
    paint();
    if(pendingSeek!=null){const time=pendingSeek;pendingSeek=null;seekReplay(time);}
  };
  video.playbackRate=v.speed;video.loop=v.source==='moment'&&v.loop;
  video.onloadedmetadata=ready;video.onloadeddata=paint;video.ontimeupdate=paint;video.onseeked=paint;video.onpause=paint;
  video.onplay=()=>{cancelAnimationFrame(overlayAnimation);animate();};
  video.onerror=()=>{const status=document.getElementById('replay-status');if(status)status.textContent='This replay could not be loaded. You can open the full video to continue.';};
  overlayResize=new ResizeObserver(paint);overlayResize.observe(frame);
  if(video.readyState>=1)ready();
  if(!video.paused)animate();
}

function render() {
  cancelAnimationFrame(overlayAnimation);overlayResize?.disconnect();
  const previousVideo=document.getElementById('replay-video');
  const previousScroll=document.querySelector('.calendar-scroll')?.scrollLeft;
  document.title=state.user?`${({home:'Overview',analyze:'Analyze',players:'Players',profile:'Account'})[state.page]} | DUPRVision`:'DUPRVision';
  app.innerHTML=state.user?shell(state.selectedId?detailView():({home:homeView,analyze:analyzeView,players:playersView,profile:profileView}[state.page])()):authView();
  let video=document.getElementById('replay-video');
  if(video&&previousVideo?.getAttribute('src')===video.getAttribute('src')) {video.replaceWith(previousVideo);video=previousVideo;}
  if(video)setupReview(video);
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
    if(target.dataset.moment!==undefined) {
      const r=state.videos.find(v=>v.id===state.selectedId)?.result;
      const moment=r?.evidence?.find(m=>m.number===Number(target.dataset.moment));
      if(!moment)return;
      Object.assign(reviewViewer(r),{source:'moment',moment:moment.number,focus:moment.timestamp});pendingSeek=null;
      render();
      const video=document.getElementById('replay-video');
      if(video){if(video.readyState>=1)video.currentTime=0;video.play().catch(()=>{});}
      document.querySelector('.review-stage')?.scrollIntoView({block:'nearest'});return;
    }
    if(target.dataset.overlay) {
      viewer.tracked=target.dataset.overlay==='tracked';
      document.querySelectorAll('[data-overlay]').forEach(b=>b.setAttribute('aria-pressed',String((b.dataset.overlay==='tracked')===viewer.tracked)));
      document.getElementById('replay-video')?.dispatchEvent(new Event('timeupdate'));return;
    }
    if(target.dataset.frameStep) {
      const video=document.getElementById('replay-video');
      if(video?.readyState>=1){video.pause();video.currentTime=Math.max(0,Math.min(video.duration,video.currentTime+Number(target.dataset.frameStep)/30));}return;
    }
    if(target.dataset.seek!==undefined){seekReplay(Number(target.dataset.seek));return;}
    if (target.dataset.page) {
      pendingSeek=null;replayRequest++;
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
    if (target.dataset.video) { pendingSeek=null;replayRequest++;Object.assign(state,{selectedId:target.dataset.video,preview:1,point:null,consent:false,externalConsent:false});render();window.scrollTo(0,0);return; }
    if (target.dataset.preview) {state.preview=Number(target.dataset.preview);state.point=null;render();return;}
    if (target.id==='preview-image') {const rect=target.getBoundingClientRect();state.point={x:(event.clientX-rect.left)/rect.width,y:(event.clientY-rect.top)/rect.height};render();return;}
    switch(target.dataset.action) {
      case 'full-replay':viewer.source='original';pendingSeek=null;render();return;
      case 'review-fullscreen':
        if(document.fullscreenElement)await document.exitFullscreen();
        else await document.querySelector('.review-stage')?.requestFullscreen?.();return;
      case 'score-method':document.getElementById('score-method-dialog').showModal();return;
      case 'report-issue':document.getElementById('issue-dialog').showModal();return;
      case 'close-dialog':target.closest('dialog').close();return;
      case 'edit-note':noteOpen.add(state.selectedId);render();document.getElementById('session-note')?.focus();return;
      case 'save-note':await persistNote(state.selectedId);return;
      case 'close-note':
        clearTimeout(noteTimers.get(state.selectedId));
        await persistNote(state.selectedId);
        if(noteDrafts.has(state.selectedId))return;
        noteOpen.delete(state.selectedId);render();return;
      case 'open-connections':openConnections();return;
      case 'toggle-sessions':state.allSessions=!state.allSessions;break;
      case 'open-replay':pendingSeek=null;document.getElementById('replay-input').click();return;
      case 'auth-toggle':state.authMode=state.authMode==='login'?'register':'login';break;
      case 'choose-video':document.getElementById('video-input').click();return;
      case 'clear-day':state.day=null;break;
      case 'back-clips':pendingSeek=null;replayRequest++;state.selectedId=null;state.page='home';break;
      case 'back-players':state.player=null;state.day=null;state.year=null;await loadPlayers();break;
      case 'next-players':state.offset+=30;await loadPlayers();break;
      case 'previous-players':state.offset=Math.max(0,state.offset-30);await loadPlayers();break;
      case 'logout':await api('/logout',{method:'POST'});state.page='home';await refresh();return;
      case 'start-analysis': {
        const v=state.videos.find(v=>v.id===state.selectedId);target.disabled=true;
        await api(`/videos/${v.id}/select`,jsonRequest('POST',{timestamp_seconds:v.duration_seconds*[.1,.4,.7][state.preview-1],...state.point,consent:state.consent,external_consent:state.externalConsent,save_evidence:state.saveEvidence,save_clips:state.saveEvidence}));
        await refresh();return;
      }
      case 'retry-video':
        await api(`/videos/${state.selectedId}/retry`,{method:'POST'});state.point=null;state.consent=false;state.externalConsent=false;await refresh();return;
      case 'reselect-video':
        await api(`/videos/${state.selectedId}/reselect`,{method:'POST'});state.point=null;state.consent=false;state.externalConsent=false;await refresh();return;
      case 'delete-video':
        if(!confirm('Permanently delete this clip and its result? The daily score will be recalculated. Upload allowance will not reset.'))return;
        await api(`/videos/${state.selectedId}`,{method:'DELETE'});noteDrafts.delete(state.selectedId);noteOpen.delete(state.selectedId);clearTimeout(noteTimers.get(state.selectedId));if(replay?.id===state.selectedId)clearReplay();state.selectedId=null;state.page='home';await refresh();return;
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
    if(form.id==='issue-form') {
      const issue=await api(`/videos/${state.selectedId}/issue`,jsonRequest('PUT',{
        reason:data.get('reason'), detail:data.get('detail'),
        timestamp_seconds:data.get('timestamp_seconds')===''?null:Number(data.get('timestamp_seconds'))
      }));
      const v=state.videos.find(v=>v.id===state.selectedId);if(v)v.issue=issue;
      form.closest('dialog').close();render();
    }
  } catch(error) {state.error=error.message;render();}
});

app.addEventListener('change',event=>{
  const target=event.target;
  if(target.id==='calendar-year') {state.year=Number(target.value);state.day=null;render();}
  if(target.id==='consent') {state.consent=target.checked;document.querySelector('[data-action="start-analysis"]').disabled=!canAnalyze();}
  if(target.id==='external-consent') {state.externalConsent=target.checked;document.querySelector('[data-action="start-analysis"]').disabled=!canAnalyze();}
  if(target.id==='video-input'&&target.files[0]) upload(target.files[0]);
  if(target.id==='replay-input'&&target.files[0])attachReplay(target.files[0]);
  if(target.id==='replay-speed'&&viewer){viewer.speed=Number(target.value);document.getElementById('replay-video').playbackRate=viewer.speed;}
  if(target.id==='review-loop'&&viewer){viewer.loop=target.checked;document.getElementById('replay-video').loop=viewer.loop;}
  if(target.id==='shot-filter'&&viewer){viewer.filter=target.value;render();}
  if(target.id==='save-evidence')state.saveEvidence=target.checked;
});

function saveNoteDraft() {
  const id=state.selectedId, v=state.videos.find(v=>v.id===id);
  noteDrafts.set(id,{note:document.getElementById('session-note').value,feedback:v?.notes?.feedback||null});
  document.getElementById('notes-status').textContent='Saving...';
  scheduleNoteSave(id,750);
}

function scheduleNoteSave(id, delay) {
  clearTimeout(noteTimers.get(id));
  noteTimers.set(id,setTimeout(()=>persistNote(id),delay));
}

async function persistNote(id) {
  if(noteRequests.has(id))return noteRequests.get(id);
  const draft=noteDrafts.get(id);
  if(!draft)return;
  const request=(async()=>{
    try {
      const saved=await api(`/videos/${id}/notes`,jsonRequest('PUT',draft));
      const v=state.videos.find(v=>v.id===id);if(v)v.notes=saved;
      if(noteDrafts.get(id)===draft){noteDrafts.delete(id);if(state.selectedId===id){const status=document.getElementById('notes-status');if(status)status.textContent='Saved';}}
    } catch(error) {
      if(state.selectedId===id){const status=document.getElementById('notes-status');if(status)status.textContent='Could not save. Try Save now.';}
    }
  })();
  noteRequests.set(id,request);
  await request;
  noteRequests.delete(id);
  if(noteDrafts.has(id)&&noteDrafts.get(id)!==draft)scheduleNoteSave(id,100);
}

app.addEventListener('input',event=>{
  if(event.target.id==='session-note'){saveNoteDraft();return;}
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
  xhr.onload=async()=>{state.busy=false;try{const result=JSON.parse(xhr.responseText);if(xhr.status>=400)throw new Error(result.detail||'Upload failed');useReplay(file,result.id,true);state.selectedId=result.id;state.preview=1;state.point=null;state.consent=false;state.externalConsent=false;await refresh();}catch(error){state.error=error.message;render();}};
  xhr.onerror=()=>{state.busy=false;state.error='Connection lost during upload.';render();};xhr.send(file);
}

let polling=false;
window.addEventListener('resize',()=>{
  const calendar=document.querySelector('.calendar-scroll');
  const day=document.querySelector(`[data-day="${state.day||state.scores?.today}"]`);
  if(calendar&&day&&calendar.scrollLeft===0)calendar.scrollLeft=Math.max(0,day.getBoundingClientRect().left-calendar.getBoundingClientRect().left-calendar.clientWidth+30);
});
setInterval(async()=>{
  if(polling||!state.user||state.busy||!state.videos.some(v=>['PROCESSING','PREPARING','QUEUED','ANALYZING','RETRY_WAIT'].includes(v.status)))return;
  polling=true;
  try {const active=document.activeElement;const editing=active&&['INPUT','SELECT','TEXTAREA'].includes(active.tagName);const viewingReport=state.videos.some(v=>v.id===state.selectedId&&v.status==='COMPLETED');await refresh(!editing&&!viewingReport&&!connectionDialog&&state.page!=='profile');}
  finally {polling=false;}
},3000);
refresh();
