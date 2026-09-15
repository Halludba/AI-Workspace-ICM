#!/usr/bin/env python3
"""Bounded external resume coordination from execution-window checkpoints."""
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess,tempfile,time
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
import sys
TOOLS=ROOT/'tools'
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
import session_planner
class ResumeError(ValueError): pass

def _read(path:Path,label:str):
 try: v=json.loads(path.read_text(encoding='utf-8-sig'))
 except (OSError,json.JSONDecodeError) as exc: raise ResumeError(f'cannot load {label}: {exc}') from exc
 if not isinstance(v,dict): raise ResumeError(f'{label} root must be object')
 return v

def load_policy(root:Path=ROOT):
 p=_read(root/'config/resume_supervisor_policy.json','resume supervisor policy')
 req={'schema_version','state_root','authority','max_dispatch_attempts','allowed_targets','automatic_canonical_mutation','automatic_publication','require_window_fingerprint_match','require_base_revision_match'}
 if set(p)!=req or p['schema_version']!='1.0' or p['automatic_canonical_mutation'] is not False or p['automatic_publication'] is not False or p['require_window_fingerprint_match'] is not True or p['require_base_revision_match'] is not True: raise ResumeError('resume supervisor safety contract invalid')
 rel=PurePosixPath(p['state_root'])
 if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0]!='.session': raise ResumeError('state_root must remain under .session')
 if not isinstance(p['allowed_targets'],list) or not p['allowed_targets']: raise ResumeError('allowed_targets invalid')
 return p

def _git(root,*args):
 pr=subprocess.run(['git',*args],cwd=root,text=True,capture_output=True,check=False)
 if pr.returncode!=0: raise ResumeError(pr.stderr.strip() or 'git failed')
 return pr.stdout.strip()

def _atomic(path:Path,v:dict):
 path.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.tmp',dir=path.parent); tmp=Path(name)
 try:
  with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as h: json.dump(v,h,indent=2); h.write('\n')
  os.replace(tmp,path)
 except Exception: tmp.unlink(missing_ok=True); raise

def _window(agent:str,root:Path):
 try: return session_planner._load_window(agent,root,session_planner.load_session_policy(root))
 except Exception as exc: raise ResumeError(f'no resumable execution window: {exc}') from exc

def capture(agent:str,root:Path=ROOT):
 p=load_policy(root); w=_window(agent,root); tasks=w['tasks']; cps=w['checkpoints']; current=None; verified=[]
 for t in tasks:
  state=(cps.get(t['task_id']) or {}).get('state')
  if state=='VERIFIED': verified.append(t['task_id']); continue
  if current is None: current=t
 if current is None: raise ResumeError('execution window already fully verified')
 body={'agent_id':agent,'base_revision':w['base_revision'],'plan_fingerprint':w['plan_fingerprint'],'window_fingerprint':hashlib.sha256(json.dumps({'base_revision':w['base_revision'],'plan_fingerprint':w['plan_fingerprint'],'tasks':tasks},sort_keys=True,separators=(',',':')).encode()).hexdigest(),'verified_prefix':verified,'current_task':{k:current.get(k) for k in ('task_id','title','route_id','target_role')},'allowed_targets':p['allowed_targets']}
 cap={'schema_version':'1.0',**body,'capsule_fingerprint':hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'authority':p['authority'],'canonical_mutation_authority':False,'publication_authority':False}
 path=root/Path(*PurePosixPath(p['state_root']).parts)/'capsules'/(hashlib.sha256(agent.encode()).hexdigest()+'.json'); _atomic(path,cap); return cap

def validate_currency(capsule:dict,root:Path=ROOT):
 p=load_policy(root); w=_window(capsule['agent_id'],root); current=_git(root,'rev-parse','HEAD'); reasons=[]
 if current!=capsule['base_revision']: reasons.append('BASE_REVISION_CHANGED')
 if w['plan_fingerprint']!=capsule['plan_fingerprint']: reasons.append('PLAN_FINGERPRINT_CHANGED')
 current_wfp=hashlib.sha256(json.dumps({'base_revision':w['base_revision'],'plan_fingerprint':w['plan_fingerprint'],'tasks':w['tasks']},sort_keys=True,separators=(',',':')).encode()).hexdigest()
 if current_wfp!=capsule['window_fingerprint']: reasons.append('WINDOW_FINGERPRINT_CHANGED')
 return {'status':'CURRENT' if not reasons else 'STALE','reasons':reasons,'dispatch_allowed':not reasons,'automatic_canonical_mutation':False,'automatic_publication':False,'authority':p['authority']}

def prepare_dispatch(agent:str,target:str,root:Path=ROOT):
 p=load_policy(root)
 if target not in p['allowed_targets']: raise ResumeError('resume target is not allowlisted')
 cap=capture(agent,root); cur=validate_currency(cap,root)
 if not cur['dispatch_allowed']: raise ResumeError('resume capsule is stale: '+','.join(cur['reasons']))
 state_root=root/Path(*PurePosixPath(p['state_root']).parts)/'dispatch'; state_root.mkdir(parents=True,exist_ok=True); path=state_root/(hashlib.sha256((agent+'|'+target).encode()).hexdigest()+'.json')
 old=_read(path,'dispatch state') if path.exists() else {'attempts':0}
 attempts=int(old.get('attempts',0))+1
 if attempts>p['max_dispatch_attempts']: raise ResumeError('resume dispatch attempt budget exhausted')
 out={'schema_version':'1.0','agent_id':agent,'target':target,'attempts':attempts,'status':'READY','capsule_fingerprint':cap['capsule_fingerprint'],'current_task':cap['current_task'],'base_revision':cap['base_revision'],'plan_fingerprint':cap['plan_fingerprint'],'authority':p['authority'],'canonical_mutation_authority':False,'publication_authority':False}
 _atomic(path,out); return out

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--root',default=str(ROOT)); sub=ap.add_subparsers(dest='cmd',required=True); c=sub.add_parser('capture'); c.add_argument('agent'); v=sub.add_parser('validate'); v.add_argument('capsule'); d=sub.add_parser('prepare-dispatch'); d.add_argument('agent'); d.add_argument('target'); a=ap.parse_args(); root=Path(a.root).resolve()
 try:
  out=capture(a.agent,root) if a.cmd=='capture' else (validate_currency(_read(Path(a.capsule),'resume capsule'),root) if a.cmd=='validate' else prepare_dispatch(a.agent,a.target,root)); print(json.dumps({'valid':True,'result':out},indent=2)); return 0
 except ResumeError as exc: print(json.dumps({'valid':False,'error':str(exc)},indent=2)); return 2
if __name__=='__main__': raise SystemExit(main())
