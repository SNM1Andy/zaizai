"""Read an installed scope across sessions and host releases, using its original native receipt."""
import json

import joint25_agenda_host as agenda


def existing(db, root, slot, tag):
    """Return the verified earlier receipt or None when there is no historical registration."""
    name, predicates, content = agenda._scope_spec(tag)
    if slot.get("id") != agenda.COG or slot.get("state") != "ready":
        raise ValueError("当前认知槽尚未就绪")
    rows = db.execute(
        "SELECT * FROM joint25_reviews WHERE kind='scope_install' AND phase='committed' AND json_extract(body,'$.tag')=? ORDER BY created", (tag,)
    ).fetchall()
    if not rows:
        return None
    native, gateway = agenda._engines(root)
    binaries, state = root / "releases/joint25/bin", root / "state/individual.pcgm"
    with native.deadline_scope(3.5):
        binary, snapshot = gateway.checkstate(binaries, state)
        events = native.history(binary, state)
        current_source = snapshot["source"].encode()
        filename = state.parent / "modules" / (name + ".cl")
        if filename.resolve() != filename or not filename.is_file() or filename.read_bytes() != content:
            raise ValueError("旧范围的当前模块文件与登记规格不符，保留存档待复核")
        for row in rows:
            value = json.loads(row["body"])
            receipt = json.loads(row["receipt"])
            prior = value["native_before_event"]
            offset = value["original_source_bytes"]
            original = {k: v for k, v in value.items() if k != "review_sha256"}
            review = row["native_pin"]
            key = agenda.sha([row["session"], row["kind"], row["actor"], row["head"], review, row["manifest"]])
            module_text = ("# module " + name + "\n").encode() + content
            if not (
                key == row["pin"] and value["review_sha256"] == review == agenda.sha(original)
                and value["actor"] == row["actor"] == snapshot["individual"]
                and value["head"] == row["head"] and value["module"] == name
                and value["proposed_code"].encode() == content and value["predicates"] == list(predicates)
                and value["module_sha256"] == native.digest(content)
                and isinstance(prior, int) and 0 <= prior < len(events)
                and native.pin(events[:prior]) == value.get("original_history_sha256")
                and events[prior] == f"event={prior + 1} install {name}"
                and isinstance(offset, int) and 0 <= offset <= len(current_source)
                and native.digest(current_source[:offset]) == value["source_sha256"]
                and current_source[offset:].lstrip(b"\r\n").startswith(module_text)
                and receipt.get("actor") == snapshot["individual"] and receipt.get("module") == name
                and ((receipt.get("scope_pin") == review and receipt.get("native_event") == prior + 1
                      and receipt.get("module_sha256") == value["module_sha256"]
                      and receipt.get("head_sha256") == value["expected_head"] and receipt.get("prior_head") == value["head"])
                     or (receipt.get("status") == "recorded" and agenda.HEX.fullmatch(receipt.get("head_sha256", ""))))
            ):
                continue
            return {"status": "already_recorded", "writes_state": False, "actor": snapshot["individual"],
                    "module": name, "module_sha256": value["module_sha256"], "head_sha256": snapshot["head"],
                    "original_review": key, "original_native_head": value["expected_head"], "native_event": prior + 1,
                    "original_receipt_sha256": agenda.sha(receipt), "observations_added": 0}
    raise ValueError("旧范围名称相同，但当前原生历史、规格与原回执未能互证，保留存档待复核")
