#!/usr/bin/env python3
"""Host-neutral Evaluation Arena contracts and replay identities."""
from __future__ import annotations
import argparse, hashlib, json, math, re, statistics, sys
from pathlib import Path, PurePosixPath
ROOT=Path(__file__).resolve().parents[1]
class EvaluationArenaError(ValueError): pass

def _read(path:Path,label:str):
    try: value=json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,json.JSONDecodeError) as exc: raise EvaluationArenaError(f'Cannot load {label}: {exc}') from exc
    if not isinstance(value,dict): raise EvaluationArenaError(f'{label} root must be object')
    return value

def load_policy(root:Path=ROOT):
    p=_read(root/'config/evaluation_arena_policy.json','evaluation arena policy')
    required={'schema_version','state_root','partitions','task_kinds','evaluator_kinds','score_min','score_max','max_source_refs','max_tags','max_strategy_params','max_model_calls','max_tool_calls','forbidden_keys','quality_floor_required','experiment_outputs_canonical','execution_authority','automatic_promotion','max_trials','required_frontier_metrics','optional_frontier_metrics','metric_directions'}
    if set(p)!=required or p.get('schema_version')!='1.0' or p.get('experiment_outputs_canonical') is not False or p.get('execution_authority')!='NONE' or p.get('automatic_promotion') is not False or p.get('quality_floor_required') is not True: raise EvaluationArenaError('evaluation arena policy safety contract invalid')
    for key in ('partitions','task_kinds','evaluator_kinds','forbidden_keys'):
        if not isinstance(p[key],list) or not p[key] or len(p[key])!=len(set(p[key])) or any(not isinstance(v,str) or not v for v in p[key]): raise EvaluationArenaError(f'{key} must be unique non-empty strings')
    for key in ('max_source_refs','max_tags','max_strategy_params','max_model_calls','max_tool_calls'):
        if isinstance(p[key],bool) or not isinstance(p[key],int) or p[key]<1: raise EvaluationArenaError(f'{key} must be positive integer')
    for key in ('score_min','score_max'):
        if isinstance(p[key],bool) or not isinstance(p[key],(int,float)) or not math.isfinite(p[key]): raise EvaluationArenaError(f'{key} must be finite number')
    if p['score_min']>=p['score_max']: raise EvaluationArenaError('score range invalid')

    if isinstance(p['max_trials'],bool) or not isinstance(p['max_trials'],int) or p['max_trials']<1: raise EvaluationArenaError('max_trials must be positive integer')
    all_frontier=p['required_frontier_metrics']+p['optional_frontier_metrics'] if isinstance(p['required_frontier_metrics'],list) and isinstance(p['optional_frontier_metrics'],list) else []
    if not p['required_frontier_metrics'] or len(all_frontier)!=len(set(all_frontier)) or set(p['metric_directions'])!=set(all_frontier) or any(p['metric_directions'][m] not in {'MAXIMIZE','MINIMIZE'} for m in all_frontier): raise EvaluationArenaError('frontier metric policy invalid')
    rel=PurePosixPath(str(p['state_root']).replace('\\','/'))
    if rel.is_absolute() or '..' in rel.parts or not rel.parts or rel.parts[0]!='.session': raise EvaluationArenaError('state_root must remain under .session')
    return p

def _privacy(value,forbidden,path='$'):
    if isinstance(value,dict):
        for key,item in value.items():
            if str(key).lower() in forbidden: raise EvaluationArenaError(f'forbidden arena key at {path}.{key}')
            _privacy(item,forbidden,path+'.'+str(key))
    elif isinstance(value,list):
        for i,item in enumerate(value): _privacy(item,forbidden,f'{path}[{i}]')

def _nonempty(value,label):
    if not isinstance(value,str) or not value.strip(): raise EvaluationArenaError(f'{label} must be non-empty string')
    return value.strip()

def _sha(value,label):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{64}',value): raise EvaluationArenaError(f'{label} must be lowercase SHA-256 hex')
    return value

def _revision(value,label='base_revision'):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-f]{40}',value): raise EvaluationArenaError(f'{label} must be full 40-hex Git commit id')
    return value

def _refs(value,label,maxn):
    if not isinstance(value,list) or len(value)>maxn or any(not isinstance(v,str) or not v.strip() for v in value): raise EvaluationArenaError(f'{label} must be bounded list of non-empty strings')
    return [v.strip() for v in value]

def _canon(value): return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode('utf-8')
def fingerprint(value): return hashlib.sha256(_canon(value)).hexdigest()

def validate_case(case:dict,root:Path=ROOT):
    p=load_policy(root); _privacy(case,{x.lower() for x in p['forbidden_keys']})
    required={'schema_version','case_id','title','task_kind','partition','base_revision','input_sha256','source_refs','tags','evaluator'}
    if not isinstance(case,dict) or set(case)!=required or case.get('schema_version')!='1.0': raise EvaluationArenaError('case fields must match contract')
    _nonempty(case['case_id'],'case_id'); _nonempty(case['title'],'title'); _revision(case['base_revision']); _sha(case['input_sha256'],'input_sha256')
    if case['task_kind'] not in p['task_kinds'] or case['partition'] not in p['partitions']: raise EvaluationArenaError('case enum invalid')
    refs=_refs(case['source_refs'],'source_refs',p['max_source_refs']); tags=_refs(case['tags'],'tags',p['max_tags'])
    ev=case['evaluator']; expected={'kind','evaluator_ref','quality_floor'}
    if not isinstance(ev,dict) or set(ev)!=expected or ev.get('kind') not in p['evaluator_kinds']: raise EvaluationArenaError('evaluator contract invalid')
    _nonempty(ev['evaluator_ref'],'evaluator_ref')
    floor=ev['quality_floor']
    if isinstance(floor,bool) or not isinstance(floor,(int,float)) or not math.isfinite(floor) or floor<p['score_min'] or floor>p['score_max']: raise EvaluationArenaError('quality_floor outside score range')
    normalized={**case,'source_refs':refs,'tags':tags,'evaluator':{**ev,'quality_floor':float(floor)}}
    return {**normalized,'case_fingerprint':fingerprint(normalized),'authority':'NONCANONICAL_EVALUATION_INPUT','execution_authority':'NONE'}

def case_execution_view(case:dict,root:Path=ROOT):
    value=validate_case(case,root)
    return {'schema_version':'1.0','case_id':value['case_id'],'title':value['title'],'task_kind':value['task_kind'],'base_revision':value['base_revision'],'input_sha256':value['input_sha256'],'source_refs':value['source_refs'],'case_fingerprint':value['case_fingerprint'],'partition_hidden':True,'evaluator_hidden':True,'authority':'BOUNDED_EXECUTION_VIEW','execution_authority':'NONE'}

def _json_scalar(value): return value is None or isinstance(value,(str,int,float,bool))
def validate_variant(variant:dict,root:Path=ROOT):
    p=load_policy(root); _privacy(variant,{x.lower() for x in p['forbidden_keys']})
    required={'schema_version','variant_id','base_revision','model_ref','context_policy_ref','planner_enabled','verification_mode','max_model_calls','max_tool_calls','strategy_params'}
    if not isinstance(variant,dict) or set(variant)!=required or variant.get('schema_version')!='1.0': raise EvaluationArenaError('variant fields must match contract')
    for key in ('variant_id','model_ref','context_policy_ref','verification_mode'): _nonempty(variant[key],key)
    _revision(variant['base_revision'])
    if not isinstance(variant['planner_enabled'],bool): raise EvaluationArenaError('planner_enabled must be boolean')
    for key,limit in [('max_model_calls',p['max_model_calls']),('max_tool_calls',p['max_tool_calls'])]:
        v=variant[key]
        if isinstance(v,bool) or not isinstance(v,int) or v<0 or v>limit: raise EvaluationArenaError(f'{key} out of range')
    params=variant['strategy_params']
    if not isinstance(params,dict) or len(params)>p['max_strategy_params'] or any(not isinstance(k,str) or not k or not _json_scalar(v) or (isinstance(v,float) and not math.isfinite(v)) for k,v in params.items()): raise EvaluationArenaError('strategy_params must be bounded scalar mapping')
    normalized={**variant,'strategy_params':dict(sorted(params.items()))}
    return {**normalized,'variant_fingerprint':fingerprint(normalized),'authority':'NONCANONICAL_EVALUATION_INPUT','execution_authority':'NONE'}

def validate_quality_evidence(evidence:dict,quality_floor:float,root:Path=ROOT):
    p=load_policy(root); _privacy(evidence,{x.lower() for x in p['forbidden_keys']})
    required={'schema_version','evaluator_kind','evaluator_id','score','evidence_refs'}
    if not isinstance(evidence,dict) or set(evidence)!=required or evidence.get('schema_version')!='1.0': raise EvaluationArenaError('quality evidence fields must match contract')
    if evidence['evaluator_kind'] not in p['evaluator_kinds']: raise EvaluationArenaError('evaluator_kind invalid')
    _nonempty(evidence['evaluator_id'],'evaluator_id'); refs=_refs(evidence['evidence_refs'],'evidence_refs',p['max_source_refs'])
    score=evidence['score']
    if isinstance(score,bool) or not isinstance(score,(int,float)) or not math.isfinite(score) or score<p['score_min'] or score>p['score_max']: raise EvaluationArenaError('score outside score range')
    if isinstance(quality_floor,bool) or not isinstance(quality_floor,(int,float)) or not math.isfinite(quality_floor) or quality_floor<p['score_min'] or quality_floor>p['score_max']: raise EvaluationArenaError('quality_floor outside score range')
    return {**evidence,'score':float(score),'evidence_refs':refs,'meets_quality_floor':score>=quality_floor,'judge_is_ground_truth':False if evidence['evaluator_kind']=='JUDGE' else None,'authority':'OBSERVED_QUALITY_EVIDENCE'}

def prepare_manifest(case:dict,variant:dict,experiment_id:str,root:Path=ROOT):
    c=validate_case(case,root); v=validate_variant(variant,root); _nonempty(experiment_id,'experiment_id')
    if c['base_revision']!=v['base_revision']: raise EvaluationArenaError('case and variant base_revision must match')
    body={'schema_version':'1.0','experiment_id':experiment_id.strip(),'base_revision':c['base_revision'],'case_fingerprint':c['case_fingerprint'],'variant_fingerprint':v['variant_fingerprint'],'quality_floor':c['evaluator']['quality_floor'],'execution_view':case_execution_view(case,root)}
    return {**body,'manifest_fingerprint':fingerprint(body),'partition':c['partition'],'partition_exposed_to_execution':False,'automatic_promotion':False,'authority':'NONCANONICAL_EXPERIMENT_MANIFEST','execution_authority':'NONE'}

def _benchmark_policy(root:Path):
    value=_read(root/'config/context_benchmark_policy.json','context benchmark policy')
    metrics=value.get('required_metrics')
    if not isinstance(metrics,list) or not metrics or len(metrics)!=len(set(metrics)): raise EvaluationArenaError('context benchmark metric vocabulary invalid')
    return value

def _observatory_policy(root:Path):
    value=_read(root/'config/developer_observatory_policy.json','developer observatory policy')
    if not isinstance(value.get('outcomes'),list) or not isinstance(value.get('rework_classes'),list): raise EvaluationArenaError('developer observatory vocabulary invalid')
    return value

def validate_trial(trial:dict,root:Path=ROOT):
    p=load_policy(root); bp=_benchmark_policy(root); op=_observatory_policy(root); _privacy(trial,{x.lower() for x in p['forbidden_keys']})
    required={'schema_version','trial_id','experiment_id','manifest_fingerprint','case_fingerprint','variant_fingerprint','partition','replicate','quality_floor','quality_evidence','observed_metrics','outcome','rework_class'}
    if not isinstance(trial,dict) or set(trial)!=required or trial.get('schema_version')!='1.0': raise EvaluationArenaError('trial fields must match contract')
    for key in ('trial_id','experiment_id'): _nonempty(trial[key],key)
    for key in ('manifest_fingerprint','case_fingerprint','variant_fingerprint'): _sha(trial[key],key)
    if trial['partition'] not in p['partitions']: raise EvaluationArenaError('trial partition invalid')
    if isinstance(trial['replicate'],bool) or not isinstance(trial['replicate'],int) or trial['replicate']<0: raise EvaluationArenaError('replicate must be non-negative integer')
    q=validate_quality_evidence(trial['quality_evidence'],trial['quality_floor'],root)
    metrics=trial['observed_metrics']
    if not isinstance(metrics,dict) or set(metrics)!=set(bp['required_metrics']): raise EvaluationArenaError('observed_metrics must match benchmark metric vocabulary')
    normalized={}
    for key,value in metrics.items():
        if value is None: normalized[key]=None; continue
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0: raise EvaluationArenaError(f'observed metric {key} must be non-negative finite number or null')
        if key in {'correctness_score','context_recall','unnecessary_context_ratio'} and value>1: raise EvaluationArenaError(f'observed metric {key} must be <= 1')
        normalized[key]=float(value)
    if trial['outcome'] not in op['outcomes']: raise EvaluationArenaError('trial outcome invalid')
    rw=trial['rework_class']
    if trial['outcome']=='REWORK':
        if rw not in op['rework_classes']: raise EvaluationArenaError('REWORK trial requires valid rework_class')
    elif rw is not None: raise EvaluationArenaError('rework_class only valid for REWORK outcome')
    return {**trial,'quality_floor':float(trial['quality_floor']),'quality_evidence':q,'observed_metrics':normalized,'quality_score':q['score'],'meets_quality_floor':q['meets_quality_floor'],'rework_count':1 if trial['outcome']=='REWORK' else 0,'authority':'OBSERVED_ARENA_TRIAL','execution_authority':'NONE'}

def _distribution(values:list[float]):
    ordered=sorted(float(v) for v in values)
    return {'n':len(ordered),'values':ordered,'min':ordered[0],'median':statistics.median(ordered),'max':ordered[-1]}

def _dominates(a:dict,b:dict,metrics:list[str],directions:dict)->bool:
    strict=False
    for metric in metrics:
        av=a[metric]['median']; bv=b[metric]['median']; direction=directions[metric]
        if direction=='MAXIMIZE':
            if av<bv: return False
            if av>bv: strict=True
        else:
            if av>bv: return False
            if av<bv: strict=True
    return strict

def analyze_trials(trials:list[dict],root:Path=ROOT):
    p=load_policy(root)
    if not isinstance(trials,list) or not trials or len(trials)>p['max_trials']: raise EvaluationArenaError('trials must be a non-empty bounded list')
    vals=[validate_trial(t,root) for t in trials]
    experiments={t['experiment_id'] for t in vals}; partitions={t['partition'] for t in vals}
    if len(experiments)!=1 or len(partitions)!=1: raise EvaluationArenaError('analysis requires one experiment_id and one partition')
    seen=set()
    for t in vals:
        key=(t['case_fingerprint'],t['variant_fingerprint'],t['replicate'])
        if key in seen: raise EvaluationArenaError('duplicate case/variant/replicate trial')
        seen.add(key)
    groups={}
    for t in vals: groups.setdefault(t['variant_fingerprint'],[]).append(t)
    coverage={variant:{t['case_fingerprint'] for t in items} for variant,items in groups.items()}
    expected=None
    for variant,cases in sorted(coverage.items()):
        if expected is None: expected=cases
        elif cases!=expected: raise EvaluationArenaError('variants must cover the same case set')
    summaries={}; required=p['required_frontier_metrics']; optional=p['optional_frontier_metrics']; directions=p['metric_directions']
    for variant,items in sorted(groups.items()):
        dist={'quality_score':_distribution([t['quality_score'] for t in items]),'rework_count':_distribution([t['rework_count'] for t in items])}
        missing=[]
        for metric in ('wall_time_ms','input_tokens_total','model_calls','tool_calls'):
            observed=[t['observed_metrics'][metric] for t in items]
            if any(v is None for v in observed): missing.append(metric)
            else: dist[metric]=_distribution(observed)
        quality_ok=all(t['meets_quality_floor'] and t['outcome'] not in {'FAILED','BLOCKED'} for t in items)
        frontier_ready=quality_ok and all(metric in dist for metric in required)
        summaries[variant]={'trial_count':len(items),'case_count':len(coverage[variant]),'quality_eligible':quality_ok,'frontier_eligible':frontier_ready,'missing_metrics':missing,'distributions':dist}
    candidates={k:v for k,v in summaries.items() if v['frontier_eligible']}
    common_optional=[metric for metric in optional if all(metric in v['distributions'] for v in candidates.values())] if candidates else []
    metrics_used=required+common_optional
    frontier=[]; dominated_by={}
    for aid,a in candidates.items():
        dominators=[]
        for bid,b in candidates.items():
            if aid!=bid and _dominates(b['distributions'],a['distributions'],metrics_used,directions): dominators.append(bid)
        dominated_by[aid]=sorted(dominators)
        if not dominators: frontier.append(aid)
    return {'schema_version':'1.0','experiment_id':next(iter(experiments)),'partition':next(iter(partitions)),'trial_count':len(vals),'variant_count':len(groups),'case_count':len(expected or []),'required_frontier_metrics':required,'optional_metrics_used':common_optional,'optional_metrics_omitted':[m for m in optional if m not in common_optional],'metrics_used_for_pareto':metrics_used,'variants':summaries,'pareto_frontier':sorted(frontier),'dominated_by':dominated_by,'canonical_total_rank':None,'automatic_promotion':False,'authority':'DERIVED_EVALUATION_ANALYSIS','execution_authority':'NONE'}


def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    c=sub.add_parser('case'); c.add_argument('case_json')
    v=sub.add_parser('variant'); v.add_argument('variant_json')
    e=sub.add_parser('evidence'); e.add_argument('evidence_json'); e.add_argument('--quality-floor',type=float,required=True)
    m=sub.add_parser('prepare'); m.add_argument('case_json'); m.add_argument('variant_json'); m.add_argument('--experiment-id',required=True)
    a=sub.add_parser('analyze'); a.add_argument('trials_json')
    args=ap.parse_args()
    try:
        if args.cmd=='case': out=validate_case(_read(Path(args.case_json),'case'))
        elif args.cmd=='variant': out=validate_variant(_read(Path(args.variant_json),'variant'))
        elif args.cmd=='evidence': out=validate_quality_evidence(_read(Path(args.evidence_json),'quality evidence'),args.quality_floor)
        elif args.cmd=='prepare': out=prepare_manifest(_read(Path(args.case_json),'case'),_read(Path(args.variant_json),'variant'),args.experiment_id)
        else:
            payload=_read(Path(args.trials_json),'trial set'); trials=payload.get('trials')
            out=analyze_trials(trials)
        print(json.dumps({'valid':True,'result':out},indent=2)); return 0
    except EvaluationArenaError as exc:
        print(json.dumps({'valid':False,'error':str(exc)},indent=2),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
