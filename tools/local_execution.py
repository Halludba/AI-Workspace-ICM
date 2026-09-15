#!/usr/bin/env python3
"""Revision-bound local execution plane with isolated Git worktrees."""
from __future__ import annotations
import argparse,hashlib,io,json,os,platform,re,subprocess,sys,tarfile,tempfile,time
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
SHA40=re.compile(r'^[0-9a-f]{40}$')
JOB=re.compile(r'^[A-Za-z0-9._:-]{1,80}$')
class LocalExecutionError(ValueError): pass

def _read(path:Path,label:str):
 try: v=json.loads(path.read_text(encoding='utf-8-sig'))
 except (OSError,json.JSONDecodeError) as exc: raise LocalExecutionError(f'cannot load {label}: {exc}') from exc
 if not isinstance(v,dict): raise LocalExecutionError(f'{label} root must be object')
 return v

def load_policy(root:Path=ROOT):
 p=_read(root/'config/local_execution_policy.json','local execution policy')
 req={'schema_version','state_root','snapshot_root','max_snapshot_untracked_paths','modes','job_statuses','verification_statuses','evidence_currency','verify_suites','max_jobs','max_scopes','worktree_layout','automatic_merge','shared_mutable_worktree','execution_authority'}
 if set(p)!=req or p['schema_version']!='1.0' or p['automatic_merge'] is not False or p['shared_mutable_worktree'] is not False or p['execution_authority']!='NONE': raise LocalExecutionError('local execution safety contract invalid')
 rel=PurePosixPath(p['state_root'])
 if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0]!='.session': raise LocalExecutionError('state_root must remain under .session')
 snap=PurePosixPath(p['snapshot_root'])
 if snap.is_absolute() or '..' in snap.parts or not snap.parts or snap.parts[0]!='.session': raise LocalExecutionError('snapshot_root must remain under .session')
 if not isinstance(p['max_snapshot_untracked_paths'],int) or isinstance(p['max_snapshot_untracked_paths'],bool) or p['max_snapshot_untracked_paths']<0: raise LocalExecutionError('max_snapshot_untracked_paths invalid')
 if p['worktree_layout']!='SIBLING_DERIVED': raise LocalExecutionError('unsupported worktree layout')
 return p

def _git(root,*args,check=True,text=True):
 pr=subprocess.run(['git',*args],cwd=root,capture_output=True,text=text,check=False)
 if check and pr.returncode!=0: raise LocalExecutionError((pr.stderr if text else pr.stderr.decode(errors='replace')).strip() or 'git failed')
 return pr.stdout

def _commit(root,ref):
 out=_git(root,'rev-parse','--verify',f'{ref}^{{commit}}').strip()
 if not SHA40.fullmatch(out): raise LocalExecutionError('invalid resolved revision')
 return out

def _tree(root,rev): return _git(root,'rev-parse',f'{rev}^{{tree}}').strip()
def _env():
 raw={'python':platform.python_version(),'implementation':platform.python_implementation(),'platform':platform.system(),'release':platform.release(),'machine':platform.machine()}
 return {'details':raw,'fingerprint':hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest()}
def _state_dir(root,p): return root/Path(*PurePosixPath(p['state_root']).parts)
def _job_path(root,p,job): return _state_dir(root,p)/'jobs'/(hashlib.sha256(job.encode()).hexdigest()+'.json')
def _evidence_path(root,p,job): return _state_dir(root,p)/'evidence'/(hashlib.sha256(job.encode()).hexdigest()+'.json')
def _worktree_root(root): return root.parent/(root.name+'.icm-worktrees')
def _worktree_path(root,job): return _worktree_root(root)/hashlib.sha256(job.encode()).hexdigest()[:20]
def _atomic(path,v):
 path.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.tmp',dir=path.parent); tmp=Path(name)
 try:
  with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as h: json.dump(v,h,indent=2); h.write('\n')
  os.replace(tmp,path)
 except Exception: tmp.unlink(missing_ok=True); raise

def _scope(v):
 if not isinstance(v,str) or not v.strip(): raise LocalExecutionError('scope must be non-empty')
 s=v.strip().replace('\\','/'); suffix=s.endswith('/**'); core=s[:-3] if suffix else s; p=PurePosixPath(core)
 if p.is_absolute() or '..' in p.parts or not p.parts: raise LocalExecutionError('scope must be confined relative path')
 return p.as_posix()+('/**' if suffix else '')
def scopes_overlap(a:list[str],b:list[str]):
 aa=[_scope(x) for x in a]; bb=[_scope(x) for x in b]; hits=[]
 def one(x,y):
  xd=x.endswith('/**'); yd=y.endswith('/**'); xp=x[:-3] if xd else x; yp=y[:-3] if yd else y
  if not xd and not yd: return xp==yp
  if xd and yd: return xp==yp or xp.startswith(yp+'/') or yp.startswith(xp+'/')
  if xd: return yp==xp or yp.startswith(xp+'/')
  return xp==yp or xp.startswith(yp+'/')
 for x in aa:
  for y in bb:
   if one(x,y): hits.append([x,y])
 return {'overlap':bool(hits),'pairs':hits}




def _canonical_status(root:Path)->str:
 lines=_git(root,'status','--porcelain=v1','--untracked-files=all').splitlines(); kept=[]
 for line in lines:
  path=line[3:].replace('\\','/') if len(line)>=4 else ''
  if path=='.session' or path.startswith('.session/'): continue
  kept.append(line)
 return '\n'.join(kept)+('\n' if kept else '')

def _confined_rel(value:str,label:str='path')->str:
 if not isinstance(value,str) or not value.strip(): raise LocalExecutionError(f'{label} must be non-empty')
 rel=PurePosixPath(value.strip().replace('\\','/'))
 if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.as_posix() in {'','.'}: raise LocalExecutionError(f'{label} must be workspace-relative and confined')
 return rel.as_posix()

def _git_env(root:Path,index_file:Path,*args:str,text=True,check=True):
 env=os.environ.copy(); env['GIT_INDEX_FILE']=str(index_file)
 pr=subprocess.run(['git',*args],cwd=root,capture_output=True,text=text,check=False,env=env)
 if check and pr.returncode!=0:
  err=pr.stderr if text else pr.stderr.decode(errors='replace')
  raise LocalExecutionError(err.strip() or 'git snapshot plumbing failed')
 return pr.stdout

def _snapshot_alias_path(root:Path,p:dict,snapshot_id:str)->Path:
 return _state_dir(root,p)/'snapshot-aliases'/(hashlib.sha256(snapshot_id.encode()).hexdigest()+'.json')

def _snapshot_base(root:Path,p:dict)->Path:
 return root/Path(*PurePosixPath(p['snapshot_root']).parts)

def create_live_snapshot(snapshot_id:str,include_untracked:list[str]|None=None,root:Path=ROOT):
 p=load_policy(root)
 if not isinstance(snapshot_id,str) or not JOB.fullmatch(snapshot_id): raise LocalExecutionError('snapshot_id invalid')
 paths=include_untracked or []
 if not isinstance(paths,list) or len(paths)>p['max_snapshot_untracked_paths']: raise LocalExecutionError('include_untracked invalid or exceeds bound')
 paths=[_confined_rel(v,'snapshot untracked path') for v in paths]
 if len(paths)!=len(set(paths)): raise LocalExecutionError('snapshot untracked paths must be unique')
 before_status=_canonical_status(root)
 base=_commit(root,'HEAD'); base_tree=_tree(root,base); index_tree=_git(root,'write-tree').strip()
 tmp_parent=_state_dir(root,p).parent; tmp_parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(prefix='icm-snapshot-index-',dir=str(tmp_parent)); os.close(fd); idx=Path(name); idx.unlink(missing_ok=True)
 try:
  _git_env(root,idx,'read-tree',base)
  _git_env(root,idx,'add','-u','--','.')
  for rel in paths:
   full=(root/Path(*PurePosixPath(rel).parts)).resolve()
   try: full.relative_to(root.resolve())
   except ValueError as exc: raise LocalExecutionError('snapshot path escapes workspace') from exc
   if not full.exists(): raise LocalExecutionError(f'snapshot untracked path missing: {rel}')
   ign=subprocess.run(['git','check-ignore','-q','--',rel],cwd=root,check=False)
   if ign.returncode==0: raise LocalExecutionError(f'ignored path cannot enter live snapshot: {rel}')
   _git_env(root,idx,'add','--',rel)
  snap_tree=_git_env(root,idx,'write-tree').strip()
  delta=_git_env(root,idx,'diff','--cached','--name-status',base).splitlines()
  payload={'schema_version':'1.0','snapshot_id':snapshot_id,'base_revision':base,'base_tree':base_tree,'index_tree':index_tree,'snapshot_tree':snap_tree,'included_untracked':paths,'worktree_status':before_status.splitlines()}
  fingerprint=hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  snap_dir=_snapshot_base(root,p)/fingerprint; workspace=snap_dir/'workspace'; manifest=snap_dir/'manifest.json'
  if not manifest.exists():
   archive=subprocess.run(['git','archive','--format=tar',snap_tree],cwd=root,capture_output=True,check=False)
   if archive.returncode!=0: raise LocalExecutionError(archive.stderr.decode(errors='replace').strip() or 'cannot archive live snapshot tree')
   workspace.mkdir(parents=True,exist_ok=True)
   with tarfile.open(fileobj=io.BytesIO(archive.stdout),mode='r:') as tf:
    for member in tf.getmembers():
     target=(workspace/member.name).resolve()
     try: target.relative_to(workspace.resolve())
     except ValueError as exc: raise LocalExecutionError('snapshot archive path escapes destination') from exc
    tf.extractall(workspace,filter='data')
   record={**payload,'snapshot_fingerprint':fingerprint,'changed_paths':[line.split('\t')[-1] for line in delta if line],'workspace_path':str(workspace),'authority':'DERIVED_IMMUTABLE_LIVE_SNAPSHOT','canonical_mutation':False}
   _atomic(manifest,record)
  else: record=_read(manifest,'live snapshot manifest')
  alias={'schema_version':'1.0','snapshot_id':snapshot_id,'snapshot_fingerprint':fingerprint,'manifest_path':str(manifest),'authority':'NONCANONICAL_SNAPSHOT_ALIAS'}; _atomic(_snapshot_alias_path(root,p,snapshot_id),alias)
  after_status=_canonical_status(root)
  if after_status!=before_status or _commit(root,'HEAD')!=base or _git(root,'write-tree').strip()!=index_tree: raise LocalExecutionError('live snapshot unexpectedly changed canonical Git/worktree state')
  return record
 finally: idx.unlink(missing_ok=True)

def live_snapshot(snapshot_id:str,root:Path=ROOT):
 p=load_policy(root); alias=_read(_snapshot_alias_path(root,p,snapshot_id),'snapshot alias'); return _read(Path(alias['manifest_path']),'live snapshot manifest')

def verify_live_snapshot(snapshot_id:str,suite:str='FULL_REGRESSION',root:Path=ROOT):
 p=load_policy(root); snap=live_snapshot(snapshot_id,root)
 if suite not in p['verify_suites']: raise LocalExecutionError('unknown verification suite')
 workspace=Path(snap['workspace_path']); start=time.perf_counter(); proc=subprocess.run([sys.executable,*p['verify_suites'][suite]],cwd=workspace,text=True,capture_output=True,check=False); wall=(time.perf_counter()-start)*1000.0
 log=_state_dir(root,p)/'logs'/('snapshot-'+snap['snapshot_fingerprint'][:24]+'.log'); log.parent.mkdir(parents=True,exist_ok=True); log.write_text((proc.stdout or '')+(proc.stderr or ''),encoding='utf-8')
 env=_env(); ev={'schema_version':'1.0','snapshot_id':snapshot_id,'tested_snapshot_fingerprint':snap['snapshot_fingerprint'],'tested_snapshot_tree':snap['snapshot_tree'],'base_revision':snap['base_revision'],'suite':suite,'outcome':'PASS' if proc.returncode==0 else 'FAIL','returncode':proc.returncode,'wall_time_ms':round(wall,3),'environment_fingerprint':env['fingerprint'],'log_ref':log.relative_to(root).as_posix(),'authority':'DERIVED_SNAPSHOT_VERIFICATION_EVIDENCE','execution_authority':'NONE'}
 return ev

def _suite_fingerprint(root,rev,suite):
 p=load_policy(root)
 if suite not in p['verify_suites']: raise LocalExecutionError('unknown verification suite')
 try: tests_tree=_git(root,'rev-parse',f'{rev}:tests').strip()
 except LocalExecutionError: tests_tree='MISSING'
 raw={'suite':suite,'tests_tree':tests_tree,'argv':p['verify_suites'][suite]}
 return hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def create_job(req:dict,root:Path=ROOT):
 p=load_policy(root); required={'job_id','mode','base_revision','suite','mutation_scope','owner'}
 if not isinstance(req,dict) or set(req)!=required: raise LocalExecutionError('job request fields invalid')
 job=req['job_id'];
 if not isinstance(job,str) or not JOB.fullmatch(job): raise LocalExecutionError('job_id invalid')
 if req['mode'] not in p['modes']: raise LocalExecutionError('mode invalid')
 rev=_commit(root,req['base_revision']); scopes=req['mutation_scope']
 if not isinstance(scopes,list) or len(scopes)>p['max_scopes']: raise LocalExecutionError('mutation_scope invalid')
 scopes=[_scope(x) for x in scopes]
 if req['mode']=='SNAPSHOT_VERIFY' and scopes: raise LocalExecutionError('snapshot verification cannot mutate')
 if req['mode']=='ISOLATED_MUTATION' and not scopes: raise LocalExecutionError('isolated mutation requires scope')
 if req['mode']=='EXCLUSIVE_LEASE' and not scopes: raise LocalExecutionError('exclusive lease requires scope')
 if req['mode']=='EXCLUSIVE_LEASE':
  jobs=_state_dir(root,p)/'jobs'
  if jobs.exists():
   for existing in jobs.glob('*.json'):
    try: other=_read(existing,'existing job')
    except LocalExecutionError: continue
    if other.get('mode')=='EXCLUSIVE_LEASE' and other.get('status') in {'READY','RUNNING'} and scopes_overlap(scopes,other.get('mutation_scope',[]))['overlap']:
     raise LocalExecutionError('exclusive mutation lease collides with active lease')
 suite=req['suite']
 if req['mode']=='SNAPSHOT_VERIFY' and suite not in p['verify_suites']: raise LocalExecutionError('snapshot verification requires known suite')
 if req['mode']!='SNAPSHOT_VERIFY' and suite is not None: raise LocalExecutionError('suite only valid for snapshot verification')
 if not isinstance(req['owner'],str) or not req['owner'].strip(): raise LocalExecutionError('owner invalid')
 path=_job_path(root,p,job)
 if path.exists(): raise LocalExecutionError('job already exists')
 wt=None
 if req['mode'] in {'SNAPSHOT_VERIFY','ISOLATED_MUTATION'}:
  wt=_worktree_path(root,job); wt.parent.mkdir(parents=True,exist_ok=True)
  _git(root,'worktree','add','--detach',str(wt),rev)
 state={'schema_version':'1.0','job_id':job,'mode':req['mode'],'base_revision':rev,'base_tree':_tree(root,rev),'suite':suite,'mutation_scope':scopes,'owner':req['owner'].strip(),'worktree_path':str(wt) if wt else None,'status':'READY','pid':None,'created_at':time.time(),'authority':'NONCANONICAL_LOCAL_EXECUTION','execution_authority':'NONE'}
 _atomic(path,state); return state

def verification_evidence(job_id:str,outcome:str,root:Path=ROOT,returncode:int|None=None,log_ref:str|None=None):
 p=load_policy(root); state=_read(_job_path(root,p,job_id),'job state')
 if state['mode']!='SNAPSHOT_VERIFY': raise LocalExecutionError('verification evidence requires snapshot job')
 if outcome not in p['verification_statuses']: raise LocalExecutionError('verification outcome invalid')
 env=_env(); ev={'schema_version':'1.0','job_id':job_id,'suite':state['suite'],'outcome':outcome,'tested_revision':state['base_revision'],'tested_tree':state['base_tree'],'suite_fingerprint':_suite_fingerprint(root,state['base_revision'],state['suite']),'environment_fingerprint':env['fingerprint'],'environment':env['details'],'returncode':returncode,'log_ref':log_ref,'authority':'DERIVED_VERIFICATION_EVIDENCE','execution_authority':'NONE'}
 _atomic(_evidence_path(root,p,job_id),ev); return ev

def _meaningful_dirty(root:Path,p:dict)->bool:
 lines=_git(root,'status','--porcelain','--untracked-files=all').splitlines(); prefix=p['state_root'].rstrip('/')+'/'
 for line in lines:
  path=line[3:].replace('\\','/') if len(line)>=4 else ''
  if path==p['state_root'] or path.startswith(prefix): continue
  return True
 return False

def evidence_currency(evidence:dict,root:Path=ROOT):
 p=load_policy(root); current=_commit(root,'HEAD'); current_tree=_tree(root,current); dirty=_meaningful_dirty(root,p); same=(current==evidence.get('tested_revision') and current_tree==evidence.get('tested_tree') and not dirty); passed=evidence.get('outcome')=='PASS'
 status=('CURRENT_SUCCESS' if passed else 'CURRENT_FAILURE') if same else ('STALE_SUCCESS' if passed else 'STALE_FAILURE')
 changed=[]
 if current!=evidence.get('tested_revision') and SHA40.fullmatch(str(evidence.get('tested_revision',''))): changed=[x for x in _git(root,'diff','--name-only',evidence['tested_revision'],current).splitlines() if x]
 return {'status':status,'tested_revision':evidence.get('tested_revision'),'current_revision':current,'current_worktree_dirty':dirty,'changed_paths':changed,'reusable_as_current_proof':status=='CURRENT_SUCCESS','stale_evidence_retained':status=='STALE_SUCCESS','authority':'DERIVED_VERIFICATION_CURRENCY'}

def run_snapshot(job_id:str,root:Path=ROOT):
 p=load_policy(root); path=_job_path(root,p,job_id); state=_read(path,'job state')
 if state['mode']!='SNAPSHOT_VERIFY' or state['status'] not in {'READY','RUNNING'}: raise LocalExecutionError('snapshot job not runnable')
 state['status']='RUNNING'; _atomic(path,state); wt=Path(state['worktree_path']); argv=[sys.executable,*p['verify_suites'][state['suite']]]
 log=_state_dir(root,p)/'logs'/(hashlib.sha256(job_id.encode()).hexdigest()+'.log'); log.parent.mkdir(parents=True,exist_ok=True)
 try:
  proc=subprocess.run(argv,cwd=wt,text=True,capture_output=True,check=False); log.write_text((proc.stdout or '')+(proc.stderr or ''),encoding='utf-8'); outcome='PASS' if proc.returncode==0 else 'FAIL'; ev=verification_evidence(job_id,outcome,root,proc.returncode,log.relative_to(root).as_posix()); state['status']='COMPLETE'; _atomic(path,state); return {'state':state,'evidence':ev}
 except Exception:
  state['status']='FAILED'; _atomic(path,state); raise

def launch_snapshot(job_id:str,root:Path=ROOT):
 p=load_policy(root); path=_job_path(root,p,job_id); state=_read(path,'job state')
 if state['mode']!='SNAPSHOT_VERIFY' or state['status']!='READY': raise LocalExecutionError('snapshot job not ready')
 args=[sys.executable,str(Path(__file__).resolve()),'--root',str(root),'_run-snapshot',job_id]
 kwargs={'cwd':str(root),'stdout':subprocess.DEVNULL,'stderr':subprocess.DEVNULL,'stdin':subprocess.DEVNULL}
 if os.name=='nt': kwargs['creationflags']=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP
 else: kwargs['start_new_session']=True
 proc=subprocess.Popen(args,**kwargs); pid=proc.pid; proc.returncode=0; state['status']='RUNNING'; state['pid']=pid; _atomic(path,state); return {'job_id':job_id,'status':'RUNNING','pid':pid,'authority':'NONCANONICAL_LOCAL_EXECUTION'}

def worker_handoff(job_id:str,root:Path=ROOT):
 p=load_policy(root); state=_read(_job_path(root,p,job_id),'job state')
 if state['mode']!='ISOLATED_MUTATION': raise LocalExecutionError('worker handoff requires isolated mutation job')
 wt=Path(state['worktree_path'])
 if not wt.is_dir() or _commit(wt,'HEAD')!=state['base_revision']: raise LocalExecutionError('isolated worker worktree no longer matches base revision')
 return {'job_id':job_id,'worktree_path':str(wt),'base_revision':state['base_revision'],'mutation_scope':state['mutation_scope'],'invoke_local_worker_inside_worktree':True,'shared_mutable_worktree':False,'automatic_merge':False,'authority':'NONCANONICAL_WORKER_HANDOFF'}

def status(job_id:str,root:Path=ROOT):
 p=load_policy(root); state=_read(_job_path(root,p,job_id),'job state'); out={'job':state}
 ep=_evidence_path(root,p,job_id)
 if ep.exists():
  ev=_read(ep,'verification evidence'); out['evidence']=ev; out['currency']=evidence_currency(ev,root)
 return out

def cleanup(job_id:str,root:Path=ROOT):
 p=load_policy(root); state=_read(_job_path(root,p,job_id),'job state'); wt=state.get('worktree_path')
 if wt and Path(wt).exists(): _git(root,'worktree','remove','--force',wt)
 state['worktree_path']=None
 if state.get('status') in {'READY','RUNNING'}: state['status']='CANCELLED'
 _atomic(_job_path(root,p,job_id),state); return {'job_id':job_id,'worktree_removed':True,'status':state['status'],'evidence_retained':_evidence_path(root,p,job_id).exists()}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--root',default=str(ROOT)); sub=ap.add_subparsers(dest='cmd',required=True)
 sc=sub.add_parser('snapshot-create'); sc.add_argument('snapshot_id'); sc.add_argument('--include-untracked',action='append',default=[]); sv=sub.add_parser('snapshot-verify'); sv.add_argument('snapshot_id'); sv.add_argument('--suite',default='FULL_REGRESSION'); c=sub.add_parser('create'); c.add_argument('request'); l=sub.add_parser('launch'); l.add_argument('job_id'); r=sub.add_parser('run'); r.add_argument('job_id'); s=sub.add_parser('status'); s.add_argument('job_id'); x=sub.add_parser('cleanup'); x.add_argument('job_id'); wh=sub.add_parser('worker-handoff'); wh.add_argument('job_id'); co=sub.add_parser('collision'); co.add_argument('a'); co.add_argument('b'); internal=sub.add_parser('_run-snapshot'); internal.add_argument('job_id')
 a=ap.parse_args(); root=Path(a.root).resolve()
 try:
  if a.cmd=='snapshot-create': out=create_live_snapshot(a.snapshot_id,a.include_untracked,root)
  elif a.cmd=='snapshot-verify': out=verify_live_snapshot(a.snapshot_id,a.suite,root)
  elif a.cmd=='create': out=create_job(_read(Path(a.request),'job request'),root)
  elif a.cmd=='launch': out=launch_snapshot(a.job_id,root)
  elif a.cmd in {'run','_run-snapshot'}: out=run_snapshot(a.job_id,root)
  elif a.cmd=='status': out=status(a.job_id,root)
  elif a.cmd=='cleanup': out=cleanup(a.job_id,root)
  elif a.cmd=='worker-handoff': out=worker_handoff(a.job_id,root)
  else: out=scopes_overlap(json.loads(a.a),json.loads(a.b))
  print(json.dumps({'valid':True,'result':out},indent=2,ensure_ascii=False)); return 0
 except (LocalExecutionError,json.JSONDecodeError) as exc:
  print(json.dumps({'valid':False,'error':str(exc)},indent=2),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
