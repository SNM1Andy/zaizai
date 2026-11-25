"""Read-only timestep refinement of the frozen R28 host field, from birth to its saved world frame."""
import argparse
from dataclasses import asdict
import hashlib
import importlib
import json
from pathlib import Path
import sys

# Chosen before the first run; small field errors are compared in the solver's dimensionless units.
PROTOCOL={"name":"r28-host-field-refinement/1","steps":[0.01,0.005,0.0025],
          "start":0.0,"sample_times":[0.05,0.10,0.15,0.20,0.25],"feature_atol":1e-7,"feature_rtol":1e-6,
          "field_atol":1e-7,"field_rtol":1e-6,"replay_atol":1e-12,"replay_rtol":1e-12,
          "refinement_floor":1e-13,"rhs_atol":1e-12,
          "comparison":"Every six-feature vector and complex field at each common checkpoint must be close. Fine-pair max error cannot exceed coarse-pair max error plus the rounding floor. The coarse-grid trajectory must recover the archived complex field. All intermediate amplitudes obey the saved fail-stop bound."}
def sha(b):return hashlib.sha256(b).hexdigest()
def packed(x):return json.dumps(x,sort_keys=True,ensure_ascii=False,separators=(",",":")).encode()
def need(x,message):
    if not x:raise ValueError(message)

def run(root):
    import numpy as np
    sys.path.insert(0,str(root/"host"))
    import inner3
    seed=inner3.seed()                 # Verify the frozen solver/source inventory and final native checkpoint.
    solver_module=importlib.import_module(type(seed["solver"]).__module__)
    runtime=importlib.import_module(solver_module.__package__+".coupled_runtime").CoupledRuntime
    stage=inner3.R28
    closed=json.loads((stage/"acceptance/closed.json").read_bytes())
    def checkpoint(name):
        raw=(stage/name).read_bytes();need(sha(raw)==closed[name],"R28 封存文件哈希不符："+name)
        wrap=json.loads(raw);return wrap["data"]["core_joint"],sha(raw)
    birth,initial_pin=checkpoint("run/birth-joint.json")
    final,final_pin=checkpoint("run/world/joint.json")
    need(final_pin==seed["snapshot"],"最终检查点不属于宿主的迁入来源")
    _,initial,calibration=runtime._decode(birth,multi_action=True)
    target=seed["solver"]
    need(initial.time==PROTOCOL["start"] and abs(target.time-PROTOCOL["sample_times"][-1])<1e-12,"封存实验与预置时段不符")
    need(initial.dt==PROTOCOL["steps"][0] and initial.method=="rk4","原版不是本次预登记的固定 RK4 步长")
    need(initial.geometry.digest==target.geometry.digest and initial.parameters==target.parameters and initial.seed==target.seed,"初终态配置发生变化")
    events=final["individual"]["state"]["events"]
    drive=solver_module.EventDrive(events,tick_duration=target.drive.tick_duration)
    need(drive.digest==target.drive.digest and drive.records,"封存时段缺少可核对驱动")
    def features(arr):return [solver_module.features(arr)[k] for k in solver_module.FEATURES]
    traces=[];summaries=[]
    for dt in PROTOCOL["steps"]:
        s=solver_module.ReferenceCGL(initial.geometry,seed=initial.seed,parameters=initial.parameters,
            method=initial.method,dt=dt,amplitude_limit=initial.amplitude_limit,drive=drive,initial=initial.field)
        fields=[];samples=[];low=float("inf");high=0
        for end in PROTOCOL["sample_times"]:
            steps=round((end-s.time)/dt)
            need(abs(s.time+steps*dt-end)<1e-12,"检查点不能由这一步长精确到达")
            for _ in range(steps):
                item=s.step()
                low=min(low,item["min_amplitude"]);high=max(high,item["max_amplitude"])
            need(abs(s.time-end)<1e-12,"未到公共采样时刻")
            fields.append(s.field)
            samples.append(dict(time=end,features=item,biases=calibration.biases(item)))
        need(not s.stopped and np.isfinite(s.field).all() and 0<=low<=high<=s.amplitude_limit,"途中数值失稳")
        traces.append(fields);summaries.append(dict(dt=dt,steps=s.steps,seed=s.seed,amplitude_range=[low,high],samples=samples))
    metrics=[]
    for i in (0,1):
        worst_f=worst_feature=0.
        for a,b in zip(traces[i],traces[i+1]):
            fa,fb=np.asarray(features(a)),np.asarray(features(b))
            need(np.allclose(a,b,atol=PROTOCOL["field_atol"],rtol=PROTOCOL["field_rtol"]),"场误差超过固定阈值")
            need(np.allclose(fa,fb,atol=PROTOCOL["feature_atol"],rtol=PROTOCOL["feature_rtol"]),"特征误差超过固定阈值")
            worst_f=max(worst_f,float(np.max(np.abs(a-b))));worst_feature=max(worst_feature,float(np.max(np.abs(fa-fb))))
        metrics.append(dict(dt=PROTOCOL["steps"][i],next_dt=PROTOCOL["steps"][i+1],field_linf=worst_f,features_linf=worst_feature))
    for k in ("field_linf","features_linf"):
        need(metrics[1][k]<=metrics[0][k]+PROTOCOL["refinement_floor"],"细步长误差没有下降到固定判据")
    replay=float(np.max(np.abs(traces[0][-1]-target.field)))
    need(np.allclose(traces[0][-1],target.field,rtol=PROTOCOL["replay_rtol"],atol=PROTOCOL["replay_atol"]),"恢复的原网格末态与封存不同")
    a=initial.field;p=initial.parameters;u=drive.at((drive.records[0].start+drive.records[0].end)/2)
    amp=np.abs(a)**2;lap=sum(np.roll(a,offset,axis) for axis in (0,1) for offset in (-1,1))-4*a
    unmodulated=(p.mu+1j*p.omega)*a+(p.D+1j*p.B)*lap-(p.g+1j*p.c)*amp*a+p.kappa*(p.E_target-np.mean(amp))*a+p.eta*u
    residue=initial._rhs(a,u)-unmodulated
    coupling=p.lambda_*initial.geometry.values*a
    real_err=float(np.max(np.abs(residue-coupling)))
    alt_err=float(np.max(np.abs(residue-(-1j*coupling))))
    need(real_err<=PROTOCOL["rhs_atol"] and alt_err>PROTOCOL["rhs_atol"],"几何项不符合实乘振幅耦合")
    return dict(passed=True,protocol=PROTOCOL,protocol_sha256=sha(packed(PROTOCOL)),
                solver=solver_module.VERSION,solver_file_sha256=sha(Path(solver_module.__file__).read_bytes()),
                identity=seed["id"],geometry_sha256=initial.geometry.digest,parameters=asdict(initial.parameters),
                birth_checkpoint_sha256=initial_pin,final_checkpoint_sha256=final_pin,grid=list(solver_module.SHAPE),
                source_event_head=drive.source_head,drive_sha256=drive.digest,source_events=len(events),
                nonzero_drive_records=[dict(index=x.index,hash=x.content_hash,start=x.start,end=x.end) for x in drive.records if x.amplitude!=0],
                runs=summaries,step_refinement=metrics,coarse_replay_linf=replay,rhs_amplitude_residual_linf=real_err,
                alternative_phase_error_linf=alt_err,amplitude_fail_stop_limit=initial.amplitude_limit,
                scope="R28 64×64、CPU、同一初态/底片/事件驱动的0.25物理时间；未验跨网格、长期轨迹、场对行为的因果作用或情绪命名。未设置或评估死区；谱系中的特征裁剪及tanh有界映射照原值读回。")

if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--root",type=Path,default=Path(__file__).resolve().parents[1])
    parser.add_argument("--out",type=Path)
    args=parser.parse_args();summary=run(args.root.resolve(strict=True))
    if args.out:args.out.write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf8")
    print(json.dumps({k:summary[k] for k in ("passed","source_events","step_refinement","coarse_replay_linf","rhs_amplitude_residual_linf","alternative_phase_error_linf")},ensure_ascii=False))
