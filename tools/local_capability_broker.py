#!/usr/bin/env python3
"""Host-neutral bounded capability broker for local ICM workers."""
from __future__ import annotations
import argparse,json,subprocess,sys
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/'tools'
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
import local_execution
class BrokerError(ValueError): pass

def _read(path:Path,label:str):
 try: v=json.loads(path.read_text(encoding='utf-8-sig'))
 except (OSError,json.JSONDecodeError) as exc: raise BrokerError(f'cannot load {label}: {exc}') from exc
 if not isinstance(v,dict): raise BrokerError(f'{label} root must be object')
 return v

def load_policy(root:Path=ROOT):
 p=_read(root/'config/local_capability_broker_policy.json','broker policy')
 req={'schema_version','capabilities','target_kinds','max_search_results','max_search_file_bytes','max_read_bytes','max_diff_bytes','max_test_seconds','arbitrary_shell','canonical_mutation','execution_authority','mutation_authority'}
 if set(p)!=req or p['schema_version']!='1.0' or p['arbitrary_shell'] is not False or p['canonical_mutation'] is not False or p['execution_authority']!='NONE' or p['mutation_authority']!='NONE': raise BrokerError('broker safety contract invalid')
 if len(p['capabilities'])!=len(set(p['capabilities'])) or not p['capabilities']: raise BrokerError('broker capabilities invalid')
 return p

def _rel(value):
 if not isinstance(value,str) or not value.strip(): raise BrokerError('path must be non-empty')
 p=PurePosixPath(value.strip().replace('\\','/'))
 if p.is_absolute() or '..' in p.parts or not p.parts: raise BrokerError('path must be confined relative')
 return p.as_posix()

def _target(kind:str,target_id:str,root:Path):
 if kind=='LIVE_SNAPSHOT':
  snap=local_execution.live_snapshot(target_id,root); return Path(snap['workspace_path']),{'kind':kind,'id':target_id,'snapshot_fingerprint':snap['snapshot_fingerprint'],'base_revision':snap['base_revision'],'mutation_scope':[]}
 if kind=='ISOLATED_JOB':
  h=local_execution.worker_handoff(target_id,root); return Path(h['worktree_path']),{'kind':kind,'id':target_id,'base_revision':h['base_revision'],'mutation_scope':h['mutation_scope']}
 raise BrokerError('unknown target kind')
def _confined(base:Path,rel:str)->Path:
 p=(base/Path(*PurePosixPath(_rel(rel)).parts)).resolve()
 try: p.relative_to(base.resolve())
 except ValueError as exc: raise BrokerError('path escapes target') from exc
 return p

def _matches_scope(path:str,scope:str):
 if scope.endswith('/**'):
  q=scope[:-3]; return path==q or path.startswith(q+'/')
 return path==scope

def _git(base:Path,*args:str,limit:int|None=None):
 pr=subprocess.run(['git',*args],cwd=base,text=True,capture_output=True,check=False)
 if pr.returncode!=0: raise BrokerError(pr.stderr.strip() or 'git capability failed')
 out=pr.stdout
 if limit is not None and len(out.encode())>limit: raise BrokerError('broker output exceeds configured bound')
 return out

def execute(req:dict,root:Path=ROOT):
 p=load_policy(root); required={'schema_version','target_kind','target_id','capability','args'}
 if not isinstance(req,dict) or set(req)!=required or req.get('schema_version')!='1.0': raise BrokerError('broker request fields invalid')
 if req['target_kind'] not in p['target_kinds'] or req['capability'] not in p['capabilities'] or not isinstance(req['target_id'],str) or not req['target_id']: raise BrokerError('broker target/capability invalid')
 if not isinstance(req['args'],dict): raise BrokerError('broker args must be object')
 base,identity=_target(req['target_kind'],req['target_id'],root); cap=req['capability']; a=req['args']
 if cap=='SOURCE_READ':
  if set(a)-{'path','start_line','end_line'}: raise BrokerError('SOURCE_READ args invalid')
  path=_confined(base,a.get('path')); data=path.read_bytes()
  if len(data)>p['max_read_bytes']: raise BrokerError('source read exceeds byte bound')
  try: text=data.decode('utf-8-sig')
  except UnicodeDecodeError as exc: raise BrokerError('source is not UTF-8 text') from exc
  lines=text.splitlines(); start=a.get('start_line',1); end=a.get('end_line',len(lines))
  if not isinstance(start,int) or not isinstance(end,int) or start<1 or end<start or end>len(lines): raise BrokerError('source line bounds invalid')
  result={'path':_rel(a['path']),'line_start':start,'line_end':end,'text':'\n'.join(lines[start-1:end])+('\n' if end>=start else '')}
 elif cap=='SOURCE_SEARCH':
  if set(a)-{'query','paths'}: raise BrokerError('SOURCE_SEARCH args invalid')
  q=a.get('query'); paths=a.get('paths', ['.'])
  if not isinstance(q,str) or not q or not isinstance(paths,list) or not paths: raise BrokerError('search query/paths invalid')
  hits=[]
  roots=[base if x=='.' else _confined(base,x) for x in paths]
  for sr in roots:
   files=[sr] if sr.is_file() else sr.rglob('*')
   for f in files:
    if len(hits)>=p['max_search_results']: break
    if not f.is_file() or '.git' in f.parts or f.stat().st_size>p['max_search_file_bytes']: continue
    try: lines=f.read_text(encoding='utf-8-sig').splitlines()
    except (UnicodeDecodeError,OSError): continue
    for i,line in enumerate(lines,1):
     if q.lower() in line.lower():
      hits.append({'path':f.relative_to(base).as_posix(),'line':i,'text':line[:500]})
      if len(hits)>=p['max_search_results']: break
   if len(hits)>=p['max_search_results']: break
  result={'query':q,'hits':hits,'truncated':len(hits)>=p['max_search_results']}
 elif cap=='GIT_STATUS':
  if identity['kind']!='ISOLATED_JOB' or a: raise BrokerError('GIT_STATUS requires isolated job and empty args')
  result={'porcelain':_git(base,'status','--porcelain=v1','--untracked-files=all',limit=p['max_diff_bytes']).splitlines()}
 elif cap=='GIT_DIFF':
  if identity['kind']!='ISOLATED_JOB' or set(a)-{'cached'}: raise BrokerError('GIT_DIFF args invalid')
  args=['diff'];
  if a.get('cached') is True: args.append('--cached')
  result={'diff':_git(base,*args,limit=p['max_diff_bytes'])}
 elif cap=='TEST_SUITE':
  if set(a)!={'suite'}: raise BrokerError('TEST_SUITE args invalid')
  suite=a['suite']; lep=local_execution.load_policy(root)
  if suite not in lep['verify_suites']: raise BrokerError('unknown test suite')
  pr=subprocess.run([sys.executable,*lep['verify_suites'][suite]],cwd=base,text=True,capture_output=True,check=False,timeout=p['max_test_seconds'])
  result={'suite':suite,'returncode':pr.returncode,'outcome':'PASS' if pr.returncode==0 else 'FAIL','stdout_tail':pr.stdout[-4000:],'stderr_tail':pr.stderr[-4000:]}
 else:
  if identity['kind']!='ISOLATED_JOB' or set(a)!={'patch'} or not isinstance(a['patch'],str): raise BrokerError('PATCH_VALIDATE args invalid')
  patch=a['patch'].encode(); parsed=subprocess.run(['git','apply','--numstat','-z','--recount','-'],cwd=base,input=patch,capture_output=True,check=False)
  if parsed.returncode!=0: raise BrokerError('invalid Git patch')
  paths=[]
  for rec in parsed.stdout.split(b'\0'):
   if not rec: continue
   parts=rec.split(b'\t',2)
   if len(parts)!=3: raise BrokerError('invalid patch framing')
   path=_rel(parts[2].decode()) ; paths.append(path)
  if any(not any(_matches_scope(path,s) for s in identity['mutation_scope']) for path in paths): raise BrokerError('patch escapes isolated mutation scope')
  check=subprocess.run(['git','apply','--check','--recount','-'],cwd=base,input=patch,capture_output=True,check=False)
  result={'valid':check.returncode==0,'paths':paths,'error':None if check.returncode==0 else check.stderr.decode(errors='replace').strip()}
 return {'schema_version':'1.0','capability':cap,'target':identity,'result':result,'arbitrary_shell_used':False,'canonical_mutation':False,'authority':'BOUNDED_LOCAL_CAPABILITY_EVIDENCE'}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('request'); ap.add_argument('--root',default=str(ROOT)); a=ap.parse_args()
 try: out=execute(_read(Path(a.request),'broker request'),Path(a.root).resolve()); print(json.dumps({'valid':True,'result':out},indent=2,ensure_ascii=False)); return 0
 except (BrokerError,subprocess.TimeoutExpired,OSError) as exc: print(json.dumps({'valid':False,'error':str(exc)},indent=2),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
