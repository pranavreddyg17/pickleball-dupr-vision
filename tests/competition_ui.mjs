// Run only against the disposable UI fixture server.
import {chromium} from 'playwright';
import assert from 'node:assert/strict';

const base=process.env.DUPRVISION_UI_URL||'http://127.0.0.1:3017';
assert.equal(new URL(base).hostname,'127.0.0.1');
const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.goto(base);
  await page.locator('#email').fill('qa-local@example.test');
  await page.locator('#password').fill('local-ui-test-2026');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.getByRole('heading',{name:'Recent sessions'}).waitFor();
  await page.getByRole('button',{name:'Events',exact:true}).click();
  await page.getByRole('button',{name:'New event',exact:true}).click();
  await page.getByRole('button',{name:/Round robin/}).click();
  await page.locator('#competition-title').fill('Friday at The Picklr');
  await page.getByRole('button',{name:'Enter manually'}).click();
  await page.locator('#plan-location').fill('The Picklr Lewisville');
  await page.locator('#competition-courts').fill('7, 8');
  await page.locator('#competition-minimum').fill('1');
  await page.screenshot({path:'/tmp/duprvision-round-robin-create.png',fullPage:true});
  await page.getByRole('button',{name:'Create event',exact:true}).click();
  await page.getByRole('heading',{name:'Friday at The Picklr'}).waitFor();
  assert.equal(await page.locator('.competition-person').count(),0,'Host must not be added as player');
  await page.getByRole('tab',{name:'Settings',exact:true}).click();
  await page.getByRole('button',{name:'Edit event',exact:true}).click();
  assert.equal(await page.locator('#competition-courts').inputValue(),'7,8');
  await page.getByRole('button',{name:'Save event',exact:true}).click();
  await page.getByRole('dialog').waitFor({state:'hidden'});
  for(let i=1;i<=9;i++){
    await page.getByRole('button',{name:'Add player',exact:true}).click();
    await page.locator('#guest-name').fill(`Guest ${i}`);
    await page.getByRole('button',{name:'Add guest',exact:true}).click();
    const attendance=page.getByRole('combobox',{name:`Attendance for Guest ${i}`,exact:true});
    await attendance.waitFor();
    await attendance.selectOption('ready');
    await page.waitForFunction(name=>Array.from(document.querySelectorAll('[data-comp-attendance]')).find(e=>e.getAttribute('aria-label')===`Attendance for ${name}`)?.value==='ready',`Guest ${i}`);
    await page.waitForFunction(()=>!competition.busy);
  }
  await page.getByRole('tab',{name:'Matches',exact:true}).click();
  await page.getByRole('button',{name:'Generate round',exact:true}).click();
  await page.getByRole('button',{name:'Start round',exact:true}).waitFor();
  assert.equal(await page.locator('.competition-matches .competition-match').count(),2);
  assert.match(await page.locator('.competition-resting').innerText(),/Guest/);
  await page.getByRole('button',{name:'Start round',exact:true}).click();
  await page.getByText('2 matches remaining',{exact:true}).waitFor();
  for(const width of [1440,768,390,320]){
    await page.setViewportSize({width,height:900});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`Overflow at ${width}`);
    await page.screenshot({path:`/tmp/duprvision-round-robin-${width}.png`,fullPage:true});
  }
  for(let i=0;i<2;i++){
    await page.getByRole('button',{name:'Record result',exact:true}).first().click();
    await page.locator('#score-a').fill('11');
    await page.locator('#score-b').fill('7');
    if(i===0){
      await page.route('**/commands',route=>route.abort('failed'),{times:1});
      await page.getByRole('button',{name:'Save result',exact:true}).click();
      await page.locator('.competition-error').waitFor({state:'visible'});
      assert.equal(await page.locator('#score-a').inputValue(),'11');
      await page.getByRole('button',{name:'Close',exact:true}).click();
      await page.getByRole('button',{name:'Record result',exact:true}).first().click();
      assert.equal(await page.locator('#score-b').inputValue(),'7','Unsent score draft must survive closing the form');
    }
    await page.getByRole('button',{name:'Save result',exact:true}).click();
    await page.getByRole('dialog').waitFor({state:'hidden'});
    if(i===0)await page.getByText('1 match remaining',{exact:true}).waitFor();
  }
  await page.getByText('Round complete',{exact:true}).waitFor();
  await page.getByRole('button',{name:'Add round',exact:true}).click();
  await page.getByRole('heading',{name:'Round 2',exact:true}).waitFor();
  await page.getByRole('button',{name:'Discard preview',exact:true}).click();
  await page.getByRole('heading',{name:'Round 1',exact:true}).waitFor();
  await page.getByRole('tab',{name:'Standings',exact:true}).click();
  assert.equal(await page.locator('.competition-standings tbody tr').count(),9);
  await page.screenshot({path:'/tmp/duprvision-round-robin-standings.png',fullPage:true});
  await page.getByRole('tab',{name:'Matches',exact:true}).click();
  await page.getByRole('button',{name:'Invite players',exact:true}).click();
  const invite=await page.locator('#competition-link').inputValue();
  await page.getByRole('button',{name:'Close',exact:true}).click();
  const member=await browser.newPage({viewport:{width:390,height:844}});
  await member.goto(invite);
  await member.locator('#email').fill('qa-follow@example.test');
  await member.locator('#password').fill('local-ui-test-2026');
  await member.getByRole('button',{name:'Sign in',exact:true}).click();
  await member.getByRole('button',{name:'Join event',exact:true}).click();
  await member.getByRole('heading',{name:'Friday at The Picklr'}).waitFor();
  assert.equal(await member.getByRole('button',{name:'Add round',exact:true}).count(),0);
  await page.reload();
  await page.getByRole('heading',{name:'Friday at The Picklr'}).waitFor();
  await page.getByRole('tab',{name:'Settings',exact:true}).click();
  await page.getByRole('button',{name:'Finish event',exact:true}).click();
  await page.locator('#finish-event').click();
  await page.getByText('Finished',{exact:true}).waitFor();
  assert.deepEqual(errors,[]);
  console.log('Round robin UI passed: host-only creation, guest check-in, 9-player rests, live scores, extra round, standings, invite joining, finish, mobile layouts.');
}finally{await browser.close();}
