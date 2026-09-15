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
    required={'schema_version','state_root','partitions','task_kinds','evaluator_kinds','score_min','score_max','max_source_refs','max_tags','max_strategy_params','max_model_calls','max_tool_calls','forbidden_keys','quality_floor_required','experiment_outputs_canonical','execution_authority','automatic_promotion','max_trials','required_frontier_metrics','optional_frontier_metrics','metric_directions','max_suite_cases','max_suite_variants','max_experiment_config_items','strategy_runner','ablation','local_worker_benchmark'}
    if set(p)!=required or p.get('schema_version')!='1.0' or p.get('experiment_outputs_canonical') is not False or p.get('execution_authority')!='NONE' or p.get('automatic_promotion') is not False or p.get('quality_floor_required') is not True: raise EvaluationArenaError('evaluation arena policy safety contract invalid')
    for key in ('partitions','task_kinds','evaluator_kinds','forbidden_keys'):
        if not isinstance(p[key],list) or not p[key] or len(p[key])!=len(set(p[key])) or any(not isinstance(v,str) or not v for v in p[key]): raise EvaluationArenaError(f'{key} must be unique non-empty strings')
    for key in ('max_source_refs','max_tags','max_strategy_params','max_model_calls','max_tool_calls','max_suite_cases','max_suite_variants','max_experiment_config_items'):
        if isinstance(p[key],bool) or not isinstance(p[key],int) or p[key]<1: raise EvaluationArenaError(f'{key} must be positive integer')
    for key in ('score_min','score_max'):
        if isinstance(p[key],bool) or not isinstance(p[key],(int,float)) or not math.isfinite(p[key]): raise EvaluationArenaError(f'{key} must be finite number')
    if p['score_min']>=p['score_max']: raise EvaluationArenaError('score range invalid')

    if isinstance(p['max_trials'],bool) or not isinstance(p['max_trials'],int) or p['max_trials']<1: raise EvaluationArenaError('max_trials must be positive integer')
    all_frontier=p['required_frontier_metrics']+p['optional_frontier_metrics'] if isinstance(p['required_frontier_metrics'],list) and isinstance(p['optional_frontier_metrics'],list) else []
    if not p['required_frontier_metrics'] or len(all_frontier)!=len(set(all_frontier)) or set(p['metric_directions'])!=set(all_frontier) or any(p['metric_directions'][m] not in {'MAXIMIZE','MINIMIZE'} for m in all_frontier): raise EvaluationArenaError('frontier metric policy invalid')
    sr=p['strategy_runner']
    sr_required={'max_variants','max_cases','max_trials','max_replicates','allowlisted_dimensions','strategy_param_allowlist','budget_maxima','required_budget_metrics','optional_token_budget_metric','early_stop','executor_partition_visible','executor_evaluator_visible','automatic_promotion'}
    if not isinstance(sr,dict) or set(sr)!=sr_required: raise EvaluationArenaError('strategy runner policy fields invalid')
    for key in ('max_variants','max_cases','max_trials','max_replicates'):
        if isinstance(sr[key],bool) or not isinstance(sr[key],int) or sr[key]<1: raise EvaluationArenaError(f'strategy runner {key} must be positive integer')
    dims=sr['allowlisted_dimensions']
    if not isinstance(dims,list) or not dims or len(dims)!=len(set(dims)) or any(not isinstance(v,str) or not v for v in dims): raise EvaluationArenaError('strategy runner allowlisted_dimensions invalid')
    allow=sr['strategy_param_allowlist']
    if not isinstance(allow,dict) or any(not isinstance(k,str) or not k or not isinstance(v,list) or not v or len(v)!=len(set(map(str,v))) for k,v in allow.items()): raise EvaluationArenaError('strategy_param_allowlist invalid')
    maxima=sr['budget_maxima']; budget_keys={'wall_time_ms','model_calls','tool_calls','input_tokens_total'}
    if not isinstance(maxima,dict) or set(maxima)!=budget_keys or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0 for v in maxima.values()): raise EvaluationArenaError('strategy runner budget_maxima invalid')
    req_budget=sr['required_budget_metrics']
    if not isinstance(req_budget,list) or not req_budget or len(req_budget)!=len(set(req_budget)) or any(v not in budget_keys for v in req_budget): raise EvaluationArenaError('required_budget_metrics invalid')
    if sr['optional_token_budget_metric']!='input_tokens_total': raise EvaluationArenaError('optional token budget metric invalid')
    stop=sr['early_stop']
    if not isinstance(stop,dict) or set(stop)!={'min_trials','quality_floor_failure','failed_or_blocked'} or isinstance(stop['min_trials'],bool) or not isinstance(stop['min_trials'],int) or stop['min_trials']<1 or not isinstance(stop['quality_floor_failure'],bool) or not isinstance(stop['failed_or_blocked'],bool): raise EvaluationArenaError('strategy runner early_stop invalid')
    if sr['executor_partition_visible'] is not False or sr['executor_evaluator_visible'] is not False or sr['automatic_promotion'] is not False: raise EvaluationArenaError('strategy runner safety boundary invalid')
    ab=p['ablation']; ab_req={'cost_metrics','minimum_relative_improvement','maximum_quality_regression','automatic_removal','quality_floor_required'}
    if not isinstance(ab,dict) or set(ab)!=ab_req or ab['automatic_removal'] is not False or ab['quality_floor_required'] is not True: raise EvaluationArenaError('ablation policy invalid')
    if not isinstance(ab['cost_metrics'],list) or not ab['cost_metrics'] or len(ab['cost_metrics'])!=len(set(ab['cost_metrics'])) or any(x not in all_frontier for x in ab['cost_metrics']): raise EvaluationArenaError('ablation cost_metrics invalid')
    if isinstance(ab['minimum_relative_improvement'],bool) or not isinstance(ab['minimum_relative_improvement'],(int,float)) or not 0<ab['minimum_relative_improvement']<1: raise EvaluationArenaError('ablation minimum_relative_improvement invalid')
    if isinstance(ab['maximum_quality_regression'],bool) or not isinstance(ab['maximum_quality_regression'],(int,float)) or not 0<=ab['maximum_quality_regression']<1: raise EvaluationArenaError('ablation maximum_quality_regression invalid')
    wb=p['local_worker_benchmark']; wb_req={'capability_id','minimum_valid_tool_call_rate','minimum_scope_compliance_rate','minimum_verified_success_rate','maximum_unnecessary_tool_call_rate','frontier_metrics','automatic_promotion'}
    if not isinstance(wb,dict) or set(wb)!=wb_req or wb['capability_id']!='LOCAL_CODE_WORKER' or wb['automatic_promotion'] is not False: raise EvaluationArenaError('local worker benchmark policy invalid')
    for key in ('minimum_valid_tool_call_rate','minimum_scope_compliance_rate','minimum_verified_success_rate','maximum_unnecessary_tool_call_rate'):
        v=wb[key]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not 0<=v<=1: raise EvaluationArenaError(f'local worker benchmark {key} invalid')
    if not isinstance(wb['frontier_metrics'],dict) or not wb['frontier_metrics'] or any(v not in {'MAXIMIZE','MINIMIZE'} for v in wb['frontier_metrics'].values()): raise EvaluationArenaError('local worker benchmark frontier metrics invalid')
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


def _bounded_scalar_map(value,label,max_items):
    if not isinstance(value,dict) or len(value)>max_items or any(not isinstance(k,str) or not k or not _json_scalar(v) or (isinstance(v,float) and not math.isfinite(v)) for k,v in value.items()): raise EvaluationArenaError(f'{label} must be bounded scalar mapping')
    return dict(sorted(value.items()))

def build_suite_manifest(cases:list[dict],variants:list[dict],experiment_config:dict,experiment_id:str,root:Path=ROOT):
    p=load_policy(root); _nonempty(experiment_id,'experiment_id')
    if not isinstance(cases,list) or not cases or len(cases)>p['max_suite_cases']: raise EvaluationArenaError('cases must be non-empty bounded list')
    if not isinstance(variants,list) or not variants or len(variants)>p['max_suite_variants']: raise EvaluationArenaError('variants must be non-empty bounded list')
    cv=[validate_case(c,root) for c in cases]; vv=[validate_variant(v,root) for v in variants]; cfg=_bounded_scalar_map(experiment_config,'experiment_config',p['max_experiment_config_items'])
    revisions={x['base_revision'] for x in cv+vv}
    if len(revisions)!=1: raise EvaluationArenaError('suite cases and variants must pin one base_revision')
    case_fps=[x['case_fingerprint'] for x in cv]; variant_fps=[x['variant_fingerprint'] for x in vv]
    if len(case_fps)!=len(set(case_fps)) or len(variant_fps)!=len(set(variant_fps)): raise EvaluationArenaError('suite identities must be unique')
    base_revision=next(iter(revisions))
    body={'schema_version':'1.0','experiment_id':experiment_id.strip(),'base_revision':base_revision,'case_fingerprints':sorted(case_fps),'variant_fingerprints':sorted(variant_fps),'experiment_config':cfg}
    execution_variants=[]
    for v in vv:
        execution_variants.append({k:v[k] for k in ('schema_version','variant_id','base_revision','model_ref','context_policy_ref','planner_enabled','verification_mode','max_model_calls','max_tool_calls','strategy_params','variant_fingerprint')})
    partitions={name:sum(1 for c in cv if c['partition']==name) for name in p['partitions']}
    return {**body,'suite_fingerprint':fingerprint(body),'partition_counts':partitions,'execution_view':{'schema_version':'1.0','experiment_id':experiment_id.strip(),'base_revision':base_revision,'cases':[case_execution_view(c,root) for c in cases],'variants':execution_variants,'experiment_config':cfg,'partition_metadata_exposed':False},'automatic_promotion':False,'authority':'NONCANONICAL_SUITE_MANIFEST','execution_authority':'NONE'}

def compare_partitions(tune:dict,holdout:dict):
    if not isinstance(tune,dict) or not isinstance(holdout,dict): raise EvaluationArenaError('partition analyses must be objects')
    if tune.get('authority')!='DERIVED_EVALUATION_ANALYSIS' or holdout.get('authority')!='DERIVED_EVALUATION_ANALYSIS': raise EvaluationArenaError('partition analyses must be arena analysis outputs')
    if tune.get('experiment_id')!=holdout.get('experiment_id'): raise EvaluationArenaError('partition analyses must share experiment_id')
    if tune.get('partition')!='TUNE' or holdout.get('partition')!='HOLDOUT': raise EvaluationArenaError('partition analyses must be TUNE then HOLDOUT')
    tv=set(tune.get('variants',{})); hv=set(holdout.get('variants',{}))
    if tv!=hv or not tv: raise EvaluationArenaError('partition analyses must cover identical variants')
    tune_front=set(tune.get('pareto_frontier',[])); hold_front=set(holdout.get('pareto_frontier',[])); variants={}
    for vid in sorted(tv):
        ta=tune['variants'][vid]; ha=holdout['variants'][vid]; signals=[]
        if vid in tune_front and vid not in hold_front: signals.append('TUNE_FRONTIER_NOT_REPRODUCED_ON_HOLDOUT')
        if ta.get('quality_eligible') and not ha.get('quality_eligible'): signals.append('QUALITY_FLOOR_NOT_REPRODUCED_ON_HOLDOUT')
        tq=ta.get('distributions',{}).get('quality_score',{}).get('median'); hq=ha.get('distributions',{}).get('quality_score',{}).get('median')
        tw=ta.get('distributions',{}).get('wall_time_ms',{}).get('median'); hw=ha.get('distributions',{}).get('wall_time_ms',{}).get('median')
        variants[vid]={'tune':{'quality_median':tq,'wall_time_median_ms':tw,'frontier':vid in tune_front,'quality_eligible':ta.get('quality_eligible')},'holdout':{'quality_median':hq,'wall_time_median_ms':hw,'frontier':vid in hold_front,'quality_eligible':ha.get('quality_eligible')},'observed_delta':{'quality_median':None if tq is None or hq is None else hq-tq,'wall_time_median_ms':None if tw is None or hw is None else hw-tw},'signals':signals}
    return {'schema_version':'1.0','experiment_id':tune['experiment_id'],'tune_frontier':sorted(tune_front),'holdout_frontier':sorted(hold_front),'stable_frontier':sorted(tune_front&hold_front),'variants':variants,'generalization_claim':'HOLDOUT_EVIDENCE_ONLY_NOT_PROOF_OF_GENERALIZATION','automatic_promotion':False,'authority':'DERIVED_HOLDOUT_COMPARISON','execution_authority':'NONE'}



def _strategy_runner_policy(root:Path=ROOT):
    return load_policy(root)['strategy_runner']

def _validate_runner_variant(variant:dict,root:Path=ROOT):
    value=validate_variant(variant,root); sr=_strategy_runner_policy(root); allow=sr['strategy_param_allowlist']; params=value['strategy_params']
    unknown=sorted(set(params)-set(allow))
    if unknown: raise EvaluationArenaError('strategy runner parameter not allowlisted: '+', '.join(unknown))
    for key,val in params.items():
        if val not in allow[key]: raise EvaluationArenaError(f'strategy runner parameter {key} value not allowlisted')
    return value

def validate_strategy_run_request(request:dict,root:Path=ROOT):
    p=load_policy(root); sr=p['strategy_runner']; _privacy(request,{x.lower() for x in p['forbidden_keys']})
    required={'schema_version','run_id','partition','variant_ids','replicates','budget'}
    if not isinstance(request,dict) or set(request)!=required or request.get('schema_version')!='1.0': raise EvaluationArenaError('strategy run request fields must match contract')
    _nonempty(request['run_id'],'run_id')
    if request['partition'] not in p['partitions']: raise EvaluationArenaError('strategy run partition invalid')
    ids=request['variant_ids']
    if not isinstance(ids,list) or not ids or len(ids)>sr['max_variants'] or len(ids)!=len(set(ids)) or any(not isinstance(v,str) or not v.strip() for v in ids): raise EvaluationArenaError('variant_ids must be unique bounded non-empty strings')
    reps=request['replicates']
    if isinstance(reps,bool) or not isinstance(reps,int) or reps<1 or reps>sr['max_replicates']: raise EvaluationArenaError('replicates out of range')
    budget=request['budget']; maxima=sr['budget_maxima']
    if not isinstance(budget,dict) or set(budget)!=set(maxima): raise EvaluationArenaError('strategy run budget fields invalid')
    normalized={}
    for key,cap in maxima.items():
        value=budget[key]
        if key==sr['optional_token_budget_metric'] and value is None:
            normalized[key]=None; continue
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or value>cap: raise EvaluationArenaError(f'budget {key} out of range')
        normalized[key]=float(value)
    if normalized['wall_time_ms']<=0: raise EvaluationArenaError('wall_time_ms budget must be positive')
    return {**request,'run_id':request['run_id'].strip(),'variant_ids':[v.strip() for v in ids],'budget':normalized}

def validate_execution_observation(value:dict,root:Path=ROOT):
    p=load_policy(root); sr=p['strategy_runner']; bp=_benchmark_policy(root); op=_observatory_policy(root); _privacy(value,{x.lower() for x in p['forbidden_keys']})
    required={'schema_version','outcome','observed_metrics','rework_class','evidence_refs'}
    if not isinstance(value,dict) or set(value)!=required or value.get('schema_version')!='1.0': raise EvaluationArenaError('execution observation fields must match contract')
    if value['outcome'] not in op['outcomes']: raise EvaluationArenaError('execution observation outcome invalid')
    refs=_refs(value['evidence_refs'],'evidence_refs',p['max_source_refs']); metrics=value['observed_metrics']
    if not isinstance(metrics,dict) or set(metrics)!=set(bp['required_metrics']): raise EvaluationArenaError('execution observation metrics must match benchmark metric vocabulary')
    normalized={}
    for key,item in metrics.items():
        if item is None: normalized[key]=None; continue
        if isinstance(item,bool) or not isinstance(item,(int,float)) or not math.isfinite(item) or item<0: raise EvaluationArenaError(f'observed metric {key} must be non-negative finite number or null')
        if key in {'correctness_score','context_recall','unnecessary_context_ratio'} and item>1: raise EvaluationArenaError(f'observed metric {key} must be <= 1')
        if key in {'model_calls','tool_calls'} and float(item).is_integer() is False: raise EvaluationArenaError(f'observed metric {key} must be integral')
        normalized[key]=float(item)
    for key in sr['required_budget_metrics']:
        if normalized.get(key) is None: raise EvaluationArenaError(f'required budget metric {key} is unavailable')
    rw=value['rework_class']
    if value['outcome']=='REWORK':
        if rw not in op['rework_classes']: raise EvaluationArenaError('REWORK observation requires valid rework_class')
    elif rw is not None: raise EvaluationArenaError('rework_class only valid for REWORK outcome')
    return {**value,'observed_metrics':normalized,'evidence_refs':refs,'authority':'OBSERVED_STRATEGY_EXECUTION','execution_authority':'NONE'}

def _remaining_budget(budget:dict,consumed:dict):
    out={}
    for key,limit in budget.items():
        if limit is None: out[key]=None
        elif consumed.get(key) is None: out[key]=None
        else: out[key]=max(0.0,float(limit)-float(consumed[key]))
    return out

def _consume_budget(budget:dict,consumed:dict,observation:dict,root:Path=ROOT):
    sr=_strategy_runner_policy(root); metrics=observation['observed_metrics']; new=dict(consumed)
    for key in sr['required_budget_metrics']:
        total=float(new[key])+float(metrics[key])
        if total>float(budget[key])+1e-9: raise EvaluationArenaError(f'executor exceeded hard budget: {key}')
        new[key]=total
    token_key=sr['optional_token_budget_metric']; token=metrics[token_key]
    if token is None:
        if budget[token_key] is not None: raise EvaluationArenaError('token budget configured but input token usage is unavailable')
        new[token_key]=None
    elif new[token_key] is not None:
        total=float(new[token_key])+float(token)
        if budget[token_key] is not None and total>float(budget[token_key])+1e-9: raise EvaluationArenaError('executor exceeded hard budget: input_tokens_total')
        new[token_key]=total
    return new

def run_strategy_search(suite:dict,request:dict,executor=None,evaluator=None,root:Path=ROOT):
    if not callable(executor): raise EvaluationArenaError('strategy execution capability unavailable')
    if not callable(evaluator): raise EvaluationArenaError('strategy evaluator capability unavailable')
    if not isinstance(suite,dict) or set(suite)!={'cases','variants','experiment_config','experiment_id'}: raise EvaluationArenaError('suite payload fields invalid for strategy run')
    req=validate_strategy_run_request(request,root); sr=_strategy_runner_policy(root)
    manifest=build_suite_manifest(suite['cases'],suite['variants'],suite['experiment_config'],suite['experiment_id'],root)
    case_pairs=[(raw,validate_case(raw,root)) for raw in suite['cases']]; variant_pairs=[(raw,_validate_runner_variant(raw,root)) for raw in suite['variants']]
    if len({v['case_id'] for _,v in case_pairs})!=len(case_pairs) or len({v['variant_id'] for _,v in variant_pairs})!=len(variant_pairs): raise EvaluationArenaError('strategy run requires unique case_id and variant_id values')
    cases=[pair for pair in case_pairs if pair[1]['partition']==req['partition']]
    if not cases: raise EvaluationArenaError('strategy run partition has no cases')
    if len(cases)>sr['max_cases']: raise EvaluationArenaError('strategy run exceeds max_cases')
    by_variant={v['variant_id']:(raw,v) for raw,v in variant_pairs}; selected=[]
    for variant_id in req['variant_ids']:
        if variant_id not in by_variant: raise EvaluationArenaError(f'unknown strategy variant_id: {variant_id}')
        selected.append(by_variant[variant_id])
    potential=len(cases)*len(selected)*req['replicates']
    if potential>sr['max_trials']: raise EvaluationArenaError('strategy run exceeds max_trials')
    exec_cases={c['case_id']:c for c in manifest['execution_view']['cases']}; exec_variants={v['variant_id']:v for v in manifest['execution_view']['variants']}
    consumed={'wall_time_ms':0.0,'model_calls':0.0,'tool_calls':0.0,'input_tokens_total':0.0}; attempts=[]; trials=[]; discarded=[]; completed=[]
    expected_per_variant=len(cases)*req['replicates']; stop_cfg=sr['early_stop']
    for raw_variant,variant in selected:
        variant_trial_count=0; stopped=False
        for raw_case,case in cases:
            if stopped: break
            for replicate in range(req['replicates']):
                packet={'schema_version':'1.0','run_id':req['run_id'],'experiment_id':suite['experiment_id'],'suite_fingerprint':manifest['suite_fingerprint'],'case':exec_cases[case['case_id']],'variant':exec_variants[variant['variant_id']],'replicate':replicate,'remaining_budget':_remaining_budget(req['budget'],consumed),'authority':'BOUNDED_STRATEGY_EXECUTION_PACKET','execution_authority':'NONE'}
                observation=validate_execution_observation(executor(packet),root); consumed=_consume_budget(req['budget'],consumed,observation,root)
                attempt={'case_id':case['case_id'],'variant_id':variant['variant_id'],'replicate':replicate,'outcome':observation['outcome'],'observed_metrics':observation['observed_metrics'],'evidence_refs':observation['evidence_refs']}; attempts.append(attempt)
                if observation['outcome'] in {'FAILED','BLOCKED'} and stop_cfg['failed_or_blocked']:
                    discarded.append({'variant_id':variant['variant_id'],'variant_fingerprint':variant['variant_fingerprint'],'reason':'EXECUTION_'+observation['outcome'],'evidence_refs':observation['evidence_refs']}); stopped=True; break
                quality_raw=evaluator(raw_case,observation,packet); quality=validate_quality_evidence(quality_raw,case['evaluator']['quality_floor'],root)
                pair_manifest=prepare_manifest(raw_case,raw_variant,suite['experiment_id'],root)
                trial={'schema_version':'1.0','trial_id':f"{req['run_id']}:{variant['variant_id']}:{case['case_id']}:{replicate}",'experiment_id':suite['experiment_id'],'manifest_fingerprint':pair_manifest['manifest_fingerprint'],'case_fingerprint':case['case_fingerprint'],'variant_fingerprint':variant['variant_fingerprint'],'partition':req['partition'],'replicate':replicate,'quality_floor':case['evaluator']['quality_floor'],'quality_evidence':quality_raw,'observed_metrics':observation['observed_metrics'],'outcome':observation['outcome'],'rework_class':observation['rework_class']}
                validate_trial(trial,root); trials.append(trial); variant_trial_count+=1
                if variant_trial_count>=stop_cfg['min_trials'] and not quality['meets_quality_floor'] and stop_cfg['quality_floor_failure']:
                    discarded.append({'variant_id':variant['variant_id'],'variant_fingerprint':variant['variant_fingerprint'],'reason':'QUALITY_FLOOR_FAILURE','evidence_refs':quality['evidence_refs']}); stopped=True; break
        if not stopped and variant_trial_count==expected_per_variant: completed.append({'variant_id':variant['variant_id'],'variant_fingerprint':variant['variant_fingerprint']})
    completed_fps={v['variant_fingerprint'] for v in completed}; analysis_trials=[t for t in trials if t['variant_fingerprint'] in completed_fps]
    analysis=analyze_trials(analysis_trials,root) if analysis_trials else None
    return {'schema_version':'1.0','run_id':req['run_id'],'experiment_id':suite['experiment_id'],'suite_fingerprint':manifest['suite_fingerprint'],'partition':req['partition'],'selected_variant_ids':req['variant_ids'],'potential_trial_count':potential,'attempt_count':len(attempts),'trial_count':len(trials),'completed_variants':completed,'discarded_variants':discarded,'budget':req['budget'],'budget_consumed':consumed,'analysis':analysis,'comparison_ready':len(completed)>=2,'executor_partition_visible':False,'executor_evaluator_visible':False,'search_bounded':True,'automatic_promotion':False,'authority':'DERIVED_BOUNDED_STRATEGY_RUN','execution_authority':'NONE'}

def fixture_callbacks(fixture:dict):
    if not isinstance(fixture,dict) or set(fixture)!={'schema_version','executions','evaluations'} or fixture.get('schema_version')!='1.0' or not isinstance(fixture['executions'],dict) or not isinstance(fixture['evaluations'],dict): raise EvaluationArenaError('strategy fixture fields invalid')
    def key(packet): return f"{packet['case']['case_id']}|{packet['variant']['variant_id']}|{packet['replicate']}"
    def executor(packet):
        k=key(packet)
        if k not in fixture['executions']: raise EvaluationArenaError(f'fixture execution missing: {k}')
        return fixture['executions'][k]
    def evaluator(case,observation,packet):
        k=key(packet)
        if k not in fixture['evaluations']: raise EvaluationArenaError(f'fixture evaluation missing: {k}')
        return fixture['evaluations'][k]
    return executor,evaluator


def compare_ablation(request:dict,root:Path=ROOT):
    p=load_policy(root); cfg=p['ablation']; required={'schema_version','experiment_id','mechanism','quality_floor','baseline','ablated'}
    if not isinstance(request,dict) or set(request)!=required or request.get('schema_version')!='1.0': raise EvaluationArenaError('ablation request fields must match contract')
    _nonempty(request['experiment_id'],'experiment_id'); mechanism=_nonempty(request['mechanism'],'mechanism')
    floor=request['quality_floor']
    if isinstance(floor,bool) or not isinstance(floor,(int,float)) or not math.isfinite(floor) or floor<p['score_min'] or floor>p['score_max']: raise EvaluationArenaError('ablation quality_floor invalid')
    measurement_fields={'quality_score',*cfg['cost_metrics'],'evidence_refs'}
    def measurement(value,label):
        if not isinstance(value,dict) or set(value)!=measurement_fields: raise EvaluationArenaError(f'{label} fields invalid')
        q=value['quality_score']
        if isinstance(q,bool) or not isinstance(q,(int,float)) or not math.isfinite(q) or q<p['score_min'] or q>p['score_max']: raise EvaluationArenaError(f'{label} quality_score invalid')
        out={'quality_score':float(q)}
        for key in cfg['cost_metrics']:
            item=value[key]
            if item is None:
                if key=='wall_time_ms': raise EvaluationArenaError(f'{label} wall_time_ms is required')
                out[key]=None; continue
            if isinstance(item,bool) or not isinstance(item,(int,float)) or not math.isfinite(item) or item<0: raise EvaluationArenaError(f'{label} {key} invalid')
            out[key]=float(item)
        out['evidence_refs']=_refs(value['evidence_refs'],f'{label}.evidence_refs',p['max_source_refs'])
        return out
    baseline=measurement(request['baseline'],'baseline'); ablated=measurement(request['ablated'],'ablated')
    base_floor=baseline['quality_score']>=floor; ab_floor=ablated['quality_score']>=floor; quality_delta=ablated['quality_score']-baseline['quality_score']
    quality_preserved=base_floor and ab_floor and quality_delta>=-cfg['maximum_quality_regression']
    deltas={}; improved=[]; regressed=[]
    for key in cfg['cost_metrics']:
        a=baseline[key]; b=ablated[key]
        if a is None or b is None:
            deltas[key]={'baseline':a,'ablated':b,'delta':None,'relative_improvement':None}; continue
        delta=b-a; rel=((a-b)/a) if a>0 else (1.0 if a==0 and b<0 else 0.0)
        deltas[key]={'baseline':a,'ablated':b,'delta':delta,'relative_improvement':rel}
        if rel>=cfg['minimum_relative_improvement']: improved.append(key)
        if b>a+1e-9: regressed.append(key)
    if not quality_preserved: verdict='QUALITY_REGRESSION'
    elif improved and not regressed: verdict='ABLATION_FAVORABLE'
    elif improved: verdict='TRADEOFF_REVIEW'
    else: verdict='NO_MATERIAL_GAIN'
    return {'schema_version':'1.0','experiment_id':request['experiment_id'],'mechanism':mechanism,'quality_floor':float(floor),'quality_delta':quality_delta,'baseline_meets_quality_floor':base_floor,'ablated_meets_quality_floor':ab_floor,'quality_preserved':quality_preserved,'cost_deltas':deltas,'materially_improved_metrics':improved,'regressed_cost_metrics':regressed,'verdict':verdict,'candidate_for_removal_review':verdict=='ABLATION_FAVORABLE','automatic_removal':False,'automatic_promotion':False,'missing_metrics_treated_as_zero':False,'authority':'ADVISORY_ABLATION_EVIDENCE'}


def compare_local_workers(request:dict,root:Path=ROOT):
    p=load_policy(root); cfg=p['local_worker_benchmark']; required={'schema_version','benchmark_id','providers'}
    if not isinstance(request,dict) or set(request)!=required or request.get('schema_version')!='1.0': raise EvaluationArenaError('local worker benchmark request fields invalid')
    _nonempty(request['benchmark_id'],'benchmark_id'); providers=request['providers']
    if not isinstance(providers,list) or not providers: raise EvaluationArenaError('local worker benchmark requires providers')
    seen=set(); scorecards=[]
    numeric_optional=('wall_time_ms','input_tokens_total','repair_count','vram_peak_mib','coding_quality_score')
    def med(vals): return None if not vals else float(statistics.median(vals))
    for item in providers:
        if not isinstance(item,dict) or set(item)!={'provider_id','capability_id','trials'}: raise EvaluationArenaError('worker provider fields invalid')
        pid=_nonempty(item['provider_id'],'provider_id')
        if pid in seen: raise EvaluationArenaError('duplicate worker provider_id')
        seen.add(pid)
        if item['capability_id']!=cfg['capability_id']: raise EvaluationArenaError('worker capability_id mismatch')
        trials=item['trials']
        if not isinstance(trials,list) or not trials: raise EvaluationArenaError('worker provider requires trials')
        tool=valid=unnecessary=scope_ok=success=patch_total=patch_correct=0; optional={k:[] for k in numeric_optional}
        for tr in trials:
            required_trial={'tool_calls','valid_tool_calls','unnecessary_tool_calls','scope_violations','verified_success','patch_correct','wall_time_ms','input_tokens_total','repair_count','vram_peak_mib','coding_quality_score'}
            if not isinstance(tr,dict) or set(tr)!=required_trial: raise EvaluationArenaError('worker trial fields invalid')
            for key in ('tool_calls','valid_tool_calls','unnecessary_tool_calls','scope_violations'):
                v=tr[key]
                if isinstance(v,bool) or not isinstance(v,int) or v<0: raise EvaluationArenaError(f'worker trial {key} invalid')
            if tr['valid_tool_calls']>tr['tool_calls'] or tr['unnecessary_tool_calls']>tr['tool_calls']: raise EvaluationArenaError('worker trial tool counts inconsistent')
            if not isinstance(tr['verified_success'],bool) or tr['patch_correct'] not in {True,False,None}: raise EvaluationArenaError('worker trial outcome fields invalid')
            tool+=tr['tool_calls']; valid+=tr['valid_tool_calls']; unnecessary+=tr['unnecessary_tool_calls']; scope_ok+=1 if tr['scope_violations']==0 else 0; success+=1 if tr['verified_success'] else 0
            if tr['patch_correct'] is not None: patch_total+=1; patch_correct+=1 if tr['patch_correct'] else 0
            for key in numeric_optional:
                v=tr[key]
                if v is None: continue
                if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or v<0: raise EvaluationArenaError(f'worker trial {key} invalid')
                optional[key].append(float(v))
        n=len(trials); valid_rate=1.0 if tool==0 else valid/tool; unnecessary_rate=0.0 if tool==0 else unnecessary/tool; scope_rate=scope_ok/n; success_rate=success/n; patch_rate=None if patch_total==0 else patch_correct/patch_total
        gates={'valid_tool_call_rate':valid_rate>=cfg['minimum_valid_tool_call_rate'],'scope_compliance_rate':scope_rate>=cfg['minimum_scope_compliance_rate'],'verified_success_rate':success_rate>=cfg['minimum_verified_success_rate'],'unnecessary_tool_call_rate':unnecessary_rate<=cfg['maximum_unnecessary_tool_call_rate']}
        eligible=all(gates.values())
        metrics={'verified_success_rate':success_rate,'patch_correctness_rate':patch_rate,'unnecessary_tool_call_rate':unnecessary_rate,'wall_time_ms_median':med(optional['wall_time_ms']),'input_tokens_total_median':med(optional['input_tokens_total']),'repair_count_median':med(optional['repair_count']),'vram_peak_mib_median':med(optional['vram_peak_mib']),'coding_quality_score_median':med(optional['coding_quality_score'])}
        scorecards.append({'provider_id':pid,'capability_id':cfg['capability_id'],'trial_count':n,'quality_gates':gates,'eligible':eligible,'metrics':metrics})
    eligible=[x for x in scorecards if x['eligible']]
    dirs=cfg['frontier_metrics']
    def dominates(a,b):
        common=[k for k in dirs if a['metrics'].get(k) is not None and b['metrics'].get(k) is not None]
        if not common: return False
        no_worse=True; strict=False
        for k in common:
            av=a['metrics'][k]; bv=b['metrics'][k]; direction=dirs[k]
            if direction=='MAXIMIZE':
                if av<bv: no_worse=False
                if av>bv: strict=True
            else:
                if av>bv: no_worse=False
                if av<bv: strict=True
        return no_worse and strict
    frontier=[]
    for candidate in eligible:
        if not any(other is not candidate and dominates(other,candidate) for other in eligible): frontier.append(candidate['provider_id'])
    return {'schema_version':'1.0','benchmark_id':request['benchmark_id'],'capability_id':cfg['capability_id'],'scorecards':scorecards,'eligible_provider_ids':[x['provider_id'] for x in eligible],'pareto_frontier_provider_ids':sorted(frontier),'tool_reliability_is_quality_gate':True,'generic_coding_score_cannot_override_failed_tool_or_scope_gate':True,'missing_metrics_treated_as_zero':False,'automatic_promotion':False,'authority':'ADVISORY_LOCAL_WORKER_BENCHMARK'}

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    c=sub.add_parser('case'); c.add_argument('case_json')
    v=sub.add_parser('variant'); v.add_argument('variant_json')
    e=sub.add_parser('evidence'); e.add_argument('evidence_json'); e.add_argument('--quality-floor',type=float,required=True)
    m=sub.add_parser('prepare'); m.add_argument('case_json'); m.add_argument('variant_json'); m.add_argument('--experiment-id',required=True)
    a=sub.add_parser('analyze'); a.add_argument('trials_json')
    sm=sub.add_parser('suite'); sm.add_argument('suite_json')
    cp=sub.add_parser('compare-partitions'); cp.add_argument('tune_json'); cp.add_argument('holdout_json')
    r=sub.add_parser('run'); r.add_argument('suite_json'); r.add_argument('request_json'); r.add_argument('--fixture')
    ab=sub.add_parser('ablation'); ab.add_argument('request_json'); wb=sub.add_parser('worker-benchmark'); wb.add_argument('request_json')
    args=ap.parse_args()
    try:
        if args.cmd=='case': out=validate_case(_read(Path(args.case_json),'case'))
        elif args.cmd=='variant': out=validate_variant(_read(Path(args.variant_json),'variant'))
        elif args.cmd=='evidence': out=validate_quality_evidence(_read(Path(args.evidence_json),'quality evidence'),args.quality_floor)
        elif args.cmd=='prepare': out=prepare_manifest(_read(Path(args.case_json),'case'),_read(Path(args.variant_json),'variant'),args.experiment_id)
        elif args.cmd=='analyze':
            payload=_read(Path(args.trials_json),'trial set'); trials=payload.get('trials'); out=analyze_trials(trials)
        elif args.cmd=='suite':
            payload=_read(Path(args.suite_json),'suite'); out=build_suite_manifest(payload.get('cases'),payload.get('variants'),payload.get('experiment_config'),payload.get('experiment_id'))
        elif args.cmd=='run':
            if not args.fixture: raise EvaluationArenaError('strategy execution capability unavailable; --fixture is required for deterministic CLI execution')
            executor,evaluator=fixture_callbacks(_read(Path(args.fixture),'strategy fixture')); out=run_strategy_search(_read(Path(args.suite_json),'suite'),_read(Path(args.request_json),'strategy run request'),executor,evaluator)
        elif args.cmd=='ablation': out=compare_ablation(_read(Path(args.request_json),'ablation request'))
        elif args.cmd=='worker-benchmark': out=compare_local_workers(_read(Path(args.request_json),'local worker benchmark request'))
        else: out=compare_partitions(_read(Path(args.tune_json),'tune analysis'),_read(Path(args.holdout_json),'holdout analysis'))
        print(json.dumps({'valid':True,'result':out},indent=2)); return 0
    except EvaluationArenaError as exc:
        print(json.dumps({'valid':False,'error':str(exc)},indent=2),file=sys.stderr); return 2
if __name__=='__main__': raise SystemExit(main())
