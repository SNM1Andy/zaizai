from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
from shutil import copy2
from contextlib import contextmanager
import json,re,subprocess

root=Path(__file__).resolve().parent
cl=root/'cl';alpha=root/'pcgm-alpha';beta=root/'pcgm-beta'
env={'PATH':'','LC_ALL':'C'}
def h(data):return sha256(data).hexdigest()
def put(path,data):path.write_bytes(data.encode() if isinstance(data,str) else data);return path
def call(tool,*args,error=None,wd=None,data=None):
    p=subprocess.run([tool,*args],cwd=wd,env=env,input=data,capture_output=True,timeout=20)
    assert p.returncode==(1 if error else 0),(p.args,p.returncode,p.stderr,p.stdout[:300])
    if error:assert error in p.stderr,p.stderr
    return p.stdout
@contextmanager
def live(tool,*args):
    with subprocess.Popen([tool,*args],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                           env=env,text=True,encoding='utf-8',bufsize=1) as p:
        try:yield p
        finally:
            if p.poll() is None:p.kill();p.wait(timeout=5)
def ask(p,text):
    p.stdin.write(text+'\n');p.stdin.flush()
    result=p.stdout.readline()
    assert result,(p.poll(),text)
    return result
def meta(line,key):return re.search(fr'{key}=([a-z0-9]+)',line)[1]
def quoted(value):return json.dumps(value,ensure_ascii=False)
with TemporaryDirectory(prefix='native CL quoted UTF-8 symbol ') as td:
    d=Path(td);host_dir=d/'detached host';host_dir.mkdir()
    host=copy2(root/'cl-unicode-sdk-check',host_dir/'consumer')
    copy2(root/'libcl_memory.so',host_dir/'libcl_memory.so')
    punctuation='mix@12 ; graph::mock(x) & ! # " \\'
    distinct=[('中文',True),('みらい 🌱',True),('عربي',True),('é',True),('e\u0301',False),(punctuation,True),('bare',True)]
    dep='module lexicon.\nexport token.\n: token(sym).\n'
    for i,(value,seen) in enumerate(distinct):
        if seen:dep+=f'& a{i} token({quoted(value)}).\n'
    dep+='& opposite !token("中文").\n'
    src=put(d/'lexicon.cl',dep)
    l=put(d/'lexicon.lock',call(cl,'lock',src))
    api=put(d/'lexicon.api',call(cl,'project-api',src,l))
    pkg=put(d/'lexicon.clpkg',call(cl,'project-pack',src,l,api))
    assert call(cl,'package-ir',pkg).startswith(b'CLIR-7\n')
    lock=put(d/'workspace.lock',f'CLWORK-1\nlexicon lexicon.clpkg {h(pkg.read_bytes())} -\n')
    pinned=h(lock.read_bytes())
    app=put(d/'app.cl','module app.\nuse lexicon.\n: known(sym).\nknown($v) <- lexicon::token($v).\n!known($v) <- !lexicon::token($v).\n')
    archive=put(d/'app.clw',call(cl,'workspace-pack',app,lock,pinned))
    goal_text=''.join(f'known({quoted(value)})\n' for value,_ in distinct)+'known(bare)\nknown(~u'+('中文').encode().hex()+')\n'
    goals=put(d/'goals',goal_text)
    for item in (src,l,api,pkg,app,lock):item.unlink()
    args=(archive,h(archive.read_bytes()),pinned,goals)
    receipt=call(cl,'workspace-prove',*args)
    assert call(host,*args,wd=host_dir)==receipt
    rows=json.loads(receipt)['results']
    assert [r['status'] for r in rows]==['CONFLICT','POSITIVE','POSITIVE','POSITIVE','UNKNOWN','POSITIVE','POSITIVE','UNKNOWN','CONFLICT']
    for r,(value,_) in zip(rows,distinct):
        assert r['goal']['arguments']==[{'type':'sym','value':value,'encoding':'quoted_utf8'}]
    assert rows[7]['goal']['arguments']==[{'type':'sym','value':'bare'}]
    for data,reason in (
        (b': one(sym).\n& a one("\xc0\xaf").\n',b'UTF-8'),
        (b': one(sym).\n& a one("\xed\xa0\x80").\n',b'UTF-8'),
        (b': one(sym).\n& a one("bad\\n").\n',b'unknown quoted CL symbol escape'),
        (': one(sym).\n& a one("\u202e右").\n'.encode(),b'control character'),
        (': one(i64).\n& a one("一").\n'.encode(),b'argument type mismatch'),
        (b': one(sym).\n& a one(~uFEFF).\n',b'malformed quoted CL wire symbol'),
    ):
        bad=put(d/'invalid.cl',data);assert not call(cl,'compile',bad,error=reason)
    legacy=put(d/'legacy.cl',': one(sym).\n& a one(bare).\n')
    assert call(cl,'compile',legacy).startswith(b'CLIR-1\n')
    seed=put(d/'seed.cl',': fact(sym).\n: seen(sym).\nseen($x) <- fact($x).\n')
    state=d/'individual'
    human=quoted('新事实 中文')
    wire='~u'+'新事实 中文'.encode().hex()
    with live(alpha,'--init-managed',seed,state) as p:
        identity=meta(p.stdout.readline(),'individual')
        assert ask(p,':observe source fact('+human+')').startswith('observation_version')
        assert ask(p,'seen('+human+')').startswith('POSITIVE')
        assert ask(p,':withdraw source').startswith('observation_version')
        assert ask(p,'seen('+wire+')').startswith('UNKNOWN')
        p.kill();assert p.wait(timeout=5)<0
    assert wire.encode() in state.read_bytes()
    with live(alpha,'--resume',state) as p:
        assert meta(p.stdout.readline(),'individual')==identity
        assert ask(p,'seen('+human+')').startswith('UNKNOWN')
        assert ask(p,':restore source').startswith('observation_version')
        target=call(beta,'--prepare',state).decode()
        handoff=ask(p,':handoff beta '+meta(target,'binary_sha256')+' '+meta(target,'snapshot_sha256'))
        assert handoff.startswith('handoff_prepared') and p.wait(timeout=5)==0
    with live(beta,'--claim',state,meta(handoff,'nonce')) as p:
        assert meta(p.stdout.readline(),'individual')==identity
        before=state.read_bytes()
        assert ask(p,'seen('+wire+')').startswith('POSITIVE')
        report=json.loads(call(beta,'--read-channel',state,data=('r proof seen('+human+')\n').encode()))
        assert report['ok'] and report['payload']['results'][0]['goal']['arguments'][0]['value']=='新事实 中文'
        assert state.read_bytes()==before
print('PASS: real CLIR-7 native Unicode values retain exact typed meanings through workspace and detached C; malformed input and syntax-like text stay data; PCGM withdrawal, restart, and A/B retain the same observation and identity.')
