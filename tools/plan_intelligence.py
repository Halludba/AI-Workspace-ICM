#!/usr/bin/env python3
"""Deterministic plan sufficiency and affected-task reconciliation."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class PlanIntelligenceError(ValueError): pass

def _read(path:Path,label:str)->dict:
    try: v=json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError,json.JSONDecodeError) as exc: raise PlanIntelligenceError(f"Cannot load {label}: {exc}") from exc
    if not isinstance(v,dict): raise PlanIntelligenceError(f"{label} root must be object")
    return v

def load_policy(root:Path=ROOT)->dict:
    p=_read(root/'config/plan_intelligence_policy.json','plan intelligence policy')
    required={'schema_version','execution_target_roles','required_execution_task_fields','verification_min_items','reconciliation_statuses','authority','mutates_plan','model_calls_required'}
    if set(p)!=required or p['schema_version']!='1.0': raise PlanIntelligenceError('plan intelligence policy fields must match contract')
    if p['mutates_plan'] is not False or p['model_calls_required'] is not False: raise PlanIntelligenceError('plan intelligence must remain deterministic/non-mutating')
    return p

def assess_task(task:dict,root:Path=ROOT)->dict:
    p=load_policy(root)
    if not isinstance(task,dict): raise PlanIntelligenceError('task must be object')
    execution=task.get('target_role') in p['execution_target_roles']
    missing=[]; invalid=[]
    if execution:
        for key in p['required_execution_task_fields']:
            if key not in task: missing.append(key)
        for key in ('objective','title','route_id','declared_scope','target_role'):
            if key in task and (not isinstance(task[key],str) or not task[key].strip()): invalid.append(key)
        for key in ('context_refs','acceptance_criteria','verification'):
            if key in task and (not isinstance(task[key],list) or not task[key] or any(not isinstance(x,str) or not x.strip() for x in task[key])): invalid.append(key)
    status='SUFFICIENT' if not missing and not invalid else 'INSUFFICIENT'
    return {'schema_version':'1.0','task_id':task.get('task_id'),'execution_class':execution,'status':status,'missing_fields':sorted(missing),'invalid_fields':sorted(set(invalid)),'authority':'ADVISORY_DETERMINISTIC_GATE','execution_authority':'NONE'}

def reconcile(plan:dict,change:dict,root:Path=ROOT)->dict:
    p=load_policy(root)
    if not isinstance(plan,dict) or not isinstance(plan.get('tasks'),list): raise PlanIntelligenceError('plan tasks must be list')
    if not isinstance(change,dict): raise PlanIntelligenceError('change must be object')
    changed_ids=set(change.get('changed_task_ids',[])); changed_refs=set(change.get('changed_context_refs',[]))
    if any(not isinstance(x,str) or not x for x in changed_ids|changed_refs): raise PlanIntelligenceError('change identifiers must be non-empty strings')
    tasks={t.get('task_id'):t for t in plan['tasks'] if isinstance(t,dict) and isinstance(t.get('task_id'),str)}
    unknown=sorted(changed_ids-set(tasks))
    if unknown: raise PlanIntelligenceError('unknown changed_task_ids: '+','.join(unknown))
    affected=set(); frontier=set(changed_ids)
    while frontier:
        source=frontier.pop()
        for tid,t in tasks.items():
            if tid in affected or t.get('status') not in p['reconciliation_statuses']: continue
            if source in t.get('depends_on',[]): affected.add(tid); frontier.add(tid)
    for tid,t in tasks.items():
        if t.get('status') in p['reconciliation_statuses'] and changed_refs.intersection(t.get('context_refs',[]) or []): affected.add(tid)
    return {'schema_version':'1.0','affected_task_ids':sorted(affected),'changed_task_ids':sorted(changed_ids),'changed_context_refs':sorted(changed_refs),'plan_mutated':False,'authority':'ADVISORY_RECONCILIATION'}

def main()->int:
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    a=sub.add_parser('assess'); a.add_argument('task_json')
    q=sub.add_parser('reconcile'); q.add_argument('plan_json'); q.add_argument('change_json')
    args=ap.parse_args()
    try:
        out=assess_task(_read(Path(args.task_json),'task')) if args.cmd=='assess' else reconcile(_read(Path(args.plan_json),'plan'),_read(Path(args.change_json),'change'))
        print(json.dumps({'valid':True,'result':out},indent=2)); return 0
    except PlanIntelligenceError as exc:
        print(json.dumps({'valid':False,'error':str(exc)},indent=2),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
