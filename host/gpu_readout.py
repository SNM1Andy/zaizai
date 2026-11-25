"""Read-only NVML samples for the Windows monitor."""
import ctypes as c

class Memory(c.Structure):
    _fields_=[(name,c.c_ulonglong) for name in ("total","free","used")]

class Utilization(c.Structure):
    _fields_=[(name,c.c_uint) for name in ("gpu","memory")]

class Readout:
    def __init__(self):
        self.api=None
        self.handle=c.c_void_p()
        try:
            api=c.CDLL("nvml.dll",winmode=0x800)
            if api.nvmlInit_v2():
                return
            self.api=api
            count=c.c_uint()
            if api.nvmlDeviceGetCount_v2(c.byref(count)) or count.value!=1:
                return
            if api.nvmlDeviceGetHandleByIndex_v2(0,c.byref(self.handle)):
                self.handle=c.c_void_p()
        except (OSError,AttributeError):
            self.close()

    def sample(self):
        if not self.api or not self.handle:
            return None
        memory,temperature,load=Memory(),c.c_uint(),Utilization()
        try:
            if (self.api.nvmlDeviceGetMemoryInfo(self.handle,c.byref(memory))
                or self.api.nvmlDeviceGetTemperature(self.handle,0,c.byref(temperature))
                or self.api.nvmlDeviceGetUtilizationRates(self.handle,c.byref(load))):
                return None
        except (OSError,AttributeError):
            return None
        return {"free_mib":memory.free//(1024*1024),"temp_c":temperature.value,"gpu_percent":load.gpu}

    def close(self):
        if self.api:
            self.api.nvmlShutdown()
            self.api=None
