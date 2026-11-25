#pragma once
#include <windows.h>
#include <filesystem>
#include <cstdlib>
#include <cstdio>
#include <algorithm>
namespace gpu_safety {
constexpr unsigned long long MiB=1024ULL*1024,GiB=1024*MiB;
constexpr unsigned long long reserve=3*GiB;
constexpr unsigned max_temperature=87, target_load=99;
// Aim for 99% while real work is queued. A full device yields one percent of
// the scheduling interval. Below target the next real batch runs immediately.
inline unsigned pacing_us(unsigned load,unsigned long long interval_ms){
    if(load<=target_load)return 0;
    return static_cast<unsigned>(std::min(interval_ms,100ULL)*1000*(load-target_load)/load);
}
inline void yield_us(unsigned us){
    if(!us)return;
    HANDLE timer=CreateWaitableTimerExW(nullptr,nullptr,0x2,TIMER_ALL_ACCESS);
    if(!timer)timer=CreateWaitableTimerW(nullptr,TRUE,nullptr);
    if(!timer){SwitchToThread();return;}
    LARGE_INTEGER due;due.QuadPart=-10LL*us;
    if(SetWaitableTimer(timer,&due,0,nullptr,nullptr,FALSE))WaitForSingleObject(timer,20);
    CloseHandle(timer);
}
inline void trace(const char* reason){
    if(std::getenv("ZAIZAI_GPU_TRACE"))std::fprintf(stderr,"cuda_fallback=%s\n",reason);
}
struct Memory{unsigned long long total,free,used;};
struct Load{unsigned gpu,memory;};
struct Monitor{
    HMODULE lib=LoadLibraryExW(L"nvml.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);
    template<class T>T fn(const char* name){return lib?reinterpret_cast<T>(GetProcAddress(lib,name)):nullptr;}
    int (*init)()=fn<decltype(init)>("nvmlInit_v2");
    int (*shutdown)()=fn<decltype(shutdown)>("nvmlShutdown");
    int (*count)(unsigned*)=fn<decltype(count)>("nvmlDeviceGetCount_v2");
    int (*device)(unsigned,void**)=fn<decltype(device)>("nvmlDeviceGetHandleByIndex_v2");
    int (*memory)(void*,Memory*)=fn<decltype(memory)>("nvmlDeviceGetMemoryInfo");
    int (*temperature)(void*,unsigned,unsigned*)=fn<decltype(temperature)>("nvmlDeviceGetTemperature");
    int (*utilization)(void*,Load*)=fn<decltype(utilization)>("nvmlDeviceGetUtilizationRates");
    void* gpu=nullptr;bool started=false;
    unsigned long long last_pacing=GetTickCount64();
    Monitor(){
        unsigned devices=0;
        if(!init||!shutdown||!count||!device||!memory||!temperature||!utilization||init())return;
        started=true;
        // With more than one card an ordinal alone cannot establish CUDA/NVML identity.
        if(count(&devices)||devices!=1||device(0,&gpu))gpu=nullptr;
    }
    ~Monitor(){if(started)shutdown();if(lib)FreeLibrary(lib);}
    bool admit(unsigned long long needed,bool first=false){
        Memory m{};Load u{};unsigned t=0;
        if(!gpu||memory(gpu,&m)||temperature(gpu,0,&t)||utilization(gpu,&u)){
            trace("telemetry_unavailable");return false;
        }
        auto floor=reserve;
        if(const char* setting=std::getenv("ZAIZAI_GPU_MIN_FREE_MIB")){
            const auto v=std::strtoull(setting,nullptr,10);
            floor=std::max(floor,std::min(v,1024ULL*1024)*MiB);
        }
        // Allow an additional 512 MiB before initializing a driver context and JIT module.
        const auto headroom=needed+(first?512*MiB:0);
        if(m.free<floor+headroom){trace("vram_reserve");return false;}
        if(t>=max_temperature){trace("temperature");return false;}
        const auto now=GetTickCount64();
        const auto interval=first?25ULL:now-last_pacing;
        if(first||interval>=25){
            const unsigned delay=pacing_us(u.gpu,interval);
            if(delay){
                yield_us(delay);
                if(memory(gpu,&m)||temperature(gpu,0,&t)){trace("telemetry_unavailable");return false;}
                if(m.free<floor+headroom){trace("vram_reserve");return false;}
                if(t>=max_temperature){trace("temperature");return false;}
            }
            last_pacing=GetTickCount64();
        }
        if(first&&std::getenv("ZAIZAI_GPU_TRACE"))
            std::fprintf(stderr,"cuda_admit free_mib=%llu temp_c=%u gpu_pct=%u reserve_mib=3072 limit_c=87 target_pct=99\n",m.free/MiB,t,u.gpu);
        return true;
    }
};
struct Ticket{
    HANDLE file=INVALID_HANDLE_VALUE;bool active=false;
    Ticket(){
        // Serialize admission across CL, both PCGM endpoints and the SDK.
        const auto clock=std::filesystem::path(L"D:\\再再2.0\\state\\gpu-admission.tick");
        file=CreateFileW(clock.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr);
        if(file==INVALID_HANDLE_VALUE){trace("another_worker_or_clock_unavailable");return;}
        active=true;
    }
    ~Ticket(){if(file!=INVALID_HANDLE_VALUE)CloseHandle(file);}
};
}
