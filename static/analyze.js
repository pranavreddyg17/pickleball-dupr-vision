function analysisSteps(current) {
  return `<ol class="analysis-steps" aria-label="Analysis progress">${['Video','Player','Review'].map((label,index)=>`<li ${index===current?'aria-current="step"':''} class="${index<=current?'reached':''}"><span>${index+1}</span>${label}</li>`).join('')}</ol>`;
}

function analyzeView() {
  const disabled=state.busy||!state.workerRunning||!state.analysisConfigured||!state.user.remaining;
  const pending=state.videos.filter(v=>!['COMPLETED','EXPIRED'].includes(v.status));
  return `<button class="text-button" data-page="home">${icon('arrow-left')}Analyze</button><div class="page-head"><h1>Analyze video</h1><span class="muted small">${state.user.remaining} uploads available today</span></div>
    ${analysisSteps(0)}
    ${!state.workerRunning?'<div class="alert">Analysis is temporarily unavailable.</div>':''}
    ${!state.analysisConfigured?'<div class="alert">Video review is awaiting owner configuration.</div>':''}
    <section class="analysis-upload" aria-label="New analysis">
      <div><h2>New video</h2><p class="fine">MP4 or MOV · Up to 3 minutes · 100 MB</p></div>
      <input id="video-input" type="file" accept="video/mp4,video/quicktime,video/x-m4v,.mp4,.mov,.m4v" hidden>
      <button class="primary" data-action="choose-video" ${disabled?'disabled':''}>${icon('upload')}Choose video</button>
      ${state.busy?`<div class="analysis-upload-progress" role="status"><progress max="100" value="${state.uploadProgress}" aria-label="Upload progress"></progress><span id="upload-percent">${state.uploadProgress}%</span></div>`:''}
    </section>
    ${pending.length?`<section class="section"><div class="section-head"><h2>In progress</h2></div>${pending.map(sessionRow).join('')}</section>`:''}`;
}

function selectionView(v) {
  return `${analysisSteps(1)}<div class="player-selection">
    <section class="selection-visual" aria-label="Choose player">
      <div class="selection-stage"><div class="preview-wrap"><img id="preview-image" src="/api/videos/${v.id}/preview/${state.preview}" alt="Select player" role="button" tabindex="0" aria-label="Select player in frame. Enter selects center; arrow keys adjust the selection.">${state.point?`<span class="point" style="left:${state.point.x*100}%;top:${state.point.y*100}%" aria-hidden="true">+</span>`:''}</div></div>
      <div class="frame-picker" role="group" aria-label="Reference frame">${[1,2,3].map(n=>`<button data-preview="${n}" aria-pressed="${n===state.preview}" aria-label="Reference at ${timestamp(v.duration_seconds*[.1,.4,.7][n-1])}"><img src="/api/videos/${v.id}/preview/${n}" alt=""><time>${timestamp(v.duration_seconds*[.1,.4,.7][n-1])}</time></button>`).join('')}</div>
    </section>
    <aside class="selection-options"><div class="selection-status" role="status">${state.point?'Player selected':'No player selected'}</div>
      <fieldset><legend>Analysis permission</legend>
        <label class="checkbox"><input id="consent" type="checkbox" ${state.consent?'checked':''}><span>I have permission to analyze this footage.</span></label>
        ${state.engine==='gemini'?`<label class="checkbox"><input id="external-consent" type="checkbox" ${state.externalConsent?'checked':''}><span>Allow Google Gemini to process this video and its player-selection frame.</span></label><p class="fine">Other players may be visible. Google's API data policy applies.</p>`:''}
      </fieldset>
      <fieldset><legend>Report media</legend><label class="checkbox"><input id="save-evidence" type="checkbox" ${state.saveEvidence?'checked':''}><span>Save key moments</span></label><p class="fine">Up to three private replays and tracked frames. The full upload is deleted after review.</p></fieldset>
      <div class="selection-actions"><button class="primary" data-action="start-analysis" ${canAnalyze()?'':'disabled'}>Analyze clip</button><button class="icon-button" data-action="delete-video" title="Delete clip" aria-label="Delete clip">${icon('trash-2')}</button></div>
    </aside>
  </div>`;
}

function assessmentCoverage(r) {
  if(!r.game_areas)return '';
  return `<section class="assessment-coverage"><h2>Game coverage</h2><dl>${r.game_areas.map(area=>`<div><dt>${esc(area.name)}</dt><dd>${area.observations?`${area.observations} assessed ${area.observations===1?'shot':'shots'}`:'Not observed'}</dd></div>`).join('')}</dl></section>`;
}

function practiceView(r) {
  const practice=r.practice;
  if(!practice)return '';
  return `<section class="practice-focus"><div><span class="label">Practice focus</span><h2>${esc(practice.title)}</h2></div><div><p>${esc(practice.observation)} ${esc(practice.exercise)}</p><div class="practice-moments">${practice.timestamps.map(time=>`<button class="text-button" data-seek="${Number(time)}" aria-label="Review supporting moment at ${timestamp(time)}">${timestamp(time)}</button>`).join('')}</div></div></section>`;
}

function scoreMethod(r) {
  const current=r.performance.version==='vision_score_v2';
  return `<button class="text-button score-method-button" data-action="score-method">Scoring method${current?' · V2':' · Earlier version'}</button>
    <dialog id="score-method-dialog" class="report-dialog" aria-labelledby="score-method-title"><div class="report-dialog-head"><h2 id="score-method-title">Scoring method</h2><button type="button" class="dialog-close" data-action="close-dialog" aria-label="Close">&times;</button></div>
    ${current?'<p>Shot control contributes 70%, balance 15%, and recovery 15%. Purposeful routine execution earns less than successful execution under visible pressure. Neutral play earns midpoint credit; visible errors earn zero.</p><p>High-confidence observations have weight 1; medium-confidence observations have weight 0.5. Each component starts with six neutral-weight observations, reducing extreme scores from small samples. The report displays these stabilized component values.</p><p>At least three evidenced observations per component across five seconds are needed. Missing skills are unobserved, not scored zero. These are product rules, not calibrated confidence bounds or a DUPR rating. Earlier scores are retained separately.</p>':'<p>This saved report used 50% shot control, 25% balance and 25% recovery, without evidence weighting or small-sample stabilization. It is not comparable with V2 scores.</p>'}
    </dialog>`;
}

app.addEventListener('keydown',event=>{
  if(event.target.id!=='preview-image')return;
  if(!['Enter',' ','ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key))return;
  event.preventDefault();
  const point=state.point||{x:.5,y:.5}, step=event.shiftKey ? .1 : .02;
  state.point={x:Math.max(0,Math.min(1,point.x+(event.key==='ArrowRight'?step:event.key==='ArrowLeft'?-step:0))),
               y:Math.max(0,Math.min(1,point.y+(event.key==='ArrowDown'?step:event.key==='ArrowUp'?-step:0)))};
  render();document.getElementById('preview-image')?.focus();
});
