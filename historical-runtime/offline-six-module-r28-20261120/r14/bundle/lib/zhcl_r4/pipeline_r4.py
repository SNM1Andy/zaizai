"""Explicit-command pipeline and in-memory synthetic receipt settlement."""
from copy import deepcopy
from threading import Lock

from . import commands
from . import provenance_r4
from . import vocab_r3

_OP_ZH = {'LIST_SCOPE': '列出目录', 'READ_TEXT': '读取文件',
          'CHECK_ACCESS': '访问检查'}

_STATUS_REASON_ZH = {
    'DENIED/ACCESS_DENIED': '访问被拒绝（权限策略）',
    'DENIED/OUTSIDE_SCOPE': '访问被拒绝（超出作用域）',
    'DENIED/UNSAFE_ENTRY': '访问被拒绝（不安全条目）',
    'DENIED/UNSUPPORTED_OPERATION': '访问被拒绝（不支持的操作）',
    'DENIED/POLICY_ACTION_FORBIDDEN': '访问被拒绝（策略禁止该动作）',
    'UNAVAILABLE/SANDBOX_UNAVAILABLE': '环境不可用（沙箱不可用）',
    'UNAVAILABLE/ADAPTER_UNAVAILABLE': '环境不可用（适配器不可用）',
    'UNAVAILABLE/SCOPE_UNAVAILABLE': '环境不可用（作用域不可用）',
    'NOT_FOUND/ENTRY_NOT_FOUND': '未找到目标条目',
    'INVALID_TEXT/NOT_STRICT_UTF8': '文本无效（非严格 UTF-8）',
    'INVALID_TEXT/BINARY_CONTENT': '文本无效（二进制内容）',
    'LIMIT_EXCEEDED/BYTE_LIMIT': '超出字节限制',
    'LIMIT_EXCEEDED/ENTRY_LIMIT': '超出条目数量限制',
    'LIMIT_EXCEEDED/DEPTH_LIMIT': '超出路径深度限制',
    'LIMIT_EXCEEDED/PATH_LIMIT': '超出路径长度限制',
    'STALE_REF/REFERENCE_EXPIRED': '引用已过期',
    'STALE_REF/ENTRY_CHANGED': '目标条目已变化',
    'IO_ERROR/READ_FAILED': '读取失败',
    'IO_ERROR/LIST_FAILED': '列表失败',
    'IO_ERROR/ACCESS_CHECK_FAILED': '访问检查失败',
}


class ZhClPipelineR4:
    def __init__(self, context=None, cl_src=None):
        self.context = context or {}
        self.cl_src = cl_src
        self.registry = {}       # candidate_id -> candidate_sha256（重复ID策略）
        self._candidates = {}     # candidate_id -> candidate
        self._receipts = {}       # candidate_id -> {verdict, receipt_sha256, conflict_count}
        self._receipt_lock = Lock()
        self.counters = {'translate_calls': 0, 'clarify_count': 0,
                         'receipt_calls': 0, 'conflicting_receipts': 0,
                         'external_api_calls': 0}

    # --- 命令 → 候选 ---------------------------------------------------------
    def translate(self, text):
        self.counters['translate_calls'] += 1
        match = commands.match_command(text, self.context)
        if match['status'] != 'OK':
            self.counters['clarify_count'] += 1
            return {'text': text, 'status': 'AMBIGUOUS',
                    'reason': match['reason'], 'question': match['question'],
                    'interpretation': {'status': 'AMBIGUOUS', 'intents': [],
                                       'questions': [match['question']],
                                       'reasons': [match['reason']]},
                    'candidates': [], 'validation': [],
                    'counters': dict(self.counters)}
        cmd = match['command']
        from zhcl.candidates import build_candidate
        from zhcl import validate_cl
        interp = {'operation': cmd['operation'], 'entry_ref': cmd['entry_ref'],
                  'intent': cmd['intent'], 'question': None,
                  'proposed_by': 'r3-explicit-command'}
        candidate = build_candidate(interp, self.context)
        ok, record = validate_cl.validate(candidate, self.context, self.registry,
                                          cl_src=self.cl_src)
        if ok:
            self.registry.setdefault(candidate['candidate_id'],
                                     candidate['candidate_sha256'])
            self._candidates.setdefault(candidate['candidate_id'], deepcopy(candidate))
        return {'text': text, 'status': 'OK', 'reason': None, 'question': None,
                'interpretation': {'status': 'OK',
                                   'intents': [interp], 'questions': [],
                                   'reasons': []},
                'candidates': [candidate] if ok else [],
                'validation': [{'candidate_id': candidate['candidate_id'],
                                **record.as_dict()}],
                'counters': dict(self.counters)}


    @property
    def candidates(self):
        """Expose registered proposals as snapshots."""
        return deepcopy(self._candidates)

    @property
    def receipts(self):
        """Expose only committed synthetic terminals as snapshots."""
        with self._receipt_lock:
            return deepcopy(self._receipts)

    def deliver_receipt(self, receipt, candidate_id):
        candidate = self._candidates.get(candidate_id) if type(candidate_id) is str else None
        if candidate is None:
            incoming = provenance_r4.unknown("UNKNOWN_CANDIDATE", "消息 ID 尚未登记。")
        else:
            incoming = provenance_r4.verify_receipt_r4(receipt, candidate, self.cl_src)
        with self._receipt_lock:
            self.counters["receipt_calls"] += 1
            if incoming["status"] == "UNKNOWN":
                verdict = incoming
                if candidate is not None and candidate_id in self._receipts:
                    verdict["detail"] += "已存合成终态仍可查询。"
            else:
                stored = self._receipts.get(candidate_id)
                if stored is None:
                    self._receipts[candidate_id] = dict(verdict=incoming, receipt_sha256=incoming["receipt_sha256"],
                                                        conflict_count=0)
                    verdict = incoming
                elif incoming["receipt_sha256"] == stored["receipt_sha256"]:
                    verdict = stored["verdict"]
                else:
                    self.counters["conflicting_receipts"] += 1
                    stored["conflict_count"] += 1
                    verdict = dict(stored["verdict"], conflict=True,
                                   conflict_detail="后到的合成回执发生冲突，保留首份合成终态。")
        return dict(verdict), self._render(candidate_id, candidate, verdict)

    def report(self, candidate_id):
        candidate = self._candidates.get(candidate_id) if type(candidate_id) is str else None
        if candidate is None:
            verdict = provenance_r4.unknown("UNKNOWN_CANDIDATE", "消息 ID 尚未登记。")
        else:
            with self._receipt_lock:
                stored = self._receipts.get(candidate_id)
                if stored is None:
                    verdict = dict(status="PROPOSED", origin=None, reason=None, receipt_sha256=None,
                                   real_execution_status="UNKNOWN", detail="仅登记了候选，尚无有效合成终态。")
                else:
                    verdict = stored["verdict"]
        return dict(verdict), self._render(candidate_id, candidate, verdict)

    @staticmethod
    def _render(candidate_id, candidate, verdict):
        status = verdict["status"]
        if status == "PROPOSED":
            return f"候选已登记，尚无有效合成终态。真实执行状态未知。消息 ID 为 {candidate_id}。"
        if status == "UNKNOWN":
            return f"本次投递或查询结果未知。{verdict['detail']}真实执行状态未知。"
        op = _OP_ZH[candidate["operation"]]
        if status == "FAILED":
            reason = _STATUS_REASON_ZH.get(verdict["reason"], verdict["reason"])
            result = f"{op}模拟失败（{reason}）。"
        else:
            result = f"{op}模拟成功。"
        prefix = verdict.get("conflict_detail", "")
        return f"{prefix}合成回执，仅用于组件验证。{result}真实执行状态未知。消息 ID 为 {candidate_id}。"
