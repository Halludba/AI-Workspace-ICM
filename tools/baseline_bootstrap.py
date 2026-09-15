#!/usr/bin/env python3
"""Git-backed baseline/delta bootstrap capsules for cheap session orientation."""
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess,tempfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
SHA40=re.compile(r'^[0-9a-f]{40}$')
class BootstrapError(ValueError): pass

def _read(path:Path,label:str):
 try: v=json.loads(path.read_text(encoding='utf-8-sig'))
 except (OSError,json.JSONDecodeError) as exc: raise BootstrapError(f'cannot load {label}: {exc}') from exc
 if not isinstance(v,dict): raise BootstrapError(f'{label} root must be object')
 return v

def load_policy(root:Path=ROOT):
 p=_read(root/'config/bootstrap_policy.json','bootstrap policy')
 req={'schema_version','state_root','authority','orientation_paths','max_changed_paths','include_untracked','reuse_when_unchanged','exact_source_escalation_on_governing_change'}
 if set(p)!=req or p['schema_version']!='1.0' or p['authority']!='DERIVED_NONCANONICAL_BOOTSTRAP': raise BootstrapError('bootstrap policy fields invalid')
 rel=PurePosixPath(p['state_root'])
 if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0]!='.session': raise BootstrapError('state_root must remain under .session')
 if not isinstance(p['orientation_paths'],list) or not p['orientation_paths']: raise BootstrapError('orientation_paths invalid')
 return p

def _git(root,*args,check=True):
 pr=subprocess.run(['git',*args],cwd=root,text=True,capture_output=True,check=False)
 if check and pr.returncode!=0: raise BootstrapError(pr.stderr.strip() or 'git failed')
 return pr.stdout.strip()

def _rev(root,ref='HEAD'):
 out=_git(root,'rev-parse','--verify',f'{ref}^{{commit}}')
 if not SHA40.fullmatch(out): raise BootstrapError('invalid commit identity')
 return out

def _tree(root,rev): return _git(root,'rev-parse',f'{rev}^{{tree}}')
def _sha_bytes(b:bytes): return hashlib.sha256(b).hexdigest()
def _canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()
def _atomic(path:Path,v:dict):
 path.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.tmp',dir=path.parent); tmp=Path(name)
 try:
  with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as h: json.dump(v,h,indent=2); h.write('\n')
  os.replace(tmp,path)
 except Exception: tmp.unlink(missing_ok=True); raise

def _orientation(root:Path,paths:list[str]):
 out=[]
 for rel in paths:
  p=root/rel
  if p.is_file(): out.append({'path':rel,'sha256':_sha_bytes(p.read_bytes()),'bytes':p.stat().st_size})
  else: out.append({'path':rel,'sha256':None,'bytes':None})
 return out

def _state_path(root,p,baseline_id):
 if not isinstance(baseline_id,str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,120}',baseline_id): raise BootstrapError('baseline_id invalid')
 return root/Path(*PurePosixPath(p['state_root']).parts)/(baseline_id+'.json')

def capture(baseline_id:str,root:Path=ROOT):
 p=load_policy(root); rev=_rev(root); tree=_tree(root,rev); orient=_orientation(root,p['orientation_paths'])
 record={'schema_version':'1.0','baseline_id':baseline_id,'revision':rev,'tree':tree,'orientation':orient,'orientation_fingerprint':_sha_bytes(_canon(orient)),'authority':p['authority']}
 record['baseline_fingerprint']=_sha_bytes(_canon({k:record[k] for k in ('revision','tree','orientation_fingerprint')}))
 _atomic(_state_path(root,p,baseline_id),record); return record

def _worktree_changes(root:Path,include_untracked:bool):
 out=[]
 pr=subprocess.run(['git','status','--porcelain=v1','--untracked-files=all' if include_untracked else '--untracked-files=no'],cwd=root,text=True,capture_output=True,check=False)
 if pr.returncode!=0: raise BootstrapError(pr.stderr.strip() or 'git status failed')
 for line in pr.stdout.splitlines():
  if not line: continue
  path=line[3:].replace('\\','/')
  if path.startswith('.session/'): continue
  if ' -> ' in path: path=path.split(' -> ',1)[1]
  out.append(path)
 return sorted(set(out))

def delta(baseline_id:str,root:Path=ROOT):
 p=load_policy(root); base=_read(_state_path(root,p,baseline_id),'baseline'); current=_rev(root); current_tree=_tree(root,current)
 committed=[] if current==base['revision'] else [x for x in _git(root,'diff','--name-only',base['revision'],current).splitlines() if x]
 live=_worktree_changes(root,p['include_untracked']); changed=sorted(set(committed+live))
 if len(changed)>p['max_changed_paths']: raise BootstrapError('changed path count exceeds bootstrap policy')
 orient=_orientation(root,p['orientation_paths']); orient_fp=_sha_bytes(_canon(orient)); governing=sorted(set(changed).intersection(p['orientation_paths']))
 unchanged=(current==base['revision'] and current_tree==base['tree'] and not live and orient_fp==base['orientation_fingerprint'])
 return {'schema_version':'1.0','baseline_id':baseline_id,'baseline_revision':base['revision'],'current_revision':current,'baseline_tree':base['tree'],'current_tree':current_tree,'changed_paths':changed,'changed_path_count':len(changed),'governing_paths_changed':governing,'baseline_reusable':unchanged and p['reuse_when_unchanged'],'orientation_reusable':orient_fp==base['orientation_fingerprint'],'exact_source_escalation_required':bool(governing) and p['exact_source_escalation_on_governing_change'],'bootstrap_mode':'REUSE_BASELINE' if unchanged else 'BASELINE_PLUS_DELTA','authority':p['authority']}

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('--root',default=str(ROOT)); sub=ap.add_subparsers(dest='cmd',required=True); c=sub.add_parser('capture'); c.add_argument('baseline_id'); d=sub.add_parser('delta'); d.add_argument('baseline_id'); a=ap.parse_args(); root=Path(a.root).resolve()
 try: out=capture(a.baseline_id,root) if a.cmd=='capture' else delta(a.baseline_id,root); print(json.dumps({'valid':True,'result':out},indent=2)); return 0
 except BootstrapError as exc: print(json.dumps({'valid':False,'error':str(exc)},indent=2)); return 2
if __name__=='__main__': raise SystemExit(main())
