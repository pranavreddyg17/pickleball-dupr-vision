// Run after ui_fixture.py and tracked_fixture.py against a disposable database.
import {chromium} from 'playwright';
import assert from 'node:assert/strict';

const base=process.env.DUPRVISION_UI_URL||'http://127.0.0.1:3017';
assert.equal(new URL(base).hostname,'127.0.0.1');
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}), errors=[];
  let pickers=0;
  page.on('pageerror',e=>errors.push(e.message));
  page.on('filechooser',()=>pickers++);
  await page.goto(base);
  await page.locator('#email').fill('qa-local@example.test');
  await page.locator('#password').fill('local-ui-test-2026');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.locator('.session-row[data-video="qa-local-0"]').click();
  const video=page.locator('#replay-video');
  await page.waitForFunction(()=>document.getElementById('replay-video')?.readyState>=2);
  assert.match(await video.getAttribute('src'),/\/evidence\/1\/clip$/);
  assert.equal(await page.locator('[data-overlay="tracked"]').getAttribute('aria-pressed'),'true');
  await video.evaluate(v=>{v.pause();v.currentTime=2;});
  await page.waitForFunction(()=>document.getElementById('tracking-overlay').dataset.tracked==='true');
  const pixels=()=>page.locator('#tracking-overlay').evaluate(c=>{
    const data=c.getContext('2d').getImageData(0,0,c.width,c.height).data;
    let count=0;for(let i=3;i<data.length;i+=4)if(data[i])count++;return count;
  });
  assert.ok(await pixels()>100,'Tracked view must paint real annotations');
  const first=await page.locator('#tracking-overlay').evaluate(c=>c.toDataURL());
  await video.evaluate(v=>{v.currentTime=2.8;});
  await page.waitForFunction(()=>Math.abs(document.getElementById('replay-video').currentTime-2.8)<.01&&!document.getElementById('replay-video').seeking);
  assert.notEqual(await page.locator('#tracking-overlay').evaluate(c=>c.toDataURL()),first,'Outline must move with the selected player');
  await page.locator('[data-overlay="original"]').click();
  assert.equal(await pixels(),0,'Original mode must remove the overlay');
  await page.locator('[data-overlay="tracked"]').click();
  assert.ok(await pixels()>100);
  const before=await video.evaluate(v=>v.currentTime);
  await page.getByRole('button',{name:'Next frame',exact:true}).click();
  assert.ok(Math.abs(await video.evaluate(v=>v.currentTime)-before-1/30)<.002);
  await page.locator('#replay-speed').selectOption('0.25');
  assert.equal(await video.evaluate(v=>v.playbackRate),.25);
  await page.locator('#review-loop').uncheck();
  assert.equal(await video.evaluate(v=>v.loop),false);
  await page.locator('#review-loop').check();
  await page.locator('#shot-filter').selectOption('drop');
  assert.equal(await page.locator('.shot-event').count(),1);
  await page.locator('#shot-filter').selectOption('all');
  await page.locator('[data-moment="2"]').click();
  await page.waitForFunction(()=>document.getElementById('replay-video')?.readyState>=2);
  assert.match(await video.getAttribute('src'),/\/evidence\/2\/clip$/);
  assert.equal(pickers,0,'Saved moments must never open a file picker');
  await video.evaluate(v=>{v.pause();v.currentTime=2;});
  await page.waitForFunction(()=>document.getElementById('tracking-overlay').dataset.tracked==='true');
  await page.getByRole('button',{name:'Expand',exact:true}).click();
  assert.equal(await page.evaluate(()=>document.fullscreenElement?.className),'review-stage');
  assert.ok(await pixels()>100,'Fullscreen must retain the overlay');
  await page.evaluate(()=>document.exitFullscreen());
  for(const width of [1440,768,390,320]) {
    await page.setViewportSize({width,height:width>800?1000:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`Overflow at ${width}`);
    await page.screenshot({path:`/tmp/duprvision-tracked-${width}.png`,fullPage:true});
  }
  assert.equal(await page.evaluate(()=>trackingBox([[0,.1,.2,.3,.4],[1,.2,.3,.4,.5]],.5)),null,'Never interpolate through tracking gaps');
  await page.reload();
  await page.waitForFunction(()=>document.getElementById('replay-video')?.readyState>=2);
  assert.equal(await page.evaluate(()=>replay),null);
  assert.match(await video.getAttribute('src'),/\/evidence\/1\/clip$/);
  await page.route('**/api/videos',async route=>{
    const response=await route.fetch(),rows=await response.json();
    const report=rows.find(v=>v.id==='qa-local-0').result;
    delete report.player_track;report.evidence.forEach(m=>delete m.clip);
    await route.fulfill({response,json:rows});
  });
  await page.reload();
  await page.locator('[data-moment="2"]').click();
  await page.waitForFunction(()=>document.querySelector('.tracked-still')?.naturalWidth>0);
  assert.match(await page.locator('.tracked-still').getAttribute('src'),/\/evidence\/2$/);
  assert.equal(await video.count(),0);
  assert.equal(pickers,0,'Legacy tracked frames should enlarge directly');
  assert.deepEqual(errors,[]);
  console.log('Tracked review passed: actual moving overlay, mode toggle, frame step, slow motion, loop, filters, fullscreen, persisted clips, legacy frames, mobile layout.');
} finally {await browser.close();}
