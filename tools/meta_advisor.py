#!/usr/bin/env python3
"""Evidence-gated suggestion/research advice and research prompt compilation."""
from __future__ import annotations
import argparse,json,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
class MetaAdvisorError(ValueError): pass

def _read(path:Path,label:str):
    try: v=json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError,json.JSONDecodeError) as exc: raise MetaAdvisorError(f'Cannot load {label}: {exc}') from exc
    if not isinstance(v,dict): raise MetaAdvisorError(f'{label} root must be object')
    return v

def load_policy(root:Path=ROOT):
    p=_read(root/'config/meta_advisor_policy.json','meta advisor policy')
    required={'schema_version','suggestion','research','presentation','max_list_items','authority','model_confidence_is_authority','automatic_mutation'}
    if set(p)!=required or p.get('schema_version')!='1.0' or p.get('authority')!='ADVISORY_ONLY' or p.get('model_confidence_is_authority') is not False or p.get('automatic_mutation') is not False: raise MetaAdvisorError('meta advisor safety contract invalid')
    if isinstance(p['max_list_items'],bool) or not isinstance(p['max_list_items'],int) or p['max_list_items']<1: raise MetaAdvisorError('max_list_items must be positive integer')
    suggestion_required={'novelty','benefit','frequency','universality','complexity','compatibility','interaction_risk','verification','reversibility','evidence_confidence','high_default_context_tax_tokens','runtime_call_review_threshold'}
    research_required={'impacts','evidence_states','max_internal_attempts_before_review'}
    presentation_required={'default','modes'}
    if not isinstance(p['suggestion'],dict) or set(p['suggestion'])!=suggestion_required: raise MetaAdvisorError('suggestion policy fields must match contract')
    if not isinstance(p['research'],dict) or set(p['research'])!=research_required: raise MetaAdvisorError('research policy fields must match contract')
    if not isinstance(p['presentation'],dict) or set(p['presentation'])!=presentation_required: raise MetaAdvisorError('presentation policy fields must match contract')
    for key in ('high_default_context_tax_tokens','runtime_call_review_threshold'):
        value=p['suggestion'][key]
        if isinstance(value,bool) or not isinstance(value,int) or value<0: raise MetaAdvisorError(f'{key} must be non-negative integer')
    if isinstance(p['research']['max_internal_attempts_before_review'],bool) or not isinstance(p['research']['max_internal_attempts_before_review'],int) or p['research']['max_internal_attempts_before_review']<1: raise MetaAdvisorError('max_internal_attempts_before_review must be positive integer')
    return p

def _enum(v,name,allowed):
    if v not in allowed: raise MetaAdvisorError(f'{name} invalid')
    return v

def _strings(v,name,maxn):
    if not isinstance(v,list) or len(v)>maxn or any(not isinstance(x,str) or not x.strip() for x in v): raise MetaAdvisorError(f'{name} must be bounded list of non-empty strings')
    return [x.strip() for x in v]

def _value_density(c:dict,s:dict)->str:
    if c['benefit']=='LIMITED': return 'LOW'
    high_cost=c['default_context_tokens_added']>s['high_default_context_tax_tokens'] or c['runtime_calls_added']>s['runtime_call_review_threshold'] or c['complexity']=='HIGH'
    if c['benefit']=='SUBSTANTIAL' and c['frequency'] in {'COMMON','OCCASIONAL'} and not high_cost: return 'HIGH'
    return 'MEDIUM'

def _evidence_confidence(c:dict,refs:list[str])->str:
    if refs and c['compatibility']=='VERIFIED' and c['verification'] in {'DETERMINISTIC','EMPIRICAL'} and c['interaction_risk']=='LOW': return 'HIGH'
    if refs and c['compatibility']!='CONFLICT' and c['interaction_risk']!='HIGH': return 'MEDIUM'
    return 'LOW'

def evaluate_suggestion(c:dict,root:Path=ROOT):
    p=load_policy(root); s=p['suggestion']; req={'suggestion_id','title','novelty','benefit','frequency','universality','repository_tokens_added','default_context_tokens_added','routed_context_tokens_added','runtime_calls_added','complexity','compatibility','interaction_risk','verification','reversibility','existing_mechanism','evidence_refs'}
    if not isinstance(c,dict) or set(c)!=req: raise MetaAdvisorError('suggestion fields must match contract')
    for k in ('suggestion_id','title'):
        if not isinstance(c[k],str) or not c[k].strip(): raise MetaAdvisorError(f'{k} invalid')
    for k in ('novelty','benefit','frequency','universality','complexity','compatibility','interaction_risk','verification','reversibility'): _enum(c[k],k,s[k])
    for k in ('repository_tokens_added','default_context_tokens_added','routed_context_tokens_added','runtime_calls_added'):
        if isinstance(c[k],bool) or not isinstance(c[k],int) or c[k]<0: raise MetaAdvisorError(f'{k} must be non-negative integer')
    if c['existing_mechanism'] is not None and (not isinstance(c['existing_mechanism'],str) or not c['existing_mechanism'].strip()): raise MetaAdvisorError('existing_mechanism invalid')
    refs=_strings(c['evidence_refs'],'evidence_refs',p['max_list_items']); reasons=[]
    if c['novelty']=='DUPLICATE': return {'verdict':'REJECT','reasons':['DUPLICATE_CAPABILITY'],'placement':None,'value_density':_value_density(c,s),'evidence_confidence':_evidence_confidence(c,refs),'confidence_basis':'EVIDENCE_CLASSIFICATIONS_NOT_MODEL_CONFIDENCE','authority':'ADVISORY_ONLY'}
    if c['compatibility']=='CONFLICT': return {'verdict':'REJECT','reasons':['KNOWN_COMPATIBILITY_CONFLICT'],'placement':None,'value_density':_value_density(c,s),'evidence_confidence':_evidence_confidence(c,refs),'confidence_basis':'EVIDENCE_CLASSIFICATIONS_NOT_MODEL_CONFIDENCE','authority':'ADVISORY_ONLY'}
    if not refs: reasons.append('INSUFFICIENT_EVIDENCE')
    if c['benefit']=='LIMITED': reasons.append('LIMITED_BENEFIT')
    if c['frequency']=='UNKNOWN': reasons.append('UNKNOWN_FREQUENCY')
    if c['interaction_risk'] in {'HIGH','UNKNOWN'}: reasons.append('INTERACTION_RISK_REVIEW')
    if c['complexity']=='HIGH': reasons.append('HIGH_COMPLEXITY')
    if c['verification'] in {'SEMANTIC_ONLY','NONE'}: reasons.append('WEAK_VERIFICATION')
    if c['default_context_tokens_added']>s['high_default_context_tax_tokens']: reasons.append('HIGH_DEFAULT_CONTEXT_TAX')
    if c['runtime_calls_added']>s['runtime_call_review_threshold']: reasons.append('ADDED_RUNTIME_CALL_TAX')
    if c['reversibility']=='HARD': reasons.append('HARD_TO_REVERSE')
    verdict='HUMAN_REVIEW' if reasons else 'RECOMMEND'
    placement={'CORE':'CORE','SHARED_OPTIONAL':'SHARED_OPTIONAL','CLONE_SPECIFIC':'CLONE'}[c['universality']]
    return {'verdict':verdict,'reasons':reasons,'placement':placement,'existing_mechanism':c['existing_mechanism'],'value_density':_value_density(c,s),'evidence_confidence':_evidence_confidence(c,refs),'confidence_basis':'EVIDENCE_CLASSIFICATIONS_NOT_MODEL_CONFIDENCE','authority':'ADVISORY_ONLY'}

def present_suggestion(candidate:dict,result:dict,mode:str='STANDARD',root:Path=ROOT)->dict:
    pol=presentation_mode(mode,root)
    if mode=='SIMPLE':
        text='\n'.join([f"Suggestion - {candidate['title']}",f"Why it helps: {candidate['benefit'].title()} expected benefit; value density {result['value_density'].lower()}.",f"Cost: +{candidate['default_context_tokens_added']} default-context tokens; +{candidate['runtime_calls_added']} runtime calls.",f"Compatibility: {candidate['compatibility'].title()}; interaction risk {candidate['interaction_risk'].lower()}.",f"Confidence: {result['evidence_confidence']} (evidence-derived).",f"Recommendation: {result['verdict']}."])
    elif mode=='TECHNICAL':
        text=json.dumps({'candidate':candidate,'evaluation':result},indent=2)
    else:
        text='\n'.join([f"Suggestion - {candidate['title']}",f"Verdict: {result['verdict']} | Value density: {result['value_density']} | Evidence confidence: {result['evidence_confidence']}",f"Placement: {result.get('placement')} | Compatibility: {candidate['compatibility']} | Interaction risk: {candidate['interaction_risk']}",f"Reasons: {', '.join(result['reasons']) if result['reasons'] else 'No gate warnings.'}"])
    return {'mode':mode,'text':text,'evaluation_unchanged':True,'presentation_policy':pol,'authority':'PRESENTATION_ONLY'}

def advise_research(d:dict,root:Path=ROOT):
    p=load_policy(root); r=p['research']; req={'decision_id','impact','evidence_state','current_empirical_dependency','current_external_dependency','research_can_resolve','internal_attempts','unresolved_questions'}
    if not isinstance(d,dict) or set(d)!=req: raise MetaAdvisorError('research decision fields must match contract')
    if not isinstance(d['decision_id'],str) or not d['decision_id'].strip(): raise MetaAdvisorError('decision_id invalid')
    _enum(d['impact'],'impact',r['impacts']); _enum(d['evidence_state'],'evidence_state',r['evidence_states'])
    for k in ('current_empirical_dependency','current_external_dependency','research_can_resolve'):
        if not isinstance(d[k],bool): raise MetaAdvisorError(f'{k} must be boolean')
    if isinstance(d['internal_attempts'],bool) or not isinstance(d['internal_attempts'],int) or d['internal_attempts']<0: raise MetaAdvisorError('internal_attempts invalid')
    qs=_strings(d['unresolved_questions'],'unresolved_questions',p['max_list_items']); reasons=[]
    if not d['research_can_resolve']:
        return {'recommend_research':False,'reasons':['RESEARCH_NOT_EXPECTED_TO_RESOLVE'],'assurance_increase':False,'authority':'ADVISORY_ONLY'}
    if d['evidence_state']=='CONFLICTING': reasons.append('CONTRADICTORY_EVIDENCE')
    if d['evidence_state'] in {'WEAK','MISSING'} and d['impact'] in {'HIGH','CRITICAL'}: reasons.append('HIGH_IMPACT_EVIDENCE_DEFICIT')
    if (d['current_empirical_dependency'] or d['current_external_dependency']) and qs: reasons.append('CURRENT_EXTERNAL_EVIDENCE_REQUIRED')
    if d['internal_attempts']>=r['max_internal_attempts_before_review'] and d['evidence_state']!='SUFFICIENT': reasons.append('INTERNAL_REASONING_WITHOUT_RESOLUTION')
    return {'recommend_research':bool(reasons),'reasons':reasons,'assurance_increase':False,'authority':'ADVISORY_ONLY'}

def compile_research_prompt(req:dict,root:Path=ROOT):
    p=load_policy(root); keys={'title','decision','source_refs','established_facts','unresolved_questions','claims_to_verify','out_of_scope','comparison_dimensions','required_output'}
    if not isinstance(req,dict) or set(req)!=keys: raise MetaAdvisorError('research prompt request fields must match contract')
    for k in ('title','decision','required_output'):
        if not isinstance(req[k],str) or not req[k].strip(): raise MetaAdvisorError(f'{k} invalid')
    vals={k:_strings(req[k],k,p['max_list_items']) for k in ('source_refs','established_facts','unresolved_questions','claims_to_verify','out_of_scope','comparison_dimensions')}
    if not vals['unresolved_questions'] and not vals['claims_to_verify']: raise MetaAdvisorError('research prompt requires an unresolved question or claim to verify')
    lines=[req['title'].strip(),'',f'Decision to inform: {req["decision"].strip()}','', 'Source references (inspect only as needed; preserve provenance):']+[f'- {x}' for x in vals['source_refs']] + ['', 'Established facts (treat as constraints; do not rediscover unless verification is explicitly requested):']
    lines += [f'- {x}' for x in vals['established_facts']] or ['- None supplied.']
    for label,key in [('Unresolved questions','unresolved_questions'),('Claims requiring evidence','claims_to_verify'),('Out of scope','out_of_scope'),('Comparison dimensions','comparison_dimensions')]:
        lines += ['',label+':']+[f'- {x}' for x in vals[key]]
    lines += ['', 'Required output:', req['required_output'].strip(),'', 'Separate sourced findings from inference/recommendation. Prefer current primary evidence where the question is time-sensitive. Do not expose private chain-of-thought.']
    text='\n'.join(lines)
    return {'prompt':text,'estimated_tokens':math.ceil(len(text)/4.0),'authority':'NONCANONICAL_RESEARCH_TRANSPORT'}

def presentation_mode(mode:str,root:Path=ROOT):
    p=load_policy(root); modes=p['presentation']['modes']; mode=mode or p['presentation']['default']; _enum(mode,'presentation_mode',modes)
    return {'mode':mode,**modes[mode],'changes_rigor':False,'changes_authority':False,'authority':'PRESENTATION_ONLY'}

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='cmd',required=True)
    s=sub.add_parser('suggest'); s.add_argument('candidate'); ps=sub.add_parser('present-suggestion'); ps.add_argument('candidate'); ps.add_argument('mode',choices=['SIMPLE','STANDARD','TECHNICAL']); r=sub.add_parser('research'); r.add_argument('decision'); c=sub.add_parser('compile-research'); c.add_argument('request'); pr=sub.add_parser('presentation'); pr.add_argument('mode',choices=['SIMPLE','STANDARD','TECHNICAL'])
    a=ap.parse_args()
    try:
        if a.cmd=='suggest': out=evaluate_suggestion(_read(Path(a.candidate),'candidate'))
        elif a.cmd=='present-suggestion':
            candidate=_read(Path(a.candidate),'candidate'); out=present_suggestion(candidate,evaluate_suggestion(candidate),a.mode)
        elif a.cmd=='research': out=advise_research(_read(Path(a.decision),'decision'))
        elif a.cmd=='compile-research': out=compile_research_prompt(_read(Path(a.request),'research request'))
        else: out=presentation_mode(a.mode)
        print(json.dumps({'valid':True,'result':out},indent=2)); return 0
    except MetaAdvisorError as exc:
        print(json.dumps({'valid':False,'error':str(exc)},indent=2)); return 2
if __name__=='__main__': raise SystemExit(main())
