"""Run the unmodified skill inspector against each authenticated real screen."""
import json
import os
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
fixture=json.loads((ROOT/'docs/evidence/stage6/http.json').read_text(encoding='utf8'))
screens=[('users','/org/users','admin'),('roles','/org/roles','admin'),('departments','/org/departments','admin'),
 ('profile','/profile','kb_admin'),('knowledge','/knowledge','kb_admin'),('import','/knowledge/import','kb_admin'),
 ('editor','/knowledge/new','kb_admin'),('detail','/knowledge/'+fixture['units'][0],'kb_admin'),
 ('chat','/chat','alice'),('dashboard','/dashboard','admin'),('settlement','/settlement','kb_admin'),
 ('published','/settlement?tab=published','kb_admin'),('gaps','/settlement?tab=gaps','kb_admin')]
summary=[]
for name,path,user in screens:
    env={**os.environ,'STAGE6_QA_USER':user}
    env.pop('FINAL_REVIEW_DIALOG',None)
    folder='.taste-skill/release-'+name
    result=subprocess.run(['node','scripts/inspect_final.mjs','http://127.0.0.1:5186'+path,'--out',folder],
        cwd=ROOT,env=env,capture_output=True,text=True,encoding='utf8',timeout=100)
    (ROOT/folder/'stdout.txt').write_text(result.stdout+result.stderr,encoding='utf8')
    summary.append({'screen':name,'path':path,'user':user,'exit_code':result.returncode,'report':folder+'/report.json'})
    print(name, result.stdout.split('RESULT:')[-1].splitlines()[0] if 'RESULT:' in result.stdout else result.stderr[-150:],flush=True)
    (ROOT/'docs/evidence/stage7/inspect-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
assert all(s['exit_code']==0 for s in summary),summary
