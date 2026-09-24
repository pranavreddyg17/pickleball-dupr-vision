// Uses only the disposable ui_fixture.py server and fixture API responses.
import {chromium} from 'playwright';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const base=process.env.DUPRVISION_UI_URL||'http://127.0.0.1:3017';
assert.equal(new URL(base).hostname,'127.0.0.1');
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  let selected=false,request=null;
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/api/health',async route=>{
    const response=await route.fetch(),health=await response.json();
    await route.fulfill({response,json:{...health,analysis_engine:'gemini',analysis_configured:true,worker_running:true}});
  });
  await page.route('**/api/videos',async route=>{
    const response=await route.fetch(),videos=await response.json();
    videos.unshift({id:'qa-selection',original_filename:'Court session.mp4',duration_seconds:26.4,
      created_at:'2026-09-23T12:00:00Z',status:selected?'ANALYZING':'WAITING_FOR_PLAYER',stage:'Reviewing shots and rallies',result:null});
    const report=videos.find(v=>v.id==='qa-local-0').result;
    report.performance.version='vision_score_v2';report.performance.sample_scope='short';report.performance.note='Limited sample';
    report.performance.components.forEach((component,index)=>component.weight=[.7,.15,.15][index]);
    report.priority='Ungrounded legacy practice tip';
    report.shots[0].evidence='The return lands deep; the player recovers behind the contact.';
    report.game_areas=[{name:'Serve & return',observations:0},{name:'Groundstrokes',observations:3},{name:'Soft game',observations:0},{name:'Net exchanges',observations:0}];
    report.practice={title:'Recovery',observation:'Late recovery observed at 1 contact.',exercise:'Return to a ready position before the next feed.',timestamps:[12]};
    await route.fulfill({response,json:videos});
  });
  await page.route('**/api/videos/qa-selection/preview/*',async route=>{
    if(process.env.DUPRVISION_PREVIEW_FIXTURE)return route.fulfill({contentType:'image/jpeg',body:await readFile(process.env.DUPRVISION_PREVIEW_FIXTURE)});
    return route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="480" height="854"><rect width="480" height="854" fill="#dde5df"/></svg>'});
  });
  await page.route('**/api/videos/qa-selection/select',async route=>{
    request=route.request().postDataJSON();selected=true;await route.fulfill({json:{ok:true}});
  });
  await page.goto(base);
  await page.locator('#email').fill('qa-local@example.test');
  await page.locator('#password').fill('local-ui-test-2026');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  assert.equal(await page.getByText('DUPR-scale equivalent',{exact:true}).count(),0);
  await page.getByRole('tab',{name:'Progress',exact:true}).click();
  await page.locator('.session-focus').getByText('Return to a ready position before the next feed.',{exact:true}).waitFor();
  assert.equal(await page.getByText('Ungrounded legacy practice tip',{exact:true}).count(),0);
  await page.locator('[data-page="analyze"]').click();
  await page.getByRole('heading',{name:'New video',exact:true}).waitFor();
  await page.screenshot({path:'/tmp/duprvision-analyze-desktop.png',fullPage:true});
  await page.locator('[data-video="qa-selection"]').click();
  assert.equal(await page.locator('#point-x,#point-y').count(),0);
  assert.equal(await page.getByRole('button',{name:'Analyze clip'}).isEnabled(),false);
  await page.locator('#preview-image').focus();await page.keyboard.press('Enter');await page.keyboard.press('ArrowRight');
  await page.getByText('Player selected',{exact:true}).waitFor();
  await page.locator('#consent').check();
  assert.equal(await page.getByRole('button',{name:'Analyze clip'}).isEnabled(),false);
  await page.locator('#external-consent').check();
  assert.equal(await page.getByRole('button',{name:'Analyze clip'}).isEnabled(),true);
  await page.locator('[data-preview="2"]').click();
  assert.equal(await page.getByRole('button',{name:'Analyze clip'}).isEnabled(),false);
  await page.locator('#preview-image').focus();await page.keyboard.press('Enter');
  for(const width of [1440,768,390,320]) {
    await page.setViewportSize({width,height:900});
    await page.reload();
    await page.locator('#preview-image').waitFor();
    await page.locator('#preview-image').focus();await page.keyboard.press('Enter');
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`Selection overflow ${width}`);
    await page.screenshot({path:`/tmp/duprvision-select-${width}.png`,fullPage:true});
  }
  await page.locator('#consent').check();await page.locator('#external-consent').check();
  await page.getByRole('button',{name:'Analyze clip'}).click();
  await page.getByRole('heading',{name:'Reviewing shots and rallies'}).waitFor();
  assert.equal(request.consent,true);assert.equal(request.external_consent,true);
  assert.equal(request.x,.5);assert.equal(request.y,.5);
  await page.locator('[data-action="back-clips"]').click();
  await page.locator('.session-row[data-video="qa-local-0"]').click();
  await page.getByRole('heading',{name:'Recovery',exact:true}).waitFor();
  assert.equal(await page.locator('.review-workspace').evaluate(e=>getComputedStyle(e).display),'grid');
  await page.getByText('The return lands deep; the player recovers behind the contact.',{exact:true}).waitFor();
  for(const width of [1440,390,320]) {
    await page.setViewportSize({width,height:900});
    await page.screenshot({path:`/tmp/duprvision-assessment-${width}.png`,fullPage:true});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`Report overflow ${width}: ${await page.evaluate(()=>[...document.querySelectorAll('main *')].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>e.className).join(', '))}`);
  }
  await page.getByRole('button',{name:'Breakdown',exact:true}).click();
  await page.getByRole('heading',{name:'Game coverage',exact:true}).waitFor();
  await page.getByText('Limited sample',{exact:true}).waitFor();
  await page.locator('[data-action="score-method"]').click();
  await page.getByRole('dialog',{name:'Scoring method',exact:true}).waitFor();
  await page.getByText(/six neutral-weight observations/).waitFor();
  await page.keyboard.press('Escape');
  assert.deepEqual(errors,[]);
  console.log('Analyze flow passed: keyboard selection, frame reset, consent, submission, evidence, method, and responsive layouts.');
} finally {await browser.close();}
