from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

root=Path(__file__).resolve().parent
cl, direct_cl=root/'cl',root/'cl-projection-direct'
pcgm, direct_pcgm=root/'pcgm-alpha',root/'pcgm-projection-direct'
def run(tool,*args,data=None,code=0):
    result=subprocess.run([tool,*args],input=data,capture_output=True,timeout=25)
    assert result.returncode==code,(result.args,result.returncode,result.stderr[:1000])
    return result.stdout if code==0 else (result.stdout,result.stderr)
@contextmanager
def live(tool,*args):
    with subprocess.Popen([tool,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def frame(p,query):
    p.stdin.write(query+'\n');p.stdin.flush()
    row=p.stdout.readline()
    assert row,(query,p.poll())
    return json.loads(row),row.encode()
def pin(path):return sha256(path.read_bytes()).hexdigest()

assert not run(root/'projection-kernel-check')
with TemporaryDirectory(prefix='CL real packed projection ') as tmp:
    d=Path(tmp)
    text=[
        ': events(sym,sym,qty(count),i64).',
        ': first(sym).',': second(sym).',': outcome(sym).',
        ': mask_one(sym).',': mask_two(sym).',': mask_full(sym).',
        'first($id) <- events(zone,$id,7@count,3).',
        '!first($id) <- !events(zone,$id,7@count,3).',
        'mask_one($id) <- events(zone,$id,$amount,$i).',
        'mask_two($id) <- events(zone,$id,7@count,$i).',
        'mask_full(n0) <- events(zone,n0,7@count,3).',
        'second($id) <- first($id).',
        'outcome($id) <- second($id).',
        '!outcome($id) <- !first($id).',
    ]
    text.extend(f'& a{i} events({"zone" if i%3==0 else "elsewhere"},n{i},{[7,5,9][i%3]}@count,{3-i%2}).' for i in range(2180))
    text.extend(f'& b{i} !events(zone,b{i},7@count,3).' for i in range(208))
    text.append('& conflict !events(zone,n0,7@count,3).')
    data='\n'.join(text)+'\n'
    source=d/'main.cl';source.write_text('module nativebatch.\n'+data)
    lock=d/'main.lock';lock.write_bytes(run(cl,'lock',source))
    api=d/'main.api';api.write_bytes(run(cl,'project-api',source,lock))
    pkg=d/'main.clpkg';pkg.write_bytes(run(cl,'project-pack',source,lock,api))
    goals=d/'goals'
    expected={
        'outcome(n6)':'POSITIVE','outcome(n0)':'CONFLICT','outcome(b5)':'NEGATIVE',
        'outcome(absent)':'UNKNOWN','mask_one(n3)':'POSITIVE','mask_two(n3)':'POSITIVE','mask_full(n0)':'POSITIVE'}
    goals.write_text('\n'.join(expected)+'\n')
    args=(pkg,pin(pkg),goals)
    a=run(cl,'package-prove',*args)
    assert a==run(direct_cl,'package-prove',*args)
    proof=json.loads(a)['results']
    assert [r['status'] for r in proof]==list(expected.values()),[r['status'] for r in proof]
    too_small=('package-prove-budget',*args,'128','12000','2000000','190')
    assert run(cl,*too_small,code=1)==run(direct_cl,*too_small,code=1)
    assert b'join index budget' in run(cl,*too_small,code=1)[1]
    frontier=d/'frontier'; old=d/'scalar_frontier'
    state_frames=[]
    for binary,path in ((cl,frontier),(direct_cl,old)):
        with live(binary,'package-round-checkpoint',*args,path) as session:
            assert json.loads(session.stdout.readline())['rounds']==0
            status,bytes_after_step=frame(session,'step 1')
            assert status['indexed']>=2180, status
            state_frames.append(bytes_after_step)
            saved,_=frame(session,'checkpoint')
            assert pin(path)==saved['sha256'],saved
            session.kill();assert session.wait(timeout=5)<0
    assert frontier.read_bytes()==old.read_bytes() and state_frames[0]==state_frames[1]
    final=[]
    for binary in (direct_cl,cl):
        with live(binary,'package-round-reopen',*args,frontier,pin(frontier)) as resumed:
            assert resumed.stdout.readline().encode()==state_frames[0]
            finished,_=frame(resumed,'finish')
            assert finished['status']=='complete'
            assert frame(resumed,'proof')[1]==a
            final.append(finished)
    assert final[0]==final[1]
    pcgm_source=d/'rules';pcgm_source.write_text(data)
    for binary,name in ((pcgm,'packed'),(direct_pcgm,'direct')):
        state=d/name
        run(binary,'--init',pcgm_source,state,data=b'')
        reply=run(binary,'--read-channel',state,data=('r inspect * 0; '+'; '.join(expected)+'\n').encode())
        result=json.loads(reply)
        assert result['ok'], result
        assert [q['status'] for q in result['payload']['proofs']['results']]==list(expected.values())
        if name=='packed':canonical=result['payload']['proofs']['results']
        else:assert result['payload']['proofs']['results']==canonical
with TemporaryDirectory(prefix='CL large actual derived projection ') as tmp:
    d=Path(tmp)
    core=': room(sym).\n: position(sym).\n: slab(sym,sym).\n: final(sym).\nslab($r,$p) <- room($r) & position($p).\nfinal($r) <- slab($r,p0).\n'
    core+=''.join(f'& room{i} room(r{i}).\n' for i in range(84))
    core+=''.join(f'& pos{i} position(p{i}).\n' for i in range(100))
    app=d/'geometry.cl';app.write_text('module geometry.\n'+core)
    lock=d/'derived.lock';lock.write_bytes(run(cl,'lock',app))
    api=d/'derived.api';api.write_bytes(run(cl,'project-api',app,lock))
    pkg=d/'derived.clpkg';pkg.write_bytes(run(cl,'project-pack',app,lock,api))
    goals=d/'goals';goals.write_text('final(r80)\nfinal(missing)\n')
    args=(pkg,pin(pkg),goals)
    wanted=run(direct_cl,'package-prove',*args)
    force=root/'cl-projection-two-worker'
    assert run(cl,'package-prove',*args)==wanted==run(force,'package-prove',*args)
    assert [q['status'] for q in json.loads(wanted)['results']]==['POSITIVE','UNKNOWN']
    ranked=d/'ranked';mappings=d/'mappings'
    two=d/'two'
    for engine,checkpoint in ((cl,ranked),(direct_cl,mappings),(force,two)):
        with live(engine,'package-round-checkpoint',*args,checkpoint) as p:
            assert json.loads(p.stdout.readline())['rounds']==0
            after,_=frame(p,'step 2')
            assert after['indexed']>=8400 and after['facts']>=8500,after
            saved,_=frame(p,'checkpoint')
            assert pin(checkpoint)==saved['sha256']
            p.kill();assert p.wait(timeout=5)<0
    assert ranked.read_bytes()==mappings.read_bytes()==two.read_bytes()
    with live(cl,'package-round-reopen',*args,mappings,pin(mappings)) as p:
        assert json.loads(p.stdout.readline())['rounds']==2
        assert frame(p,'finish')[0]['status']=='complete'
        assert frame(p,'proof')[1]==wanted
    old=d/'original.cl';old.write_text(core)
    state=d/'known.state'
    run(pcgm,'--init',old,state,data=b'')
    original=state.read_bytes()
    normal=run(pcgm,'--read-channel',state,data=b'r proof final(r80)\n')
    direct=run(direct_pcgm,'--read-channel',state,data=b'r proof final(r80)\n')
    assert normal==direct and state.read_bytes()==original
    assert json.loads(normal)['payload']['results'][0]['status']=='POSITIVE'
print('PASS: real CL and PCGM projected indexes preserve proof order and budgets; runtime crosses dense and parallel thresholds, resumes a byte-identical CL checkpoint on old and new CPU paths, and rejects invalid packed rows.')
