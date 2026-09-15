#!/usr/bin/env python3
"""Bounded local worker packet construction, Ollama execution, and result validation."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path, PurePosixPath

ROOT=Path(__file__).resolve().parents[1]
TOOLS=ROOT/"tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0,str(TOOLS))
import context_runtime
import local_compute
import source_navigator

SHA256_RE=re.compile(r"^[0-9a-f]{64}$")
REV_RE=re.compile(r"^[0-9a-f]{40}$")
JOB_RE=re.compile(r"^[A-Za-z0-9._:-]{1,80}$")
SYSTEM_CONTRACT=(
    "You are a bounded local implementation worker. Use only the supplied job packet. "
    "Return only the required structured JSON result. Do not reveal or include private reasoning, "
    "scratchpad, chain-of-thought, or hidden deliberation. Do not claim tests ran: no tools are supplied. "
    "Do not mutate files. Return a unified diff candidate only within the declared mutation scope."
)

class LocalWorkerError(ValueError): pass


def _read(path:Path,label:str)->dict:
    try: value=json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError,json.JSONDecodeError) as exc: raise LocalWorkerError(f"Cannot load {label}: {exc}") from exc
    if not isinstance(value,dict): raise LocalWorkerError(f"{label} root must be an object")
    return value


def load_policy(root:Path=ROOT)->dict:
    p=_read(root/"config/local_worker_policy.json","local worker policy")
    required={"schema_version","provider","endpoint","model","timeout_seconds","max_packet_estimated_tokens","max_context_items","max_changed_files","max_repair_cycles","max_response_bytes","max_patch_bytes","session_state_root","require_current_base_revision","structured_output_required","capture_private_reasoning","canonical_mutation","result_statuses","test_statuses"}
    if set(p)!=required or p.get("schema_version")!="1.0": raise LocalWorkerError("local worker policy fields must match contract")
    if p["provider"]!="ollama" or not isinstance(p["model"],str) or not p["model"]: raise LocalWorkerError("local worker provider/model contract invalid")
    parsed=urllib.parse.urlparse(p["endpoint"])
    if parsed.scheme!="http" or parsed.hostname not in {"127.0.0.1","::1"} or parsed.path!="/api/chat": raise LocalWorkerError("local worker endpoint must be loopback Ollama /api/chat")
    for key in ("timeout_seconds","max_packet_estimated_tokens","max_context_items","max_changed_files","max_response_bytes","max_patch_bytes"):
        if not isinstance(p[key],int) or isinstance(p[key],bool) or p[key]<1: raise LocalWorkerError(f"{key} must be a positive integer")
    if not isinstance(p["max_repair_cycles"],int) or isinstance(p["max_repair_cycles"],bool) or p["max_repair_cycles"]<0: raise LocalWorkerError("max_repair_cycles must be non-negative integer")
    state=PurePosixPath(str(p["session_state_root"]).replace("\\","/"))
    if state.is_absolute() or ".." in state.parts or not state.parts or state.parts[0]!=".session": raise LocalWorkerError("session_state_root must be confined under .session/")
    if p["require_current_base_revision"] is not True or p["structured_output_required"] is not True or p["capture_private_reasoning"] is not False or p["canonical_mutation"] is not False: raise LocalWorkerError("local worker safety flags must match contract")
    if p["result_statuses"]!=["SUCCESS","NEEDS_REPAIR","BLOCKED"] or p["test_statuses"]!=["PROPOSED","NOT_RUN"]: raise LocalWorkerError("local worker result status vocabulary must match contract")
    return p


def _head(root:Path)->str:
    proc=subprocess.run(["git","rev-parse","HEAD"],cwd=root,text=True,capture_output=True,check=False)
    if proc.returncode!=0 or not REV_RE.fullmatch(proc.stdout.strip()): raise LocalWorkerError("cannot resolve current Git HEAD")
    return proc.stdout.strip()


def _rel(value:str,label:str)->str:
    if not isinstance(value,str) or not value.strip(): raise LocalWorkerError(f"{label} must be non-empty")
    rel=PurePosixPath(value.strip().replace("\\","/"))
    if rel.is_absolute() or ".." in rel.parts or rel.as_posix() in {"",".","*","**"}: raise LocalWorkerError(f"{label} must be confined workspace-relative path")
    if any("*" in part for part in rel.parts): raise LocalWorkerError(f"{label} wildcard is only allowed as trailing /** scope")
    return rel.as_posix()


def _scope(value:str,label:str)->str:
    if not isinstance(value,str) or not value.strip(): raise LocalWorkerError(f"{label} must be non-empty")
    normalized=value.strip().replace("\\","/")
    if normalized.endswith("/**"):
        return _rel(normalized[:-3],label)+"/**"
    return _rel(normalized,label)


def _matches_scope(path:str,pattern:str)->bool:
    if pattern.endswith("/**"):
        prefix=pattern[:-3]
        return path==prefix or path.startswith(prefix+"/")
    return path==pattern


def context_item_from_retrieval(retrieval:dict)->dict:
    if not isinstance(retrieval,dict) or retrieval.get("retrieval_kind") not in {"EXACT_SYMBOL","EXACT_REGION","EXACT_FILE"}: raise LocalWorkerError("worker context requires exact symbol/region/file retrieval")
    source=retrieval.get("source")
    if not isinstance(source,dict) or not isinstance(retrieval.get("text"),str): raise LocalWorkerError("retrieval lacks exact text/source provenance")
    if retrieval.get("exact_source_recoverable") is not True: raise LocalWorkerError("retrieval must preserve exact-source recoverability")
    path=_rel(source.get("path"),"source path")
    sha=source.get("sha256")
    if not isinstance(sha,str) or not SHA256_RE.fullmatch(sha): raise LocalWorkerError("retrieval source SHA-256 invalid")
    suffix=""
    if retrieval["retrieval_kind"]=="EXACT_SYMBOL": suffix=f'#symbol={retrieval.get("symbol",{}).get("qualified_name",retrieval.get("symbol",{}).get("name",""))}'
    elif retrieval["retrieval_kind"]=="EXACT_REGION": suffix=f'#L{retrieval.get("selection",{}).get("line_start")}-L{retrieval.get("selection",{}).get("line_end")}'
    return {"source_ref":path+suffix,"retrieval_kind":retrieval["retrieval_kind"],"source_sha256":sha,"content":retrieval["text"],"exact_source_recoverable":True}


def _verified_retrieval(item:dict,base_revision:str,root:Path)->dict:
    source_ref=item["source_ref"]
    path,sep,fragment=source_ref.partition("#")
    path=_rel(path,"context source path")
    kind=item["retrieval_kind"]
    if kind=="EXACT_FILE":
        if sep: raise LocalWorkerError("EXACT_FILE source_ref cannot contain a fragment")
        retrieval=source_navigator.retrieve_file(path,base_revision,root=root)
    elif kind=="EXACT_REGION":
        match=re.fullmatch(r"L([1-9][0-9]*)-L([1-9][0-9]*)",fragment) if sep else None
        if match is None: raise LocalWorkerError("EXACT_REGION source_ref must end with #L<start>-L<end>")
        retrieval=source_navigator.retrieve_region(path,int(match.group(1)),int(match.group(2)),base_revision,root=root)
    elif kind=="EXACT_SYMBOL":
        if not sep or not fragment.startswith("symbol=") or not fragment[7:]: raise LocalWorkerError("EXACT_SYMBOL source_ref must end with #symbol=<qualified-name>")
        retrieval=source_navigator.retrieve_symbol(path,fragment[7:],base_revision,root=root,use_cache=False)
    else:
        raise LocalWorkerError("worker context must be exact symbol, region, or file source")
    return retrieval


def _process_context_item(item:object,base_revision:str,root:Path)->dict:
    required={"source_ref","retrieval_kind","source_sha256","content","exact_source_recoverable"}
    if not isinstance(item,dict) or set(item)!=required: raise LocalWorkerError("context item fields must match contract")
    if not isinstance(item["source_ref"],str) or not item["source_ref"].strip(): raise LocalWorkerError("context source_ref must be non-empty")
    if item["retrieval_kind"] not in {"EXACT_SYMBOL","EXACT_REGION","EXACT_FILE"}: raise LocalWorkerError("worker context kind must be bounded exact source")
    if not isinstance(item["source_sha256"],str) or not SHA256_RE.fullmatch(item["source_sha256"]): raise LocalWorkerError("context source_sha256 invalid")
    if not isinstance(item["content"],str): raise LocalWorkerError("context content must be text")
    if item["exact_source_recoverable"] is not True: raise LocalWorkerError("worker context must preserve exact-source recoverability")
    try:
        exact=_verified_retrieval(item,base_revision,root)
    except (source_navigator.SourceNavigatorError,source_navigator.PolicyError) as exc:
        raise LocalWorkerError(f"worker context cannot be recovered from base revision: {exc}") from exc
    if exact["source"]["sha256"]!=item["source_sha256"] or exact["text"]!=item["content"]:
        raise LocalWorkerError("worker context does not match exact source at base_revision")
    data=item["content"].encode("utf-8")
    return {**item,"content_sha256":hashlib.sha256(data).hexdigest(),"estimated_tokens":math.ceil(len(item["content"])/4.0)}


def _task_text(core:dict)->str:
    return json.dumps({"objective":core["objective"],"acceptance_criteria":core["acceptance_criteria"],"mutation_scope":core["mutation_scope"],"forbidden_scope":core["forbidden_scope"]},sort_keys=True,ensure_ascii=False)


def _finalize_packet(core:dict,policy:dict,root:Path)->dict:
    blocks=[{"id":"worker-system-contract","class":"STABLE_AUTHORITY","source_ref":"_core/LOCAL_WORKER_PROTOCOL.md#worker-contract","sha256":hashlib.sha256(SYSTEM_CONTRACT.encode()).hexdigest(),"estimated_tokens":math.ceil(len(SYSTEM_CONTRACT)/4.0)}]
    for i,item in enumerate(core["context_items"]):
        blocks.append({"id":f"context-{i:03d}","class":"STABLE_ROUTED_CONTEXT","source_ref":item["source_ref"],"sha256":item["content_sha256"],"estimated_tokens":item["estimated_tokens"]})
    task=_task_text(core)
    blocks.append({"id":"job-task","class":"DYNAMIC_TASK","source_ref":f'job:{core["job_id"]}',"sha256":hashlib.sha256(task.encode()).hexdigest(),"estimated_tokens":math.ceil(len(task)/4.0)})
    plan=context_runtime.build_prompt_plan({"schema_version":"1.0","blocks":blocks},root)
    packet={"schema_version":"1.0",**core,"prompt_plan":plan,"authority":"NONCANONICAL_WORKER_PACKET","execution_authority":"NONE","canonical_mutation":False}
    encoded=json.dumps(packet,sort_keys=True,separators=(",",":"),ensure_ascii=False)
    packet["estimated_tokens"]=math.ceil(len(encoded)/4.0)
    if packet["estimated_tokens"]>policy["max_packet_estimated_tokens"]: raise LocalWorkerError("worker packet exceeds max_packet_estimated_tokens; reduce context or escalate architecturally")
    packet["packet_fingerprint"]=hashlib.sha256(json.dumps(packet,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest()
    return packet


def build_packet(job:dict,root:Path=ROOT)->dict:
    p=load_policy(root)
    required={"schema_version","job_id","architect_role","objective","base_revision","context_level","context_items","mutation_scope","forbidden_scope","acceptance_criteria"}
    if not isinstance(job,dict) or set(job)!=required or job.get("schema_version")!="1.0": raise LocalWorkerError("job fields must match contract")
    if not isinstance(job["job_id"],str) or not JOB_RE.fullmatch(job["job_id"]): raise LocalWorkerError("job_id format invalid")
    if job["architect_role"]!="icm-runtime-architect": raise LocalWorkerError("local worker must be delegated by ICM Runtime Architect")
    if not isinstance(job["objective"],str) or not job["objective"].strip(): raise LocalWorkerError("objective must be non-empty")
    if not isinstance(job["base_revision"],str) or not REV_RE.fullmatch(job["base_revision"]): raise LocalWorkerError("base_revision must be full Git commit SHA")
    if p["require_current_base_revision"] and job["base_revision"]!=_head(root): raise LocalWorkerError("worker base_revision is stale relative to current HEAD")
    if job["context_level"] not in {"C1_EXACT_SYMBOL","C2_LOCAL_DEPENDENCIES","C3_CROSS_FILE_SLICE","C4_WHOLE_SOURCE","C5_SUBSYSTEM_GLOBAL"}: raise LocalWorkerError("worker requires bounded C1-C5 context")
    items=job["context_items"]
    if not isinstance(items,list) or not items or len(items)>p["max_context_items"]: raise LocalWorkerError("context_items must be non-empty and within configured bound")
    processed=[_process_context_item(v,job["base_revision"],root) for v in items]
    scopes=job["mutation_scope"]; forbidden=job["forbidden_scope"]
    if not isinstance(scopes,list) or not scopes: raise LocalWorkerError("mutation_scope must be non-empty")
    if not isinstance(forbidden,list): raise LocalWorkerError("forbidden_scope must be a list")
    scopes=[_scope(v,"mutation scope") for v in scopes]; forbidden=[_scope(v,"forbidden scope") for v in forbidden]
    if len(scopes)!=len(set(scopes)) or len(forbidden)!=len(set(forbidden)): raise LocalWorkerError("scope entries must be unique")
    criteria=job["acceptance_criteria"]
    if not isinstance(criteria,list) or not criteria or any(not isinstance(v,str) or not v.strip() for v in criteria): raise LocalWorkerError("acceptance_criteria must be non-empty strings")
    core={"job_id":job["job_id"],"architect_role":job["architect_role"],"objective":job["objective"].strip(),"base_revision":job["base_revision"],"context_level":job["context_level"],"context_items":processed,"mutation_scope":scopes,"forbidden_scope":forbidden,"acceptance_criteria":[v.strip() for v in criteria]}
    return _finalize_packet(core,p,root)


def validate_packet(packet:dict,root:Path=ROOT)->dict:
    p=load_policy(root)
    required={"schema_version","job_id","architect_role","objective","base_revision","context_level","context_items","mutation_scope","forbidden_scope","acceptance_criteria","prompt_plan","authority","execution_authority","canonical_mutation","estimated_tokens","packet_fingerprint"}
    if not isinstance(packet,dict) or set(packet)!=required or packet.get("schema_version")!="1.0": raise LocalWorkerError("worker packet fields must match contract")
    core={k:packet[k] for k in ("job_id","architect_role","objective","base_revision","context_level","context_items","mutation_scope","forbidden_scope","acceptance_criteria")}
    # Reconstruct a raw job by removing derived context fields.
    raw_items=[]
    for item in core["context_items"]:
        if not isinstance(item,dict) or not {"content_sha256","estimated_tokens"}.issubset(item): raise LocalWorkerError("worker packet context item missing derived integrity fields")
        raw={k:item[k] for k in ("source_ref","retrieval_kind","source_sha256","content","exact_source_recoverable")}
        raw_items.append(raw)
    raw_job={"schema_version":"1.0",**{k:core[k] for k in ("job_id","architect_role","objective","base_revision","context_level","mutation_scope","forbidden_scope","acceptance_criteria")},"context_items":raw_items}
    expected=build_packet(raw_job,root)
    if packet!=expected: raise LocalWorkerError("worker packet derived fields/fingerprint do not match canonical construction")
    return packet


def _result_schema(policy:dict)->dict:
    return {"type":"object","additionalProperties":False,"properties":{"status":{"type":"string","enum":policy["result_statuses"]},"changed_files":{"type":"array","items":{"type":"string"},"maxItems":policy["max_changed_files"]},"patch":{"type":"string"},"tests":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"command":{"type":"string"},"status":{"type":"string","enum":policy["test_statuses"]}},"required":["command","status"]}},"evidence":{"type":"array","items":{"type":"object","additionalProperties":False,"properties":{"source_ref":{"type":"string"},"claim":{"type":"string"}},"required":["source_ref","claim"]}},"assumptions":{"type":"array","items":{"type":"string"}},"unresolved":{"type":"array","items":{"type":"string"}}},"required":["status","changed_files","patch","tests","evidence","assumptions","unresolved"]}


def _patch_paths(patch:str,root:Path)->set[str]:
    if not patch.strip(): return set()
    if "GIT binary patch" in patch or "Binary files " in patch: raise LocalWorkerError("binary worker patches are not supported")
    data=patch.encode("utf-8")
    parsed=subprocess.run(["git","apply","--numstat","-z","--recount","-"],cwd=root,input=data,capture_output=True,check=False)
    if parsed.returncode!=0:
        raise LocalWorkerError("worker patch is not a valid Git patch: "+parsed.stderr.decode(errors="replace").strip())
    paths=set()
    for record in parsed.stdout.split(b"\0"):
        if not record: continue
        parts=record.split(b"\t",2)
        if len(parts)!=3: raise LocalWorkerError("worker patch numstat framing invalid")
        try: path=parts[2].decode("utf-8")
        except UnicodeDecodeError as exc: raise LocalWorkerError("worker patch paths must be UTF-8") from exc
        paths.add(_rel(path,"patch path"))
    if not paths: raise LocalWorkerError("non-empty worker patch must modify at least one path")
    checked=subprocess.run(["git","apply","--check","--recount","-"],cwd=root,input=data,capture_output=True,check=False)
    if checked.returncode!=0:
        raise LocalWorkerError("worker patch does not apply cleanly to current checkout: "+checked.stderr.decode(errors="replace").strip())
    return paths


def validate_result(packet:dict,result:dict,root:Path=ROOT)->dict:
    packet=validate_packet(packet,root); p=load_policy(root)
    required={"status","changed_files","patch","tests","evidence","assumptions","unresolved"}
    if not isinstance(result,dict) or set(result)!=required: raise LocalWorkerError("worker result fields must match contract; private reasoning fields are forbidden")
    if result["status"] not in p["result_statuses"]: raise LocalWorkerError("worker result status invalid")
    files=result["changed_files"]
    if not isinstance(files,list) or len(files)>p["max_changed_files"]: raise LocalWorkerError("changed_files invalid or exceeds configured bound")
    files=[_rel(v,"changed file") for v in files]
    if len(files)!=len(set(files)): raise LocalWorkerError("changed_files must be unique")
    for path in files:
        if not any(_matches_scope(path,scope) for scope in packet["mutation_scope"]): raise LocalWorkerError(f"worker changed path outside mutation scope: {path}")
        if any(_matches_scope(path,scope) for scope in packet["forbidden_scope"]): raise LocalWorkerError(f"worker changed path is forbidden: {path}")
    if not isinstance(result["patch"],str): raise LocalWorkerError("patch must be string")
    if len(result["patch"].encode("utf-8"))>p["max_patch_bytes"]: raise LocalWorkerError("worker patch exceeds max_patch_bytes")
    patch_paths=_patch_paths(result["patch"],root)
    if patch_paths!=set(files): raise LocalWorkerError("patch paths must exactly match changed_files")
    if result["status"]=="SUCCESS" and not patch_paths: raise LocalWorkerError("SUCCESS requires a non-empty candidate patch")
    if result["status"]=="BLOCKED" and (patch_paths or files): raise LocalWorkerError("BLOCKED result cannot carry candidate mutations")
    if not isinstance(result["tests"],list): raise LocalWorkerError("tests must be a list")
    for t in result["tests"]:
        if not isinstance(t,dict) or set(t)!={"command","status"} or not isinstance(t["command"],str) or not t["command"].strip() or t["status"] not in p["test_statuses"]: raise LocalWorkerError("worker tests must be PROPOSED/NOT_RUN structured entries")
    refs={i["source_ref"] for i in packet["context_items"]}
    if not isinstance(result["evidence"],list): raise LocalWorkerError("evidence must be a list")
    for e in result["evidence"]:
        if not isinstance(e,dict) or set(e)!={"source_ref","claim"} or e["source_ref"] not in refs or not isinstance(e["claim"],str) or not e["claim"].strip(): raise LocalWorkerError("worker evidence must reference supplied packet context")
    for name in ("assumptions","unresolved"):
        if not isinstance(result[name],list) or any(not isinstance(v,str) or not v.strip() for v in result[name]): raise LocalWorkerError(f"{name} must be a list of non-empty strings")
    return {**result,"changed_files":files,"authority":"CANDIDATE_ONLY","canonical_mutation":False}


def preflight(observation:dict|None=None,root:Path=ROOT)->dict:
    obs=observation or local_compute.discover(root)
    readiness=local_compute.resolve_workload("LOCAL_OLLAMA_WORKER",obs,root)
    return {"schema_version":"1.0","status":readiness["status"],"readiness":readiness,"authority":"OBSERVATIONAL_NONCANONICAL","execution_authority":"NONE"}


def _state_path(packet:dict,root:Path,policy:dict,state_root:Path|None)->Path:
    if state_root is not None: base=state_root
    else: base=root/Path(*PurePosixPath(policy["session_state_root"]).parts)
    return base/(hashlib.sha256(packet["job_id"].encode()).hexdigest()+".json")


def _write_state(path:Path,value:dict)->None:
    path.parent.mkdir(parents=True,exist_ok=True); fd,name=tempfile.mkstemp(prefix=f".{path.name}.",suffix=".tmp",dir=path.parent); tmp=Path(name)
    try:
        with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as h: json.dump(value,h,indent=2); h.write("\n")
        os.replace(tmp,path)
    except Exception: tmp.unlink(missing_ok=True); raise


def _job_lock_path(packet:dict,root:Path,policy:dict,state_root:Path|None)->Path:
    return _state_path(packet,root,policy,state_root).with_suffix(".lock")


def _acquire_job_lock(packet:dict,root:Path,policy:dict,state_root:Path|None)->Path:
    lock=_job_lock_path(packet,root,policy,state_root)
    lock.parent.mkdir(parents=True,exist_ok=True)
    try: lock.mkdir()
    except FileExistsError as exc: raise LocalWorkerError("worker job already has an in-flight attempt; fail closed") from exc
    return lock


def _release_job_lock(lock:Path)->None:
    try: lock.rmdir()
    except FileNotFoundError: pass


def _reserve_attempt(packet:dict,root:Path,policy:dict,state_root:Path|None,repair_feedback:str|None)->tuple[Path,dict,int]:
    path=_state_path(packet,root,policy,state_root); state={"schema_version":"1.0","job_id":packet["job_id"],"packet_fingerprint":packet["packet_fingerprint"],"attempts":0,"last_outcome":None,"authority":"NONCANONICAL_ATTEMPT_GUARD"}
    if path.exists():
        try: state=json.loads(path.read_text(encoding="utf-8"))
        except (OSError,json.JSONDecodeError) as exc: raise LocalWorkerError(f"invalid worker attempt state: {exc}") from exc
    if state.get("packet_fingerprint")!=packet["packet_fingerprint"]: raise LocalWorkerError("job_id already exists for a different worker packet")
    if state.get("last_outcome") in {"SUCCESS","BLOCKED"}: raise LocalWorkerError("worker job is terminal; no further model call permitted")
    max_attempts=1+policy["max_repair_cycles"]
    attempts=state.get("attempts")
    if not isinstance(attempts,int) or attempts<0: raise LocalWorkerError("worker attempt state is invalid")
    if attempts>=max_attempts: raise LocalWorkerError("worker repair budget exhausted")
    feedback=repair_feedback.strip() if isinstance(repair_feedback,str) else ""
    if state.get("last_outcome")=="NEEDS_REPAIR" and not feedback:
        raise LocalWorkerError("repair attempt requires explicit architect repair feedback")
    if feedback and state.get("last_outcome")!="NEEDS_REPAIR":
        raise LocalWorkerError("repair feedback is only valid after NEEDS_REPAIR")
    state["attempts"]=attempts+1; state["last_outcome"]="IN_PROGRESS"; _write_state(path,state)
    return path,state,attempts+1


def _finish_attempt(path:Path,state:dict,outcome:str)->None:
    state=dict(state); state["last_outcome"]=outcome; _write_state(path,state)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        return None


def _http_transport(endpoint:str,payload:dict,timeout:float,max_response_bytes:int)->dict:
    req=urllib.request.Request(endpoint,data=json.dumps(payload).encode("utf-8"),headers={"Content-Type":"application/json"},method="POST")
    opener=urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req,timeout=timeout) as resp: data=resp.read(max_response_bytes+1)
    except (urllib.error.URLError,TimeoutError,OSError) as exc: raise LocalWorkerError(f"local worker transport failed: {exc}") from exc
    if len(data)>max_response_bytes: raise LocalWorkerError("local worker provider response exceeds max_response_bytes")
    try: value=json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as exc: raise LocalWorkerError("local worker returned malformed provider JSON") from exc
    if not isinstance(value,dict): raise LocalWorkerError("local worker provider response must be object")
    return value


def _attempt_prompt_plan(packet:dict,repair_feedback:str|None,root:Path)->dict:
    blocks=[dict(item) for item in packet["prompt_plan"]["blocks"]]
    if repair_feedback:
        feedback=repair_feedback.strip()
        blocks.append({"id":"architect-repair-feedback","class":"DYNAMIC_TASK","source_ref":f'job:{packet["job_id"]}:repair',"sha256":hashlib.sha256(feedback.encode()).hexdigest(),"estimated_tokens":math.ceil(len(feedback)/4.0)})
    return context_runtime.build_prompt_plan({"schema_version":"1.0","blocks":blocks},root)


def _payload(packet:dict,policy:dict,repair_feedback:str|None)->dict:
    user_content={"packet":packet}
    if repair_feedback: user_content["architect_repair_feedback"]=repair_feedback.strip()
    return {"model":policy["model"],"messages":[{"role":"system","content":SYSTEM_CONTRACT},{"role":"user","content":json.dumps(user_content,ensure_ascii=False)}],"stream":False,"think":False,"format":_result_schema(policy),"options":{"temperature":0}}


def _telemetry(packet:dict,response:dict,wall_ms:float,root:Path,prompt_plan:dict)->dict:
    sources=[{"source_ref":i["source_ref"],"sha256":i["content_sha256"],"estimated_tokens":i["estimated_tokens"],"block_class":"STABLE_ROUTED_CONTEXT"} for i in packet["context_items"]]
    rec=context_runtime.telemetry_template(packet["job_id"],sources,root); rec["provider"]="ollama"; rec["model"]=load_policy(root)["model"]; rec["prompt_plan_fingerprint"]=prompt_plan["plan_fingerprint"]
    def observed(name,value):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or value<0: return
        if name in {"input_tokens_total","output_tokens","model_calls","tool_calls"}: value=int(value)
        rec["observed_metrics"][name]=value; rec["metric_availability"][name]="OBSERVED"
    observed("input_tokens_total",response.get("prompt_eval_count")); observed("output_tokens",response.get("eval_count")); observed("model_calls",1); observed("tool_calls",0); observed("wall_time_ms",wall_ms)
    total=response.get("total_duration")
    if isinstance(total,(int,float)) and not isinstance(total,bool): observed("model_time_ms",total/1_000_000.0)
    return context_runtime.validate_telemetry(rec,root)


def execute_packet(packet:dict,*,user_authorized:bool,root:Path=ROOT,transport=None,observation:dict|None=None,state_root:Path|None=None,repair_feedback:str|None=None)->dict:
    if user_authorized is not True: raise LocalWorkerError("worker execution requires explicit current user authorization assertion")
    packet=validate_packet(packet,root); policy=load_policy(root)
    if policy["require_current_base_revision"] and packet["base_revision"]!=_head(root): raise LocalWorkerError("worker packet became stale before execution")
    readiness=preflight(observation,root)
    if readiness["status"]!="READY": raise LocalWorkerError("LOCAL_OLLAMA_WORKER is unavailable: "+json.dumps(readiness["readiness"]["missing"],separators=(",",":")))
    lock=_acquire_job_lock(packet,root,policy,state_root)
    try:
        path,state,attempt=_reserve_attempt(packet,root,policy,state_root,repair_feedback)
        attempt_plan=_attempt_prompt_plan(packet,repair_feedback,root)
        start=time.perf_counter()
        try:
            payload=_payload(packet,policy,repair_feedback)
            response=transport(policy["endpoint"],payload,policy["timeout_seconds"]) if transport is not None else _http_transport(policy["endpoint"],payload,policy["timeout_seconds"],policy["max_response_bytes"])
            wall=(time.perf_counter()-start)*1000.0
            if not isinstance(response,dict) or not isinstance(response.get("message"),dict) or not isinstance(response["message"].get("content"),str): raise LocalWorkerError("local worker response missing structured message content")
            if response.get("model") not in {None,policy["model"]}: raise LocalWorkerError("local worker response model does not match configured worker")
            try: result=json.loads(response["message"]["content"])
            except json.JSONDecodeError as exc: raise LocalWorkerError("local worker message content is not valid JSON") from exc
            validated=validate_result(packet,result,root)
            telemetry=_telemetry(packet,response,wall,root,attempt_plan)
            _finish_attempt(path,state,validated["status"])
            return {"schema_version":"1.0","attempt":attempt,"result":validated,"telemetry":telemetry,"raw_provider_response_persisted":False,"private_reasoning_persisted":False,"authority":"CANDIDATE_ONLY"}
        except Exception as exc:
            _finish_attempt(path,state,"FAILED_VALIDATION_OR_TRANSPORT")
            if isinstance(exc,LocalWorkerError): raise
            raise LocalWorkerError(f"local worker execution failed closed: {exc}") from exc
    finally:
        _release_job_lock(lock)


def main()->int:
    parser=argparse.ArgumentParser(description="Bounded local worker delegation; never applies patches.")
    sub=parser.add_subparsers(dest="command",required=True)
    packet_cmd=sub.add_parser("packet"); packet_cmd.add_argument("job")
    sub.add_parser("preflight")
    validate=sub.add_parser("validate-result"); validate.add_argument("packet"); validate.add_argument("result")
    execute=sub.add_parser("execute"); execute.add_argument("packet"); execute.add_argument("--authorized",action="store_true"); execute.add_argument("--repair-feedback")
    args=parser.parse_args()
    try:
        if args.command=="packet": result={"valid":True,"packet":build_packet(_read(Path(args.job),"worker job"))}
        elif args.command=="preflight": result={"valid":True,"preflight":preflight()}
        elif args.command=="validate-result": result={"valid":True,"result":validate_result(_read(Path(args.packet),"worker packet"),_read(Path(args.result),"worker result"))}
        else: result={"valid":True,"execution":execute_packet(_read(Path(args.packet),"worker packet"),user_authorized=args.authorized,repair_feedback=args.repair_feedback)}
        print(json.dumps(result,indent=2,ensure_ascii=False)); return 0
    except LocalWorkerError as exc:
        print(json.dumps({"valid":False,"error":str(exc)},indent=2),file=sys.stderr); return 2

if __name__=="__main__": raise SystemExit(main())
