// Run against the disposable ui_fixture.py server, never production data.
import {chromium} from 'playwright';
import assert from 'node:assert/strict';

const base=process.env.DUPRVISION_UI_URL||'http://127.0.0.1:3017';
assert.equal(new URL(base).hostname,'127.0.0.1');
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try {
  const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[];
  let preview=false;
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/health',async route=>{
    if(!preview)return route.continue();
    const response=await route.fetch(),health=await response.json();
    await route.fulfill({response,json:{...health,analysis_engine:'gemini',analysis_configured:true,worker_running:true}});
  });
  await page.route('**/api/videos/qa-lowres/preview/*',route=>route.fulfill({
    contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="144" height="256"><rect width="144" height="256" fill="#ddd"/></svg>'}));
  await page.route('**/api/videos',async route=>{
    const response=await route.fetch(),videos=await response.json();
    const report=videos.find(video=>video.id==='qa-local-0').result;
    report.capture_quality={width:144,height:256,fps:30};
    report.tracking_check={status:'checked',aligned_shots:1,reported_shots:1};
    report.shots[0].player_visible=true;
    report.shot_breakdown=[{type:'drive',assessed:1,controlled:0,neutral:1,errors:0}];
    report.performance.sample_scope='short';
    report.performance.note='Short sample: 3 assessed shots.';
    if(preview)videos.unshift({id:'qa-lowres',original_filename:'Court clip.mp4',duration_seconds:27,
      created_at:'2026-09-23T12:00:00Z',status:'WAITING_FOR_PLAYER',stage:'Choose your player',result:null});
    await route.fulfill({response,json:videos});
  });
  await page.goto(base);
  await page.locator('#email').fill('qa-local@example.test');
  await page.locator('#password').fill('local-ui-test-2026');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.locator('.session-row[data-video="qa-local-0"]').click();
  await page.getByRole('button',{name:'Breakdown',exact:true}).click();
  await page.getByRole('heading',{name:'Shot control by type'}).waitFor();
  await page.getByText('Short sample: 3 assessed shots.',{exact:true}).waitFor();
  assert.equal(await page.locator('.shot-breakdown tbody tr').count(),1);
  assert.match(await page.locator('.shot-breakdown tbody').innerText(),/Drive\s+1\s+0\s+1\s+0/);
  for(const width of [1440,390,320]){
    await page.setViewportSize({width,height:850});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`Report overflow at ${width}`);
    if(width===390)await page.screenshot({path:'/tmp/duprvision-analysis-report-390.png',fullPage:true});
  }
  assert.equal(await page.getByText('Recording resolution is too low for a reliable score.').count(),0);
  preview=true;
  await page.goto(base+'/#videos');
  await page.reload();
  await page.locator('.session-row[data-video="qa-lowres"]').click();
  await page.locator('#external-consent').waitFor();
  assert.equal(await page.locator('#external-consent').isVisible(),true);
  await page.locator('#preview-image').click({position:{x:50,y:100}});
  await page.locator('#consent').check();
  assert.equal(await page.getByRole('button',{name:'Analyze clip'}).isEnabled(),false);
  await page.locator('#external-consent').check();
  assert.equal(await page.getByRole('button',{name:'Analyze clip'}).isEnabled(),true);
  assert.deepEqual(errors,[]);
  console.log('Analysis UI passed: small-video scoring, external consent, and mobile widths.');
} finally {await browser.close();}
