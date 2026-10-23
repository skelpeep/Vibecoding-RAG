// Unchanged skill inspector, authenticated with a real current account.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
const skill=process.env.TASTE_SKILL_PATH||'C:/Users/fi4h/.codex/skills/design-taste-frontend';
const { Browser }=await import(pathToFileURL(resolve(skill,'scripts/lib/cdp.mjs')).href);
const target=process.argv[2]||'http://127.0.0.1:5185/chat';
const username=process.env.STAGE5_QA_USER||'alice';
const credentials=JSON.parse(readFileSync('var/setup/stage2-accounts.json','utf8'));
const response=await fetch(`${process.env.STAGE5_API_ORIGIN||'http://127.0.0.1:8104'}/api/auth/login`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username,password:credentials[username]})});
if(!response.ok)throw Error(`Login failed: ${response.status}`);
const token=(await response.json()).access_token;
const newPage=Browser.prototype.newPage;
Browser.prototype.newPage=async function(options){
 const page=await newPage.call(this,options);
 await page.send('Page.addScriptToEvaluateOnNewDocument',{source:`if(location.origin===${JSON.stringify(new URL(target).origin)})sessionStorage.setItem('kb-platform-token',${JSON.stringify(token)});`});
 const goto=page.goto.bind(page);
 page.goto=async(...args)=>{
  const result=await goto(...args);
  await page.eval(`new Promise((resolve,reject)=>{const start=Date.now();function check(){if(document.querySelector('h1')&&!document.querySelector('.chat-skeleton'))return resolve(true);if(Date.now()-start>20000)return reject(Error('Page did not load'));setTimeout(check,100)}check()})`);
  if(await page.eval('location.pathname')!==new URL(target).pathname)throw Error('Protected route redirected');
  if(process.env.STAGE5_QA_SESSION){
   await page.eval(`(()=>{const button=Array.from(document.querySelectorAll('.chat-session-select')).find(x=>x.textContent.includes(${JSON.stringify(process.env.STAGE5_QA_SESSION)}));if(!button)throw Error('QA session not found');button.click()})()`);
   await page.eval(`new Promise((resolve,reject)=>{const start=Date.now();function check(){if(document.querySelector('.chat-detail-open')&&!document.querySelector('.chat-history-skeleton'))return resolve(true);if(Date.now()-start>20000)return reject(Error('History did not load'));setTimeout(check,100)}check()})`);
  }
  if(process.env.STAGE5_QA_CITATION==='1'){
   await page.eval(`(()=>{const button=document.querySelector('.chat-source-button');if(!button)throw Error('Citation not found');button.click()})()`);
   await page.eval(`new Promise((resolve,reject)=>{const start=Date.now();function check(){if(document.querySelector('.chat-citation-detail'))return resolve(true);if(Date.now()-start>20000)return reject(Error('Citation did not load'));setTimeout(check,100)}check()})`);
   await page.eval('Promise.all(document.getAnimations().map(animation=>animation.finished.catch(()=>{})))');
  }
  return result;
 };return page;
};
process.argv=[process.argv[0],resolve(skill,'scripts/inspect.mjs'),target,'--app',...process.argv.slice(3)];
await import(pathToFileURL(resolve(skill,'scripts/inspect.mjs')).href);
