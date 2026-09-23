import {chromium, request} from 'playwright';
import {mkdtemp, mkdir, copyFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';

const base = process.env.DEMO_URL || 'http://127.0.0.1:3001';
const target = new URL(base);
if (!['localhost','127.0.0.1'].includes(target.hostname) || target.port === '3000') {
  throw new Error('Record only against a disposable local instance, never the live app.');
}
const resume = process.env.DEMO_RESUME === '1';
const clip = resolve(process.argv[2] || '');
const output = resolve(process.argv[3] || 'docs/demo-capture.webm');
if (!process.argv[2]) throw new Error('Usage: node scripts/record_demo.mjs /path/to/1.mp4 [output.webm]');

const folder = await mkdtemp(join(tmpdir(), 'duprvision-video-'));
const api = await request.newContext({baseURL: base});
let storageState;
if (resume) {
  const login = await api.post('/api/login', {data:{email:'jordan.demo@example.test',password:'demo-password-only'}});
  if (!login.ok()) throw new Error(`Demo sign-in failed: ${login.status()}`);
  storageState = await api.storageState();
} else {
  const guest = await api.post('/api/register', {data:{email:'taylor.demo@example.test',password:'demo-password-only',display_name:'Taylor Morgan'}});
  if (!guest.ok() && guest.status() !== 409) throw new Error(`Fixture account failed: ${guest.status()}`);
  await api.put('/api/me', {data:{display_name:'Taylor Morgan',discoverable:true}});
}
await api.dispose();

const browser = await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH || '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const context = await browser.newContext({viewport:{width:1280,height:800},recordVideo:{dir:folder,size:{width:1280,height:800}},reducedMotion:'reduce',...(storageState?{storageState}:{})});
const page = await context.newPage();
const shot = async (name) => page.screenshot({path:join(folder,`${name}.png`)});
try {
  await page.goto(base, {waitUntil:'networkidle'});
  await page.waitForTimeout(1000);
  if (resume) {
    await page.locator('.session-row').first().click();
  } else {
  await page.getByRole('button',{name:'Create account'}).click();
  await page.waitForTimeout(800);
  await page.getByLabel('Name').fill('Jordan Demo');
  await page.getByLabel('Email').fill('jordan.demo@example.test');
  await page.getByLabel('Password').fill('demo-password-only');
  await page.locator('#auth-form button[type="submit"]').click();
  await page.getByRole('heading',{name:'Jordan Demo'}).waitFor({timeout:15000});
  await page.waitForTimeout(1800);
  await shot('overview-empty');

  await page.locator('nav [data-page="analyze"]').click();
  await page.waitForTimeout(1400);
  await page.locator('#video-input').setInputFiles(clip);
  await page.getByRole('heading',{name:'Select player'}).waitFor({timeout:120000});
  await page.waitForTimeout(1200);
  await shot('select-player');
  await page.locator('#point-x').fill('37');
  await page.locator('#point-y').fill('54');
  await page.locator('#consent').check();
  await page.locator('#external-consent').check();
  await page.waitForTimeout(1200);
  await page.getByRole('button',{name:'Analyze clip'}).click();
  }
  await page.locator('.performance-summary').waitFor({timeout:180000});
  await page.waitForTimeout(2500);
  await shot('report-top');
  await page.mouse.wheel(0,530);
  await page.waitForTimeout(2300);
  await shot('report-details');
  await page.mouse.wheel(0,-700);
  await page.waitForTimeout(900);

  await page.locator('nav [data-page="home"]').click();
  await page.waitForTimeout(2000);
  await shot('overview-scored');
  await page.mouse.wheel(0,430);
  await page.waitForTimeout(1500);
  await page.locator('nav [data-page="players"]').click();
  await page.waitForTimeout(1700);
  await shot('players');
  const follow = page.getByRole('button',{name:'Follow',exact:true});
  if (await follow.count()) {
    await follow.first().click();
    await page.waitForTimeout(1300);
  }
  await page.locator('nav [data-page="profile"]').click();
  await page.waitForTimeout(1800);
  await shot('account');
  await page.locator('nav [data-page="home"]').click();
  await page.waitForTimeout(1600);
} finally {
  const video = page.video();
  await context.close();
  await mkdir(dirname(output),{recursive:true});
  if (video) await copyFile(await video.path(),output);
  await browser.close();
  process.stdout.write(`Capture: ${output}\nFrames: ${folder}\n`);
}
