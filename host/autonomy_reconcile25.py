"""Reconcile issued internal tickets against the current native reader before a fresh agenda proposal."""
import hashlib


def issued_enrollment(db, slot):
    import joint25_agenda_host as agenda
    row=db.execute("SELECT * FROM joint25_reviews WHERE kind='enroll' AND phase='issued' ORDER BY created LIMIT 1").fetchone()
    if not row:
        return None
    approval="PCGM-LOCAL-AGENDA-APPROVAL-1\n"+row["actor"]+"\n"+row["head"]+"\n"+row["native_pin"]+"\n"
    pin=hashlib.sha256(approval.encode()).hexdigest()
    try:
        observed=agenda.port(db,slot,"C4","enroll_receipt",{"entry":agenda.entry(row)},ms=1200)
    except (ValueError,TimeoutError,RuntimeError) as exc:
        return {"kind":"native_agenda_wait","topic":"原生问询","summary":"原登记等待核对："+str(exc)[:180],"progress":False}
    verified=(observed.get("schema")=="pcgm-agenda-enrollment-receipt-v1" and observed.get("actor")==row["actor"]
              and observed.get("writes_state") is False and observed.get("approval_sha256")==pin
              and agenda.HEX.fullmatch(observed.get("head_sha256","")))
    if not verified or observed.get("status") not in {"recorded","not_recorded"}:
        return {"kind":"native_agenda_wait","topic":"原生问询","summary":"旧题回执缺少可信状态，保留原单。","progress":False}
    if observed["status"]=="recorded":
        if not observed.get("ticket"):
            return {"kind":"native_agenda_wait","topic":"原生问询","summary":"已登记状态缺少问题编号。","progress":False}
        with db:
            db.execute("UPDATE joint25_reviews SET phase='committed',receipt=? WHERE pin=? AND phase='issued'",
                       (agenda.packed(observed),row["pin"]))
        return {"kind":"native_agenda_enrollment","topic":"原生问询","summary":"按原回执找回已登记内部票 "+observed["ticket"],
                "ticket":observed["ticket"],"review_pin":row["pin"],"receipt":agenda.sha(observed),"progress":True}
    if observed.get("ticket") is not None:
        return {"kind":"native_agenda_wait","topic":"原生问询","summary":"未登记状态带有票号，保留原单。","progress":False}
    if observed["head_sha256"]!=row["head"] or slot["manifest_sha256"]!=row["manifest"]:
        with db:
            db.execute("UPDATE joint25_reviews SET phase='not_recorded',receipt=? WHERE pin=? AND phase='issued'",
                       (agenda.packed(observed),row["pin"]))
    # A same-version, same-head request remains 'issued' and the normal approve path checks its receipt again.
    return None
