#!/usr/bin/env python3
"""Bounded local model discovery/tool loop over the ICM local capability broker."""
from __future__ import annotations
import argparse,hashlib,json,time,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/'tools'
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
import local_capability_broker as broker
import local_worker
class LocalAgentError(ValueError): pass

def _read(path:Path,label:str):
 try: v=json.loads(path.read_text(encoding='utf-8-sig'))
 except (OSError,json.JSONDecodeError) as exc: raise LocalAgentError(f'cannot load {label}: {exc}') from exc
 if not isinstance(v,dict): raise LocalAgentError(f'{label} root must be object')
 return v

def load_policy(root:Path=ROOT):
 p=_read(root/'config/local_worker_agent_policy.json','local worker agent policy')
 req={'schema_version','max_tool_calls','max_wall_time_ms','max_history_items','allowed_capabilities','final_statuses','automatic_patch_apply','canonical_mutation','execution_authority'}
 if set(p)!=req or p['schema_version']!='1.0' or p['automatic_patch_apply'] is not False or p['canonical_mutation'] is not False or p['execution_authority']!='NONE': raise LocalAgentError('local worker agent safety contract invalid')
 if not isinstance(p['max_tool_calls'],int) or p['max_tool_calls']<1 or not isinstance(p['max_wall_time_ms'],(int,float)) or p['max_wall_time_ms']<=0: raise LocalAgentError('agent budgets invalid')
 if not isinstance(p['allowed_capabilities'],list) or not p['allowed_capabilities']: raise LocalAgentError('allowed capabilities invalid')
 return p

def _target_identity(kind,target_id,root):
 try:
  base,identity=broker._target(kind,target_id,root)
 except Exception as exc: raise LocalAgentError(str(exc)) from exc
 return identity

def _action_schema(policy):
 return {'type':'object','additionalProperties':False,'properties':{
  'kind':{'type':'string','enum':['TOOL','FINAL']},'capability':{'type':['string','null']},'args':{'type':'object'},
  'status':{'type':['string','null'],'enum':[None,*policy['final_statuses']]},'summary':{'type':['string','null']},'patch':{'type':['string','null']}
 },'required':['kind','capability','args','status','summary','patch']}

def _default_transport(messages:list[dict],policy:dict,root:Path):
 wp=local_worker.load_policy(root); provider=local_worker.load_provider(root,wp)
 payload={'model':provider['model'],'messages':messages,'stream':False,'think':False,'format':_action_schema(policy),'options':{'temperature':0}}
 response=local_worker._http_transport(provider['endpoint'],payload,provider['timeout_seconds'],wp['max_response_bytes'])
 if not isinstance(response,dict) or not isinstance(response.get('message'),dict) or not isinstance(response['message'].get('content'),str): raise LocalAgentError('provider response missing structured action')
 try: return json.loads(response['message']['content'])
 except json.JSONDecodeError as exc: raise LocalAgentError('provider action is not JSON') from exc

def _validate_action(a,policy):
 req={'kind','capability','args','status','summary','patch'}
 if not isinstance(a,dict) or set(a)!=req: raise LocalAgentError('agent action fields invalid')
 if a['kind']=='TOOL':
  if a['capability'] not in policy['allowed_capabilities'] or not isinstance(a['args'],dict) or a['status'] is not None or a['summary'] is not None or a['patch'] is not None: raise LocalAgentError('TOOL action invalid')
 else:
  if a['capability'] is not None or a['args']!={} or a['status'] not in policy['final_statuses'] or not isinstance(a['summary'],str) or not a['summary'].strip() or not isinstance(a['patch'],str): raise LocalAgentError('FINAL action invalid')
 return a

def _trace_digest(trace): return hashlib.sha256(json.dumps(trace,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

def run_agent(request:dict,root:Path=ROOT,transport=None):
 policy=load_policy(root); req={'schema_version','job_id','target_kind','target_id','objective'}
 if not isinstance(request,dict) or set(request)!=req or request.get('schema_version')!='1.0': raise LocalAgentError('agent request fields invalid')
 if not isinstance(request['job_id'],str) or not request['job_id'] or not isinstance(request['objective'],str) or not request['objective'].strip(): raise LocalAgentError('job/objective invalid')
 target=_target_identity(request['target_kind'],request['target_id'],root)
 system=('You are LOCAL_CODE_WORKER operating through a bounded capability broker. Request only one allowed tool at a time. '
         'Do not request arbitrary shell commands, do not claim unseen source, do not include private reasoning, and do not apply mutations. '
         'Finish with a concise structured candidate; patches are candidate-only and are validated deterministically.')
 messages=[{'role':'system','content':system},{'role':'user','content':json.dumps({'objective':request['objective'],'target':target,'allowed_capabilities':policy['allowed_capabilities'],'max_tool_calls':policy['max_tool_calls']},ensure_ascii=False)}]
 trace=[]; started=time.perf_counter(); tool_calls=0; call=transport or (lambda msgs: _default_transport(msgs,policy,root))
 while True:
  if (time.perf_counter()-started)*1000.0>policy['max_wall_time_ms']: raise LocalAgentError('agent wall-time budget exhausted')
  action=_validate_action(call(messages),policy)
  if action['kind']=='FINAL':
   patch=action['patch']; validation=None
   if patch:
    if request['target_kind']!='ISOLATED_JOB': raise LocalAgentError('snapshot worker cannot return mutation patch')
    try: validation=broker.execute({'schema_version':'1.0','target_kind':'ISOLATED_JOB','target_id':request['target_id'],'capability':'PATCH_VALIDATE','args':{'patch':patch}},root)
    except broker.BrokerError as exc: raise LocalAgentError(f'candidate patch invalid: {exc}') from exc
    if validation['result']['valid'] is not True: raise LocalAgentError('candidate patch does not apply cleanly')
   return {'schema_version':'1.0','job_id':request['job_id'],'status':action['status'],'summary':action['summary'].strip(),'patch':patch,'patch_validation':validation,'tool_calls':tool_calls,'tool_trace_digest':_trace_digest(trace),'target':target,'wall_time_ms':round((time.perf_counter()-started)*1000.0,3),'automatic_patch_apply':False,'canonical_mutation':False,'private_reasoning_persisted':False,'authority':'CANDIDATE_ONLY'}
  if tool_calls>=policy['max_tool_calls']: raise LocalAgentError('agent tool-call budget exhausted')
  tool_req={'schema_version':'1.0','target_kind':request['target_kind'],'target_id':request['target_id'],'capability':action['capability'],'args':action['args']}
  try: result=broker.execute(tool_req,root)
  except broker.BrokerError as exc: result={'error':str(exc),'capability':action['capability']}
  entry={'call_index':tool_calls+1,'capability':action['capability'],'args':action['args'],'result':result}; trace.append(entry); tool_calls+=1
  messages.append({'role':'assistant','content':json.dumps({'tool_request':action['capability'],'args':action['args']},ensure_ascii=False)})
  messages.append({'role':'tool','content':json.dumps(result,ensure_ascii=False)})
  if len(messages)>2+policy['max_history_items']*2: messages=messages[:2]+messages[-policy['max_history_items']*2:]

def main():
 ap=argparse.ArgumentParser(); ap.add_argument('request'); ap.add_argument('--root',default=str(ROOT)); a=ap.parse_args()
 try: out=run_agent(_read(Path(a.request),'agent request'),Path(a.root).resolve()); print(json.dumps({'valid':True,'result':out},indent=2,ensure_ascii=False)); return 0
 except LocalAgentError as exc: print(json.dumps({'valid':False,'error':str(exc)},indent=2),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
