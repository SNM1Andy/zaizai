"""Read-only verification. Decode stored observations and M5 DBs; never import business modules."""
import copy
from contextlib import closing
from datetime import datetime
import os
import re
import sqlite3
from base import PACKAGE, DENIALS, check, digest, gate, read, sha

def frame(path):
    d = read(path)
    check(set(d)=={'data','sha256'} and digest(d['data'])==d['sha256'], 'state frame '+path.name)
    return d['data']

def from_process(run,role,supervisor,pins,pin):
    ended = read(run/(role+'.exit.json'))
    stdout,stderr = run/(role+'.stdout'),run/(role+'.stderr')
    check(ended['exit_code']==0 and ended['parent']==supervisor and datetime.fromisoformat(ended['ended'])>=
          datetime.fromisoformat(ended['started']) and ended['stdout_bytes']==stdout.stat().st_size and
          ended['stderr_bytes']==stderr.stat().st_size==0 and ended['stdout_sha256']==sha(stdout) and
          ended['stderr_sha256']==sha(stderr),'raw process evidence')
    doc = read(stdout)
    check(doc['pid']==ended['pid'] and doc['role']==role and doc['parent']==supervisor and doc['freeze_sha256']==pin
          and doc['isolated']==doc['no_site']==1 and doc['no_bytecode'] and
          doc['python']==pins['python_version'], 'role/process binding')
    for item in doc['project_modules'].values():
        check(item['sha256']==pins['files'][item['file']], 'foreign executable')
    return doc

def verify_tx(t,slot,index,session,commit,event,record,directory):
    req = commit['payload']['action_requested']
    oid = req['action_id']
    campaign = 'TEST-'+session['run_id']+'-'+slot
    expected_binding = dict(identity=session['identity'],instance=campaign,freeze_sha256=session['freeze_sha256'],
                            origin='R13_SIMULATED_WORLD',request=req,commit_head=commit['hash'])
    check(t['binding']==expected_binding and t['route']==dict(original_id=oid,campaign=campaign,job=f'world-{index}'),
          'mismatched scoped action binding')
    check(commit['kind']=='commit' and event['previous']==commit['hash'] and event==t['feedback'] and
          event['kind']=='feedback' and event['payload']['action_id']==oid and
          record==t['receipt'] and record['action_id']==oid and record['dedup_key']==req['dedup_key'] and
          record['payload']=={k:req[k] for k in ('proposal','world_version','world_digest','position')} and
          record['operation']=='sandbox_observe' and record['status']=='SUCCEEDED' and record['error'] is None and
          record['result']=={k:event['payload'][k] for k in ('position','value','target')} and
          record['result']['target']==req['proposal']['target'], 'unbound world receipt')
    bound = digest(expected_binding)
    check([x['state'] for x in t['rows']]==['PLANNED','RESERVED','COMPLETED'] and
          all(x['request_sha256']==bound for x in t['rows']) and t['rows'][0]['claim_sha256'] is None and
          re.fullmatch('[0-9a-f]{64}',t['rows'][1]['claim_sha256']) and t['rows'][2]['claim_sha256'] is None,
          'claim transition')
    path = directory/f'm5-{index}.sqlite'
    check(path.name==t['db'] and sha(path)==t['db_sha256'], 'database pin')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
        check(db.execute('PRAGMA integrity_check').fetchall()==[('ok',)] and
              db.execute('SELECT * FROM authority').fetchall()==[(campaign,)] and
              db.execute('SELECT * FROM binding').fetchall()==[(f'world-{index}',campaign,oid)] and
              db.execute('SELECT * FROM action').fetchall()==[(oid,bound,'COMPLETED',None)], 'M5 disk rows')

def verify_ui(ui, language, slot, state, joint, receipts, session):
    turns = ui['turns']
    statuses = [t['output']['status'] for t in turns]
    check(statuses==['STATE','CANDIDATE','CANCELLED','REFUSED','CANDIDATE','UNKNOWN','REFUSED','HOLD'],
          'confirmation state machine')
    snap = turns[0]['output']['snapshot']
    check(snap==dict(identity=state['id'],instance='TEST-'+session['run_id']+'-'+slot,revision=state['version'],
                     stage='READY_LIST',receipts=receipts,head=state['events'][-1]['hash'],joint_sha256=digest(joint),
                     freeze_sha256=session['freeze_sha256']), 'UI state does not match joint and ledger')
    candidate, = language['listing']['candidates']
    proposal = turns[4]['output']['proposal']
    check(proposal['operation']==candidate['operation']=='LIST_SCOPE' and proposal['identity']==snap['identity']
          and proposal['instance']==snap['instance'] and proposal['state_sha256']==digest(snap) and
          proposal['candidate_sha256']==candidate['candidate_sha256'] and
          turns[5]['input']==turns[6]['input']==turns[4]['output']['confirmation']=='确认 '+proposal['proposal_id']
          and turns[4]['output']['executed'] is False, 'Chinese proposal/confirmation binding')
    req = candidate['request']
    denied = ui['m2_result']
    check(denied['request_sha256']==digest(req) and all(denied[k]==req[k] for k in
          ('schema','request_id','operation','scope_ref','entry_ref')) and denied['status']=='UNAVAILABLE' and
          denied['reason']=='ADAPTER_UNAVAILABLE' and denied['payload'] is None and ui['driver_constructed'] is False
          and ui['held'] and ui['disabled_interface_calls']==1 and turns[5]['output']['retry'] is False,
          'M2 must close without payload or host driver')

def verify(run,pin,pins,seal_pin):
    check(sha(run/'seal.json')==seal_pin,'RUN_SEAL_PIN')
    seal=read(run/'seal.json')
    check(seal['freeze_sha256']==pin,'run/package binding')
    expected={'session.json'}|{r+ext for r in ('world','language') for ext in ('.exit.json','.stdout','.stderr')}
    for slot in ('amber','teal'):
        expected.update('data/'+slot+'/'+f for f in ('world/joint.json','world/actions.json','m5-1.sqlite','m5-2.sqlite'))
    disk={p.relative_to(run).as_posix() for p in run.rglob('*') if p.is_file()}
    check(expected==set(seal['files'])==disk-{'seal.json'},'run files/locks/sidecars')
    for rel in expected:
        path=run/rel
        check(path.resolve()==path and sha(path)==seal['files'][rel],'evidence bytes '+rel)
    session=read(run/'session.json')
    check(session['identity']=='TEST-R13-'+session['run_id'] and session['freeze_sha256']==pin and
          session['scope_ref']=='scope_'+session['run_id'] and re.fullmatch('[0-9a-f]{32}',session['run_id']), 'identity')
    lng, w = [from_process(run,r,seal['supervisor_pid'],pins,pin) for r in ('language','world')]
    check(lng['numpy_version'] is None and w['numpy_version']==pins['numpy_version'] and
          lng['pid']!=w['pid'] and 'al01.folder_broker' not in lng['project_modules'] and
          'al01.integrated' not in lng['project_modules'] and 'zhcl_r4.pipeline_r4' not in w['project_modules'],
          'separate role origins')
    language, world = lng['result'],w['result']
    check(language['session']==world['session']==session and world['language_sha256']==digest(language),
          'cross-process handoff')
    listing=language['listing']
    candidate,=listing['candidates']
    check(listing['text']=='列出目录' and listing['validation'][0]['passed'] and
          listing['validation'][0]['checks']['real_cl'] and candidate['provenance']['authority']=='NONE' and
          candidate['candidate_sha256']==digest({k:v for k,v in candidate.items() if k!='candidate_sha256'}) and
          candidate['request']['scope_ref']==session['scope_ref'] and language['verdict']['status']=='PROPOSED' and
          language['chinese'] and language['counters']['external_api_calls']==0 and
          [n['reason'] for n in language['negatives']]==['NEGATED','NOT_A_COMMAND'] and
          all(n['status']=='AMBIGUOUS' and n['question'] and n['candidates']==[] for n in language['negatives']),
          'bounded Chinese understanding and expression')
    lc=language['trace']['calls']
    check(lc['zhcl_r4.pipeline_r4.ZhClPipelineR4.translate']==3 and lc['zhcl.validate_cl.validate']==1 and
          lc['al01.core.Compiler.compile']>=1 and lc['zhcl_r4.pipeline_r4.ZhClPipelineR4.report']==1,
          'language call evidence')
    check(world['gates']==[gate(k) for k in DENIALS],'missing fail-closed route')
    rows={}
    negatives=[]
    for slot,(value,target) in pins['expected'].items():
        path=run/'data'/slot
        b=world['branches'][slot]
        joint=frame(path/'world/joint.json')
        journal=frame(path/'world/actions.json')['records']
        core=joint['core_joint']
        state=core['individual']['state']
        events=state['events']
        check(len(events)==4 and len(journal)==2 and b['closed_tick']==state['tick']==4 and
              b['phase']==core['phase']=='READY' and state['id']==session['identity'] and
              b['joint_sha256']==sha(path/'world/joint.json') and b['actions_sha256']==sha(path/'world/actions.json'),
              'original joint/dispatch files')
        prev='0'*64
        for i,e in enumerate(events):
            check(e['previous']==prev and e['tick']==i+1 and e['index']==i and
                  e['hash']==digest({k:v for k,v in e.items() if k!='hash'}),'event chain')
            prev=e['hash']
        txs=b['transactions']
        check(len(txs)==2,'two scoped transactions')
        receipts=[]
        for i,t in enumerate(txs):
            oid=t['route']['original_id']
            verify_tx(t,slot,i+1,session,events[2*i],events[2*i+1],journal[oid],path)
            receipts.append(dict(origin='R13_SIMULATED_WORLD',action_id=oid,db_sha256=t['db_sha256'],
                                 feedback_head=events[2*i+1]['hash']))
        q=b['association']
        check(txs[0]['receipt']['result']==q['result']['observation'] and
              q['event_head']==b['semantic']['claims'][0]['evidence'][0]['feedback_ref']['hash']==events[1]['hash'] and
              q['result']['observation']['value']==b['semantic']['provisional_claim']['value']==value and
              q['result']['observation']['target']=='object_0000' and
              [t['selected'] for t in core['decision_traces']]==['object_0000',target] and
              [g['arbitration']['action_id'] for g in joint['modules']['governance']]==['object_0000',target] and
              txs[1]['receipt']['result']['target']==target, 'R12 integrated next selection')
        verify_ui(b['ui'],language,slot,state,joint,receipts,session)
        calls,edges=b['trace']['calls'],b['trace']['edges']
        check(not b['trace']['forbidden_hits'] and calls['al01.integrated.IntegratedLife.step']==4 and
              edges['IntegratedLife.step -> al01.governance.arbitrate']==2 and
              edges['IntegratedLife.step -> al01.development.apply_feedback']==2 and
              edges['WorldDispatcher._adapter -> al01.core.World.observe']==2 and
              calls['original_action.complete']==calls['original_action.decide']==calls['original_action.enroll']==2 and
              calls['al01.folder_broker.FolderBroker.handle']==1 and calls['cli_frozen.Shell.handle']==8
              and calls['cli_frozen.readable']==8, 'direct live calls')
        # Falsification on detached dictionaries: never present another request to the runtime.
        other='teal' if slot=='amber' else 'amber'
        cross=world['branches'][other]['transactions'][0]['receipt']
        bad_ui=copy.deepcopy(b['ui'])
        bad_ui['m2_result']['payload']={'entries':[]}
        for label,fn,args in [
            ('cross-world receipt',verify_tx,(txs[0],slot,1,session,events[0],events[1],cross,path)),
            ('payload on unavailable',verify_ui,(bad_ui,language,slot,state,joint,receipts,session))]:
            try:
                fn(*args)
            except ValueError as exc:
                negatives.append(dict(branch=slot,case=label,rejected=str(exc)))
            else:
                raise ValueError('accepted '+label)
        rows[slot]=dict(first_feedback=value,next_target=target,tick=4,m5_states=[t['rows'][-1]['state'] for t in txs],
                        m2=b['ui']['m2_result']['reason'],actual_calls=calls,live_edges=edges)
    return dict(verdict='PASS_OFFLINE_ONLY',verifier_pid=os.getpid(),freeze_sha256=pin,seal_sha256=seal_pin,
                session=session,processes=dict(supervisor=seal['supervisor_pid'],language=lng['pid'],world=w['pid']),
                results=rows,language_calls=lc,negative_controls=negatives,blocked=world['gates'],
                verification='sealed streams, event and receipt linkage, immutable read-only SQLite, process call traces')
