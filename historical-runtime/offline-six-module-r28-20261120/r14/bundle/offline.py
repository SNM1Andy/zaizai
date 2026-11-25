"""R13 glue. All executable actions belong to IntegratedLife's simulated World."""
import copy
from contextlib import closing
import os
import sqlite3
from base import PACKAGE, check, digest, gate, read, sha
from observe import Trace
from r14_world import bounded_exercise

def translate(session):
    from zhcl_r4 import ZhClPipelineR4
    p = ZhClPipelineR4(context=dict(scope_ref=session['scope_ref'],entries=[]))
    with Trace() as trace:
        listing = p.translate('列出目录')
        item, = listing['candidates']
        check(listing['validation'][0]['passed'] and item['operation']=='LIST_SCOPE', 'LIST_VALIDATION')
        verdict, phrase = p.report(item['candidate_id'])
        negative = [p.translate(cmd) for cmd in ('不要列出目录','读取 question-1.txt')]
    check(verdict['status']=='PROPOSED' and all(not r['candidates'] and r['question'] for r in negative),
          'language fail closed')
    return dict(session=session, listing=listing, negatives=negative, verdict=verdict,
                chinese=phrase, counters=p.counters, trace=trace.data())

def dbrow(dbpath, oid):
    with closing(sqlite3.connect(dbpath.as_uri()+'?mode=ro',uri=True)) as db:
        row = db.execute('SELECT request_sha256,state,claim FROM action WHERE original_id=?',(oid,)).fetchone()
    check(row is not None, 'missing transaction row')
    return dict(request_sha256=row[0],state=row[1],claim_sha256=digest(row[2]) if row[2] else None)

def settled_receipt(request, record, event):
    from al01.actions import journal_payload, validate_result
    validate_result(request,record['result'])
    check(record['status']=='SUCCEEDED' and record['operation']=='sandbox_observe' and record['error'] is None and
          record['action_id']==request['action_id']==event['payload']['action_id'] and
          record['dedup_key']==request['dedup_key'] and record['payload']==journal_payload(request) and
          event['kind']=='feedback' and
          {k:event['payload'][k] for k in ('position','value','target')}==record['result'], 'world receipt binding')

def transaction(life, directory, session, slot, index):
    import original_action as m5
    check(life.step() and life.phase=='REQUESTED', 'M4 commit')
    req = copy.deepcopy(life.individual.state['requested_actions'][0])
    oid = req['action_id']
    commit = life.individual.state['events'][-1]
    route = dict(original_id=oid,job=f'world-{index}',campaign='TEST-'+session['run_id']+'-'+slot)
    binding = dict(identity=session['identity'], instance=route['campaign'],freeze_sha256=session['freeze_sha256'],
                   origin='R13_SIMULATED_WORLD',request=req,commit_head=commit['hash'])
    dbpath = directory/f'm5-{index}.sqlite'
    bound = digest(binding)
    m5.enroll(dbpath,route['campaign'],[(oid,bound)],[(route['job'],route['campaign'],oid)])
    before = dbrow(dbpath,oid)
    decision = m5.decide(dbpath,route['campaign'],route,bound,recovery=False)
    claim = decision['claim']
    reserved = dbrow(dbpath,oid)
    check(before['state']=='PLANNED' and decision['granted'] and reserved['state']=='RESERVED' and
          reserved['claim_sha256']==digest(claim) and before['request_sha256']==reserved['request_sha256']==bound,
          'no confirmed M5 reservation')
    # A failure below leaves the original ledger and joint journal in place. No retry.
    check(life.step() and life.phase=='READY', 'world feedback')
    journal = read(life.journal_path)
    check(digest(journal['data'])==journal['sha256'], 'journal integrity')
    record = journal['data']['records'][oid]
    event = life.individual.state['events'][-1]
    settled_receipt(req,record,event)
    check(event['previous']==commit['hash'], 'feedback does not follow commit')
    m5.complete(dbpath,route['campaign'],oid,claim)
    final = dbrow(dbpath,oid)
    check(final==dict(request_sha256=bound,state='COMPLETED',claim_sha256=None),'M5 completion')
    return dict(route=route,binding=binding,rows=[before,reserved,final],receipt=record,
                feedback=event,db=dbpath.name,db_sha256=sha(dbpath))

class Preview:
    """Translate and confirm a LIST preview. This branch has no host authority."""
    def __init__(self, snapshot, candidate, broker):
        self.state = snapshot
        self.candidate = candidate
        self.broker = broker
        self.proposal = dict(operation=candidate['operation'],identity=snapshot['identity'],instance=snapshot['instance'],
                             state_sha256=digest(snapshot),candidate_sha256=candidate['candidate_sha256'],
                             proposal_id='preview_'+digest([candidate,snapshot])[:32])
        self.result = None
        self.calls = 0

    def snapshot(self):
        return copy.deepcopy(self.state)

    def propose(self, operation):
        check(operation==self.candidate['operation'], 'unsupported operation')
        return copy.deepcopy(self.proposal)

    def dispatch(self, proposal):
        check(proposal==self.proposal and not self.broker.enabled and self.calls==0, 'DISABLED_PREVIEW_ONLY')
        self.calls += 1
        from al01.folder_contracts import validate_result
        request = self.candidate['request']
        self.result = self.broker.handle(request)
        validate_result(self.result,request)
        check(self.result['status']=='UNAVAILABLE' and self.result['payload'] is None, 'M2 unexpected answer')
        return dict(status='UNAVAILABLE', diagnostic=dict(status='ADAPTER_UNAVAILABLE',
                    reason=dict(text='当前只有离线接口，没有启动 Windows 读取。')))

def interface(life, folder, session, transactions, language):
    from cli_frozen import Shell,readable
    from al01.folder_broker import FolderBroker
    candidate, = language['listing']['candidates']
    check(language['session']==session and candidate['provenance']['authority']=='NONE' and
          digest({k:v for k,v in candidate.items() if k!='candidate_sha256'})==candidate['candidate_sha256'] and
          candidate['request']['scope_ref']==session['scope_ref'], 'translator/session mismatch')
    check(not folder.exists(),'M2 boundary placeholder must not exist')
    broker = FolderBroker(str(folder),scope_ref=session['scope_ref'],application_checks_acknowledged=False)
    state = life.individual.state
    snapshot = dict(identity=state['id'],instance=transactions[-1]['route']['campaign'],revision=state['version'],
                    stage='READY_LIST', receipts=[dict(origin='R13_SIMULATED_WORLD',action_id=t['route']['original_id'],
                    db_sha256=t['db_sha256'],feedback_head=t['feedback']['hash']) for t in transactions],
                    head=state['events'][-1]['hash'],joint_sha256=life.sha,freeze_sha256=session['freeze_sha256'])
    backend = Preview(snapshot,candidate,broker)
    ui = Shell(backend)
    def turn(text):
        reply = ui.handle(text)
        return dict(input=text, output=reply, chinese=readable(reply))
    turns = [turn('状态'),turn('列出目录'),turn('取消'),turn('确认 无此提案'),turn('列出目录')]
    confirmation = turns[-1]['output']['confirmation']
    check(backend.calls==0, 'early handoff')
    turns.extend([turn(confirmation),turn(confirmation),turn('列出目录')])
    check([t['output']['status'] for t in turns]==
          ['STATE','CANDIDATE','CANCELLED','REFUSED','CANDIDATE','UNKNOWN','REFUSED','HOLD'] and
          backend.calls==1 and broker._backend is None and not folder.exists(), 'UI boundary')
    return dict(turns=turns,disabled_interface_calls=backend.calls,m2_result=backend.result,
                driver_constructed=broker._backend is not None,held=ui.held)

def exercise(run, session, language, np, expected):
    if run.name in ('fresh-r14-first','fresh-r14-next'):
        return bounded_exercise(run,session,language,np)
    from r12_birth import birth
    from al01.core import digest as native_digest
    cfg = read(PACKAGE/'r12-protocol.json')
    branches = {}
    for slot in ('amber','teal'):
        directory = run/'data'/slot
        directory.mkdir()
        with Trace() as trace:
            life = birth(directory/'world',session['identity'],cfg['slots'][slot],cfg,np)
            first = transaction(life,directory,session,slot,1)
            spec = cfg['query']
            semantic = life.semantic_query(spec['entity'])
            ind = life.individual
            tx = ind.vm.prepare(spec['source'],ind.state,ind.candidates())
            check(not tx.proposals and len(tx.neuron_calls)==1, 'read-only CL query')
            association = tx.neuron_calls[0]['contract']
            second = transaction(life,directory,session,slot,2)
            source_value, next_choice = expected[slot]
            check(semantic['provisional_claim']['value']==association['result']['observation']['value']==source_value
                  and first['receipt']['result']['target']=='object_0000'
                  and second['receipt']['result']['target']==next_choice, 'paired outcome')
            ui = interface(life,directory/'never-opened',session,[first,second],language)
        check(not trace.blocked and life.sha==native_digest(read(life.path)['data']), 'joint closure')
        branches[slot] = dict(transactions=[first,second],semantic=semantic,association=association,ui=ui,
                              trace=trace.data(),closed_tick=life.individual.state['tick'],phase=life.phase,
                              joint_sha256=sha(life.path),actions_sha256=sha(life.journal_path))
    return dict(session=session,language_sha256=digest(language),branches=branches,
                gates=[gate(k) for k in ('native-dispatch','outside-read','live-translation','cold-recover')])
