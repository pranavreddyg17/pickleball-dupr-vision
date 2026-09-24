const routes={home:'videos',schedule:'play',players:'players',profile:'account',analyze:'analyze'};
function pushRoute(route){if(location.hash!==`#${route}`)history.pushState(null,'',`#${route}`);}
async function navigateTo(page){
  state.page=page;state.selectedId=null;state.player=null;state.error='';state.notice='';
  if(page==='players')await loadPlayers();
  if(page==='schedule')await Promise.all([loadSchedule(),loadUpcoming(),loadCompetitions()]);
  pushRoute(routes[page]||'videos');render();window.scrollTo(0,0);
}
async function restoreRoute(){
  const [route,id]=location.hash.slice(1).split('/');
  state.selectedId=null;state.player=null;
  if(route==='event'&&id){competition.data=await api(`/competitions/${encodeURIComponent(id)}`);competition.join=null;state.page='competition';return;}
  if(route==='join'&&id){competition.join=id;state.page='competition';return;}
  if(route==='video'&&state.videos.some(v=>v.id===id)){state.page='home';state.selectedId=id;return;}
  if(route==='player'&&id){state.page='players';state.player=await api(`/players/${encodeURIComponent(id)}`);return;}
  state.page=Object.keys(routes).find(key=>routes[key]===route)||'home';
  if(state.page==='players')await loadPlayers();
  if(state.page==='schedule')await Promise.all([loadSchedule(),loadUpcoming(),loadCompetitions()]);
}
function workspaceDialog(title,body){
  const dialog=document.createElement('dialog');dialog.className='workspace-dialog';
  dialog.innerHTML=`<header><h2>${title}</h2><button class="dialog-close" aria-label="Close">&times;</button></header>${body}`;
  dialog.querySelector('header button').onclick=()=>dialog.close();
  dialog.addEventListener('close',()=>dialog.remove());document.body.append(dialog);dialog.showModal();return dialog;
}
function explainAverage(){workspaceDialog('About your clip score','<p>A summary of the observable shots, balance and recovery in your uploaded videos. It is not a DUPR rating or a measure of your overall playing level.</p><p>Each scored day has equal weight in this average. Repeated uploads of the same clip do not count again. Scores from different scoring versions are kept separate.</p><p>Compare similar recordings over time. Camera coverage, clip length and the shots visible can change the result.</p>');}
app.addEventListener('click',e=>{
  if(!e.target.closest('[data-workspace-new]'))return;
  const dialog=workspaceDialog('New event','<div class="event-choices"><button data-choice="session"><strong>Play session</strong><span>A place and time to play with friends</span></button><button data-choice="robin"><strong>Round robin</strong><span>Players, courts, rounds and live scores</span></button></div>');
  dialog.querySelectorAll('[data-choice]').forEach(button=>button.onclick=()=>{dialog.close();button.dataset.choice==='session'?openPlan():openCompetitionCreate();});
});
window.addEventListener('hashchange',async()=>{if(!state.user)return;try{await restoreRoute();render();}catch(error){state.error=error.message;render();}});
