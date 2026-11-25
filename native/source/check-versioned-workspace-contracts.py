from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import re, json, subprocess

root=Path(__file__).resolve().parent
cl,alpha,beta=root/'cl',root/'pcgm-alpha',root/'pcgm-beta'
def pin(path):return sha256(path.read_bytes()).hexdigest()
def write(path,val):path.write_bytes(val if isinstance(val,bytes) else val.encode());return path
def short(binary,*args,data=None):
    q=subprocess.run([binary,*args],input=data,capture_output=True,timeout=25)
    assert not q.returncode,(q.args,q.returncode,q.stderr,q.stdout)
    return q.stdout
@contextmanager
def live(binary,*args):
    with subprocess.Popen([binary,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def issue(p,s):
    p.stdin.write(s+'\n');p.stdin.flush()
    row=p.stdout.readline()
    assert row,(s,p.poll())
    return row.strip()
def val(row,key):return re.search(fr'{key}=([a-z0-9]+)',row)[1]
def growth(binary,state):
    line=json.loads(short(binary,'--read-channel',state,data=b'v workspace_growth suite\n'))
    assert line['ok'],line
    return line['payload']
def chosen(receipt):
    result=json.loads(receipt)['decision']
    return result,result['options'][result['selected']]
with TemporaryDirectory(prefix='native PCGM active version interface ') as work:
    d=Path(work);imports=d/'imports';imports.mkdir();build=d/'build_inputs';build.mkdir()
    for library,amount in (('bank',80),('grant',20)):
        src=write(imports/(library+'.cl'),f'module {library}.\nexport liq.\n: liq(qty(cny_cent)).\n& qty liq({amount}@cny_cent).\n')
        lock=write(src.with_suffix('.lock'),short(cl,'lock',src))
        api=write(src.with_suffix('.api'),short(cl,'project-api',src,lock))
        write(src.with_suffix('.clpkg'),short(cl,'project-pack',src,lock,api))
    lock=write(imports/'exact.lock','CLWORK-1\n'+''.join(f'{m} {m}.clpkg {pin(imports/(m+".clpkg"))} -\n' for m in ('bank','grant')))
    lock_sha=pin(lock)
    old='''module stable.
use bank.
use grant.
export bill.
: bill(qty(cny_cent)).
: offset(qty(cny_cent)).
bill($x) <- bank::liq($x).
offset($x) <- grant::liq($x).
'''
    newer=old+'''export covered.
: covered(sym).
covered(yes) <- bill(80@cny_cent) & offset(20@cny_cent).
'''
    maintained=newer+'covered(extra) <- bill(80@cny_cent).\n'
    baseline=write(imports/'suite.clw',short(cl,'workspace-pack',write(imports/'app.cl',old),lock,lock_sha))
    base_pin=pin(baseline)
    base_ir=sha256(short(cl,'workspace-bundle-ir',baseline,base_pin,lock_sha)).hexdigest()
    drafted=write(build/'suite.cl',newer)
    wanted=write(build/'suite.goals','bill(80@cny_cent)\noffset(20@cny_cent)\n')
    goals_pin=pin(wanted)
    candidate=write(d/'candidate',short(cl,'workspace-branch-additive',baseline,base_pin,lock_sha,drafted,pin(drafted),wanted,goals_pin))
    new_pin=pin(candidate)
    new_ir=sha256(short(cl,'workspace-bundle-ir',candidate,new_pin,lock_sha)).hexdigest()
    state=d/'actor'
    seed=write(d/'seed.cl',''': phase(sym).
: remember(sym).
~ meter remember.
= meter versions suite.
& steady stable(yes).
| hard positive stable(yes).
| hard unknown artifact_suite__covered(yes) when phase(repair).
| wish positive artifact_suite__covered(yes) when phase(expansion).
| wish positive artifact_suite__covered(extra) when phase(upkeep).
| hard unknown artifact_suite__covered(extra) when phase(trim).
''')
    with live(alpha,'--init-managed',seed,state) as p:
        who=val(p.stdout.readline(),'individual')
        assert issue(p,f':install_workspace suite {base_pin} {lock_sha}').startswith('package_installed')
        assert growth(alpha,state)['active_ir_sha256']==base_ir
        head=pin(state)
        fmt=lambda proof: f':retain_workspace_additive suite {base_ir} {lock_sha} {base_pin} {pin(drafted)} {proof} {head}'
        assert 'regression goals digest mismatch' in issue(p,fmt('0'*64)) and pin(state)==head
        marker=issue(p,fmt(goals_pin))
        assert marker.startswith('workspace_candidate_retained') and new_ir in marker,marker
        assert growth(alpha,state)=={
            'schema':'pcgm-workspace-growth-v1','alias':'suite','active_ir_sha256':base_ir,
            'edges':[{'before_ir_sha256':base_ir,'after_ir_sha256':new_ir,'goals_sha256':goals_pin}]}
        assert 'UNKNOWN' in issue(p,'artifact_suite__covered(yes)')
        baseline.write_bytes(candidate.read_bytes())
        attempt=issue(p,f':replace_workspace suite {base_ir} {new_pin} {pin(state)}')
        assert 'require an explicit PCGM comparison' in attempt,attempt
        assert growth(alpha,state)['active_ir_sha256']==base_ir
        baseline.unlink();drafted.unlink();wanted.unlink()
        assert 'observed go' in issue(p,':observe go phase(expansion)')
        assert 'observed noted' in issue(p,':observe noted remember(later)')
        inbox=d/'incoming';inbox.mkdir()
        write(inbox/'candidate_signal.packet','source meter 1\nremember(sent)\n')
        assert issue(p,':cycle candidate_signal').startswith('cycle_committed')
        # Drain any optional cycle summaries using an always-known control query.
        p.stdin.write('stable(yes)\n');p.stdin.flush()
        for _ in range(8):
            if p.stdout.readline().startswith('POSITIVE'):break
        else:raise AssertionError('sensor call did not finish')
        assert growth(alpha,state)['active_ir_sha256']==base_ir

        preview,option=chosen(issue(p,':compare_versions_parallel_json'))
        assert option['kind']=='artifact' and option['target']=='suite:'+new_ir and preview['status']=='recommended'
        assert growth(alpha,state)['active_ir_sha256']==base_ir
        report,option=chosen(issue(p,':decide_versions_parallel_json'))
        assert option['target']=='suite:'+new_ir and report['status']=='committed'
        assert 'POSITIVE' in issue(p,'artifact_suite__covered(yes)')
        draft=write(build/'suite.cl',maintained)
        packaged=write(d/'later.clw',short(cl,'workspace-rebuild',candidate,new_pin,lock_sha,draft,pin(draft)))
        maintained_pin=pin(packaged)
        maintained_ir=sha256(short(cl,'workspace-bundle-ir',packaged,maintained_pin,lock_sha)).hexdigest()
        ack=issue(p,f':retain_workspace_source suite {new_ir} {lock_sha} {new_pin} {pin(draft)} {pin(state)}')
        assert ack.startswith('workspace_candidate_retained') and maintained_ir in ack,ack
        draft.unlink()
        assert growth(alpha,state)['active_ir_sha256']==new_ir
        assert 'observed maintenance' in issue(p,':observe maintenance phase(upkeep)')
        report,option=chosen(issue(p,':decide_versions_parallel_json'))
        assert report['status']=='committed' and option['target']=='suite:'+maintained_ir
        assert 'POSITIVE' in issue(p,'artifact_suite__covered(extra)')
        p.kill();assert p.wait(timeout=5)<0
    transfer=d/'transfer'
    assert b'transfer_exported' in short(alpha,'--export-complete',state,transfer)
    portable=transfer/'state.bundle'
    manifest=transfer/'TRANSFER'
    body,original_manifest=portable.read_bytes(),manifest.read_bytes()
    marker=next(line for line in body.splitlines() if line.startswith(b'workspace_version_contract suite '+maintained_pin.encode()+b' '))
    old_api=marker.rsplit(b' ',1)[1]
    assert old_api!=b'0'*64
    magic,_,payload=body.split(b'\n',2)
    altered=payload.replace(marker,marker.rsplit(b' ',1)[0]+b' '+b'0'*64,1)
    checksum=14695981039346656037
    for byte in altered:checksum=((checksum^byte)*1099511628211)&((1<<64)-1)
    mutated=magic+b'\n'+str(checksum).encode()+b'\n'+altered
    portable.write_bytes(mutated)
    manifest.write_bytes(original_manifest.replace(sha256(body).hexdigest().encode(),sha256(mutated).hexdigest().encode(),1))
    reject=d/'refused'
    outcome=subprocess.run([alpha,'--restore-copy',transfer,reject],capture_output=True,timeout=15)
    assert outcome.returncode==1 and b'transferred workspace disagrees with recorded CL provenance' in outcome.stderr,outcome
    assert not reject.exists()
    portable.write_bytes(body);manifest.write_bytes(original_manifest)
    target=d/'remote';target.mkdir()
    restored=target/'actor'
    assert b'activation=required' in short(beta,'--restore-copy',transfer,restored)
    assert growth(beta,restored)['active_ir_sha256']==maintained_ir
    assert not (target/'build_inputs').exists()
    with live(alpha,'--resume',state) as p:
        assert val(p.stdout.readline(),'individual')==who
        assert growth(alpha,state)['active_ir_sha256']==maintained_ir
        blocked=json.loads(issue(p,':compare_versions_parallel_json'))['decision']
        candidates={item['target']:item for item in blocked['options']}
        assert 'different API generations' in candidates['suite:'+base_ir]['blocked_reason'] or 'no admitted transition' in candidates['suite:'+base_ir]['blocked_reason']
        assert 'withdrawn maintenance' in issue(p,':withdraw maintenance')
        assert 'observed shrink' in issue(p,':observe shrink phase(trim)')
        report,option=chosen(issue(p,':decide_versions_parallel_json'))
        assert report['status']=='committed' and option['target']=='suite:'+new_ir
        assert 'UNKNOWN' in issue(p,'artifact_suite__covered(extra)')
        assert 'withdrawn go' in issue(p,':withdraw go')
        assert 'observed fix' in issue(p,':observe fix phase(repair)')
        report,option=chosen(issue(p,':decide_versions_parallel_json'))
        assert report['status']=='committed' and option['target']=='suite:'+base_ir
        assert 'POSITIVE' in issue(p,'remember(later)')
        assert 'UNKNOWN' in issue(p,'artifact_suite__covered(yes)')
        ready=short(beta,'--prepare',state).decode()
        turn=issue(p,':handoff beta '+val(ready,'binary_sha256')+' '+val(ready,'snapshot_sha256'))
        assert turn.startswith('handoff_prepared') and p.wait(timeout=10)==0
    with live(beta,'--claim',state,val(turn,'nonce')) as p:
        assert val(p.stdout.readline(),'individual')==who
        assert growth(beta,state)['active_ir_sha256']==base_ir and len(growth(beta,state)['edges'])==1
        assert 'POSITIVE' in issue(p,'remember(later)') and 'POSITIVE' in issue(p,'phase(repair)')
print('PASS: native active interface provenance supports strict successor maintenance, rejects unregistered crossings and tampered restored contracts, then chooses two reverse transitions with later observations preserved through A/B.')
