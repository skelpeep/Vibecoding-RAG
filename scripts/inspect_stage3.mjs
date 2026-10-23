// Authenticate the skill's real Chrome pages with a freshly issued local login.
// The original inspector runs unchanged; no app route, bypass or test token is added.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { pathToFileURL } from 'node:url';

const skill = process.env.TASTE_SKILL_PATH || 'C:/Users/fi4h/.codex/skills/design-taste-frontend';
const { Browser } = await import(pathToFileURL(resolve(skill, 'scripts/lib/cdp.mjs')).href);
const target = process.argv[2] || 'http://127.0.0.1:5183/org/users';
const username = process.env.STAGE3_QA_USER || 'admin';
let token = '';
if (!target.endsWith('/login')) {
  const credentials = JSON.parse(readFileSync('var/setup/stage2-accounts.json', 'utf8'));
  const response = await fetch('http://127.0.0.1:8102/api/auth/login', {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({username, password: credentials[username]}),
  });
  if (!response.ok) throw new Error(`QA login failed: HTTP ${response.status}`);
  token = (await response.json()).access_token;
}
const newPage = Browser.prototype.newPage;
Browser.prototype.newPage = async function(options) {
  const page = await newPage.call(this, options);
  if (token) await page.send('Page.addScriptToEvaluateOnNewDocument', {source:
    `if (location.origin === 'http://127.0.0.1:5183') sessionStorage.setItem('kb-platform-token', ${JSON.stringify(token)});`});
  const goto = page.goto.bind(page);
  page.goto = async (...args) => {
    const result = await goto(...args);
    await page.eval(`new Promise((resolve, reject) => { const start=Date.now(); const check=()=>{
      if(document.querySelector('h1') && !document.querySelector('.skeleton-list')) return resolve(true);
      if(Date.now()-start>15000) return reject(new Error('Page did not finish loading'));
      setTimeout(check,100);
    }; check(); })`);
    if (token) {
      const actual = await page.eval('location.pathname');
      if (actual !== new URL(target).pathname) throw new Error('Protected page redirected; refusing login-page inspection');
    }
    if (process.env.STAGE3_QA_DETAIL === '1') await page.eval(`document.querySelector('.object-row,.department-row')?.click()`);
    return result;
  };
  return page;
};
process.argv = [process.argv[0], resolve(skill, 'scripts/inspect.mjs'), target, '--app', ...process.argv.slice(3)];
await import(pathToFileURL(resolve(skill, 'scripts/inspect.mjs')).href);
