"""Guard the semantic mapping of an approved native claim against later view withdrawals."""
import json
import release25_lexicon

def why_unavailable(db,detail):
    if not isinstance(detail,dict) or not detail.get("sense_id") or not detail.get("sense_digest"):return None
    release=detail.get("lexicon_version") or detail.get("release_sha256") or release25_lexicon.RELEASE_PIN
    saved=release25_lexicon.resolve(detail["sense_id"],detail["sense_digest"],release_sha256=release,db=db)
    if saved["state"]=="tombstone":return f"历史引用的义项 {detail['sense_id']} 已在当前词库视图撤回，原回执保留。"
    return None
def for_atom(db,atom):
    names=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='joint25_goals'").fetchone()
    if not names:return None
    row=db.execute("SELECT description FROM joint25_goals WHERE atom=?",(atom,)).fetchone()
    if not row:return None
    try:desc=json.loads(row[0])
    except (TypeError,ValueError):return None
    return why_unavailable(db,desc)

