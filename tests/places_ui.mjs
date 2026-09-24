import {chromium} from 'playwright';
import assert from 'node:assert/strict';
const base=process.env.DUPRVISION_UI_URL||'http://127.0.0.1:3017';
assert.equal(new URL(base).hostname,'127.0.0.1');
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
try {
  const page=await browser.newPage({viewport:{width:1280,height:1000},locale:'en-US',timezoneId:'America/Chicago'}),errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  // Deterministic tiles avoid automated pan/zoom traffic to community tile servers.
  await page.route('https://tile.openstreetmap.org/**',route=>route.fulfill({contentType:'image/svg+xml',body:'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256"><rect width="256" height="256" fill="#eef1ec"/><path d="M0 128H256M128 0V256" stroke="white" stroke-width="12"/><text x="15" y="35" fill="#637060" font-size="12">Map test tile</text></svg>'}));
  const place={location:'Court search fixture',address:'100 Main Street, Dallas, Texas',latitude:32.8,longitude:-96.8};
  await page.route('**/api/places/search',route=>route.fulfill({json:{places:[place]}}));
  await page.goto(base);
  await page.locator('#email').fill('qa-local@example.test');
  await page.locator('#password').fill('local-ui-test-2026');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.locator('.nav-item[data-page="schedule"]').click();
  await page.getByRole('button',{name:'New event',exact:true}).click();
  await page.getByRole('button',{name:/Play session/}).click();
  await page.locator('#place-query').fill('Court Dallas');
  await page.locator('#place-query').press('Enter');
  await page.getByRole('button',{name:/Court search fixture/}).click();
  await page.getByRole('button',{name:'Map',exact:true}).click();
  await page.locator('.leaflet-marker-icon').waitFor();
  assert.equal(await page.locator('.leaflet-tile-loaded').count()>0,true);
  for(const width of [1280,390,320]) {
    await page.setViewportSize({width,height:1000});
    assert.equal(await page.getByRole('dialog').evaluate(e=>e.scrollWidth>e.clientWidth),false);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
    await page.screenshot({path:`/tmp/duprvision-places-${width}.png`});
  }
  await page.getByRole('button',{name:'Close map',exact:true}).click();
  const date=new Date(Date.now()+2*86400000).toISOString().slice(0,10);
  await page.locator('#plan-start').fill(`${date}T18:00`);
  await page.locator('#plan-end').fill(`${date}T19:30`);
  await page.getByRole('button',{name:'Add',exact:true}).click();
  await page.getByRole('heading',{name:place.location}).waitFor();
  assert.match(await page.getByRole('link',{name:'Open map'}).getAttribute('href'),/32.8%2C-96.8/);
  await page.reload();
  await page.locator('.nav-item[data-page="schedule"]').click();
  await page.getByRole('button',{name:'New event',exact:true}).click();
  await page.getByRole('button',{name:/Play session/}).click();
  await page.getByText('Recent places',{exact:true}).waitFor();
  await page.getByRole('button',{name:/Court search fixture/}).click();
  await page.getByRole('button',{name:'Map',exact:true}).click();
  await page.locator('.leaflet-marker-icon').waitFor();
  await page.locator('.place-map').click({position:{x:180,y:120}});
  await page.locator('#pin-name').waitFor();
  await page.getByRole('button',{name:'Use map center',exact:true}).click();
  await page.locator('#pin-name').fill('Outdoor court fixture');
  await page.getByRole('button',{name:'Close map',exact:true}).click();
  await page.getByRole('button',{name:'Add',exact:true}).click();
  await page.getByRole('heading',{name:'Outdoor court fixture'}).waitFor();
  // Search failure remains recoverable and manual entry clears the old pin.
  await page.getByRole('button',{name:'New event',exact:true}).click();
  await page.getByRole('button',{name:/Play session/}).click();
  await page.unroute('**/api/places/search');
  await page.route('**/api/places/search',route=>route.fulfill({status:503,json:{detail:'Place search is unavailable. Choose on the map or enter the location yourself.'}}));
  await page.locator('#place-query').fill('Unlisted court');
  await page.locator('#place-query').press('Enter');
  await page.getByRole('status').filter({hasText:'Place search is unavailable'}).waitFor();
  await page.getByRole('button',{name:'Enter manually',exact:true}).click();
  await page.locator('#plan-location').fill('Manual court fixture');
  await page.getByRole('button',{name:'Add',exact:true}).click();
  await page.getByRole('heading',{name:'Manual court fixture'}).waitFor();
  assert.deepEqual(errors,[]);
  const saved=await page.request.get(base+'/api/schedule?'+new URLSearchParams({start:new Date().toISOString(),end:new Date(Date.now()+30*86400000).toISOString(),view:'mine'}));
  for(const event of (await saved.json()).events){if([place.location,'Outdoor court fixture','Manual court fixture'].includes(event.location))await page.request.delete(base+'/api/schedule/'+event.id);}
  console.log('Place picker passed: search selection, map and marker rendering, exact links, persistence, recents, pin name, manual fallback and responsive layouts.');
}finally{await browser.close();}
