from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from select import select
from tempfile import TemporaryDirectory
import json
import os
import re
import shutil
import subprocess

root = Path(__file__).resolve().parent
cl, pcgm = root/'cl', root/'pcgm-alpha'
env = dict(os.environ, PATH='', LC_ALL='C')
def digest(x):
    return sha256(x).hexdigest()
def put(path, data):
    path.write_bytes(data.encode() if isinstance(data, str) else data)
    return path
def call(exe, *args, ok=0, error=b'', cwd=None, data=b''):
    p = subprocess.run([exe,*args],env=env,cwd=cwd,input=data,capture_output=True,timeout=60)
    assert p.returncode == ok, (p.args,p.returncode,p.stdout[:400],p.stderr[:800])
    assert error in p.stderr, (p.args,p.stderr[:800])
    return p.stdout
@contextmanager
def session(exe,*args,cwd=None):
    with subprocess.Popen([exe,*args],env=env,cwd=cwd,stdin=subprocess.PIPE,
                          stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,
                          encoding='utf-8',bufsize=1) as p:
        try:
            yield p
        finally:
            if p.poll() is None:
                p.kill()
            p.wait(timeout=5)
def line(p):
    assert select([p.stdout],[],[],60)[0], 'No session response'
    data=p.stdout.readline()
    assert data, (p.poll(),p.stderr.read()[:1000])
    return data.strip()
def ask(p,text):
    p.stdin.write(text+'\n');p.stdin.flush()
    return line(p)
def msg(p,text,ok=True):
    row=json.loads(ask(p,text))
    assert row['id']==text.split()[0] and row['ok']==ok,row
    return row['payload'] if ok else row['error']

with TemporaryDirectory(prefix='authored CL Unicode and live revision ') as t:
    d=Path(t)
    sg=root/'fixtures'/'unicode-standard-grammar.cl'
    fg=root/'fixtures'/'unicode-forward-grammar.cl'
    g0=root/'profiles'/'standard.clcp'
    f0=root/'profiles'/'forward.clcp'
    types=root/'stages'/'numeric-type-checker.clir'
    lower=root/'stages'/'lowerer.clir'
    clir=[]
    for mode,src in [('standard',sg),('forward',fg)]:
        grammar=put(d/(mode+'.clir'),call(cl,'compile',src))
        out=call(cl,'compiler-profile',grammar,types,lower)
        assert out==(root/'profiles'/('unicode-'+mode+'.clcp')).read_bytes()
        assert grammar.read_bytes()==(root/'stages'/('unicode-'+mode+'-grammar.clir')).read_bytes()
        clir.append(put(d/(mode+'.clcp'),out))
    std,fwd=clir
    stdpin,fwdpin=map(lambda s:digest(s.read_bytes()),clir)
    literal='"上海 #東京, (ok)! 😀"'
    escaped=json.dumps('引号"及路径\\符号',ensure_ascii=False)
    prefix=': item(sym).\n: result(sym).\n& visible item('+literal+'). # real comment\n& quoted item('+escaped+').\n'
    tail='\n? result('+literal+').\n? result('+escaped+').\n'
    canonical=put(d/'canonical.cl',prefix+'result($x) <- item($x).'+tail)
    authored=put(d/'authored.cl',prefix+'item($x) => result($x).'+tail)
    immediate=call(cl,'compile',put(d/'direct.cl',canonical.read_bytes().replace(b' # real comment',b'')))
    assert immediate.startswith(b'CLIR-7\n')
    assert call(cl,'profile-build',std,stdpin,canonical)==immediate
    assert call(cl,'profile-build',fwd,fwdpin,authored)==immediate
    assert call(cl,'grammar-direct-ir',d/'forward.clir',types,lower,authored)==immediate
    for old,src in [(g0,canonical),(f0,authored)]:
        assert not call(cl,'profile-build',old,digest(old.read_bytes()),src,ok=1,error=b'grammar rejected source segment')
    assert not call(cl,'profile-build',std,'0'*64,canonical,ok=1,error=b'not the expected value')
    tree=json.loads(call(cl,'grammar-ast',fg,authored))
    raw=authored.read_bytes()
    statements=tree['statements']
    assert [s['kind'] for s in statements]==['declaration','declaration','observation','observation','rule','question','question']
    a,b=statements[2]['span']['bytes']
    assert raw[a:b].decode()=='& visible item('+literal+').'
    a,b=statements[-1]['literals'][0]['span']['bytes']
    assert raw[a:b].decode()=='result('+escaped+')'
    assert tree['context']['source_sha256']==digest(raw)
    multiple=put(d/'multi.cl', ': item(sym).\n'+''.join(f'& row{i} item("值{i}").\n' for i in range(52))+'? item("值51").\n')
    assert call(cl,'profile-build',std,stdpin,multiple)==call(cl,'compile',multiple)
    invalid=d/'invalid.cl'
    for text,why in [(b': item(sym).\n? item("\\n").\n',b'unknown quoted'),
                     (b': item(sym).\n? item("\xc0\xaf").\n',b'invalid UTF-8'),
                     (b': item(sym).\n? item("never).\n',b'quoted CL symbol'),
                     (': "name"(sym).\n',b'grammar rejected'),
                     (': item(i64).\n? item("12").\n',b'type audit rejected')]:
        assert not call(cl,'profile-build',std,stdpin,put(invalid,text),ok=1,error=why)

    # Native CL compiles and checks all three stage sources to their fixed point,
    # activates a new profile without process replacement, then reloads its journal.
    for name,src in [('grammar',sg),('types',root/'fixtures'/'numeric-type-checker.cl'),
                     ('lower',root/'fixtures'/'lowerer.cl')]:
        shutil.copyfile(src,d/(name+'.cl'))
    smoke=put(d/'smoke.cl',': anchor(sym).\nanchor(steady).\n? anchor(steady).\n')
    smokeir=call(cl,'compile',smoke)
    journal=d/'compiler.journal'
    pinned=[digest((d/(i+'.cl')).read_bytes()) for i in ('grammar','types','lower')]
    pin0=digest(g0.read_bytes())
    with session(cl,'compiler-init',journal,g0,d,smoke,digest(smokeir)) as live:
        assert msg(live,'a status')['epoch']==0
        assert 'grammar rejected' in msg(live,'b build canonical',False)
        staged=msg(live,'c self_stage grammar types lower '+' '.join([pin0]+pinned))
        assert staged['active_profile_sha256']==pin0 and staged['staged_profile_sha256']==stdpin
        assert 'grammar rejected' in msg(live,'d build canonical',False)
        active=msg(live,'e activate '+stdpin)
        assert active['active_profile_sha256']==stdpin and active['epoch']==1
        assert bytes.fromhex(msg(live,'f build canonical')['ir_hex'])==immediate
    with session(cl,'compiler-resume',journal,d) as resumed:
        assert msg(resumed,'g status')['epoch']==1
        assert bytes.fromhex(msg(resumed,'h build canonical')['ir_hex'])==immediate
        assert msg(resumed,'i stage_retained '+stdpin+' '+pin0)['staged_profile_sha256']==pin0
        assert msg(resumed,'j activate '+pin0)['epoch']==2
        assert 'grammar rejected' in msg(resumed,'k build canonical',False)
    with session(cl,'compiler-resume',journal,d) as restored:
        assert msg(restored,'l status')['active_profile_sha256']==pin0
        assert bytes.fromhex(msg(restored,'m build smoke')['ir_hex'])==smokeir

    # PCGM owns acceptance: before an explicit state-bound commit the compiled
    # candidate cannot affect its runtime. After SIGKILL read back its own proof.
    inputs=d/'build_inputs';inputs.mkdir()
    put(inputs/'text.cl',authored.read_bytes())
    put(inputs/'text.clcp',fwd.read_bytes())
    seed=put(d/'seed.cl',': later(sym).\nlater(seed).\n')
    state=d/'state'
    with session(pcgm,'--init',seed,state,cwd=d) as actor:
        uid=re.search(r'individual=(\w+)',line(actor))[1]
        old_state=state.read_bytes()
        receipt=ask(actor,f':stage_cl text {fwdpin} {digest(authored.read_bytes())} {digest(old_state)}')
        assert receipt.startswith('cl_staged text ') and digest(immediate) in receipt,receipt
        assert state.read_bytes()==old_state
        receipt=ask(actor,f':commit_cl text {digest(immediate)} {digest(old_state)}')
        assert receipt.startswith('cl_committed text ') and digest(immediate) in receipt,receipt
    shutil.rmtree(inputs)
    authored.unlink();canonical.unlink();seed.unlink()
    stored=state.read_bytes()
    evidence=call(pcgm,'--read-channel',state,cwd=d,
                  data=('r generated\np inspect * 0; artifact_text__result('+literal+')\n').encode())
    origin,proof=[json.loads(row)['payload'] for row in evidence.splitlines()]
    assert origin['state']['individual']==uid and origin['results'][0]['ir_sha256']==digest(immediate)
    assert proof['proofs']['results'][0]['status']=='POSITIVE'
    assert '上海 #東京, (ok)! 😀' in json.dumps(proof,ensure_ascii=False)
    assert state.read_bytes()==stored
    detached=put(d/'just-image.clir',immediate)
    detached_results=json.loads(call(cl,'ir-json',detached))['results']
    assert [row['status'] for row in detached_results]==['POSITIVE','POSITIVE']
    assert any(row['goal']['arguments']==[{'type':'sym','value':'上海 #東京, (ok)! 😀','encoding':'quoted_utf8'}]
               for row in detached_results)
print('PASS: CL-authored Unicode profiles produce exact direct CLIR-7; real compiler fixed point, hot activation/recovery/retained rollback, detached evaluation and PCGM committed state and identity verified.')
