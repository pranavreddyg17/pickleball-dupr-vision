import {chromium, request} from 'playwright';
import {mkdtemp, mkdir, readFile, writeFile} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import {dirname, join, resolve} from 'node:path';
import {spawnSync} from 'node:child_process';

const base=process.env.DEMO_URL||'http://127.0.0.1:3018';
const target=new URL(base);
if(!['localhost','127.0.0.1'].includes(target.hostname)||['','3000'].includes(target.port))throw Error('Use a disposable local server, never the live app.');
if(!process.argv[2]||!process.argv[3])throw Error('Usage: node scripts/record_demo.mjs /path/to/1.mp4 /path/to/2.mp4 [output.mp4]');
const clips=process.argv.slice(2,4).map(resolvePath=>resolve(resolvePath));
const output=resolve(process.argv[4]||'docs/demo.mp4');
const folder=await mkdtemp(join(tmpdir(),'duprvision-demo-'));
const previous=process.env.DEMO_RESUME_CAPTURE?JSON.parse(await readFile(process.env.DEMO_RESUME_CAPTURE,'utf8')):null;
const email=previous?.email||'demo-'+Date.now()+'@example.test',password='demo-recording-only';
const api=await request.newContext({baseURL:base});
const peer=await api.post('/api/register',{data:{email:'partner-'+Date.now()+'@example.test',password,display_name:'Taylor Morgan'}});
if(!peer.ok())throw Error('Could not prepare demo player.');
await api.put('/api/me',{data:{display_name:'Taylor Morgan',discoverable:true}});
let storageState;
if(previous){const response=await api.post('/api/login',{data:{email,password}});if(!response.ok())throw Error('Cannot resume demo account');storageState=await api.storageState();}
await api.dispose();
const browser=await chromium.launch({headless:true,executablePath:process.env.CHROME_PATH||'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
const context=await browser.newContext({viewport:{width:1440,height:960},recordVideo:{dir:folder,size:{width:1440,height:960}},reducedMotion:'reduce',...(storageState?{storageState}:{})});
const page=await context.newPage(),started=Date.now(),cuts=[],chapters=[],reports=[];
const seconds=()=> (Date.now()-started)/1000;
const hold=async(ms=1500)=>page.waitForTimeout(ms);
const chapter=async title=>{chapters.push({title,at:seconds()});console.log(title);await page.screenshot({path:join(folder,'chapter-'+chapters.length+'.png')});};
const nav=async name=>{await page.locator('nav').getByRole('button',{name,exact:true}).click();await hold();};
let completed=false;
try{
 await page.goto(base);await hold();
 if(!previous){
 await page.getByRole('button',{name:'Create account',exact:true}).click();
 await page.getByLabel('Name',{exact:true}).fill('Jordan Ellis');await page.getByLabel('Email',{exact:true}).fill(email);await page.getByLabel('Password',{exact:true}).fill(password);
 await hold();await page.locator('#auth-form button[type=submit]').click();await page.locator('.workspace-toolbar').waitFor();
 await chapter('Analyze workspace');await hold();
 }
 for(let i=previous?1:0;i<clips.length;i++){
  if(!previous){
  await nav('Analyze');await page.getByRole('button',{name:'Analyze video',exact:true}).click();await hold();
  await chapter('Upload '+(i+1));await page.locator('#video-input').setInputFiles(clips[i]);
  await page.getByRole('heading',{name:'Select player',exact:true}).waitFor({timeout:120000});
  await page.locator('[data-preview="2"]').click();await hold();
  const bounds=await page.locator('#preview-image').boundingBox();
  const point=i===0?{x:.37,y:.51}:{x:.24,y:.36};
  await page.locator('#preview-image').click({position:{x:bounds.width*point.x,y:bounds.height*point.y}});
  await page.locator('#consent').check();if(await page.locator('#external-consent').count())await page.locator('#external-consent').check();
  await chapter('Select player '+(i+1));await hold(2000);
  await page.getByRole('button',{name:'Analyze clip',exact:true}).click();
  }else{
   await page.locator('.session-row').filter({hasText:'2.mp4'}).first().click();
  }
  const waiting=seconds();
  await page.waitForFunction(()=>document.querySelector('.performance-summary')||state.videos.find(v=>v.id===state.selectedId)?.status==='FAILED',{},{timeout:600000});
  if(await page.locator('.failure').count())throw Error(await page.locator('.failure').innerText());
  const ready=seconds();if(ready-waiting>6)cuts.push([waiting+3,ready-1]);
  const video=await page.evaluate(()=>state.videos.find(v=>v.id===state.selectedId));reports.push({file:video.original_filename,score:video.result.performance.score,shots:video.result.performance.observed_shots,status:video.status});
  await chapter('Completed report '+(i+1));await hold(3500);
  await page.locator('.replay-section').scrollIntoViewIfNeeded();await hold();
  const replay=page.locator('#replay-video');if(await replay.count()){await replay.evaluate(video=>video.play());await hold(5500);await replay.evaluate(video=>video.pause());}
  await chapter('Tracked replay '+(i+1));
  await page.getByRole('button',{name:'Breakdown',exact:true}).click();await hold(2500);
  await page.locator('.performance-metrics').scrollIntoViewIfNeeded();await chapter('Score breakdown '+(i+1));await hold(2500);
 }
 await nav('Analyze');await page.getByRole('tab',{name:'Progress',exact:true}).click();await chapter('Daily progress');await hold(2500);
 await nav('Events');await page.getByRole('button',{name:'New event',exact:true}).click();await hold();
 await page.getByRole('button',{name:/Play session/}).click();await page.getByRole('button',{name:'Enter manually',exact:true}).click();
 await page.locator('#plan-location').fill('The Picklr Lewisville');await page.locator('#plan-address').fill('Lewisville, Texas');await page.locator('#plan-kind').selectOption('practice');
 await chapter('Plan a session');await hold();await page.getByRole('button',{name:'Add',exact:true}).click();await page.locator('#plan-form').waitFor({state:'hidden'});await hold();
 await page.getByRole('button',{name:'Calendar',exact:true}).click();await chapter('Events calendar');await hold(2000);
 await page.getByRole('button',{name:'New event',exact:true}).click();await page.getByRole('button',{name:/Round robin/}).click();
 await page.locator('#competition-title').fill('Friday doubles');await page.getByRole('button',{name:'Enter manually',exact:true}).click();await page.locator('#plan-location').fill('The Picklr Lewisville');
 await page.locator('#competition-count').fill('1');await page.locator('#competition-courts').fill('Court 4');await page.locator('#competition-minimum').fill('1');
 await page.getByRole('button',{name:'Create event',exact:true}).click();await page.getByRole('heading',{name:'Friday doubles'}).waitFor();
 for(const name of ['Alex','Sam','Casey','Riley']){await page.getByRole('button',{name:'Add player',exact:true}).click();await page.locator('#guest-name').fill(name);await page.getByRole('button',{name:'Add guest',exact:true}).click();await page.getByRole('combobox',{name:'Attendance for '+name,exact:true}).selectOption('ready');await page.waitForFunction(()=>!competition.busy);}
 await chapter('Organizer and players');await hold(1500);await page.getByRole('tab',{name:'Matches',exact:true}).click();await page.getByRole('button',{name:'Generate round',exact:true}).click();await page.getByRole('button',{name:'Start round',exact:true}).click();await hold(2000);
 await page.getByRole('button',{name:'Record result',exact:true}).click();await page.locator('#score-a').fill('11');await page.locator('#score-b').fill('7');await hold(1500);await page.getByRole('button',{name:'Save result',exact:true}).click();await page.getByRole('dialog').waitFor({state:'hidden'});
 await page.getByRole('tab',{name:'Standings',exact:true}).click();await chapter('Round-robin standings');await hold(2500);
 await nav('Players');await page.getByRole('searchbox',{name:'Search players'}).fill('Taylor');await page.getByRole('button',{name:'Search',exact:true}).click();await page.getByRole('button',{name:'Follow',exact:true}).first().click();await hold();await chapter('Players and following');await hold(2000);
 await nav('Analyze');await page.getByRole('tab',{name:'Sessions',exact:true}).click();await chapter('Both completed reviews');await hold(2500);completed=true;
}finally{
 const video=page.video();await context.close();await browser.close();
 const raw=await video.path();await writeFile(join(folder,'capture.json'),JSON.stringify({base,email,chapters,cuts,reports,raw,completed},null,2));
 console.log('Capture details: '+folder);
 if(completed){
  const duration=Number(spawnSync('ffprobe',['-v','error','-show_entries','format=duration','-of','csv=p=0',raw],{encoding:'utf8'}).stdout.trim());
  const ranges=[];let last=0;
  if(previous){for(const [start,end]of previous.cuts){ranges.push([0,last,start]);last=end;}ranges.push([0,last,previous.chapters.at(-1).at+5]);last=0;}
  for(const [start,end]of cuts){ranges.push([previous?1:0,last,start]);last=end;}ranges.push([previous?1:0,last,duration]);
  const filters=ranges.map(([input,start,end],i)=>'['+input+':v]trim=start='+start+':end='+end+',setpts=PTS-STARTPTS[v'+i+']');
  filters.push(ranges.map((_,i)=>'[v'+i+']').join('')+'concat=n='+ranges.length+':v=1:a=0[out]');
  await mkdir(dirname(output),{recursive:true});
  const result=spawnSync('ffmpeg',['-hide_banner','-loglevel','error','-y',...(previous?['-i',previous.raw]:[]),'-i',raw,'-filter_complex',filters.join(';'),'-map','[out]','-c:v','libx264','-crf','23','-pix_fmt','yuv420p','-movflags','+faststart',output],{stdio:'inherit'});
  if(result.status!==0)throw Error('Demo encoding failed; raw capture retained in '+folder);
  console.log('Demo: '+output);console.log(JSON.stringify(reports));
 }
}
