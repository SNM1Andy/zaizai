from pathlib import Path
from tempfile import TemporaryDirectory
from contextlib import contextmanager
from hashlib import sha256
import subprocess
import json

root = Path(__file__).resolve().parent

@contextmanager
def live(exe, *args):
    with subprocess.Popen([root/exe, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, text=True, bufsize=1) as process:
        try:
            yield process
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)

def issue(process, text):
    process.stdin.write(text + '\n')
    process.stdin.flush()
    line = process.stdout.readline().strip()
    assert line, (text, process.poll())
    return line

def compiler_reply(process, text, ok=True):
    body = json.loads(issue(process, text))
    assert body['ok'] == ok, body
    return body.get('payload', body.get('error'))

def digest(path):
    return sha256(path.read_bytes()).hexdigest()

with TemporaryDirectory(prefix='real anchored native journals ') as folder:
    home = Path(folder)
    parent = home/'current'
    moved = home/'relocated'
    region = home/'inputs'
    parent.mkdir()
    region.mkdir()
    standard = root/'profiles'/'standard.clcp'
    (region/'candidate.clcp').write_bytes((root/'profiles'/'forward.clcp').read_bytes())
    smoke = root/'fixtures'/'arithmetic.cl'
    output = subprocess.check_output([root/'cl', 'compile', smoke], timeout=12)
    first, candidate = digest(standard), digest(region/'candidate.clcp')
    compiler = parent/'compiler'
    actor = parent/'actor'
    example = root/'fixtures'/'base.cl'
    with live('cl', 'compiler-init', compiler, standard, region, smoke, sha256(output).hexdigest()) as c:
        before = compiler_reply(c, 'hello status')
        compiler_reply(c, f'build stage candidate {first} {candidate}')
        with live('pcgm-alpha', '--init-managed', example, actor) as p:
            identity = p.stdout.readline().strip()
            assert 'individual=' in identity, identity
            assert issue(p, ':observe original affordable(gamma)').startswith('observation_version')
            original = {x.name: x.read_bytes() for x in (actor, compiler)}
            parent.rename(moved)
            parent.mkdir()
            for name, content in original.items():
                (parent/name).write_bytes(content)
            before_decoy = set(parent.iterdir())
            assert 'directory moved' in compiler_reply(c, 'commit activate '+candidate, False)
            assert 'directory moved' in issue(p, ':observe discarded affordable(delta)')
            assert set(parent.iterdir()) == before_decoy
            for name, content in original.items():
                assert (parent/name).read_bytes() == (moved/name).read_bytes() == content
    with live('cl', 'compiler-resume', moved/'compiler', region) as c:
        assert compiler_reply(c, 'again status') == before
        compiler_reply(c, f'again stage candidate {first} {candidate}')
        assert compiler_reply(c, 'retry activate '+candidate)['epoch'] == 1
    with live('pcgm-alpha', '--resume', moved/'actor') as p:
        reopened = p.stdout.readline().strip()
        assert identity.split('individual=')[1].split()[0] == reopened.split('individual=')[1].split()[0]
        assert issue(p, 'affordable(gamma)').startswith('POSITIVE')
        assert issue(p, 'affordable(delta)').endswith('UNKNOWN')
        assert issue(p, ':observe repaired affordable(delta)').startswith('observation_version')
    for name, content in original.items():
        assert (moved/name).read_bytes() != content
        assert (parent/name).read_bytes() == content
print('PASS: actual CL/PCGM sessions reject replaced parent, old bytes remain identical, and intentional reopen resumes distinct durable updates.')
