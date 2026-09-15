#!/usr/bin/env python3
"""Content-addressed validated-state evidence reuse and host capability facts."""
from __future__ import annotations
import argparse,hashlib,json,os,re,subprocess,tempfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
class EvidenceReuseError(ValueError): pass

def _read(path:Path,label:str):
 try: v=json.loads(path.read_text(encoding='utf-8-sig'))
 except (OSError,json.JSONDecodeError) as exc: raise EvidenceReuseError(f'cannot load {label}: {exc}') from exc
 if not isinstance(v,dict): raise EvidenceReuseError(f'{label} root must be object')
 return v

def load_policy(root:Path=ROOT):
 p=_read(root/'config/evidence_reuse_policy.json','evidence reuse policy')
 req={'schema_version','state_root','host_profile_root','volatility_classes','reusable_classes','host_fact_classes','durable_host_fact_classes','max_inputs','max_evidence_refs','max_summary_chars','canonical','execution_authority','automatic_authority'}
 if set(p)!=req or p['schema_version']!='1.0' or p['canonical'] is not False or p['execution_authority']!='NONE' or p['automatic_authority'] is not False: raise EvidenceReuseError('evidence reuse policy safety contract invalid')
 for key in ('state_root','host_profile_root'):
  rel=PurePosixPath(str(p[key]).replace('\\','/'))
  if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0]!='.session': raise EvidenceReuseError(f'{key} must remain under .session')
 if set(p['reusable_classes'])-set(p['volatility_classes']): raise EvidenceReuseError('reusable_classes invalid')
 if set(p['durable_host_fact_classes'])-set(p['host_fact_classes']): raise EvidenceReuseError('durable_host_fact_classes invalid')
 for k in ('max_inputs','max_evidence_refs','max_summary_chars'):
  if isinstance(p[k],bool) or not isinstance(p[k],int) or p[k]<1: raise EvidenceReuseError(f'{k} invalid')
 return p

def _canon(v): return json.dumps(v,sort_keys=True,separators=(',',':'),ensure_ascii=False)
def _hash(v): return hashlib.sha256((_canon(v) if not isinstance(v,(bytes,bytearray)) else bytes(v)).encode('utf-8') if not isinstance(v,(bytes,bytearray)) else bytes(v)).hexdigest()
def _atomic(path:Path,v:dict):
 path.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(prefix='.'+path.name+'.',suffix='.tmp',dir=path.parent); tmp=Path(name)
 try:
  with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as h: json.dump(v,h,indent=2,ensure_ascii=False); h.write('\n')
  os.replace(tmp,path)
 except Exception: tmp.unlink(missing_ok=True); raise

def _inputs(values,p):
 if not isinstance(values,list) or len(values)>p['max_inputs']: raise EvidenceReuseError('inputs must be bounded list')
 out=[]; seen=set()
 for i,x in enumerate(values):
  if not isinstance(x,dict) or set(x)!={'ref','kind','fingerprint'}: raise EvidenceReuseError(f'inputs[{i}] fields invalid')
  if any(not isinstance(x[k],str) or not x[k].strip() for k in x): raise EvidenceReuseError(f'inputs[{i}] values invalid')
  key=(x['ref'],x['kind']);
  if key in seen: raise EvidenceReuseError('duplicate input dependency')
  seen.add(key); out.append({k:x[k].strip() for k in ('ref','kind','fingerprint')})
 return sorted(out,key=lambda x:(x['kind'],x['ref']))

def evidence_key(request:dict,root:Path=ROOT):
 p=load_policy(root); req={'producer','producer_version','volatility','inputs','environment_fingerprint'}
 if not isinstance(request,dict) or set(request)!=req: raise EvidenceReuseError('evidence key request fields invalid')
 for k in ('producer','producer_version'):
  if not isinstance(request[k],str) or not request[k].strip(): raise EvidenceReuseError(f'{k} invalid')
 if request['volatility'] not in p['volatility_classes']: raise EvidenceReuseError('volatility invalid')
 env=request['environment_fingerprint']
 if env is not None and (not isinstance(env,str) or not env.strip()): raise EvidenceReuseError('environment_fingerprint invalid')
 if request['volatility'] in {'ENVIRONMENT_DEPENDENT','HOST_CAPABILITY'} and not env: raise EvidenceReuseError('environment-dependent evidence requires environment_fingerprint')
 envelope={'producer':request['producer'].strip(),'producer_version':request['producer_version'].strip(),'volatility':request['volatility'],'inputs':_inputs(request['inputs'],p),'environment_fingerprint':env}
 return {'key':_hash(envelope),'envelope':envelope}

def _record_path(key,root,p): return root/Path(*PurePosixPath(p['state_root']).parts)/(key+'.json')
def store(record:dict,root:Path=ROOT):
 p=load_policy(root); req={'producer','producer_version','volatility','inputs','environment_fingerprint','result_summary','evidence_refs'}
 if not isinstance(record,dict) or set(record)!=req: raise EvidenceReuseError('evidence record fields invalid')
 if not isinstance(record['result_summary'],str) or not record['result_summary'].strip() or len(record['result_summary'])>p['max_summary_chars']: raise EvidenceReuseError('result_summary invalid')
 refs=record['evidence_refs']
 if not isinstance(refs,list) or len(refs)>p['max_evidence_refs'] or any(not isinstance(x,str) or not x.strip() for x in refs): raise EvidenceReuseError('evidence_refs invalid')
 k=evidence_key({x:record[x] for x in ('producer','producer_version','volatility','inputs','environment_fingerprint')},root)
 if record['volatility']=='VOLATILE': return {'stored':False,'status':'BYPASS_VOLATILE','key':k['key'],'authority':'DERIVED_NONCANONICAL'}
 value={'schema_version':'1.0','key':k['key'],'envelope':k['envelope'],'result_summary':record['result_summary'].strip(),'evidence_refs':[x.strip() for x in refs],'authority':'DERIVED_NONCANONICAL','execution_authority':'NONE'}
 path=_record_path(k['key'],root,p); _atomic(path,value)
 return {'stored':True,'status':'STORED','key':k['key'],'path':path.relative_to(root).as_posix(),'authority':'DERIVED_NONCANONICAL'}

def lookup(request:dict,root:Path=ROOT):
 p=load_policy(root); k=evidence_key(request,root)
 if request['volatility']=='VOLATILE': return {'status':'BYPASS_VOLATILE','key':k['key'],'reusable':False,'authority':'DERIVED_NONCANONICAL'}
 path=_record_path(k['key'],root,p)
 if not path.exists(): return {'status':'MISS','key':k['key'],'reusable':False,'authority':'DERIVED_NONCANONICAL'}
 value=_read(path,'evidence record')
 if value.get('key')!=k['key'] or value.get('envelope')!=k['envelope']: return {'status':'INVALID_RECORD','key':k['key'],'reusable':False,'authority':'DERIVED_NONCANONICAL'}
 return {'status':'HIT','key':k['key'],'reusable':True,'result_summary':value.get('result_summary'),'evidence_refs':value.get('evidence_refs',[]),'authority':'DERIVED_NONCANONICAL'}

def _git(root,*args):
 proc=subprocess.run(['git',*args],cwd=root,capture_output=True,check=False)
 if proc.returncode!=0: raise EvidenceReuseError(proc.stderr.decode(errors='replace').strip() or 'git command failed')
 return proc.stdout

def repository_fingerprint(paths:list[str]|None=None,root:Path=ROOT):
 pathargs=[] if not paths else ['--',*paths]
 head=_git(root,'rev-parse','HEAD').decode().strip(); tree=_git(root,'rev-parse','HEAD^{tree}').decode().strip()
 index=_git(root,'diff','--cached','--binary',*pathargs); work=_git(root,'diff','--binary',*pathargs)
 untracked=_git(root,'ls-files','--others','--exclude-standard','-z',*pathargs).split(b'\0'); items=[]
 for raw in untracked:
  if not raw: continue
  rel=raw.decode('utf-8'); path=root/rel
  if path.is_file(): items.append({'path':rel.replace('\\','/'),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
 state={'head':head,'tree':tree,'index_sha256':hashlib.sha256(index).hexdigest(),'worktree_sha256':hashlib.sha256(work).hexdigest(),'untracked':sorted(items,key=lambda x:x['path']),'scope':'FULL' if not paths else 'PATHS','paths':sorted(paths or [])}
 return {**state,'fingerprint':_hash(state),'authority':'GIT_AND_CONTENT_IDENTITY'}

def _host_path(fact_id,root,p): return root/Path(*PurePosixPath(p['host_profile_root']).parts)/(hashlib.sha256(fact_id.encode()).hexdigest()+'.json')
def record_host_fact(fact:dict,root:Path=ROOT):
 p=load_policy(root); req={'fact_id','classification','value','cause','reproducible','evidence_refs','environment_fingerprint'}
 if not isinstance(fact,dict) or set(fact)!=req: raise EvidenceReuseError('host fact fields invalid')
 for k in ('fact_id','cause','environment_fingerprint'):
  if not isinstance(fact[k],str) or not fact[k].strip(): raise EvidenceReuseError(f'{k} invalid')
 if fact['classification'] not in p['host_fact_classes'] or not isinstance(fact['reproducible'],bool): raise EvidenceReuseError('host fact classification/reproducible invalid')
 if not isinstance(fact['evidence_refs'],list) or any(not isinstance(x,str) or not x.strip() for x in fact['evidence_refs']): raise EvidenceReuseError('host fact evidence_refs invalid')
 durable=fact['classification'] in p['durable_host_fact_classes'] and fact['reproducible']
 if not durable: return {'stored':False,'status':'NOT_DURABLE','reason':'TRANSIENT_UNKNOWN_OR_NOT_REPRODUCIBLE','authority':'DERIVED_NONCANONICAL'}
 value={'schema_version':'1.0',**fact,'authority':'DERIVED_LOCAL_HOST_FACT','execution_authority':'NONE'}; path=_host_path(fact['fact_id'],root,p); _atomic(path,value)
 return {'stored':True,'status':'STORED','path':path.relative_to(root).as_posix(),'authority':'DERIVED_LOCAL_HOST_FACT'}

def lookup_host_fact(fact_id:str,environment_fingerprint:str,root:Path=ROOT):
 p=load_policy(root); path=_host_path(fact_id,root,p)
 if not path.exists(): return {'status':'MISS','reusable':False,'authority':'DERIVED_LOCAL_HOST_FACT'}
 fact=_read(path,'host fact')
 if fact.get('environment_fingerprint')!=environment_fingerprint: return {'status':'INVALIDATED_ENVIRONMENT','reusable':False,'authority':'DERIVED_LOCAL_HOST_FACT'}
 return {'status':'HIT','reusable':True,'fact_id':fact_id,'classification':fact.get('classification'),'value':fact.get('value'),'cause':fact.get('cause'),'authority':'DERIVED_LOCAL_HOST_FACT'}

def main():
 ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
 k=sub.add_parser('key'); k.add_argument('request'); s=sub.add_parser('store'); s.add_argument('record'); l=sub.add_parser('lookup'); l.add_argument('request')
 rf=sub.add_parser('repo-fingerprint'); rf.add_argument('--path',action='append',default=[])
 hr=sub.add_parser('host-record'); hr.add_argument('fact'); hg=sub.add_parser('host-get'); hg.add_argument('fact_id'); hg.add_argument('environment_fingerprint')
 a=ap.parse_args()
 try:
  if a.cmd=='key': out=evidence_key(_read(Path(a.request),'request'))
  elif a.cmd=='store': out=store(_read(Path(a.record),'record'))
  elif a.cmd=='lookup': out=lookup(_read(Path(a.request),'request'))
  elif a.cmd=='repo-fingerprint': out=repository_fingerprint(a.path or None)
  elif a.cmd=='host-record': out=record_host_fact(_read(Path(a.fact),'host fact'))
  else: out=lookup_host_fact(a.fact_id,a.environment_fingerprint)
  print(json.dumps({'valid':True,'result':out},indent=2,ensure_ascii=False)); return 0
 except EvidenceReuseError as exc:
  print(json.dumps({'valid':False,'error':str(exc)},indent=2),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
