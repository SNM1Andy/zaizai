"""One target publishes only numeric milestones into reserved AMD64 mapping cells."""
import ctypes
import sys
import time

BASE, CAP, STRIDE, OVERFLOW = 4096, 96, 40, 8184
NAMES = ('SOURCE_A_BEGIN','SOURCE_A_END','SOURCE_B_BEGIN','SOURCE_B_END',
         'IMPORTS_BEGIN','NUMPY_BEGIN','NUMPY_END','IMPORTS_END','FRESH_BEGIN','FRESH_END',
         'BIND_BEGIN','BIND_END','SESSION_BEGIN','SESSION_END','PREPARE_BEGIN','PREPARE_END',
         'DECISION_BEGIN','DECISION_END','OBJECT_BEGIN','OBJECT_END',
         'APPEND','REDUCER_BEGIN','REDUCER_END','HEAD_BEGIN','HEAD_COMMITTED',
         'SUBMIT_BEGIN','SUBMIT_END','BROKER_BEGIN','BROKER_END','READFILE_BEGIN','READFILE_END',
         'RECORD_BEGIN','RECORD_END','PUBLISH_BEGIN','PUBLISH_END','CONSUME_BEGIN','CONSUME_END',
         'CAPTURE_BEGIN','CAPTURE_END','CAPTURE_OBJECT_BEGIN','CAPTURE_OBJECT_END','POINTER_BEGIN',
         'POINTER_END','REPORT_BEGIN','REPORT_END','COLD_BEGIN','COLD_END')
CODES = {name:i for i,name in enumerate(NAMES,1)}
_writer=None
_count=0

class PhaseOverflow(BaseException):
    """Fatal target stop. Application-level Exception handlers cannot convert it to a receipt."""

def check_capacity(ch):
    if ctypes.c_int64.from_buffer(ch.mem,OVERFLOW).value != 0:
        raise PhaseOverflow('PHASE_OVERFLOW')

def attach(channel):
    global _writer
    if _writer is not None or any(channel.mem[BASE:]):
        raise ValueError('phase buffer already used')
    _writer=channel.mem

def mark(name,seq=0):
    global _count
    if _writer is None:
        return
    if _count>=CAP:
        ctypes.c_int64.from_buffer(_writer,OVERFLOW).value=1
        raise PhaseOverflow('PHASE_OVERFLOW')
    index=_count
    _count+=1
    row=(ctypes.c_int64*5).from_buffer(_writer,BASE+index*STRIDE)
    row[0]=-1
    row[1]=CODES[name]
    row[2]=seq
    row[3]=time.monotonic_ns()
    row[4]=time.process_time_ns()
    row[0]=index+1

def numpy_begin():
    mark('NUMPY_BEGIN',int('numpy' in sys.modules))

class Observer:
    """One read of each committed record. All pre-termination observations remain in memory."""
    def __init__(self):
        self.events=[]
        self.live={}
        self.polls=0
    def sample(self,ch,live):
        start=time.monotonic_ns()
        for i in range(len(self.events),CAP):
            row=(ctypes.c_int64*5).from_buffer(ch.mem,BASE+i*STRIDE)
            if row[0]!=i+1:
                break
            self.events.append([i+1,*row[1:5],time.monotonic_ns()])
        if live:
            self.live[len(self.events)]=start
        self.polls+=1
    def finish(self,ch):
        self.sample(ch,False)
        n=len(self.events)
        return dict(schema='phase-clock-1',records=self.events,live_prefix=self.live,polls=self.polls,
                    overflow=ctypes.c_int64.from_buffer(ch.mem,OVERFLOW).value,
                    next_commit=ctypes.c_int64.from_buffer(ch.mem,BASE+n*STRIDE).value if n<CAP else None)
