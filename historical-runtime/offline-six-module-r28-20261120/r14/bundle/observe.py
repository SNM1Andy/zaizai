import sys
from collections import Counter

WATCH = {
    'al01.integrated': ['IntegratedLife.step','IntegratedLife.semantic_query'],
    'al01.core': ['World.observe','Compiler.compile','CVM.prepare','Individual.step'],
    'al01.durable': ['WorldDispatcher._adapter'],
    'al01.governance': ['arbitrate','schedule'],
    'al01.development': ['apply_feedback'],
    'al01.semantic_memory': ['apply_observation'],
    'al01.folder_broker': ['FolderBroker.handle'],
    'zhcl_r4.pipeline_r4': ['ZhClPipelineR4.translate','ZhClPipelineR4.report','ZhClPipelineR4._render'],
    'zhcl.validate_cl': ['validate'],
    'cli_frozen': ['Shell.handle','readable'],
    'original_action': ['enroll','decide','complete','transaction'],
}
FORBIDDEN = {
    ('al01.folder_broker','FolderBroker._driver'), ('al01.folder_broker','_Windows.__init__'),
    ('al01.folder_broker','_Posix.__init__'), ('cli_frozen','JsonBackend.call'),
    ('cli_frozen','JsonBackend.dispatch'), ('phase_clock','attach'),
}
class Trace:
    def __init__(self):
        self.counts = Counter()
        self.edges = Counter()
        self.blocked = []
    def hook(self, frame, event, arg):
        if event != 'call':
            return
        mod = frame.f_globals.get('__name__','')
        if mod not in WATCH and mod != 'phase_clock':
            return
        qual = frame.f_code.co_qualname
        if (mod,qual) in FORBIDDEN:
            self.blocked.append(mod+'.'+qual)
            raise PermissionError(mod+'.'+qual)
        if qual in WATCH.get(mod,()):
            name = mod+'.'+qual
            self.counts[name] += 1
            self.edges[frame.f_back.f_code.co_qualname+' -> '+name] += 1
    def __enter__(self):
        sys.setprofile(self.hook)
        return self
    def __exit__(self,*unused):
        sys.setprofile(None)
    def data(self):
        return dict(calls=dict(self.counts), edges=dict(self.edges), forbidden_hits=self.blocked)
