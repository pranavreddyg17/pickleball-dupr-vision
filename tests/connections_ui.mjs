import {chromium} from 'playwright';
import assert from 'node:assert/strict';
const base=process.env.DUPRVISION_UI_URL||'http://127.0.0.1:3017';
assert.equal(new URL(base).hostname,'127.0.0.1');
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try {
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);
  await page.locator('#email').fill('qa-local@example.test');
  await page.locator('#password').fill('local-ui-test-2026');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.locator('[data-action="open-connections"]').waitFor();
  assert.equal((await page.request.post(base+'/api/players/qa-follow/follow')).status(),200);
  await page.reload();
  assert.equal(await page.locator('.connection-count').innerText(),'1');
  await page.locator('[data-action="open-connections"]').click();
  await page.getByRole('dialog').getByText('Alex Morgan',{exact:true}).waitFor();
  await page.getByRole('dialog').getByRole('button',{name:'Following',exact:true}).click();
  await page.getByRole('dialog').getByText('Alex Morgan',{exact:true}).waitFor();
  for(const width of [1440,390,320]) {
    await page.setViewportSize({width,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:`/tmp/duprvision-connections-${width}.png`,fullPage:true});
  }
  await page.getByRole('dialog').getByRole('button',{name:'Unfollow',exact:true}).click();
  await page.getByText("You aren't following anyone yet.",{exact:true}).waitFor();
  assert.equal(await page.locator('.connection-count').innerText(),'0');
  await page.getByRole('dialog').getByRole('button',{name:'Followers',exact:true}).click();
  await page.getByText('No followers yet.',{exact:true}).waitFor();
  await page.keyboard.press('Escape');
  assert.equal(await page.evaluate(()=>document.activeElement?.dataset.action),'open-connections');
  assert.equal(await page.locator('.nav-item[aria-current="page"]').innerText(),'Overview');
  for(const [key,title] of [['analyze','Analyze'],['players','Players'],['profile','Account']]) {
    await page.locator(`[data-page="${key}"]`).click();
    await page.getByRole('heading',{name:title,exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:`/tmp/duprvision-${key}-refined.png`,fullPage:true});
  }
  assert.deepEqual(errors,[]);
  console.log('Connections and app-wide UI passed: in-place panel, count, filtering, unfollow, Escape/focus return, all main screens at 320px.');
} finally {await browser.close();}
