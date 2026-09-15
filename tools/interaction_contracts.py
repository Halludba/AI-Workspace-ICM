#!/usr/bin/env python3
"""Validate ICM interaction contracts and conservative rule-centralization candidates."""
from __future__ import annotations
import argparse, json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
POLICY=ROOT/'config'/'interaction_policy.json'
class InteractionError(ValueError): pass

def _read(path:Path,label:str):
    try: value=json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,json.JSONDecodeError) as exc: raise InteractionError(f'cannot load {label}: {exc}') from exc
    if not isinstance(value,dict): raise InteractionError(f'{label} root must be object')
    return value

def _rel_exists(root:Path,ref:str)->bool:
    p=(root/ref).resolve()
    try: p.relative_to(root.resolve())
    except ValueError: return False
    return p.is_file()

def validate_policy(root:Path=ROOT)->dict:
    p=_read(root/'config'/'interaction_policy.json','interaction policy')
    required={'schema_version','authority','grants_execution_authority','grants_mutation_authority','automatic_rule_deletion','components','invariants','contracts','maintenance'}
    if set(p)!=required or p['schema_version']!='1.0': raise InteractionError('interaction policy fields/schema invalid')
    if p['authority']!='SUBORDINATE_SHARED_INVARIANTS' or p['grants_execution_authority'] is not False or p['grants_mutation_authority'] is not False or p['automatic_rule_deletion'] is not False: raise InteractionError('interaction safety boundary invalid')
    components=p['components']
    if not isinstance(components,dict) or not components: raise InteractionError('components must be non-empty object')
    for name,ref in components.items():
        if not isinstance(name,str) or not name or not isinstance(ref,str) or not _rel_exists(root,ref): raise InteractionError(f'component reference invalid: {name}')
    invs=p['invariants']
    if not isinstance(invs,list) or not invs: raise InteractionError('invariants must be non-empty list')
    invmap={}
    for item in invs:
        if not isinstance(item,dict) or set(item)!={'id','statement','source_refs'}: raise InteractionError('invariant fields invalid')
        iid=item['id']
        if not isinstance(iid,str) or not iid or iid in invmap: raise InteractionError('duplicate/invalid invariant id')
        if not isinstance(item['statement'],str) or not item['statement'].strip(): raise InteractionError(f'invariant statement invalid: {iid}')
        refs=item['source_refs']
        if not isinstance(refs,list) or len(refs)<2 or any(not isinstance(x,str) or not _rel_exists(root,x) for x in refs): raise InteractionError(f'invariant source refs invalid: {iid}')
        invmap[iid]=item
    contracts=p['contracts']
    if not isinstance(contracts,list) or not contracts: raise InteractionError('contracts must be non-empty list')
    seen=set(); used=set()
    for c in contracts:
        if not isinstance(c,dict) or set(c)!={'id','left','right','invariants'}: raise InteractionError('contract fields invalid')
        cid=c['id']
        if not isinstance(cid,str) or not cid or cid in seen: raise InteractionError('duplicate/invalid contract id')
        seen.add(cid)
        if c['left'] not in components or c['right'] not in components or c['left']==c['right']: raise InteractionError(f'contract component invalid: {cid}')
        ids=c['invariants']
        if not isinstance(ids,list) or not ids or len(ids)!=len(set(ids)) or any(x not in invmap for x in ids): raise InteractionError(f'contract invariants invalid: {cid}')
        used.update(ids)
    if used!=set(invmap): raise InteractionError('every invariant must be owned by at least one contract')
    m=p['maintenance']; req={'events','structural_validation_on_component_change','structural_validation_on_local_seal','structural_validation_on_publication','semantic_review_on_multi_component_change','semantic_review_publication_commit_interval','automatic_rule_deletion'}
    if not isinstance(m,dict) or set(m)!=req or m['events']!=['COMPONENT_CHANGE','LOCAL_SEAL','PUBLICATION'] or m['automatic_rule_deletion'] is not False: raise InteractionError('interaction maintenance policy invalid')
    if isinstance(m['semantic_review_publication_commit_interval'],bool) or not isinstance(m['semantic_review_publication_commit_interval'],int) or m['semantic_review_publication_commit_interval']<1: raise InteractionError('interaction maintenance interval invalid')
    return {'valid':True,'schema_version':'1.0','contract_count':len(contracts),'invariant_count':len(invs),'authority':p['authority'],'grants_execution_authority':False,'grants_mutation_authority':False,'automatic_rule_deletion':False}

def contract(contract_id:str,root:Path=ROOT)->dict:
    validate_policy(root); p=_read(root/'config'/'interaction_policy.json','interaction policy')
    by_inv={x['id']:x for x in p['invariants']}
    for c in p['contracts']:
        if c['id']==contract_id: return {**c,'invariant_details':[by_inv[x] for x in c['invariants']],'authority':'SUBORDINATE_SHARED_INVARIANTS'}
    raise InteractionError(f'unknown interaction contract: {contract_id}')

def assess_dedup(candidate:dict,root:Path=ROOT)->dict:
    validate_policy(root)
    required={'contract_id','duplicate_rule_refs','relevant_paths','covered_paths'}
    if not isinstance(candidate,dict) or set(candidate)!=required: raise InteractionError('dedup candidate fields invalid')
    contract(candidate['contract_id'],root)
    for key in ('duplicate_rule_refs','relevant_paths','covered_paths'):
        vals=candidate[key]
        if not isinstance(vals,list) or not vals or any(not isinstance(x,str) or not x.strip() for x in vals): raise InteractionError(f'{key} must be non-empty string list')
    relevant=set(candidate['relevant_paths']); covered=set(candidate['covered_paths'])
    missing=sorted(relevant-covered); extra=sorted(covered-relevant)
    all_refs_exist=all(_rel_exists(root,x) for x in candidate['duplicate_rule_refs'])
    eligible=not missing and not extra and all_refs_exist
    return {'valid':True,'contract_id':candidate['contract_id'],'coverage_complete':not missing and not extra,'missing_paths':missing,'extra_paths':extra,'duplicate_refs_exist':all_refs_exist,'eligible_for_semantic_review':eligible,'semantic_equivalence_required':True,'automatic_delete':False,'authority':'ADVISORY_DEDUPLICATION_ASSESSMENT'}

def maintenance_review(changed_paths:list[str],event:str='COMPONENT_CHANGE',commits_since_semantic_review:int=0,root:Path=ROOT)->dict:
    validate_policy(root); p=_read(root/'config'/'interaction_policy.json','interaction policy'); m=p['maintenance']
    if event not in m['events']: raise InteractionError('unknown interaction maintenance event')
    if not isinstance(changed_paths,list) or any(not isinstance(x,str) or not x.strip() for x in changed_paths): raise InteractionError('changed_paths must be string list')
    if isinstance(commits_since_semantic_review,bool) or not isinstance(commits_since_semantic_review,int) or commits_since_semantic_review<0: raise InteractionError('commits_since_semantic_review invalid')
    changed={x.replace('\\','/').strip() for x in changed_paths}; touched=sorted(name for name,ref in p['components'].items() if ref in changed)
    structural=(bool(touched) and m['structural_validation_on_component_change']) or (event=='LOCAL_SEAL' and m['structural_validation_on_local_seal']) or (event=='PUBLICATION' and m['structural_validation_on_publication'])
    semantic=(len(touched)>=2 and m['semantic_review_on_multi_component_change']) or (event=='PUBLICATION' and commits_since_semantic_review>=m['semantic_review_publication_commit_interval'])
    return {'valid':True,'event':event,'touched_components':touched,'structural_validation_recommended':structural,'semantic_dedup_review_recommended':semantic,'semantic_review_reason':('MULTI_COMPONENT_CHANGE' if len(touched)>=2 else 'PUBLICATION_INTERVAL' if semantic else None),'automatic_rule_deletion':False,'authority':'ADVISORY_MAINTENANCE_TRIGGER'}

def main()->int:
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    sub.add_parser('validate'); show=sub.add_parser('show'); show.add_argument('contract_id'); ded=sub.add_parser('dedupe'); ded.add_argument('candidate'); mt=sub.add_parser('maintenance'); mt.add_argument('--event',choices=['COMPONENT_CHANGE','LOCAL_SEAL','PUBLICATION'],default='COMPONENT_CHANGE'); mt.add_argument('--path',action='append',default=[]); mt.add_argument('--commits-since-semantic-review',type=int,default=0)
    a=ap.parse_args()
    try:
        if a.cmd=='validate': out=validate_policy()
        elif a.cmd=='show': out=contract(a.contract_id)
        elif a.cmd=='dedupe': out=assess_dedup(_read(Path(a.candidate),'dedup candidate'))
        else: out=maintenance_review(a.path,a.event,a.commits_since_semantic_review)
        print(json.dumps({'valid':True,'result':out},indent=2)); return 0
    except InteractionError as exc:
        print(json.dumps({'valid':False,'error':str(exc)},indent=2)); return 2
if __name__=='__main__': raise SystemExit(main())