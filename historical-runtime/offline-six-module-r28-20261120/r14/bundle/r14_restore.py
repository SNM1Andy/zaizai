"""Admission of two clean, positive R13-world TEST checkpoints. No business dispatch callbacks."""
from contextlib import contextmanager
import os
import re
import sys
from collections import Counter
from base import BASE, LIB, PACKAGE, enable_numeric, project_origins
from evidence_io import decode, digest, frame, plain, read, require, same, sha
from r10_checked import check_db, fresh_file, image, inventory

ROOT = PACKAGE.parent
EV = ROOT/'evidence'
ORIGIN = 'R13_SIMULATED_WORLD'

def record(root, name):
    return decode(read(root,name))

def path_for(kind, gen):
    require(kind in ('backup','restored') and type(gen) is int and gen in (1,2), 'fixed generation')
    return EV/kind/str(gen)

def layout(gen):
    require(type(gen) is int and gen in (1,2), 'generation')
    return sorted(['world/joint.json','world/actions.json'] +
                  [f'{name}-{i}.{ext}' for i in range(1,gen+1)
                   for name,ext in [('m5','sqlite'),('commit','json')]])

def logical(root, gen, session, language):
    from review import verify_ui
    inv = inventory(root)
    same(inv['directories'], ['world'], 'directory / closure')
    same(sorted(inv['files']), layout(gen), 'closed checkpoint members, sidecars and locks')
    joint, joint_file = frame(root,'world/joint.json')
    journal, actions_file = frame(root,'world/actions.json')
    core, modules = joint['core_joint'], joint['modules']
    state = core['individual']['state']
    require(re.fullmatch('[0-9a-f]{32}',session['run_id']) is not None, 'session uuid')
    same(session,dict(run_id=session['run_id'], identity='TEST-R13-'+session['run_id'],
                      scope_ref='scope_'+session['run_id'], freeze_sha256=sha((PACKAGE/'FREEZE.json').read_bytes()),
                      job_id=None, attempt=1),'owner and version')
    same(language['session'],session,'translator / owner')
    same([core['phase'],state['id'],state['version'],state['tick'],joint['generation'],state['closed_loops']],
         ['READY',session['identity'],2*gen,2*gen,2*gen,gen], 'business checkpoint generation')
    require(not any(state[k] for k in ('requested_actions','inbox','pending','tasks')) and
            state['pending_action_id'] is None,'unsettled world action')
    events, records = state['events'],journal['records']
    same(journal['schema'],'dispatch-0.1','journal version')
    same([e['kind'] for e in events],['commit','feedback']*gen,'business sequence')
    prev = '0'*64
    for pos,e in enumerate(events):
        same([e['index'],e['tick'],e['previous'],e['hash']],
             [pos,pos+1,prev,digest({k:v for k,v in e.items() if k!='hash'})], 'world event chain')
        prev = e['hash']
    ids, txs, receipts, dbs = [], [], [], {}
    owner = 'TEST-'+session['run_id']+'-amber'
    for i in range(1,gen+1):
        meta = record(root,f'commit-{i}.json')
        t = meta['transaction']
        c,e = events[2*i-2:2*i]
        req = c['payload']['action_requested']
        oid = req['action_id']
        ids.append(oid)
        same([meta['session'],meta['origin'],meta['generation'],meta['phase'],meta['language_sha256']],
             [session,ORIGIN,i,'READY',digest(language)], 'business / identity / intent')
        binding = dict(identity=session['identity'],instance=owner,freeze_sha256=session['freeze_sha256'],
                       origin=ORIGIN,request=req,commit_head=c['hash'])
        route = dict(original_id=oid,job=f'world-{i}',campaign=owner)
        same([t['binding'],t['route'],t['feedback']],[binding,route,e],'world/M5 action linkage')
        require(oid in records, 'missing historical receipt')
        saved = records[oid]
        same(t['receipt'],saved,'business / journal receipt')
        same([saved['action_id'],saved['dedup_key'],saved['operation'],saved['status'],saved['error'],
              saved['payload'],saved['result']],
             [oid,req['dedup_key'],'sandbox_observe','SUCCEEDED',None,
              {k:req[k] for k in ('proposal','world_version','world_digest','position')},
              {k:e['payload'][k] for k in ('position','value','target')}], 'world receipt body')
        target = 'object_0000' if i == 1 else 'object_0001'
        same([e['payload']['action_id'],req['proposal'],saved['result']['target'],saved['result']['value']],
             [oid,{'kind':'observe','target':target},target,1], 'expected amber observation')
        same([core['decision_traces'][i-1]['selected'],modules['governance'][i-1]['arbitration']['action_id']],
             [target,target],'approved selection')
        bound = digest(binding)
        rows = t['rows']
        require(len(rows)==3 and re.fullmatch('[0-9a-f]{64}',rows[1]['claim_sha256']) is not None,
                'reservation trace')
        same(rows,[dict(request_sha256=bound,state=s,claim_sha256=claim)
                   for s,claim in [('PLANNED',None),('RESERVED',rows[1]['claim_sha256']),('COMPLETED',None)]],
             'observed M5 sequence')
        dbname = f'm5-{i}.sqlite'
        same(t['db'],dbname,'M5 file route')
        dbs[dbname] = check_db(root/dbname,'m5')
        same(dbs[dbname],dict(authority=[[owner]], action=[[oid,bound,'COMPLETED',None]],
                              binding=[[route['job'],owner,oid]]),'M5 action/owner/claim')
        receipts.append(dict(origin=ORIGIN,action_id=oid,db_sha256=t['db_sha256'],feedback_head=e['hash']))
        txs.append(meta)
    same(sorted(records),sorted(ids),'exact terminal receipt set')
    require(len(set(ids)) == gen,'duplicate historical action')
    last = txs[-1]
    same([last['joint_sha256'],last['actions_sha256'],last['probe']['head'],last['probe']['tick']],
         [joint_file,actions_file,prev,gen*2],'joint/action/decision checkpoint')
    same(txs[0]['before'],None,'initial commit')
    same(txs[0]['ui'],None,'initial interface unused')
    same(last['probe']['semantic']['claims'][0]['evidence'][0]['feedback_ref']['hash'],
         events[1]['hash'],'first experience evidence')
    effect = None
    if gen == 2:
        same(last['before'],txs[0]['probe'],'cold experience entering second decision')
        trace = core['decision_traces'][1]
        same(trace['source_event_head'],events[1]['hash'],'decision consumes first close')
        audit = modules['score_audit'][1]
        same(audit['action_id'],ids[1],'score/actual action')
        weights = {a['entity_ref']:a['experience'] for a in audit['adjustments']}
        same(weights,last['before']['experience'],'cold experience / actual score contribution')
        scores = {a['entity_ref']:a['final_score'] for a in trace['ranked']}
        without = {k:v-weights[k] for k,v in scores.items()}
        require(set(scores)=={'object_0001','object_0002'} and scores['object_0001']>scores['object_0002']
                and without['object_0001']<without['object_0002'],'experience ranking crossover')
        effect = dict(actual_scores=scores,experience=weights,subtract_experience_only=without,
                      approved=trace['selected'],source_head=trace['source_event_head'])
        verify_ui(last['ui'], language,'amber',state,joint,receipts,session)
    return dict(session=session,generation=gen,head=prev,event_hashes=[e['hash'] for e in events],
                action_ids=ids,databases=dbs,joint_sha256=joint_file,actions_sha256=actions_file,
                commit_pins=[inv['files'][f'commit-{i}.json'] for i in range(1,gen+1)],
                schema=joint['schema'],versions=core['versions'],experience_effect=effect,
                ui='HELD_UNAVAILABLE_NO_PAYLOAD' if gen==2 else 'NO_CONFIRMATION',phase=core['phase'])

def transfer(source, target, gen):
    require(target.resolve().is_relative_to(ROOT) and not os.path.lexists(target),'fresh local target')
    plain(target.parent,directory=True)
    before = inventory(source)
    same(sorted(before['files']),layout(gen),'transfer input set')
    same(before['directories'],['world'],'transfer input directories')
    target.mkdir()
    (target/'world').mkdir()
    progress = {}
    for name,h in before['files'].items():
        dest = target/name
        if name.endswith('.sqlite'):
            progress[name] = image(source/name,dest)
        else:
            fresh_file(dest,read(source,name,h))
    same(inventory(source),before,'source changed during transfer')
    return progress

def admitted(source, anchor, pin, gen, language):
    same(digest(anchor),pin,'external close pin')
    same([anchor['generation'],anchor['class']],[gen,'CLOSED_R14_AMBER_TEST'],'designated generation')
    same(inventory(source),anchor['backup_inventory'],'sealed backup members / bytes')
    facts = logical(source,gen,anchor['session'],language)
    same(facts,anchor['logical'],'backup/anchor semantics')
    return facts

def restore(source,target,anchor,pin,gen,language):
    facts = admitted(source,anchor,pin,gen,language)
    progress = transfer(source,target,gen)
    same(logical(target,gen,anchor['session'],language),facts,'restored semantics')
    return dict(progress=progress,inventory=inventory(target),gen=gen)

@contextmanager
def no_actions():
    counts = Counter()
    blocked = []
    def hook(f,event,arg):
        if event != 'call':
            return
        mod = f.f_globals.get('__name__','')
        q = f.f_code.co_qualname
        name = mod+'.'+q
        if (mod in ('original_action','al01.folder_broker','al01.dispatch','al01.durable','cli_frozen')
            and (mod in ('original_action','al01.folder_broker','cli_frozen') or
                 'execute' in q or 'prepare_request' in q or '_adapter' in q or '_save' in q)) or name in {
                    'al01.integrated.IntegratedLife.step','al01.core.Individual.step',
                    'al01.core.World.observe','al01.core.World.movement','al01.multi_action_policy.execute_action',
                    'al01.coupled_runtime.CoupledRuntime._save','r12_birth.birth'}:
            blocked.append(name)
            raise PermissionError(name)
        if name in ('al01.integrated.IntegratedLife._load','al01.integrated.IntegratedLife.semantic_query',
                    'al01.core.CVM.prepare','al01.coupled_runtime.CoupledRuntime._association'):
            counts[name] += 1
    sys.setprofile(hook)
    try:
        yield counts,blocked
    finally:
        sys.setprofile(None)

def cold_guard(dest):
    # The unmodified runtime uses an exclusive ephemeral lock for construction and semantic_query.
    lock = dest/'world/joint.lock'
    def audit(event,args):
        if event == 'open' and not isinstance(args[0],int):
            raw = os.path.abspath(args[0])
            if args[2] & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
                require(raw == str(lock) and args[2] & os.O_EXCL,'cold write denied')
            else:
                p = type(dest)(raw).resolve()
                require(any(p.is_relative_to(r) for r in (BASE,PACKAGE,dest)), 'cold read scope')
        if event == 'os.remove':
            require(os.path.abspath(args[0])==str(lock),'cold remove denied')
        if event.startswith(('socket.','subprocess.','os.spawn','winreg.','os.exec','os.startfile')) or event in (
                'os.system','os.mkdir','os.rename','os.chmod','os.link','os.symlink','os.rmdir','os.truncate',
                'sqlite3.load_extension'):
            raise PermissionError(event)
        if event == 'sqlite3.connect':
            allowed = { (dest/name).as_uri()+'?mode=ro&immutable=1' for name in ('m5-1.sqlite','m5-2.sqlite') }
            require(args[0] in allowed or args[0]==':memory:', 'cold database scope')
    sys.addaudithook(audit)

def cold(gen,pin,pins,anchor_pin):
    dest = path_for('restored',gen)
    anchor = record(EV,f'close-{gen}.json')
    same(digest(anchor),anchor_pin,'external cold pin')
    same([anchor['generation'],anchor['class'],anchor['session']['freeze_sha256']],
         [gen,'CLOSED_R14_AMBER_TEST',pin],'cold identity/version/generation')
    language = anchor['language']
    before = inventory(dest)
    receipt = record(EV,f'restore-{gen}.json')
    same(receipt['gen'],gen,'restore receipt generation')
    same(receipt['inventory'],before,'restored member seal')
    # Authenticate the non-SQL bytes against the externally pinned close as well.
    for name in layout(gen):
        if not name.endswith('.sqlite'):
            same(before['files'][name],anchor['backup_inventory']['files'][name],'cold member '+name)
    sys.path.insert(0,str(LIB))
    sys.pycache_prefix = str(PACKAGE/'.no-bytecode')
    cold_guard(dest)
    facts = logical(dest,gen,anchor['session'],language)
    same(facts,anchor['logical'],'cold admitted semantics')
    from r14_world import memory_probe
    enable_numeric(pins)
    from al01.integrated import IntegratedLife
    with no_actions() as (calls,blocked):
        life = IntegratedLife(dest/'world')
        probe = memory_probe(life)
        same(probe,record(dest,f'commit-{gen}.json')['probe'],'actual runtime cold query')
        same([life.individual.state['id'],life.phase,life.sha],
             [facts['session']['identity'],'READY',record(dest,'world/joint.json')['sha256']],
             'cold runtime binding')
    same(inventory(dest),before,'cold mutated checkpoint')
    require(not blocked and calls['al01.integrated.IntegratedLife._load']>=1,'actual runtime load')
    return dict(status='PASS_CLOSED_TEST_COLD_OPEN',pid=os.getpid(),parent=os.getppid(),directory=str(dest),
                generation=gen,anchor_pin=anchor_pin,freeze=pin,logical=facts,probe=probe,
                guarded_calls=dict(calls),forbidden_calls=blocked,unchanged=True,mode='ro immutable SQLite',
                python=sys.version,numpy=pins['numpy_version'],modules=project_origins(pins))

