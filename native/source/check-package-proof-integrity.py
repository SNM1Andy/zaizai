from hashlib import sha256
from pathlib import Path
import json
import subprocess
import tempfile

root=Path(__file__).resolve().parent
engine=root/'cl'
def digest(data):return sha256(data).hexdigest()
def run(*args, error=None):
    result=subprocess.run([engine,*args],capture_output=True,timeout=30)
    if error:
        assert result.returncode and error.encode() in result.stderr and not result.stdout,(args,result.stderr)
    else:
        assert result.returncode==0,(args,result.stderr)
    return result.stdout

with tempfile.TemporaryDirectory() as temp:
    d=Path(temp)
    src=d/'civic.cl'
    src.write_text("""module civics.
: leader(sym,i64).
: winner(sym,i64).
: outcome(sym,i64).
: distinct(sym,sym).
: dirty(sym).
: base(sym).
: alternative(sym).
: independent(sym).
: routes(sym).
: dirty_only(sym).
: nested(sym).
: denied(sym).
: cycle_a(sym).
: cycle_b(sym).
& us_fec_2016 leader(clinton,2016).
& us_nara_2016 winner(trump,2016).
& identity distinct(clinton,trump).
& a dirty(example).
& b !dirty(example).
& c alternative(example).
& d !base(example).
outcome($p,$year) <- leader($p,$year) & winner($w,$year) & distinct($p,$w).
independent($x) <- alternative($x).
routes($x) <- dirty($x).
routes($x) <- independent($x).
dirty_only($x) <- dirty($x).
nested($x) <- dirty_only($x).
!denied($x) <- !base($x).
cycle_a($x) <- cycle_b($x).
cycle_b($x) <- cycle_a($x).
""")
    lock=d/'civic.lock';lock.write_bytes(run('lock',src))
    api=d/'civic.api';api.write_bytes(run('project-api',src,lock))
    package=d/'civic.pack';package.write_bytes(run('project-pack',src,lock,api))
    queries=d/'goals';queries.write_text('outcome(clinton,2016)\noutcome(trump,2016)\ndirty(example)\nroutes(example)\nnested(example)\ndenied(example)\ncycle_a(example)\n')
    pin=digest(package.read_bytes())
    originals={x.name:x.read_bytes() for x in d.iterdir()}
    legacy=run('package-prove',package,pin,queries)
    output=run('package-proof-integrity',package,pin,queries)
    result=json.loads(output)
    assert result['package_sha256']==pin and result['goals_sha256']==digest(queries.read_bytes())
    actual=[(x['positive_status'],x['negative_status']) for x in result['results']]
    assert actual==[('CLEAN_WITNESS','NO_SUPPORT'),('NO_SUPPORT','NO_SUPPORT'),('DIRECT_DISPUTE','DIRECT_DISPUTE'),('CLEAN_WITNESS','NO_SUPPORT'),('DISPUTED_ANCESTRY','NO_SUPPORT'),('NO_SUPPORT','CLEAN_WITNESS'),('NO_SUPPORT','NO_SUPPORT')],actual
    assert 'obs:us_fec_2016' in str(result['results'][0]) and 'obs:us_nara_2016' in str(result['results'][0])
    assert 'obs:c' in str(result['results'][3]['positive_witness'])
    assert 'obs:a' in str(json.loads(legacy)['results'][3]['positive'])
    assert run('package-proof-integrity',package,pin,queries)==output
    assert run('package-prove',package,pin,queries)==legacy
    run('package-proof-integrity',package,'0'*64,queries,error='package does not match supplied SHA-256')
    assert originals=={x.name:x.read_bytes() for x in d.iterdir()}
    for fixture, name, goal in (
            ('closed-portfolio.cl','fold_case','support_count(active,3)'),
            ('observed-unit-conversion.cl','conversion_case','lower(known,1@token)')):
        src=d/(name+'.cl')
        src.write_bytes(f'module {name}.\n'.encode()+(root/'fixtures'/fixture).read_bytes())
        lock.write_bytes(run('lock',src))
        api.write_bytes(run('project-api',src,lock))
        package.write_bytes(run('project-pack',src,lock,api))
        queries.write_text(goal+'\n')
        pin=digest(package.read_bytes())
        assert 'results' in json.loads(run('package-prove',package,pin,queries))
        run('package-proof-integrity',package,pin,queries,
            error='proof integrity v1 does not cover closed folds or observed unit conversion')
print('PASS: native exact read-only CL package audits official-source witness, direct/ancestral dispute, independently rederived proof, negative polarity, empty cycle and bad pin; legacy signed proof identical.')
