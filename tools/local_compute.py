#!/usr/bin/env python3
"""Read-only discovery and resolution of local compute/software capability."""
from __future__ import annotations
import argparse, hashlib, json, os, platform, shutil, subprocess, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]

class LocalComputeError(ValueError): pass

def _read(path:Path,label:str)->dict:
    try: value=json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError,json.JSONDecodeError) as exc: raise LocalComputeError(f"Cannot load {label}: {exc}") from exc
    if not isinstance(value,dict): raise LocalComputeError(f"{label} root must be an object")
    return value

def load_policy(root:Path=ROOT)->dict:
    p=_read(root/"config/local_compute_policy.json","local compute policy")
    required={"schema_version","authority","execution_authority","probe_allowlist","features","workloads"}
    if set(p)!=required or p.get("schema_version")!="1.0": raise LocalComputeError("local compute policy fields must match contract")
    if p["authority"]!="OBSERVATIONAL_NONCANONICAL" or p["execution_authority"]!="NONE": raise LocalComputeError("local compute discovery must remain non-authoritative")
    allow=p["probe_allowlist"]
    if not isinstance(allow,list) or not allow or any(not isinstance(v,str) or not v for v in allow) or len(allow)!=len(set(allow)): raise LocalComputeError("probe_allowlist must contain unique command names")
    if set(p["features"])!={"NVIDIA_GPU","NVENC"}: raise LocalComputeError("feature policy must match current contract")
    for name,work in p["workloads"].items():
        if not isinstance(name,str) or not isinstance(work,dict) or set(work)!={"requires_executables","requires_features"}: raise LocalComputeError("workload fields must match contract")
        if any(v not in allow for v in work["requires_executables"]): raise LocalComputeError(f"{name} requires executable outside probe allowlist")
        if any(v not in p["features"] for v in work["requires_features"]): raise LocalComputeError(f"{name} requires unknown feature")
    return p

def _which(name:str)->str|None: return shutil.which(name)

def _run(args:list[str],timeout:float=5.0)->subprocess.CompletedProcess:
    return subprocess.run(args,capture_output=True,text=True,check=False,timeout=timeout)

def _version_line(command:str,path:str)->str|None:
    args=[path,"--version"] if command not in {"ffmpeg","ffprobe"} else [path,"-version"]
    try: proc=_run(args)
    except (OSError,subprocess.SubprocessError): return None
    text=(proc.stdout or proc.stderr or "").strip().splitlines()
    return text[0][:300] if proc.returncode==0 and text else None

def _nvidia_inventory(path:str)->list[dict]:
    try: proc=_run([path,"--query-gpu=name,memory.total,driver_version","--format=csv,noheader,nounits"])
    except (OSError,subprocess.SubprocessError): return []
    if proc.returncode!=0: return []
    gpus=[]
    for line in proc.stdout.splitlines():
        parts=[v.strip() for v in line.split(",")]
        if len(parts)!=3: continue
        try: mem=int(float(parts[1]))
        except ValueError: mem=None
        gpus.append({"name":parts[0],"memory_mib":mem,"driver_version":parts[2]})
    return gpus

def _ffmpeg_encoders(path:str)->list[str]:
    try: proc=_run([path,"-hide_banner","-encoders"])
    except (OSError,subprocess.SubprocessError): return []
    if proc.returncode!=0: return []
    found=[]
    for marker in ("h264_nvenc","hevc_nvenc","av1_nvenc"):
        if marker in proc.stdout: found.append(marker)
    return found

def discover(root:Path=ROOT)->dict:
    p=load_policy(root)
    executables={}
    for name in p["probe_allowlist"]:
        path=_which(name)
        executables[name]={"available":path is not None,"resolved_path":path,"version":_version_line(name,path) if path else None}
    nvidia_path=executables["nvidia-smi"]["resolved_path"]
    gpus=_nvidia_inventory(nvidia_path) if nvidia_path else []
    nvidia_available=bool(gpus)
    ffmpeg_path=executables["ffmpeg"]["resolved_path"]
    encoders=_ffmpeg_encoders(ffmpeg_path) if ffmpeg_path else []
    if not nvidia_available:
        nvenc={"status":"UNAVAILABLE_HARDWARE","encoders":[],"missing":["NVIDIA_GPU"]}
    elif not ffmpeg_path:
        nvenc={"status":"BLOCKED_MISSING_EXECUTABLE","encoders":[],"missing":["ffmpeg"]}
    elif encoders:
        nvenc={"status":"AVAILABLE","encoders":encoders,"missing":[]}
    else:
        nvenc={"status":"UNAVAILABLE_ENCODER","encoders":[],"missing":["NVENC_ENCODER"]}
    raw={"platform":platform.system(),"architecture":platform.machine(),"logical_cpu_count":os.cpu_count(),"executables":executables,"gpus":{"nvidia":gpus},"features":{"NVIDIA_GPU":{"status":"AVAILABLE" if nvidia_available else "UNAVAILABLE","device_count":len(gpus)},"NVENC":nvenc}}
    fingerprint=hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    return {"schema_version":"1.0",**raw,"observation_fingerprint":fingerprint,"authority":"OBSERVATIONAL_NONCANONICAL","execution_authority":"NONE","mutation_authority":"NONE"}

def resolve_workload(name:str,observation:dict|None=None,root:Path=ROOT)->dict:
    p=load_policy(root)
    if name not in p["workloads"]: raise LocalComputeError(f"unknown workload: {name}")
    obs=observation or discover(root); req=p["workloads"][name]; missing=[]
    for exe in req["requires_executables"]:
        if not obs.get("executables",{}).get(exe,{}).get("available",False): missing.append({"kind":"EXECUTABLE","name":exe})
    for feature in req["requires_features"]:
        if obs.get("features",{}).get(feature,{}).get("status")!="AVAILABLE": missing.append({"kind":"FEATURE","name":feature,"observed_status":obs.get("features",{}).get(feature,{}).get("status","UNKNOWN")})
    return {"schema_version":"1.0","workload":name,"status":"READY" if not missing else "BLOCKED","missing":missing,"observation_fingerprint":obs.get("observation_fingerprint"),"authority":"OBSERVATIONAL_NONCANONICAL","execution_authority":"NONE","mutation_authority":"NONE"}

def main()->int:
    parser=argparse.ArgumentParser(description="Discover local compute capability without granting execution authority.")
    sub=parser.add_subparsers(dest="command",required=True); sub.add_parser("discover"); res=sub.add_parser("resolve"); res.add_argument("workload")
    args=parser.parse_args()
    try:
        result=discover() if args.command=="discover" else resolve_workload(args.workload)
        print(json.dumps({"valid":True,**result},indent=2,ensure_ascii=False)); return 0
    except LocalComputeError as exc:
        print(json.dumps({"valid":False,"error":str(exc)},indent=2),file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
