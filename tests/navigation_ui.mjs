import {chromium} from 'playwright';
import assert from 'node:assert/strict';
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
 const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
 page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:3017');
 await page.locator('#email').fill('qa-local@example.test');await page.locator('#password').fill('local-ui-test-2026');
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByRole('heading',{name:'Recent sessions'}).waitFor();
 assert.deepEqual(await page.locator('nav .nav-item').allTextContents(),['Analyze','Events','Players']);
 assert.equal(await page.locator('.calendar-section,.overview-calendar,.score-summary').count(),0);
 await page.getByRole('button',{name:'View all',exact:true}).click();assert.equal(await page.locator('.session-row').count(),36);
 await page.getByRole('button',{name:'Show recent',exact:true}).click();
 for(const width of [1440,768,390,320]){
  await page.setViewportSize({width,height:900});
  assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`Overflow ${width}`);
  await page.screenshot({path:`/tmp/duprvision-navigation-${width}.png`,fullPage:true});
 }
 await page.getByRole('tab',{name:'Progress',exact:true}).click();
 await page.screenshot({path:'/tmp/duprvision-progress-mobile.png',fullPage:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
 await page.getByRole('button',{name:'About this score'}).click();
 await page.getByRole('dialog').waitFor();await page.keyboard.press('Escape');
 await page.locator('.session-row').first().click();
 await page.getByRole('heading',{name:'Session review'}).waitFor();
 await page.reload();await page.getByRole('heading',{name:'Session review'}).waitFor();
 await page.getByRole('button',{name:'Breakdown',exact:true}).click();await page.locator('.performance-metrics').waitFor();
 await page.getByRole('button',{name:'Events',exact:true}).click();
 await page.getByRole('button',{name:'New event',exact:true}).click();
 await page.getByRole('button',{name:/Play session/}).click();await page.locator('#plan-form').waitFor();
 await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'Calendar',exact:true}).click();await page.locator('.play-grid').waitFor();
 await page.screenshot({path:'/tmp/duprvision-play-mobile.png',fullPage:true});
 await page.getByRole('button',{name:'Players',exact:true}).click();await page.locator('#search-form').waitFor();
 await page.getByRole('button',{name:'Connections 0',exact:true}).click();await page.getByRole('dialog').waitFor();await page.keyboard.press('Escape');
 await page.goBack();await page.getByRole('group',{name:'Play views'}).waitFor();
 await page.getByRole('button',{name:'Account',exact:true}).click();await page.locator('#profile-form').waitFor();
 assert.deepEqual(errors,[]);console.log('Navigation, report reload, event entry, connections, browser Back and responsive checks passed.');
}finally{await browser.close();}
