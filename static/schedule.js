const playKinds={open_play:'Open play',dupr_match:'DUPR match',practice:'Practice',lesson:'Lesson',league:'League',tournament:'Tournament',other:'Other'};
const playing={month:new Date(new Date().getFullYear(),new Date().getMonth(),1),day:null,layout:'agenda',view:'all',events:[],upcoming:[],hasMore:false};
let planDialog=null, scheduleRequest=0;
const localDay=date=>`${date.getFullYear()}-${String(date.getMonth()+1).padStart(2,'0')}-${String(date.getDate()).padStart(2,'0')}`;
const localInput=date=>`${localDay(date)}T${String(date.getHours()).padStart(2,'0')}:${String(date.getMinutes()).padStart(2,'0')}`;
const playZone=()=>Intl.DateTimeFormat().resolvedOptions().timeZone;
const playZoneLabel=()=>new Intl.DateTimeFormat(undefined,{timeZoneName:'longGeneric'}).formatToParts(new Date()).find(part=>part.type==='timeZoneName')?.value||'Local time';
const playTime=value=>new Date(value).toLocaleTimeString(undefined,{hour:'numeric',minute:'2-digit'});
const playDate=value=>new Date(value).toLocaleDateString(undefined,{weekday:'short',month:'short',day:'numeric'});
const playRange=e=>`${playTime(e.starts_at)} – ${localDay(new Date(e.starts_at))===localDay(new Date(e.ends_at))?'':playDate(e.ends_at)+' '}${playTime(e.ends_at)}`;

async function loadSchedule() {
  const request=++scheduleRequest,month=playing.month,userId=state.user?.id;
  const start=new Date(month.getFullYear(),month.getMonth(),1),end=new Date(month.getFullYear(),month.getMonth()+1,1);
  const result=await api(`/schedule?${new URLSearchParams({start:start.toISOString(),end:end.toISOString(),view:state.page==='home'?'all':playing.view})}`);
  if(request===scheduleRequest&&userId===state.user?.id)Object.assign(playing,{events:result.events,hasMore:result.has_more});
}

async function loadUpcoming() {
  const userId=state.user?.id,start=new Date(),end=new Date(start.getTime()+30*86400000);
  const result=await api(`/schedule?${new URLSearchParams({start:start.toISOString(),end:end.toISOString()})}`);
  if(userId===state.user?.id)playing.upcoming=result.events.filter(event=>event.competition_phase!=='finished');
}

function planRow(e,compact=false) {
  if(e.competition_title)return `<article class="plan-row"><div class="plan-date"><span>${new Date(e.starts_at).toLocaleDateString(undefined,{month:'short'})}</span><strong>${new Date(e.starts_at).getDate()}</strong></div><div class="plan-info"><div class="plan-caption">Round robin · ${competitionStatus[e.competition_phase]}</div><h3>${esc(e.competition_title)}</h3><p>${esc(e.location)} · ${esc(playRange(e))}</p><div class="plan-links">${e.competition_access?`<button class="text-button" data-comp-open="${e.id}">Open event</button>`:''}<a href="${esc(e.maps_url)}" target="_blank" rel="noopener noreferrer">Open map</a></div></div></article>`;
  return `<article class="plan-row"><div class="plan-date"><span>${new Date(e.starts_at).toLocaleDateString(undefined,{month:'short'})}</span><strong>${new Date(e.starts_at).getDate()}</strong></div><div class="plan-info"><div class="plan-caption"><span>${esc(playKinds[e.kind])}</span>${e.is_owner?`<span>${e.visibility==='private'?'Only me':'Followers'}</span>`:''}</div><h3>${esc(e.location)}</h3><p><time datetime="${esc(e.starts_at)}">${esc(playRange(e))}</time> <span>· ${e.is_owner?'You':esc(e.display_name)}</span></p>${!compact&&e.address?`<p class="muted">${esc(e.address)}</p>`:''}${!compact&&e.note?`<p class="plan-note">${esc(e.note)}</p>`:''}<div class="plan-links"><a href="${esc(e.maps_url)}" target="_blank" rel="noopener noreferrer">Open map</a>${e.is_owner?`<button class="text-button" data-plan-edit="${e.id}">Edit</button>`:''}</div></div></article>`;
}

function upcomingView(events) {
  if(!events.length)return '';
  return `<section class="section upcoming-playing"><div class="section-head"><h2>Upcoming play</h2></div>${events.slice(0,3).map(e=>planRow(e,true)).join('')}</section>`;
}

function scheduleView() {
  const header=`<div class="workspace-toolbar"><div class="view-tabs" role="group" aria-label="Play views">${[['agenda','Upcoming'],['calendar','Calendar'],['history','Your events']].map(([key,label])=>`<button data-play-layout="${key}" aria-pressed="${playing.layout===key}">${label}</button>`).join('')}</div><button class="primary toolbar-action" data-workspace-new>New event</button></div>`;
  if(playing.layout==='history')return header+`<section class="section"><h2>Round robins</h2>${competition.list.length?competition.list.map(event=>`<button class="competition-list-row" data-comp-open="${esc(event.id)}"><span><strong>${esc(event.title)}</strong><small>${esc(playDate(event.starts_at))} · ${esc(event.location)}</small></span><span>${competitionStatus[event.phase]} &rsaquo;</span></button>`).join(''):'<p class="empty">No round robins yet.</p>'}</section>`;
  if(playing.layout==='agenda')return header+`<section class="section"><div class="section-head"><h2>Next 30 days</h2><span class="fine">${esc(playZoneLabel())}</span></div>${playing.upcoming.length?playing.upcoming.map(e=>planRow(e)).join(''):'<div class="playing-empty"><h2>Room for a game</h2><p>No upcoming events.</p></div>'}</section>`;
  return header+scheduleCalendarView();
}

function scheduleCalendarView() {
  const month=playing.month, today=localDay(new Date());
  const first=new Date(month.getFullYear(),month.getMonth(),1),offset=(first.getDay()+6)%7;
  const days=new Date(month.getFullYear(),month.getMonth()+1,0).getDate(),count=Math.ceil((offset+days)/7)*7;
  const cells=Array.from({length:count},(_,i)=>{
    const date=new Date(month.getFullYear(),month.getMonth(),i-offset+1),key=localDay(date),next=new Date(date);next.setDate(next.getDate()+1);
    const events=playing.events.filter(e=>new Date(e.starts_at)<next&&new Date(e.ends_at)>date);
    return `<button class="play-day ${date.getMonth()!==month.getMonth()?'outside':''} ${key===today?'today':''}" data-play-day="${key}" aria-pressed="${playing.day===key}" ${key===today?'aria-current="date"':''} aria-label="${esc(playDate(date))}, ${events.length} events"><span>${date.getDate()}</span><span class="play-dots">${events.length?'<i></i>':''}</span></button>`;
  }).join('');
  let events=playing.events;
  if(playing.day){const start=new Date(playing.day+'T00:00:00'),end=new Date(start);end.setDate(end.getDate()+1);events=events.filter(e=>new Date(e.starts_at)<end&&new Date(e.ends_at)>start);}
  return `<div class="playing-filters" role="group" aria-label="Events to show">${[['all','All'],['mine','Mine'],['following','Following']].map(([key,label])=>`<button data-play-filter="${key}" aria-pressed="${playing.view===key}">${label}</button>`).join('')}</div>
    <div class="playing-layout"><section class="play-month"><div class="play-month-heading"><h2>${month.toLocaleDateString(undefined,{month:'long',year:'numeric'})}</h2><div class="month-controls"><button class="month-today" data-play-today>Today</button><button class="icon-button" data-play-month="-1" aria-label="Previous month" title="Previous month">${icon('arrow-left')}</button><button class="icon-button next-frame" data-play-month="1" aria-label="Next month" title="Next month">${icon('arrow-left')}</button></div></div><div class="play-weekdays" aria-hidden="true">${['M','T','W','T','F','S','S'].map(d=>`<span>${d}</span>`).join('')}</div><div class="play-grid">${cells}</div></section><section class="play-agenda"><div class="section-head"><h2>${playing.day?playDate(playing.day+'T12:00:00'):'This month'}</h2>${playing.day?'<button class="text-button" data-play-clear>All dates</button>':''}</div>${events.length?events.map(e=>planRow(e)).join(''):`<div class="playing-empty"><p>${playing.view==='following'?'No events shared yet.':'Nothing scheduled.'}</p></div>`}${playing.hasMore?'<p class="fine">Showing the first 500 events. Filter by Mine or Following to see more.</p>':''}</section></div>`;
}

function closePlan() {if(planDialog){planDialog.placePicker?.destroy();planDialog.close();planDialog.remove();planDialog=null;}}

function openPlan(event=null) {
  closePlan();
  const anchor=state.page==='schedule'?playing.day:null;
  const date=new Date(anchor?anchor+'T18:00:00':Date.now()+3600000);date.setSeconds(0,0);
  if(!anchor)date.setMinutes(0);
  const start=event?new Date(event.starts_at):date,end=event?new Date(event.ends_at):new Date(start.getTime()+90*60000);
  const dialog=document.createElement('dialog');planDialog=dialog;
  dialog.className='plan-dialog';dialog.setAttribute('aria-labelledby','plan-title');
  const visibility=event?.visibility||(state.user.discoverable?'followers':'private');
  dialog.innerHTML=`<form id="plan-form"><header class="plan-editor-heading"><button type="button" data-plan-close>Cancel</button><h2 id="plan-title">${event?'Edit event':'New event'}</h2><button type="submit">${event?'Save':'Add'}</button></header><div class="plan-editor-body">
    <fieldset class="plan-fields"><legend class="sr-only">Place and session</legend><div id="place-picker"></div><div class="plan-field"><label for="plan-kind">Session</label><select id="plan-kind" name="kind">${Object.entries(playKinds).map(([key,label])=>`<option value="${key}" ${event?.kind===key?'selected':''}>${label}</option>`).join('')}</select></div></fieldset>
    <fieldset class="plan-fields"><legend class="sr-only">Date and time</legend><div class="plan-field plan-time-field"><label for="plan-start">Starts</label><input id="plan-start" type="datetime-local" name="start" required value="${localInput(start)}"></div><div class="plan-field plan-time-field"><label for="plan-end">Ends</label><input id="plan-end" type="datetime-local" name="end" required value="${localInput(end)}"></div><div class="plan-zone" title="Times are shown in your local time zone">${esc(playZoneLabel())}</div></fieldset>
    <fieldset class="plan-fields"><legend class="sr-only">Sharing and notes</legend><div class="plan-sharing"><span>Visibility${!state.user.discoverable?'<small title="Enable profile visibility in Account to share events with followers.">Private profile</small>':''}</span><div class="plan-audience" role="group" aria-label="Event visibility">${[['private','Only me'],['followers','Followers']].map(([value,label])=>`<label><input type="radio" name="visibility" value="${value}" ${visibility===value?'checked':''}><span>${label}</span></label>`).join('')}</div></div><div class="plan-field plan-note-field"><label for="plan-note">Note</label><textarea id="plan-note" name="note" maxlength="300" rows="2">${esc(event?.note||'')}</textarea></div></fieldset>
    <p class="plan-error" role="alert"></p>${event?`<button type="button" class="plan-delete" data-plan-delete>${icon('trash-2')}Delete event</button>`:''}</div></form>`;
  dialog.querySelector('[data-plan-close]').onclick=closePlan;
  dialog.addEventListener('cancel',e=>{e.preventDefault();closePlan();});
  dialog.querySelector('[data-plan-delete]')?.addEventListener('click',async()=>{
    if(!confirm('Delete this event? It will also be removed from your followers’ calendars.'))return;
    const button=dialog.querySelector('[data-plan-delete]');button.disabled=true;
    try{await api(`/schedule/${event.id}`,{method:'DELETE'});closePlan();await reloadPlans();}catch(error){dialog.querySelector('.plan-error').textContent=error.message;button.disabled=false;}
  });
  dialog.querySelector('form').onsubmit=async e=>{
    e.preventDefault();const form=e.target,button=form.querySelector('[type=submit]'),data=new FormData(form);button.disabled=true;
    try {
      const start=new Date(data.get('start')),end=new Date(data.get('end'));
      if(!Number.isFinite(start.getTime())||!Number.isFinite(end.getTime()))throw Error('Enter a valid start and end time.');
      if(localInput(start)!==data.get('start')||localInput(end)!==data.get('end'))throw Error('This time does not exist because the clocks change. Choose another time.');
      await api(event?`/schedule/${event.id}`:'/schedule',jsonRequest(event?'PUT':'POST',{
        kind:data.get('kind'),...dialog.placePicker.value(),starts_at:start.toISOString(),ends_at:end.toISOString(),
        timezone:playZone(),visibility:data.get('visibility'),note:data.get('note')
      }));
      playing.month=new Date(start.getFullYear(),start.getMonth(),1);playing.day=localDay(start);
      if(!event){state.page='schedule';state.selectedId=null;pushRoute('play');}
      state.notice='';closePlan();await reloadPlans();
    }catch(error){dialog.querySelector('.plan-error').textContent=error.message;button.disabled=false;}
  };
  document.body.append(dialog);dialog.showModal();dialog.placePicker=createPlacePicker(dialog,event);dialog.placePicker.focus();
}

async function reloadPlans() {
  await Promise.all([loadSchedule(),loadUpcoming()]);
  if(state.player)state.player=await api(`/players/${state.player.id}`);
  render();
}

app.addEventListener('click',async e=>{
  const button=e.target.closest('button');if(!button)return;
  try {
    if(button.dataset.playLayout){playing.layout=button.dataset.playLayout;render();return;}
    if(button.dataset.planEdit){const event=[...playing.events,...playing.upcoming,...(state.player?.playing||[])].find(e=>e.id===button.dataset.planEdit);if(event)openPlan(event);return;}
    if(button.dataset.playDay){playing.day=button.dataset.playDay;const date=new Date(playing.day+'T12:00:00');if(date.getMonth()!==playing.month.getMonth()||date.getFullYear()!==playing.month.getFullYear()){playing.month=new Date(date.getFullYear(),date.getMonth(),1);await loadSchedule();}render();return;}
    if(button.hasAttribute('data-play-clear')){playing.day=null;render();return;}
    if(button.dataset.playFilter){playing.view=button.dataset.playFilter;await loadSchedule();render();return;}
    if(button.dataset.playMonth){playing.month=new Date(playing.month.getFullYear(),playing.month.getMonth()+Number(button.dataset.playMonth),1);playing.day=null;await loadSchedule();render();return;}
    if(button.hasAttribute('data-play-today')){const today=new Date();playing.month=new Date(today.getFullYear(),today.getMonth(),1);playing.day=localDay(today);await loadSchedule();render();}
  }catch(error){state.error=error.message;render();}
});

window.addEventListener('focus',async()=>{
  if(!state.user||planDialog)return;
  try{if(state.page==='schedule')await reloadPlans();}catch(error){state.error=error.message;render();}
});

let refreshingPlans=false;
setInterval(async()=>{
  if(refreshingPlans||!state.user||document.hidden||planDialog||connectionDialog||state.selectedId)return;
  if(['INPUT','SELECT','TEXTAREA'].includes(document.activeElement?.tagName))return;
  refreshingPlans=true;
  try {
    if(state.page==='schedule')await reloadPlans();
    else if(state.page==='players'&&state.player){state.player=await api(`/players/${state.player.id}`);render();}
  }catch(error){if(error.status===404&&state.player){state.player=null;await loadPlayers();render();}}
  finally{refreshingPlans=false;}
},60000);
