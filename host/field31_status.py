"""Display the installed PCGM field and its last attributed operation, without advancing it."""
import json
import native as n
import slots31

def command(db,text):
    if text.strip().rstrip("。！？?!") not in {"原生几何状态","几何接入"}:
        return None
    binding=db.execute("""SELECT identity,module_sha256,receipt_sha256,initialized_event FROM round31_native_reference
                          ORDER BY bound_ns DESC LIMIT 1""").fetchone()
    if not binding:return "本机尚未登记核过的原生几何安装回执。"
    frame=slots31.dispatch(db,"C9",{"operation":"geometry_status"})
    result=frame["output"]
    if result.get("refused"):return "认知槽未提供当前几何状态："+result["reason"]
    if binding["identity"]!=n.IDENTITY or result.get("identity")!=n.IDENTITY or result.get("module_sha256")!=binding["module_sha256"]:
        raise ValueError("当前身份或模块文件与安装回执不一致。")
    status=result["field_status"]
    if not status.startswith("field_tick="):raise ValueError("原生几何状态协议不匹配")
    rows=[f"PCGM 0.159 原生几何，初始化事件 {binding['initialized_event']}。",status]
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='geo31_steps'").fetchone():
        last=db.execute("SELECT receipt FROM geo31_steps WHERE phase='committed' ORDER BY committed DESC LIMIT 1").fetchone()
        if last:
            receipt=json.loads(last[0]);choice=receipt["decision"]
            rows.extend([f"最近一次有来源的原生场步：{receipt['request']}，上下文 {choice['context']}。",
                         f"合法集合中的基础首选 {choice['baseline']}，加几何偏好后选择 {choice['selected']}。"])
            rows.extend(f"{k} · {v['truth']} · "+("合格" if v["eligible"] else "不合格") for k,v in choice["candidates"].items())
    rows.append("宿主 R28 的逐轮评分另见「调度依据」。这里的 features 是原生场最近一步结束后的读数。")
    return "\n".join(rows)
