// Requires the disposable tests/ui_fixture.py server, never the production database.
import {chromium} from 'playwright';
import assert from 'node:assert/strict';

const base=process.env.DUPRVISION_UI_URL||'http://127.0.0.1:3017';
assert.equal(new URL(base).hostname,'127.0.0.1');
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1050}}), errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.goto(base);
  await page.locator('#email').fill('qa-local@example.test');
  await page.locator('#password').fill('local-ui-test-2026');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('heading',{name:'Recent sessions'}).waitFor();
  for(const label of ['Active days','Completed analyses','Today'])assert.equal(await page.getByText(label,{exact:true}).count(),0);
  assert.equal(await page.locator('.session-row').count(),6);
  assert.equal(await page.locator('.form-details,.trend-chart').count(),0);
  assert.equal(await page.locator('.topbar nav img').count(),0);
  await page.getByRole('button',{name:'View all',exact:true}).click();
  assert.equal(await page.locator('.session-row').count(),36);
  await page.getByRole('button',{name:'Show recent',exact:true}).click();
  for(const width of [1440,768,390,320]) {
    await page.setViewportSize({width,height:width>800?1050:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`Overflow at ${width}`);
    await page.screenshot({path:`/tmp/duprvision-overview-${width}.png`,fullPage:true});
  }
  await page.locator('.day.level-3').first().click();
  await page.getByRole('heading',{name:'Sessions on this day'}).waitFor();
  assert.equal(await page.locator('.session-row').count(),1);
  await page.getByRole('button',{name:'Clear',exact:true}).click();
  await page.locator('[data-action="open-connections"]').click();
  await page.getByRole('dialog',{name:'Connections 0'}).waitFor();
  await page.getByText('No connections yet.',{exact:true}).waitFor();
  assert.equal(await page.locator('.nav-item[aria-current="page"]').innerText(),'Overview');
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('dialog').count(),0);
  await page.route('**/api/me',async route=>{
    const response=await route.fetch(),user=await response.json();
    await route.fulfill({response,json:{...user,display_name:'A'.repeat(80)}});
  });
  await page.route('**/api/videos',route=>route.fulfill({json:[]}));
  await page.route('**/api/progress',route=>route.fulfill({json:{days:[],metrics:[]}}));
  await page.route('**/api/scores',async route=>{
    const response=await route.fetch(),scores=await response.json();
    await route.fulfill({response,json:{...scores,days:[],average:null,dupr_equivalent:null}});
  });
  await page.goto(base);
  await page.getByRole('heading',{name:'A'.repeat(80)}).waitFor();
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Long name overflow');
  await page.getByText('Your completed sessions will appear here.').waitFor();
  await page.screenshot({path:'/tmp/duprvision-overview-empty-mobile.png',fullPage:true});
  assert.deepEqual(errors,[]);
  console.log('Overview UI passed: text-only navigation, no chart/disclosure, session expansion, day filter, connections dialog, desktop/tablet/mobile layouts.');
} finally {await browser.close();}
