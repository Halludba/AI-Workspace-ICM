#!/usr/bin/env python3
"""Deterministic prompt-plan and host-observed telemetry validation for ICM."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/"tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0,str(TOOLS))
import context_benchmark

SHA256_RE=re.compile(r"^[0-9a-f]{64}$")

class ContextRuntimeError(ValueError):
    pass

def _read(path:Path,label:str)->dict:
    try: value=json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError,json.JSONDecodeError) as exc: raise ContextRuntimeError(f"Cannot load {label}: {exc}") from exc
    if not isinstance(value,dict): raise ContextRuntimeError(f"{label} root must be an object")
    return value

def load_policy(root:Path=ROOT)->dict:
    p=_read(root/"config/context_runtime_policy.json","context runtime policy")
    if set(p)!={"schema_version","metric_schema","prompt","telemetry"} or p.get("schema_version")!="1.0": raise ContextRuntimeError("context runtime policy fields must match contract")
    if p["metric_schema"]!="config/context_benchmark_policy.json": raise ContextRuntimeError("metric_schema must reuse context benchmark policy")
    pr=p["prompt"]; req={"block_order","stable_classes","dynamic_classes","forbid_padding_for_cache","cache_hint_authority"}
    if not isinstance(pr,dict) or set(pr)!=req: raise ContextRuntimeError("prompt policy fields must match contract")
    expected=["STABLE_AUTHORITY","STABLE_ROUTED_CONTEXT","DYNAMIC_TASK","DYNAMIC_STATE"]
    if pr["block_order"]!=expected or pr["stable_classes"]!=expected[:2] or pr["dynamic_classes"]!=expected[2:]: raise ContextRuntimeError("prompt block classes/order must match contract")
    if pr["forbid_padding_for_cache"] is not True or pr["cache_hint_authority"]!="PERFORMANCE_HINT_ONLY": raise ContextRuntimeError("cache hints must remain non-authoritative and padding-free")
    tel=p["telemetry"]
    if not isinstance(tel,dict) or set(tel)!={"availability_states","cache_states","provider_fields_optional"}: raise ContextRuntimeError("telemetry policy fields must match contract")
    if tel["availability_states"]!=["OBSERVED","UNAVAILABLE"] or tel["cache_states"]!=["COLD","WARM","UNKNOWN"] or tel["provider_fields_optional"] is not True: raise ContextRuntimeError("telemetry states must match contract")
    return p

def _metric_schema(root:Path)->tuple[list[str],dict]:
    try: bench=context_benchmark.load_policy(root)
    except Exception as exc: raise ContextRuntimeError(f"cannot load shared benchmark metric schema: {exc}") from exc
    return list(bench["required_metrics"]),dict(bench["metric_groups"])

def _sha(value:object)->str:
    raw=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()

def _block(block:object,allowed:set[str])->dict:
    required={"id","class","source_ref","sha256","estimated_tokens"}
    if not isinstance(block,dict) or set(block)!=required: raise ContextRuntimeError("prompt block fields must match contract")
    if not isinstance(block["id"],str) or not block["id"].strip(): raise ContextRuntimeError("prompt block id must be non-empty")
    if block["class"] not in allowed: raise ContextRuntimeError("unknown prompt block class")
    if not isinstance(block["source_ref"],str) or not block["source_ref"].strip(): raise ContextRuntimeError("source_ref must be non-empty")
    if not isinstance(block["sha256"],str) or not SHA256_RE.fullmatch(block["sha256"]): raise ContextRuntimeError("prompt block sha256 must be lowercase SHA-256")
    if not isinstance(block["estimated_tokens"],int) or isinstance(block["estimated_tokens"],bool) or block["estimated_tokens"]<0: raise ContextRuntimeError("estimated_tokens must be a non-negative integer")
    return dict(block)

def build_prompt_plan(request:dict,root:Path=ROOT)->dict:
    p=load_policy(root); pr=p["prompt"]
    if not isinstance(request,dict) or set(request)!={"schema_version","blocks"} or request.get("schema_version")!="1.0": raise ContextRuntimeError("prompt request fields must match contract")
    if not isinstance(request["blocks"],list) or not request["blocks"]: raise ContextRuntimeError("prompt request requires blocks")
    allowed=set(pr["block_order"]); blocks=[_block(b,allowed) for b in request["blocks"]]
    ids=[b["id"] for b in blocks]
    if len(ids)!=len(set(ids)): raise ContextRuntimeError("prompt block ids must be unique")
    rank={name:i for i,name in enumerate(pr["block_order"])}
    ordered=sorted(enumerate(blocks),key=lambda pair:(rank[pair[1]["class"]],pair[0]))
    blocks=[b for _,b in ordered]
    stable=[b for b in blocks if b["class"] in pr["stable_classes"]]
    dynamic=[b for b in blocks if b["class"] in pr["dynamic_classes"]]
    stable_identity=[{"id":b["id"],"sha256":b["sha256"]} for b in stable]
    all_identity=[{"id":b["id"],"class":b["class"],"sha256":b["sha256"]} for b in blocks]
    stable_fingerprint=_sha(stable_identity) if stable else None
    return {
      "schema_version":"1.0","blocks":blocks,
      "stable_prefix":{"block_ids":[b["id"] for b in stable],"estimated_tokens":sum(b["estimated_tokens"] for b in stable),"fingerprint":stable_fingerprint,"boundary_after":stable[-1]["id"] if stable else None},
      "dynamic_suffix":{"block_ids":[b["id"] for b in dynamic],"estimated_tokens":sum(b["estimated_tokens"] for b in dynamic)},
      "total_estimated_tokens":sum(b["estimated_tokens"] for b in blocks),
      "plan_fingerprint":_sha(all_identity),
      "cache_hint":{"stable_prefix_fingerprint":stable_fingerprint,"stable_prefix_boundary_after":stable[-1]["id"] if stable else None,"authority":"PERFORMANCE_HINT_ONLY"},
      "padding_applied":False,"provider_specific_controls":None,"authority":"NONCANONICAL_ASSEMBLY_PLAN"
    }

def telemetry_template(subject_id:str,context_sources:list[dict]|None=None,root:Path=ROOT)->dict:
    if not isinstance(subject_id,str) or not subject_id.strip(): raise ContextRuntimeError("subject_id must be non-empty")
    metrics,_groups=_metric_schema(root)
    return {"schema_version":"1.0","subject_id":subject_id,"provider":None,"model":None,"cache_state":"UNKNOWN","observed_metrics":{m:None for m in metrics},"metric_availability":{m:"UNAVAILABLE" for m in metrics},"context_sources":context_sources or [],"prompt_plan_fingerprint":None}

def _source(item:object,classes:set[str])->dict:
    required={"source_ref","sha256","estimated_tokens","block_class"}
    if not isinstance(item,dict) or set(item)!=required: raise ContextRuntimeError("context source fields must match contract")
    if not isinstance(item["source_ref"],str) or not item["source_ref"].strip(): raise ContextRuntimeError("context source_ref must be non-empty")
    if not isinstance(item["sha256"],str) or not SHA256_RE.fullmatch(item["sha256"]): raise ContextRuntimeError("context source sha256 must be lowercase SHA-256")
    if not isinstance(item["estimated_tokens"],int) or isinstance(item["estimated_tokens"],bool) or item["estimated_tokens"]<0: raise ContextRuntimeError("context source estimated_tokens must be non-negative integer")
    if item["block_class"] not in classes: raise ContextRuntimeError("context source block_class is invalid")
    return dict(item)

def validate_telemetry(record:dict,root:Path=ROOT)->dict:
    p=load_policy(root); metrics,groups=_metric_schema(root)
    required={"schema_version","subject_id","provider","model","cache_state","observed_metrics","metric_availability","context_sources","prompt_plan_fingerprint"}
    if not isinstance(record,dict) or set(record)!=required or record.get("schema_version")!="1.0": raise ContextRuntimeError("telemetry fields must match contract")
    if not isinstance(record["subject_id"],str) or not record["subject_id"].strip(): raise ContextRuntimeError("subject_id must be non-empty")
    for name in ("provider","model"):
        if record[name] is not None and (not isinstance(record[name],str) or not record[name].strip()): raise ContextRuntimeError(f"{name} must be non-empty string or null")
    if record["cache_state"] not in p["telemetry"]["cache_states"]: raise ContextRuntimeError("invalid cache_state")
    obs=record["observed_metrics"]; avail=record["metric_availability"]
    if not isinstance(obs,dict) or set(obs)!=set(metrics) or not isinstance(avail,dict) or set(avail)!=set(metrics): raise ContextRuntimeError("telemetry metric keys must match shared benchmark schema")
    calls=set(groups["calls"]); token_metrics=set(groups["tokens"]); correctness=set(groups["correctness"])
    for name in metrics:
        value=obs[name]; state=avail[name]
        if state not in p["telemetry"]["availability_states"]: raise ContextRuntimeError(f"{name} availability is invalid")
        if state=="UNAVAILABLE":
            if value is not None: raise ContextRuntimeError(f"{name} must be null when unavailable")
            continue
        if value is None or isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0: raise ContextRuntimeError(f"{name} observed value must be finite non-negative numeric")
        if name in calls|token_metrics and (not isinstance(value,int) or isinstance(value,bool)): raise ContextRuntimeError(f"{name} must be an integer when observed")
        if name in correctness and not 0<=value<=1: raise ContextRuntimeError(f"{name} must be between 0 and 1")
    trio=[obs["input_tokens_total"],obs["input_tokens_cached"],obs["input_tokens_uncached"]]
    trio_states=[avail["input_tokens_total"],avail["input_tokens_cached"],avail["input_tokens_uncached"]]
    if trio_states==["OBSERVED"]*3 and trio[0] != trio[1]+trio[2]: raise ContextRuntimeError("observed input token totals must reconcile cached + uncached")
    classes=set(p["prompt"]["block_order"])
    if not isinstance(record["context_sources"],list): raise ContextRuntimeError("context_sources must be a list")
    sources=[_source(v,classes) for v in record["context_sources"]]
    fp=record["prompt_plan_fingerprint"]
    if fp is not None and (not isinstance(fp,str) or not SHA256_RE.fullmatch(fp)): raise ContextRuntimeError("prompt_plan_fingerprint must be SHA-256 or null")
    return {"valid":True,**record,"context_sources":sources,"authority":"NONCANONICAL_RUNTIME_EVIDENCE"}

def compare_cache_records(records:list[dict],root:Path=ROOT)->dict:
    if not isinstance(records,list) or not records: raise ContextRuntimeError("cache comparison requires a non-empty record list")
    valid=[validate_telemetry(r,root) for r in records]
    grouped={state:[] for state in ("COLD","WARM")}
    for rec in valid:
        if rec["cache_state"] in grouped: grouped[rec["cache_state"]].append({"observed_metrics":rec["observed_metrics"]})
    summaries={}
    for state,items in grouped.items(): summaries[state]=context_benchmark.summarize_samples(items,root) if items else {"schema_version":"1.0","sample_count":0,"metrics":{m:{"status":"UNAVAILABLE","samples":0,"p50":None,"p95":None} for m in _metric_schema(root)[0]}}
    deltas={}
    for name in _metric_schema(root)[0]:
        c=summaries["COLD"]["metrics"][name]["p50"]; w=summaries["WARM"]["metrics"][name]["p50"]
        deltas[name]=None if c is None or w is None else w-c
    return {"schema_version":"1.0","groups":summaries,"warm_minus_cold_p50":deltas,"padding_used":False,"authority":"DIAGNOSTIC_ONLY"}

def main()->int:
    parser=argparse.ArgumentParser(description="Plan stable/dynamic prompt blocks and validate runtime telemetry.")
    sub=parser.add_subparsers(dest="command",required=True)
    plan=sub.add_parser("plan"); plan.add_argument("request")
    template=sub.add_parser("template"); template.add_argument("subject_id")
    validate=sub.add_parser("validate"); validate.add_argument("record")
    compare=sub.add_parser("compare-cache"); compare.add_argument("records")
    args=parser.parse_args()
    try:
        if args.command=="plan": result=build_prompt_plan(_read(Path(args.request),"prompt request"))
        elif args.command=="template": result={"valid":True,"telemetry":telemetry_template(args.subject_id)}
        elif args.command=="validate": result=validate_telemetry(_read(Path(args.record),"telemetry record"))
        else:
            raw=json.loads(Path(args.records).read_text(encoding="utf-8-sig")); result={"valid":True,"comparison":compare_cache_records(raw)}
        print(json.dumps(result,indent=2,ensure_ascii=False)); return 0
    except (ContextRuntimeError,OSError,json.JSONDecodeError,context_benchmark.BenchmarkError,context_benchmark.PolicyError) as exc:
        print(json.dumps({"valid":False,"error":str(exc)},indent=2),file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
