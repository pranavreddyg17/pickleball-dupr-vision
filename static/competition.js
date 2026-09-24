const competition={data:null,list:[],tab:'matches',busy:false,dialog:null,join:null};
const competitionNames=ids=>ids.map(id=>competition.data.players.find(p=>p.id===id)?.name||'Player').join(' / ');
const competitionStatus={registration:'Check-in',live:'In progress',paused:'Paused',finished:'Finished'};
const matchStatus={scheduled:'Ready',live:'Playing',submitted:'Awaiting confirmation',disputed:'Needs organizer',confirmed:'Final',forfeit:'Forfeit',void:'Not played'};

async function loadCompetitions(){competition.list=await api('/competitions');}
async function openCompetition(id){
  competition.data=await api(`/competitions/${encodeURIComponent(id)}`);competition.join=null;
  state.page='competition';state.selectedId=null;state.error='';competition.tab='matches';
  pushRoute(`event/${id}`);render();window.scrollTo(0,0);
}
function competitionView(){
  if(competition.join)return `<div class="competition-join"><h1>Join round robin</h1><p class="muted">Join with your DUPRVision profile.</p><button class="primary" data-comp-join>Join event</button></div>`;
  const c=competition.data;if(!c)return '<p class="empty">Event unavailable.</p>';
  const current=c.rounds.at(-1), locked=c.phase==='finished';
  if(locked&&competition.tab==='settings')competition.tab='matches';
  const myId=c.players.find(p=>p.is_me)?.id;
  const currentMatches=c.matches.filter(m=>m.round_id===current?.id);
  const myMatch=currentMatches.find(m=>m.a.includes(myId)||m.b.includes(myId));
  const available=c.players.filter(p=>p.availability==='ready');
  const resting=available.filter(p=>!currentMatches.some(m=>m.a.includes(p.id)||m.b.includes(p.id)));
  const pending=currentMatches.filter(m=>!['confirmed','forfeit','void'].includes(m.status)).length;
  const scoring=c.rules.minutes?`${c.rules.minutes}-minute games · ties count as draws`:`To ${c.rules.target} · win by ${c.rules.win_by}`;
  return `<button class="text-button" data-page="schedule">${icon('arrow-left')}Events</button><div class="page-head competition-heading"><div><p class="label">${competitionStatus[c.phase]}</p><h1>${esc(c.title)}</h1><p class="muted small">${esc(c.plan.location)} · ${esc(playDate(c.plan.starts_at))} · ${esc(playTime(c.plan.starts_at))}</p></div>${c.is_host?'<button class="secondary" data-comp-invite>Invite players</button>':''}</div>
    <div class="competition-summary"><span>${c.rules.format==='fixed'?'Fixed teams':'Rotating partners'}</span><span>${scoring}</span><span>${c.rules.scoring==='rally'?'Rally scoring':'Side-out scoring'}</span><span>${c.players.length} players · ${c.rules.courts.length} ${c.rules.courts.length===1?'court':'courts'}</span></div>
    <div class="tabs competition-tabs" role="tablist" aria-label="Event views">${['matches','players','standings',...(c.is_host&&!locked?['settings']:[])].map(tab=>`<button data-comp-tab="${tab}" role="tab" aria-selected="${competition.tab===tab}" class="${competition.tab===tab?'active':''}">${capital(tab)}</button>`).join('')}</div>
    ${competition.tab==='settings'?`<section class="section"><h2>Event settings</h2><div class="competition-footer">${!c.rounds.length?'<button class="secondary" data-comp-edit>Edit event</button>':''}<button class="secondary" data-comp-courts>Manage courts</button>${c.phase==='paused'?'<button class="secondary" data-comp-action="resume">Resume event</button>':'<button class="secondary" data-comp-action="pause">Pause new rounds</button>'}<button class="text-button" data-comp-finish>Finish event</button></div></section>`:competition.tab==='players'?competitionPlayersView():competition.tab==='standings'?competitionStandingsView():`
    ${myMatch&&!locked?`<div class="your-match"><strong>${myMatch.status==='scheduled'?'Your next game':'Your game'} · ${esc(myMatch.court)}</strong><span>${esc(competitionNames(myMatch.a))} <span class="muted">vs</span> ${esc(competitionNames(myMatch.b))}</span></div>`:''}
    <div class="section-head competition-round-head"><div><h2>${current?`Round ${current.number}`:'Ready when you are'}</h2><p class="fine">${c.fixed_complete?'All teams have played each other':!current?'Check in players to build the first round.':current.status==='draft'?'Preview':current.status==='completed'?'Round complete':`${pending} ${pending===1?'match':'matches'} remaining`}</p></div><div class="competition-actions">${c.is_host&&!locked?`${c.phase==='paused'?'<button class="primary" data-comp-action="resume">Resume event</button>':c.fixed_complete?'':!current||current.status==='completed'?'<button class="primary" data-comp-action="generate">'+(current?'Add round':'Generate round')+'</button>':current.status==='draft'?'<button class="text-button" data-comp-action="discard">Discard preview</button><button class="primary" data-comp-action="start">Start round</button>':''}`:''}</div></div>
    ${c.rules.minutes&&current?.status==='live'?`<p class="round-clock" data-round-start="${esc(current.started_at)}">${competitionClock(current.started_at,c.rules.minutes)}</p>`:''}
    <div class="competition-matches">${currentMatches.map(competitionMatchView).join('')}</div>${current&&resting.length?`<p class="competition-resting"><strong>Resting this round</strong> ${resting.map(p=>esc(p.name)).join(', ')}</p>`:''}
    ${c.is_host&&current?.status==='draft'&&c.rules.format==='rotating'?'<button class="text-button" data-comp-swap>Swap players</button>':''}
    ${c.rounds.length>1?`<section class="section"><h2>Earlier rounds</h2>${c.rounds.slice(0,-1).reverse().map(round=>`<div class="competition-history"><h3>Round ${round.number}</h3>${c.matches.filter(m=>m.round_id===round.id).map(competitionMatchView).join('')}</div>`).join('')}</section>`:''}
    `}`;
}
function competitionClock(start,minutes){
  const seconds=Math.max(0,Math.ceil((new Date(start).getTime()+minutes*60000-Date.now())/1000));
  return seconds?`${Math.floor(seconds/60)}:${String(seconds%60).padStart(2,'0')} remaining`:'Time elapsed · finish the current rally and record scores';
}
function competitionMatchView(m){
  const c=competition.data, me=c.players.find(p=>p.is_me)?.id;
  const canScore=c.phase!=='finished'&&m.status!=='scheduled'&&(c.is_host||((m.a.includes(me)||m.b.includes(me))&&!['confirmed','forfeit','void'].includes(m.status)));
  return `<article class="competition-match"><div class="match-caption"><strong>${esc(m.court)}</strong><span class="match-state ${m.status==='disputed'?'danger':''}">${matchStatus[m.status]}</span></div><div class="match-team"><span>${esc(competitionNames(m.a))}</span><b>${m.score_a??(m.status==='forfeit'&&m.winner===1?'W':'—')}</b></div><div class="match-team"><span>${esc(competitionNames(m.b))}</span><b>${m.score_b??(m.status==='forfeit'&&m.winner===2?'W':'—')}</b></div>${m.reason?`<p class="fine">${esc(m.reason)}</p>`:''}${canScore?`<button class="text-button" data-comp-score="${m.id}">${m.status==='submitted'?'Review score':m.status==='confirmed'?'Correct score':'Record result'}</button>`:''}</article>`;
}
function competitionPlayersView(){
  const c=competition.data, editable=c.is_host&&c.phase!=='finished';
  return `<p class="fine">Organizers: ${c.organizers.map(p=>esc(p.display_name)).join(', ')}</p><div class="section-head competition-round-head"><h2>Players <span class="muted">${c.players.length}</span></h2>${editable?'<button class="secondary" data-comp-player>Add player</button>':''}</div>${editable&&!c.players.some(p=>p.is_me)?'<button class="text-button" data-comp-add-me>Join as a player</button>':''}
    <div class="competition-roster">${c.players.map(p=>`<div class="competition-person"><div><strong>${esc(p.name)}</strong><span class="fine">${p.is_host?'Organizer · ':''}${p.user_id?'Member':'Guest'}${p.team?' · '+esc(p.team):''}</span></div>${editable?`<select data-comp-attendance="${p.id}" aria-label="Attendance for ${esc(p.name)}">${[['expected','Expected'],['ready','Checked in'],['resting','Resting'],['withdrawn','Withdrawn']].map(([key,label])=>`<option value="${key}" ${p.availability===key?'selected':''}>${label}</option>`).join('')}</select>${c.rules.format==='fixed'&&!c.rounds.length?`<button class="text-button" data-comp-team="${p.id}">Team</button>`:''}${c.is_owner&&p.user_id&&!p.is_host?`<button class="text-button" data-comp-host="${p.id}">Make organizer</button>`:''}`:`<span class="muted small">${p.availability==='ready'?'Checked in':capital(p.availability)}</span>`}</div>`).join('')||'<p class="empty">Invite players or add guests to your roster.</p>'}</div>`;
}
function competitionStandingsView(){
  const c=competition.data;
  return `<div class="section-head competition-round-head"><h2>Standings</h2></div><p class="fine">${c.rules.format==='fixed'?'Wins':'Win percentage'}, then average point difference. ${c.rules.minimum_games} games to qualify. Ties share a place.</p><div class="standings-scroll"><table class="competition-standings"><thead><tr><th>Place</th><th>${c.rules.format==='fixed'?'Team':'Player'}</th><th>Played</th><th>W–L–D</th><th>Win %</th><th>Avg. +/−</th></tr></thead><tbody>${c.standings.map(p=>`<tr><td>${p.rank??'—'}</td><th scope="row">${esc(p.name)}${!p.eligible?'<small>Provisional</small>':''}</th><td>${p.games}</td><td>${p.wins}–${p.losses}–${p.draws}</td><td>${p.percentage}%</td><td>${p.average_differential>0?'+':''}${p.average_differential}</td></tr>`).join('')}</tbody></table></div>${c.is_host?`<details class="competition-audit"><summary>Event history</summary>${c.audit.map(a=>`<p><time>${esc(new Date(a.created_at).toLocaleString())}</time> ${esc(a.action.replaceAll('_',' '))}${a.action==='score'?` · ${JSON.parse(a.detail).score_a}–${JSON.parse(a.detail).score_b}`:''}</p>`).join('')}</details>`:''}`;
}
function closeCompetitionDialog(){if(competition.dialog){competition.dialog.placePicker?.destroy();competition.dialog.close();competition.dialog.remove();competition.dialog=null;}}
function competitionDialog(title,body){
  closeCompetitionDialog();const dialog=document.createElement('dialog');dialog.className='competition-dialog';
  dialog.setAttribute('aria-labelledby','competition-dialog-title');
  dialog.innerHTML=`<header><h2 id="competition-dialog-title">${title}</h2><button class="icon-button" data-comp-close aria-label="Close">×</button></header><div class="competition-dialog-body">${body}<p class="competition-error" role="alert"></p></div>`;
  dialog.querySelector('[data-comp-close]').onclick=closeCompetitionDialog;
  dialog.addEventListener('cancel',e=>{e.preventDefault();closeCompetitionDialog();});
  document.body.append(dialog);competition.dialog=dialog;dialog.showModal();return dialog;
}
function showCompetitionError(error){
  if(competition.dialog)competition.dialog.querySelector('.competition-error').textContent=error.message;
  else {state.error=error.message;render();}
}
async function competitionCommand(action,fields={},saved=null){
  const c=competition.data;
  const payload=saved||{action,...fields,version:c.version,request_id:crypto.randomUUID()};
  competition.busy=true;
  try{
    const result=await api(`/competitions/${c.id}/commands`,jsonRequest('POST',payload));
    if(competition.data?.id===result.id)competition.data=result;
    state.error='';render();return result;
  }catch(error){
    if(error.status===409)competition.data=await api(`/competitions/${c.id}`);
    throw error;
  }finally{competition.busy=false;}
}
function openCompetitionCreate(existing=null){
  const start=new Date(Date.now()+3600000);start.setMinutes(0,0,0);
  const dialog=competitionDialog('New round robin',`<form id="competition-create"><label for="competition-title">Event name</label><input id="competition-title" name="title" maxlength="100" required><div id="place-picker"></div><div class="competition-form-grid"><div><label for="competition-start">Starts</label><input id="competition-start" name="start" type="datetime-local" value="${localInput(start)}" required></div><div><label for="competition-end">Ends</label><input id="competition-end" name="end" type="datetime-local" value="${localInput(new Date(start.getTime()+90*60000))}" required></div></div><p class="fine">${esc(playZoneLabel())}</p><div class="competition-form-grid"><div><label for="competition-format">Partners</label><select id="competition-format" name="format"><option value="rotating">Rotate each round</option><option value="fixed">Fixed teams</option></select></div><div><label for="competition-count">Courts</label><input id="competition-count" name="count" type="number" min="1" max="8" value="2" required></div></div><label for="competition-courts">Court names</label><input id="competition-courts" name="courts" maxlength="320" placeholder="7, 8 or leave blank"><div class="competition-form-grid"><div><label for="competition-length">Game length</label><select id="competition-length" name="length"><option value="11">To 11</option><option value="15">To 15</option><option value="21">To 21</option><option value="timed10">10 minutes</option><option value="timed15">15 minutes</option></select></div><div><label for="competition-margin">Win by</label><select id="competition-margin" name="margin"><option value="2">2 points</option><option value="1">1 point</option></select></div></div><div class="competition-form-grid"><div><label for="competition-scoring">Scoring</label><select id="competition-scoring" name="scoring"><option value="side_out">Side-out</option><option value="rally">Rally</option></select></div><div><label for="competition-minimum">Games to qualify</label><input id="competition-minimum" name="minimum" type="number" min="1" max="20" value="3" required></div></div><label class="checkbox"><input type="checkbox" name="playing">I'm playing</label><button class="primary full" type="submit">Create event</button></form>`);
  dialog.placePicker=createPlacePicker(dialog,existing?.plan||null);
  if(existing){
    dialog.querySelector('#competition-dialog-title').textContent='Edit event';
    const form=dialog.querySelector('form'),r=existing.rules,p=existing.plan;
    for(const [name,value] of Object.entries({title:existing.title,start:localInput(new Date(p.starts_at)),end:localInput(new Date(p.ends_at)),format:r.format,count:r.courts.length,courts:r.courts.join(','),length:r.minutes?'timed'+r.minutes:r.target,margin:r.win_by,scoring:r.scoring,minimum:r.minimum_games}))form.elements.namedItem(name).value=value;
    form.elements.playing.closest('label').hidden=true;form.querySelector('[type=submit]').textContent='Save event';
  }
  dialog.querySelector('form').onsubmit=async event=>{
    event.preventDefault();const data=new FormData(event.target),button=event.target.querySelector('[type=submit]');button.disabled=true;
    try{
      const count=Number(data.get('count')),names=String(data.get('courts')).split(',').map(s=>s.trim());
      if(names.some(Boolean)&&names.length!==count)throw Error('Enter one court name per court, separated by commas.');
      const start=new Date(data.get('start')),end=new Date(data.get('end'));
      if(localInput(start)!==data.get('start')||localInput(end)!==data.get('end'))throw Error('Choose a valid local time.');
      const length=String(data.get('length')),timed=length.startsWith('timed');
      const body={title:data.get('title'),playing:data.has('playing'),
        plan:{kind:'open_play',...dialog.placePicker.value(),starts_at:start.toISOString(),ends_at:end.toISOString(),timezone:playZone(),visibility:'private',note:''},
        rules:{format:data.get('format'),courts:names.some(Boolean)?names:Array(count).fill(''),target:timed?11:Number(length),minutes:timed?Number(length.slice(5)):0,win_by:Number(data.get('margin')),scoring:data.get('scoring'),minimum_games:Number(data.get('minimum'))}};
      const result=existing?await competitionCommand('settings',{title:body.title,plan:body.plan,rules:body.rules}):await api('/competitions',jsonRequest('POST',body));
      closeCompetitionDialog();await loadCompetitions();await openCompetition(result.id);competition.tab='players';render();
    }catch(error){showCompetitionError(error);}finally{button.disabled=false;}
  };
  dialog.querySelector('#competition-title').focus();
}
function openCompetitionScore(id){
  const c=competition.data,m=c.matches.find(m=>m.id===id),key=`duprvision-score:${state.user.id}:${c.id}:${id}`;
  let draft={};try{draft=JSON.parse(localStorage.getItem(key)||'{}');}catch{}
  const dialog=competitionDialog('Match result',`<form id="competition-score"><div class="score-entry"><label for="score-a">${esc(competitionNames(m.a))}</label><input id="score-a" name="a" type="number" min="0" max="99" required value="${esc(draft.a??m.score_a??'')}"><label for="score-b">${esc(competitionNames(m.b))}</label><input id="score-b" name="b" type="number" min="0" max="99" required value="${esc(draft.b??m.score_b??'')}"></div><p class="fine">${c.rules.minutes?'Timed game · equal scores are a draw':`To ${c.rules.target}, win by ${c.rules.win_by}`}</p><button class="primary full" type="submit">${c.is_host?'Save result':'Submit score'}</button><p class="fine" id="score-save-state">${draft.command?'A previous submission is unsent. Retry to check its status.':''}</p></form>${m.status==='submitted'?'<div class="competition-result-actions"><button class="secondary" data-score-confirm>Confirm score</button><button class="text-button" data-score-dispute>Dispute</button></div>':''}${c.is_host?'<div class="competition-result-actions"><button class="text-button" data-score-forfeit>Record forfeit</button><button class="text-button" data-score-void>Mark unplayed</button></div>':''}`);
  const form=dialog.querySelector('form');
  form.oninput=()=>{draft={a:form.elements.a.value,b:form.elements.b.value};try{localStorage.setItem(key,JSON.stringify(draft));dialog.querySelector('#score-save-state').textContent='Draft saved on this device';}catch{}};
  form.onsubmit=async event=>{
    event.preventDefault();const submit=form.querySelector('[type=submit]');submit.disabled=true;
    try{
      draft.command=draft.command||{version:competition.data.version,request_id:crypto.randomUUID(),action:'score',match_id:id,score_a:Number(form.elements.a.value),score_b:Number(form.elements.b.value)};
      try{localStorage.setItem(key,JSON.stringify({...draft,a:form.elements.a.value,b:form.elements.b.value}));}catch{}
      await competitionCommand('score',{},draft.command);localStorage.removeItem(key);closeCompetitionDialog();
    }catch(error){if(error.status){draft.command=null;try{localStorage.setItem(key,JSON.stringify(draft));}catch{}}else error.message='Connection lost. Your score is saved on this device; retry when connected.';showCompetitionError(error);}
    finally{submit.disabled=false;}
  };
  for(const action of ['confirm','dispute'])dialog.querySelector(`[data-score-${action}]`)?.addEventListener('click',async event=>{
    event.currentTarget.disabled=true;try{await competitionCommand(action,{match_id:id});localStorage.removeItem(key);closeCompetitionDialog();}catch(error){showCompetitionError(error);event.currentTarget.disabled=false;}
  });
  for(const action of ['void','forfeit'])dialog.querySelector(`[data-score-${action}]`)?.addEventListener('click',()=>{
    const d=competitionDialog(action==='void'?'Unplayed match':'Forfeit',`<form><label for="result-reason">Reason</label><input id="result-reason" name="reason" maxlength="300" required>${action==='forfeit'?`<label for="result-winner">Winning team</label><select id="result-winner" name="winner"><option value="1">${esc(competitionNames(m.a))}</option><option value="2">${esc(competitionNames(m.b))}</option></select>`:''}<button class="primary full" type="submit">Save result</button></form>`);
    d.querySelector('form').onsubmit=async e=>{e.preventDefault();const data=new FormData(e.target);try{await competitionCommand(action,{match_id:id,reason:data.get('reason'),winner:Number(data.get('winner')||1)});localStorage.removeItem(key);closeCompetitionDialog();}catch(error){showCompetitionError(error);}};
  });
}
function openCompetitionPlayers(){
  const d=competitionDialog('Add player',`<form id="guest-form"><label for="guest-name">Guest name</label><input id="guest-name" name="name" maxlength="80" required><button type="submit" class="primary full">Add guest</button></form><form id="member-search"><label for="member-query">Find a member</label><div class="competition-search"><input id="member-query" name="q" type="search" maxlength="80" required><button class="secondary" type="submit">Search</button></div>${competition.data.is_owner?'<label for="member-role">Add as</label><select id="member-role"><option value="add_player">Player</option><option value="host">Co-organizer</option></select>':''}</form><div id="member-results"></div>`);
  d.querySelector('#guest-form').onsubmit=async e=>{e.preventDefault();try{await competitionCommand('add_player',{name:new FormData(e.target).get('name')});closeCompetitionDialog();}catch(error){showCompetitionError(error);}};
  d.querySelector('#member-search').onsubmit=async e=>{e.preventDefault();try{
    const results=await api('/players?q='+encodeURIComponent(new FormData(e.target).get('q')));
    d.querySelector('#member-results').innerHTML=results.players.map(p=>`<button type="button" class="competition-member" data-member="${p.id}">${esc(p.display_name)} <span>Add</span></button>`).join('')||'<p class="fine">No members found.</p>';
    d.querySelectorAll('[data-member]').forEach(b=>b.onclick=async()=>{try{await competitionCommand(d.querySelector('#member-role')?.value||'add_player',{user_id:b.dataset.member});closeCompetitionDialog();}catch(error){showCompetitionError(error);}});
  }catch(error){showCompetitionError(error);}};
}
app.addEventListener('click',async event=>{
  const b=event.target.closest('button');if(!b||!Object.keys(b.dataset).some(k=>k.startsWith('comp')))return;
  if(competition.busy)return;
  try{
    if(b.hasAttribute('data-comp-edit')){openCompetitionCreate(competition.data);return;}
    if(b.dataset.compOpen){await openCompetition(b.dataset.compOpen);return;}
    if(b.hasAttribute('data-comp-join')){b.disabled=true;const c=await api('/competitions/join',jsonRequest('POST',{token:competition.join}));await loadCompetitions();await openCompetition(c.id);return;}
    if(b.dataset.compTab){competition.tab=b.dataset.compTab;render();return;}
    if(b.dataset.compAction){b.disabled=true;await competitionCommand(b.dataset.compAction);return;}
    if(b.dataset.compScore){openCompetitionScore(b.dataset.compScore);return;}
    if(b.hasAttribute('data-comp-player')){openCompetitionPlayers();return;}
    if(b.hasAttribute('data-comp-add-me')){await competitionCommand('add_player',{user_id:state.user.id});return;}
    if(b.dataset.compHost){await competitionCommand('host',{player_id:b.dataset.compHost});return;}
    if(b.hasAttribute('data-comp-invite')){
      const d=competitionDialog('Invite players',`<label for="competition-link">Joining link</label><input id="competition-link" readonly value="${esc(location.origin+'/#join/'+competition.data.invite)}"><button class="primary full" id="copy-invite">Copy link</button><button class="text-button" id="reset-invite">Replace invitation link</button>`);
      d.querySelector('#copy-invite').onclick=async()=>{try{await navigator.clipboard.writeText(d.querySelector('input').value);d.querySelector('#copy-invite').textContent='Copied';}catch{d.querySelector('input').select();}};
      d.querySelector('#reset-invite').onclick=async()=>{try{await competitionCommand('rotate_invite');closeCompetitionDialog();}catch(error){showCompetitionError(error);}};return;
    }
    if(b.hasAttribute('data-comp-finish')){
      const d=competitionDialog('Finish event','<p>Confirm the results before finishing. This locks the event and its standings.</p><button class="primary full" id="finish-event">Finish event</button>');
      d.querySelector('#finish-event').onclick=async()=>{try{await competitionCommand('finish');await loadCompetitions();closeCompetitionDialog();}catch(error){showCompetitionError(error);}};return;
    }
    if(b.dataset.compTeam){
      const p=competition.data.players.find(p=>p.id===b.dataset.compTeam);
      const d=competitionDialog('Assign team',`<form><label for="team-name">Team name for ${esc(p.name)}</label><input id="team-name" name="team" value="${esc(p.team)}" maxlength="40" required><button class="primary full" type="submit">Save team</button></form>`);
      d.querySelector('form').onsubmit=async e=>{e.preventDefault();try{await competitionCommand('team',{player_id:p.id,team:new FormData(e.target).get('team')});closeCompetitionDialog();}catch(error){showCompetitionError(error);}};return;
    }
    if(b.hasAttribute('data-comp-courts')){
      const c=competition.data;const d=competitionDialog('Courts for next round',`<form><label for="court-count">Number of courts</label><input id="court-count" name="count" type="number" min="1" max="8" value="${c.rules.courts.length}" required><label for="court-names">Court names</label><input id="court-names" name="names" value="${esc(c.rules.courts.join(','))}" placeholder="7, 8 or leave blank"><button class="primary full" type="submit">Save courts</button></form>`);
      d.querySelector('form').onsubmit=async e=>{e.preventDefault();const data=new FormData(e.target),count=Number(data.get('count')),names=String(data.get('names')).split(',').map(s=>s.trim());try{if(names.some(Boolean)&&names.length!==count)throw Error('Enter one name per court.');await competitionCommand('courts',{courts:names.some(Boolean)?names:Array(count).fill('')});closeCompetitionDialog();}catch(error){showCompetitionError(error);}};return;
    }
    if(b.hasAttribute('data-comp-swap')){
      const options=competition.data.players.filter(p=>p.availability==='ready').map(p=>`<option value="${p.id}">${esc(p.name)}</option>`).join('');
      const d=competitionDialog('Swap players',`<form><label for="swap-a">Player</label><select id="swap-a" name="a">${options}</select><label for="swap-b">Swap with</label><select id="swap-b" name="b">${options}</select><button class="primary full" type="submit">Swap</button></form>`);
      d.querySelector('form').onsubmit=async e=>{e.preventDefault();const data=new FormData(e.target);try{await competitionCommand('swap',{player_id:data.get('a'),other_id:data.get('b')});closeCompetitionDialog();}catch(error){showCompetitionError(error);}};
    }
  }catch(error){b.disabled=false;showCompetitionError(error);}
});
app.addEventListener('change',async event=>{
  const id=event.target.dataset.compAttendance;if(!id)return;
  try{await competitionCommand('attendance',{player_id:id,availability:event.target.value});}catch(error){showCompetitionError(error);}
});
setInterval(async()=>{
  if(!state.user||state.page!=='competition'||!competition.data||competition.dialog||competition.busy||document.hidden)return;
  competition.busy=true;
  try{const c=await api(`/competitions/${competition.data.id}`);if(c.version>competition.data.version){competition.data=c;render();}}
  catch{}finally{competition.busy=false;}
},5000);
setInterval(()=>{const clock=document.querySelector('[data-round-start]');if(clock)clock.textContent=competitionClock(clock.dataset.roundStart,competition.data.rules.minutes);},1000);
