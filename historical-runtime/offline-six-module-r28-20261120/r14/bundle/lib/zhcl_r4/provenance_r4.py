"""Pure classification of R3 wire receipts under the R4 settlement rules."""
from . import vocab_r3


def make_receipt_r4(request, result, origin):
    """Build a wire envelope. Only the public verifier can classify its evidence."""
    if origin not in vocab_r3.RECEIPT_ORIGINS:
        raise ValueError("unrecognized receipt origin")
    return dict(schema=vocab_r3.R3_RECEIPT_SCHEMA, origin=origin, request=request,
                result=result, receipt_sha256=vocab_r3.receipt_sha256(origin, request, result))


def unknown(reason, detail, origin=None):
    return dict(status="UNKNOWN", origin=origin, reason=reason, detail=detail,
                receipt_sha256=None, real_execution_status="UNKNOWN")


def verify_receipt_r4(receipt, expected_candidate, cl_src=None):
    """Return UNKNOWN for inadmissible input. SHA identity is set only for a valid terminal."""
    if receipt is None:
        return unknown("NO_RECEIPT", "未收到回执。")
    if type(receipt) is not dict or receipt.keys() != set(vocab_r3.R3_RECEIPT_FIELDS):
        return unknown("RECEIPT_CONTRACT_VIOLATION", "回执必须为包含约定字段的对象。")
    if receipt["schema"] != vocab_r3.R3_RECEIPT_SCHEMA:
        return unknown("RECEIPT_CONTRACT_VIOLATION", "回执版本不受支持。")
    origin = receipt["origin"]
    if type(origin) is not str or origin not in vocab_r3.RECEIPT_ORIGINS:
        return unknown("ORIGIN_NOT_ENUMERATED", "回执来源不在约定的枚举中。")
    request = expected_candidate["request"]
    result = receipt["result"]
    from zhcl.cl_imports import load
    _, contracts = load(cl_src)
    try:
        contracts.validate_request(receipt["request"])
        if receipt["request"] != request:
            return unknown("RECEIPT_UNVERIFIABLE", "回执与当前候选请求不匹配。", origin)
        contracts.validate_result(result, request)
        actual = vocab_r3.receipt_sha256(origin, request, result)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return unknown("RECEIPT_UNVERIFIABLE", "请求或结果未通过约定的结构、内容与绑定校验。", origin)
    if type(receipt["receipt_sha256"]) is not str or receipt["receipt_sha256"] != actual:
        return unknown("RECEIPT_UNVERIFIABLE", "回执摘要不匹配。", origin)
    if origin == "REAL":
        return unknown("REAL_NOT_CERTIFIABLE", "自报真实来源缺少独立签发证据。", origin)
    if origin == "UNKNOWN":
        return unknown("SOURCE_UNKNOWN", "回执来源未知。", origin)
    success = result["status"] == "OK"
    return dict(status="SUCCESS" if success else "FAILED", origin=origin,
                reason=None if success else result["status"] + "/" + result["reason"],
                detail="合成回执校验通过，仅记录组件内的模拟结果。",
                receipt_sha256=actual, real_execution_status="UNKNOWN")
