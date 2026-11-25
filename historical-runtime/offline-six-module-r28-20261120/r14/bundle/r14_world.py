"""R14 schedule of the unchanged R13 small-world transaction function."""
import os
from base import PACKAGE, check, digest, read, save, sha
from observe import Trace

def memory_probe(life):
    from al01.development import score_adjustment
    spec = read(PACKAGE/'r12-protocol.json')['query']
    ind = life.individual
    semantic = life.semantic_query(spec['entity'])
    tx = ind.vm.prepare(spec['source'], ind.state, ind.candidates())
    check(not tx.proposals and len(tx.neuron_calls) == 1, 'query emitted a proposal')
    entities = ('object_0001', 'object_0002')
    weights = {name:score_adjustment(life.modules['development'], ind.world.objects[name]['position'])
               for name in entities}
    return dict(identity=ind.state['id'], head=ind.state['events'][-1]['hash'], tick=ind.state['tick'],
                semantic=semantic, association=tx.neuron_calls[0]['contract'], experience=weights,
                development_sha256=digest(life.modules['development']))

def bounded_exercise(run, session, language, np):
    from al01.integrated import IntegratedLife
    from offline import interface, transaction
    from r12_birth import birth
    folder = run/'data/amber'
    generation = 1 if run.name == 'fresh-r14-first' else 2
    cfg = read(PACKAGE/'r12-protocol.json')
    check(session == language['session'], 'language session')
    with Trace() as trace:
        if generation == 1:
            folder.mkdir()
            life = birth(folder/'world', session['identity'], cfg['slots']['amber'], cfg, np)
            before = None
        else:
            # The controller admits a fingerprinted restored generation before this explicit action.
            # Verify the handed-off image again before constructing a writable runtime.
            handoff = read(run/'admission.json')
            files = {p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()}
            check(files == handoff['files'] and set(files) ==
                  {'world/joint.json','world/actions.json','m5-1.sqlite','commit-1.json'}, 'continuation image')
            check(handoff['session'] == session and handoff['generation'] == 1 and
                  sha(folder/'world/joint.json') == handoff['closed_joint_sha256'], 'continuation owner')
            life = IntegratedLife(folder/'world')
            before = memory_probe(life)
            check(life.phase == 'READY' and before['tick'] == 2 and before == handoff['cold_probe']
                  and before['identity'] == session['identity'], 'continuation memory and owner')
        # A failed/interrupted explicit attempt leaves its marker outside the checkpoint.
        save(run/'data'/('attempt-'+str(generation)+'.json'),
             dict(pid=os.getpid(),generation=generation,identity=session['identity']))
        t = transaction(life,folder,session,'amber',generation)
        probe = memory_probe(life)
        interface_record = None
        if generation == 2:
            first = read(folder/'commit-1.json')['transaction']
            interface_record = interface(life,folder/'never-opened',session,[first,t],language)
        record = dict(generation=generation,session=session,transaction=t,origin='R13_SIMULATED_WORLD',
                      writer=os.getpid(),phase=life.phase,joint_sha256=sha(life.path),
                      actions_sha256=sha(life.journal_path),before=before,probe=probe,
                      ui=interface_record,language_sha256=digest(language))
        save(folder/f'commit-{generation}.json',record)
    return dict(commit=record,trace=trace.data())

