#!/usr/bin/env python3
"""Local noncanonical developer observability for ICM."""
from __future__ import annotations
import argparse, datetime, hashlib, json, math, os, re, tempfile
from pathlib import Path, PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
class ObservatoryError(ValueError): pass

def _read(path:Path,label:str):
    try: return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,json.JSONDecodeError) as exc: raise ObservatoryError(f'Cannot load {label}: {exc}') from exc

def load_policy(root:Path=ROOT):
    p=_read(root/'config/developer_observatory_policy.json','observatory policy')
    required={'schema_version','state_root','modes','phases','outcomes','rework_classes','forbidden_keys','normal_mode_model_calls','canonical','execution_authority','max_context_refs','max_directive_refs','max_causal_refs'}
    if not isinstance(p,dict) or set(p)!=required or p.get('schema_version')!='1.0' or p.get('canonical') is not False or p.get('execution_authority')!='NONE' or p.get('normal_mode_model_calls') is not False: raise ObservatoryError('observatory policy safety contract invalid')
    if not all(isinstance(p[k],list) and p[k] and len(p[k])==len(set(p[k])) for k in ('modes','phases','outcomes','rework_classes','forbidden_keys')): raise ObservatoryError('observatory policy vocabularies must be unique non-empty lists')
    for k in ('max_context_refs','max_directive_refs','max_causal_refs'):
        if isinstance(p[k],bool) or not isinstance(p[k],int) or p[k]<1: raise ObservatoryError(f'{k} must be positive integer')
    return p

def _privacy(value,forbidden,path='$'):
    if isinstance(value,dict):
        for k,v in value.items():
            if str(k).lower() in forbidden: raise ObservatoryError(f'forbidden observatory key at {path}.{k}')
            _privacy(v,forbidden,path+'.'+str(k))
    elif isinstance(value,list):
        for i,v in enumerate(value): _privacy(v,forbidden,f'{path}[{i}]')

def validate_event(event:dict,root:Path=ROOT):
    p=load_policy(root); forbidden={x.lower() for x in p['forbidden_keys']}; _privacy(event,forbidden)
    required={'schema_version','event_id','session_id','mode','phase','timestamp','trigger','role','mechanism','duration_ms','context_refs','directive_refs','causal_refs','model_calls','tool_calls','outcome','rework_class','context_escalation'}
    if not isinstance(event,dict) or set(event)!=required or event.get('schema_version')!='1.0': raise ObservatoryError('event fields must match contract')
    for k in ('event_id','session_id','trigger','role','mechanism','timestamp'):
        if not isinstance(event[k],str) or not event[k].strip(): raise ObservatoryError(f'{k} must be non-empty string')
    ts=event['timestamp'];
    if not (ts.endswith('Z') or ('+' in ts[10:] or '-' in ts[10:])): raise ObservatoryError('timestamp must include timezone')
    if event['mode'] not in p['modes'] or event['phase'] not in p['phases'] or event['outcome'] not in p['outcomes']: raise ObservatoryError('event enum invalid')
    try:
        stamp=datetime.datetime.fromisoformat(event['timestamp'].replace('Z','+00:00'))
    except ValueError as exc: raise ObservatoryError('timestamp must be ISO-8601') from exc
    if stamp.tzinfo is None: raise ObservatoryError('timestamp requires timezone')
    if isinstance(event['duration_ms'],bool) or not isinstance(event['duration_ms'],(int,float)) or not math.isfinite(event['duration_ms']) or event['duration_ms']<0: raise ObservatoryError('duration_ms must be finite non-negative')
    for k,maxn in [('context_refs',p['max_context_refs']),('directive_refs',p['max_directive_refs']),('causal_refs',p['max_causal_refs'])]:
        if not isinstance(event[k],list) or len(event[k])>maxn or any(not isinstance(x,str) or not x.strip() for x in event[k]): raise ObservatoryError(f'{k} invalid')
    for k in ('model_calls','tool_calls'):
        if event[k] is not None and (isinstance(event[k],bool) or not isinstance(event[k],int) or event[k]<0): raise ObservatoryError(f'{k} must be non-negative integer or null when unavailable')
    if event['rework_class'] is not None and event['rework_class'] not in p['rework_classes']: raise ObservatoryError('rework_class invalid')
    if event['outcome']=='REWORK' and event['rework_class'] is None: raise ObservatoryError('REWORK outcome requires rework_class')
    if event['outcome']!='REWORK' and event['rework_class'] is not None: raise ObservatoryError('rework_class is only valid for REWORK outcome')
    if event['outcome']=='REWORK' and event['rework_class'] is None: raise ObservatoryError('REWORK outcome requires rework_class')
    if event['outcome']!='REWORK' and event['rework_class'] is not None: raise ObservatoryError('rework_class is only valid for REWORK outcome')
    ce=event['context_escalation']
    if ce is not None:
        if not isinstance(ce,dict) or set(ce)!={'from_level','to_level','added_estimated_tokens'}: raise ObservatoryError('context_escalation fields invalid')
        if not all(isinstance(ce[k],str) and ce[k] for k in ('from_level','to_level')): raise ObservatoryError('context escalation levels invalid')
        if isinstance(ce['added_estimated_tokens'],bool) or not isinstance(ce['added_estimated_tokens'],int) or ce['added_estimated_tokens']<=0: raise ObservatoryError('added_estimated_tokens must be positive for an escalation')
        if not re.fullmatch(r'C[0-5](?:_[A-Z0-9_]+)?',ce['from_level']) or not re.fullmatch(r'C[0-5](?:_[A-Z0-9_]+)?',ce['to_level']) or ce['from_level']==ce['to_level']: raise ObservatoryError('context escalation levels invalid')
    return {**event,'observer_model_calls':0,'authority':'DERIVED_NONCANONICAL','execution_authority':'NONE'}

def _state_root(root,p):
    rel=PurePosixPath(str(p['state_root']).replace('\\','/'))
    if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0]!='.session': raise ObservatoryError('observatory state_root must be under .session')
    return root/Path(*rel.parts)

def record_event(event:dict,root:Path=ROOT):
    value=validate_event(event,root); p=load_policy(root); base=_state_root(root,p)/hashlib.sha256(event['session_id'].encode()).hexdigest(); base.mkdir(parents=True,exist_ok=True)
    name=hashlib.sha256(event['event_id'].encode()).hexdigest()+'.json'; dest=base/name
    if dest.exists():
        old=_read(dest,'existing observatory event')
        if old!=value: raise ObservatoryError('event_id already exists with different content')
        return {'path':dest.relative_to(root).as_posix(),'idempotent':True,'event':value}
    fd,tmpname=tempfile.mkstemp(prefix='.'+name+'.',suffix='.tmp',dir=base); tmp=Path(tmpname)
    try:
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as h: json.dump(value,h,indent=2); h.write('\n')
        os.replace(tmp,dest)
    except Exception: tmp.unlink(missing_ok=True); raise
    return {'path':dest.relative_to(root).as_posix(),'idempotent':False,'event':value}

def summarize(events:list[dict],root:Path=ROOT):
    vals=[validate_event(e,root) for e in events]
    phases={}; mechanisms={}; directives={}; rework={}; escalations=0; added=0
    total_ms=0.0; model_calls=0; tool_calls=0; model_known=True; tool_known=True
    for e in vals:
        total_ms+=e['duration_ms']
        if e['model_calls'] is None: model_known=False
        else: model_calls+=e['model_calls']
        if e['tool_calls'] is None: tool_known=False
        else: tool_calls+=e['tool_calls']
        phases[e['phase']]=phases.get(e['phase'],0)+1
        mechanisms[e['mechanism']]=mechanisms.get(e['mechanism'],0)+1
        for d in e['directive_refs']:
            directives[d]=directives.get(d,0)+1
        if e['rework_class']:
            rework[e['rework_class']]=rework.get(e['rework_class'],0)+1
        if e['context_escalation']:
            escalations+=1
            added+=e['context_escalation']['added_estimated_tokens']
    n=len(vals); rw=sum(rework.values())
    return {
        'schema_version':'1.0','event_count':n,'total_duration_ms':round(total_ms,3),
        'observed_model_calls':(model_calls if model_known else None),
        'observed_tool_calls':(tool_calls if tool_known else None),'observer_model_calls':0,
        'phase_counts':dict(sorted(phases.items())),'mechanism_counts':dict(sorted(mechanisms.items())),
        'directive_reference_counts':dict(sorted(directives.items())),'rework_counts':dict(sorted(rework.items())),
        'rework_ratio':(rw/n if n else None),'context_escalations':escalations,
        'context_added_estimated_tokens':added,
        'average_added_tokens_per_escalation':(added/escalations if escalations else None),
        'value_claim':'OBSERVED_USAGE_ONLY_NOT_CAUSAL_VALUE','authority':'DERIVED_NONCANONICAL'
    }

def compare_audit(baseline:dict,variant:dict):
    allowed={'wall_time_ms','input_tokens_total','input_tokens_uncached','output_tokens','model_calls','tool_calls','correctness_score','context_recall','unnecessary_context_ratio'}
    out={}
    for k in sorted(allowed):
        a=baseline.get(k); b=variant.get(k)
        if isinstance(a,(int,float)) and not isinstance(a,bool) and isinstance(b,(int,float)) and not isinstance(b,bool) and math.isfinite(a) and math.isfinite(b): out[k]={'baseline':a,'variant':b,'delta':b-a}
    return {'schema_version':'1.0','observed_deltas':out,'causal_percentage_claimed':False,'authority':'EXPLICIT_AUDIT_COMPARISON'}

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    v=sub.add_parser('validate'); v.add_argument('event')
    r=sub.add_parser('record'); r.add_argument('event')
    s=sub.add_parser('summarize'); s.add_argument('events')
    a=sub.add_parser('audit'); a.add_argument('baseline'); a.add_argument('variant')
    args=ap.parse_args()
    try:
        if args.cmd=='validate': out=validate_event(_read(Path(args.event),'event'))
        elif args.cmd=='record': out=record_event(_read(Path(args.event),'event'))
        elif args.cmd=='summarize':
            ev=_read(Path(args.events),'events');
            if not isinstance(ev,list): raise ObservatoryError('events must be array')
            out=summarize(ev)
        else: out=compare_audit(_read(Path(args.baseline),'baseline'),_read(Path(args.variant),'variant'))
        print(json.dumps({'valid':True,'result':out},indent=2)); return 0
    except ObservatoryError as exc:
        print(json.dumps({'valid':False,'error':str(exc)},indent=2)); return 2
if __name__=='__main__': raise SystemExit(main())
