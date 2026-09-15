#!/usr/bin/env python3
"""Compile compact ICM continuity presentation and validate concept callouts."""
from __future__ import annotations
import argparse,json
from pathlib import Path
from tools import session_planner,suggestion_queue
ROOT=Path(__file__).resolve().parents[1]
class PresentationError(ValueError): pass

def _read(path:Path,label:str):
 try: v=json.loads(path.read_text(encoding='utf-8-sig'))
 except (OSError,json.JSONDecodeError) as exc: raise PresentationError(f'cannot load {label}: {exc}') from exc
 if not isinstance(v,dict): raise PresentationError(f'{label} root must be object')
 return v

def policy(root:Path=ROOT):
 p=_read(root/'config'/'human_presentation_policy.json','human presentation policy')
 req={'schema_version','authority','concept_recognition','continuity_footer','changes_rigor','changes_authority'}
 if set(p)!=req or p['schema_version']!='1.0' or p['authority']!='PRESENTATION_ONLY' or p['changes_rigor'] is not False or p['changes_authority'] is not False: raise PresentationError('presentation safety contract invalid')
 c=p['concept_recognition']; f=p['continuity_footer']
 if c.get('private_reasoning_allowed') is not False or c.get('force_single_name_when_ambiguous') is not False: raise PresentationError('concept recognition boundary invalid')
 if f.get('candidate_is_executable') is not False or f.get('repeat_full_suggestion_body') is not False: raise PresentationError('continuity footer boundary invalid')
 if f.get('enforcement')!='DETERMINISTIC_VALIDATE_WHEN_SUBSTANTIAL' or f.get('required_heading')!='Next optimal step' or f.get('missing_executable_next_step_is_error') is not True: raise PresentationError('continuity footer enforcement invalid')
 return p

def validate_concept_callout(value:dict,root:Path=ROOT):
 p=policy(root)['concept_recognition']; req={'term','term_status','mapping_strength','user_path','basis'}
 if not isinstance(value,dict) or set(value)!=req: raise PresentationError('concept callout fields invalid')
 if value['term_status'] not in p['term_statuses'] or value['mapping_strength'] not in p['mapping_strengths']: raise PresentationError('concept classification invalid')
 for k in ('term',):
  if not isinstance(value[k],str) or not value[k].strip(): raise PresentationError(f'{k} invalid')
 path=value['user_path']; basis=value['basis']
 if not isinstance(path,list) or not (1<=len(path)<=p['max_path_steps']) or any(not isinstance(x,str) or not x.strip() for x in path): raise PresentationError('user_path invalid')
 if not isinstance(basis,list) or not basis or any(not isinstance(x,str) or not x.strip() for x in basis): raise PresentationError('basis invalid')
 surface=value['mapping_strength']==p['default_surface_strength'] and value['term_status']=='ESTABLISHED_TERM'
 return {'valid':True,'surface_as_rediscovery':surface,'term':value['term'],'term_status':value['term_status'],'mapping_strength':value['mapping_strength'],'user_path':path,'private_reasoning_used':False,'authority':'PRESENTATION_ONLY'}

def _planner_next(agent:str,root:Path):
 try: plan=session_planner.load_plan(agent,root); task=session_planner.select_next_task(plan,root=root)
 except session_planner.SessionPlanError: return None
 if task is None: return None
 return {'kind':'EXECUTABLE','task_id':task['task_id'],'title':task['title'],'status':task['status'],'source':'ACTIVE_PLANNER' if task['status']=='IN_PROGRESS' else 'ELIGIBLE_PLANNER','execution_authority':'NONE'}

def compile_footer(agent:str,root:Path=ROOT):
 p=policy(root); nxt=_planner_next(agent,root)
 try: compact=suggestion_queue.compact(agent,root)
 except suggestion_queue.SuggestionError: compact={'unresolved_count':0,'suggestions':[],'hidden_count':0}
 if nxt is None and compact['suggestions']:
  first=compact['suggestions'][0]; nxt={'kind':'CANDIDATE','suggestion_id':first['suggestion_id'],'title':first['title'],'source':'UNRESOLVED_SUGGESTION','execution_authority':'NONE'}
 titles=[x['title'] for x in compact['suggestions'][:p['continuity_footer']['max_suggestion_titles']]]
 lines=[]
 if nxt: lines.append(f"Next optimal step: {nxt['title']}" if nxt['kind']=='EXECUTABLE' else f"Candidate next step: {nxt['title']}")
 if titles:
  suffix=f" (+{compact['hidden_count']} more)" if compact.get('hidden_count',0) else ''
  lines.append('Unopposed / unresolved ideas: '+' · '.join(titles)+suffix)
 return {'next_step':nxt,'unresolved_titles':titles,'unresolved_count':compact['unresolved_count'],'text':'\n'.join(lines),'authority':'PRESENTATION_ONLY','changes_rigor':False,'changes_authority':False}

def validate_response_contract(agent:str,value:dict,root:Path=ROOT):
 p=policy(root); required={'substantial_icm','footer_heading','footer_text'}
 if not isinstance(value,dict) or set(value)!=required: raise PresentationError('response contract fields invalid')
 if not isinstance(value['substantial_icm'],bool): raise PresentationError('substantial_icm must be boolean')
 for k in ('footer_heading','footer_text'):
  if not isinstance(value[k],str): raise PresentationError(f'{k} must be string')
 nxt=_planner_next(agent,root); required_footer=value['substantial_icm'] and nxt is not None and nxt.get('kind')=='EXECUTABLE'
 present=value['footer_heading'].strip()==p['continuity_footer']['required_heading'] and bool(value['footer_text'].strip())
 if required_footer and not present and p['continuity_footer']['missing_executable_next_step_is_error']:
  raise PresentationError('substantial ICM response omitted required Next optimal step footer')
 return {'valid':True,'footer_required':required_footer,'footer_present':present,'next_step':nxt,'authority':'PRESENTATION_ONLY'}


def main():
 ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True); f=sub.add_parser('footer'); f.add_argument('agent'); c=sub.add_parser('concept'); c.add_argument('file'); v=sub.add_parser('validate-response'); v.add_argument('agent'); v.add_argument('file')
 a=ap.parse_args()
 try:
  out=compile_footer(a.agent) if a.cmd=='footer' else (validate_concept_callout(_read(Path(a.file),'concept callout')) if a.cmd=='concept' else validate_response_contract(a.agent,_read(Path(a.file),'response contract')))
  print(json.dumps({'valid':True,'result':out},indent=2)); return 0
 except PresentationError as exc: print(json.dumps({'valid':False,'error':str(exc)},indent=2)); return 2
if __name__=='__main__': raise SystemExit(main())