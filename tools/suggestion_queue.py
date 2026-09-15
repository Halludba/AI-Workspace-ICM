#!/usr/bin/env python3
"""Noncanonical suggestion continuity and explicit approval-scope mechanics."""
from __future__ import annotations
import argparse,datetime,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class SuggestionError(ValueError): pass

def _now(): return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat().replace('+00:00','Z')
def _read(path:Path,label:str):
 try: v=json.loads(path.read_text(encoding='utf-8-sig'))
 except (OSError,json.JSONDecodeError) as exc: raise SuggestionError(f'cannot load {label}: {exc}') from exc
 if not isinstance(v,dict): raise SuggestionError(f'{label} root must be object')
 return v

def policy(root:Path=ROOT):
 p=_read(root/'config'/'suggestion_policy.json','suggestion policy')
 required={'schema_version','queue_root','authority','statuses','unresolved_statuses','promotion_status','topic_change_effect','silence_effect','approval_scopes','exact_phrase_scopes','max_suggestions','compact_summary_limit','automatic_execution','automatic_planner_mutation'}
 if set(p)!=required or p['schema_version']!='1.0' or p['authority']!='NON_AUTHORITATIVE_SUGGESTION_QUEUE': raise SuggestionError('suggestion policy invalid')
 if p['topic_change_effect']!='NONE' or p['silence_effect']!='NONE' or p['automatic_execution'] is not False or p['automatic_planner_mutation'] is not False: raise SuggestionError('suggestion authority boundary invalid')
 if p['promotion_status']!='ACCEPTED' or set(p['unresolved_statuses'])!={'PROPOSED','UNOPPOSED'}: raise SuggestionError('suggestion lifecycle invalid')
 return p

def _agent(agent:str):
 if not isinstance(agent,str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,120}',agent): raise SuggestionError('agent_id invalid')
 return agent

def queue_path(agent:str,root:Path=ROOT):
 p=policy(root); _agent(agent); base=(root/p['queue_root']).resolve(); path=(base/f'{agent}.json').resolve()
 try: path.relative_to(base)
 except ValueError: raise SuggestionError('queue path escapes queue root')
 return path

def _empty(agent:str): return {'schema_version':'1.0','agent_id':agent,'updated_utc':_now(),'suggestions':[]}
def load_queue(agent:str,root:Path=ROOT):
 path=queue_path(agent,root); q=_empty(agent) if not path.exists() else _read(path,'suggestion queue'); validate_queue(q,root); return q

def validate_queue(q:dict,root:Path=ROOT):
 p=policy(root); required={'schema_version','agent_id','updated_utc','suggestions'}
 if not isinstance(q,dict) or set(q)!=required or q['schema_version']!='1.0': raise SuggestionError('queue fields invalid')
 _agent(q['agent_id']); items=q['suggestions']
 if not isinstance(items,list) or len(items)>p['max_suggestions']: raise SuggestionError('suggestions invalid')
 seen=set()
 for s in items:
  req={'suggestion_id','title','reason','status','bundle_id','evidence_refs','compatibility_state','last_reviewed_revision','created_utc','updated_utc'}
  if not isinstance(s,dict) or set(s)!=req: raise SuggestionError('suggestion fields invalid')
  sid=s['suggestion_id']
  if not isinstance(sid,str) or not sid or sid in seen: raise SuggestionError('suggestion id invalid/duplicate')
  seen.add(sid)
  if s['status'] not in p['statuses']: raise SuggestionError(f'suggestion status invalid: {sid}')
  for k in ('title','reason','bundle_id','compatibility_state','last_reviewed_revision','created_utc','updated_utc'):
   if not isinstance(s[k],str) or not s[k].strip(): raise SuggestionError(f'{k} invalid: {sid}')
  if not isinstance(s['evidence_refs'],list) or any(not isinstance(x,str) or not x.strip() for x in s['evidence_refs']): raise SuggestionError(f'evidence refs invalid: {sid}')
 return {'valid':True,'count':len(items),'authority':p['authority'],'automatic_execution':False,'automatic_planner_mutation':False}

def save_queue(q:dict,root:Path=ROOT):
 validate_queue(q,root); path=queue_path(q['agent_id'],root); path.parent.mkdir(parents=True,exist_ok=True); q['updated_utc']=_now(); path.write_text(json.dumps(q,indent=2)+'\n',encoding='utf-8'); return path

def add(agent:str,item:dict,root:Path=ROOT):
 q=load_queue(agent,root); req={'suggestion_id','title','reason','bundle_id','evidence_refs','compatibility_state','last_reviewed_revision'}
 if not isinstance(item,dict) or set(item)!=req: raise SuggestionError('new suggestion fields invalid')
 if any(x['suggestion_id']==item['suggestion_id'] for x in q['suggestions']): raise SuggestionError('suggestion already exists')
 now=_now(); q['suggestions'].append({**item,'status':'PROPOSED','created_utc':now,'updated_utc':now}); save_queue(q,root); return q['suggestions'][-1]

_ALLOWED={'PROPOSED':{'UNOPPOSED','ACCEPTED','REJECTED','SUPERSEDED','EXPIRED'},'UNOPPOSED':{'ACCEPTED','REJECTED','SUPERSEDED','EXPIRED'},'ACCEPTED':set(),'REJECTED':set(),'SUPERSEDED':set(),'EXPIRED':set()}
def transition(agent:str,sid:str,status:str,root:Path=ROOT):
 q=load_queue(agent,root); target=next((x for x in q['suggestions'] if x['suggestion_id']==sid),None)
 if target is None: raise SuggestionError('unknown suggestion')
 if status not in _ALLOWED[target['status']]: raise SuggestionError(f'illegal transition {target["status"]}->{status}')
 target['status']=status; target['updated_utc']=_now(); save_queue(q,root); return target

def resolve_phrase(phrase:str,current_bundle_ids:list[str],pending_ids:list[str],primary_id:str|None=None,root:Path=ROOT):
 p=policy(root); norm=' '.join(phrase.strip().lower().split()); scope=p['exact_phrase_scopes'].get(norm)
 if scope is None: return {'recognized':False,'scope':None,'targets':[],'authorization':'NONE'}
 if scope=='PRIMARY_CURRENT': targets=[primary_id] if primary_id else []
 elif scope=='CURRENT_BUNDLE': targets=list(dict.fromkeys(current_bundle_ids))
 else: targets=list(dict.fromkeys(pending_ids))
 return {'recognized':True,'scope':scope,'targets':[x for x in targets if x],'authorization':'SUGGESTION_ACCEPTANCE_ONLY'}

def compact(agent:str,root:Path=ROOT):
 p=policy(root); q=load_queue(agent,root); items=[x for x in q['suggestions'] if x['status'] in p['unresolved_statuses']]; shown=items[:p['compact_summary_limit']]
 return {'unresolved_count':len(items),'suggestions':[{'suggestion_id':x['suggestion_id'],'title':x['title'],'status':x['status']} for x in shown],'hidden_count':max(0,len(items)-len(shown)),'authority':p['authority']}

def promotion_candidate(agent:str,sid:str,root:Path=ROOT):
 q=load_queue(agent,root); s=next((x for x in q['suggestions'] if x['suggestion_id']==sid),None)
 if s is None: raise SuggestionError('unknown suggestion')
 if s['status']!='ACCEPTED': raise SuggestionError('only ACCEPTED suggestions are promotion-eligible')
 return {'suggestion_id':sid,'title':s['title'],'reason':s['reason'],'evidence_refs':s['evidence_refs'],'planner_mutation_performed':False,'execution_authority':'NONE','requires_plan_sufficiency':True}

def main():
 ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True); v=sub.add_parser('validate'); v.add_argument('agent'); c=sub.add_parser('compact'); c.add_argument('agent'); r=sub.add_parser('resolve-approval'); r.add_argument('phrase'); r.add_argument('--current',action='append',default=[]); r.add_argument('--pending',action='append',default=[]); r.add_argument('--primary'); pr=sub.add_parser('promotion'); pr.add_argument('agent'); pr.add_argument('suggestion_id')
 a=ap.parse_args()
 try:
  if a.cmd=='validate': out=validate_queue(load_queue(a.agent))
  elif a.cmd=='compact': out=compact(a.agent)
  elif a.cmd=='resolve-approval': out=resolve_phrase(a.phrase,a.current,a.pending,a.primary)
  else: out=promotion_candidate(a.agent,a.suggestion_id)
  print(json.dumps({'valid':True,'result':out},indent=2)); return 0
 except SuggestionError as exc: print(json.dumps({'valid':False,'error':str(exc)},indent=2)); return 2
if __name__=='__main__': raise SystemExit(main())