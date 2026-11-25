#pragma once
// CUDA Driver API. Returns a permutation; the engine verifies every submitted row.
#include <windows.h>
#include <cstdlib>
#include <cstdio>
#include <vector>
#include <cstdint>
#include <chrono>
#include "gpu-safety-win.hpp"
namespace win_cuda {
using Address=unsigned long long;
using Context=void*;
using Module=void*;
using Kernel=void*;
struct Driver{
    HMODULE lib=LoadLibraryExW(L"nvcuda.dll",nullptr,LOAD_LIBRARY_SEARCH_SYSTEM32);
    template<class T>T get(const char* n){return lib?reinterpret_cast<T>(GetProcAddress(lib,n)):nullptr;}
    int (WINAPI *init)(unsigned)=get<decltype(init)>("cuInit");
    int (WINAPI *device)(int*,int)=get<decltype(device)>("cuDeviceGet");
    int (WINAPI *retain)(Context*,int)=get<decltype(retain)>("cuDevicePrimaryCtxRetain");
    int (WINAPI *release)(int)=get<decltype(release)>("cuDevicePrimaryCtxRelease_v2");
    int (WINAPI *unload)(Module)=get<decltype(unload)>("cuModuleUnload");
    int (WINAPI *push)(Context)=get<decltype(push)>("cuCtxPushCurrent_v2");
    int (WINAPI *pop)(Context*)=get<decltype(pop)>("cuCtxPopCurrent_v2");
    int (WINAPI *load)(Module*,const void*)=get<decltype(load)>("cuModuleLoadData");
    int (WINAPI *find)(Kernel*,Module,const char*)=get<decltype(find)>("cuModuleGetFunction");
    int (WINAPI *alloc)(Address*,size_t)=get<decltype(alloc)>("cuMemAlloc_v2");
    int (WINAPI *free)(Address)=get<decltype(free)>("cuMemFree_v2");
    int (WINAPI *upload)(Address,const void*,size_t)=get<decltype(upload)>("cuMemcpyHtoD_v2");
    int (WINAPI *download)(void*,Address,size_t)=get<decltype(download)>("cuMemcpyDtoH_v2");
    int (WINAPI *launch)(Kernel,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,unsigned,void*,void**,void**)=get<decltype(launch)>("cuLaunchKernel");
    Context ctx=nullptr;Module module=nullptr;Kernel kernel=nullptr;int device_id=0;
    ~Driver(){
        if(module&&ctx&&push(ctx)==0){unload(module);Context old;pop(&old);}
        if(ctx)release(device_id);
        if(lib)FreeLibrary(lib);
    }
    Driver(){
        if(!init||!device||!retain||!release||!unload||!push||!pop||!load||!find||!alloc||!free||!upload||!download||!launch||
            init(0)||device(&device_id,0)||retain(&ctx,device_id)||push(ctx))return;
        const char* ptx=R"PTX(.version 7.0
.target sm_52
.address_size 64
.visible .entry compare_stage(.param .u64 rows,.param .u64 order,.param .u32 count,.param .u32 step,.param .u32 span){
.reg .b32 %r<24>; .reg .b64 %d<12>; .reg .pred %p<10>;
ld.param.u64 %d0,[rows]; ld.param.u64 %d1,[order]; ld.param.u32 %r0,[count];
ld.param.u32 %r1,[step]; ld.param.u32 %r2,[span];
mov.u32 %r3,%ctaid.x; mov.u32 %r4,%ntid.x; mov.u32 %r5,%tid.x; mad.lo.u32 %r6,%r3,%r4,%r5;
setp.ge.u32 %p0,%r6,%r0; @%p0 bra done;
xor.b32 %r7,%r6,%r1; setp.le.u32 %p0,%r7,%r6; @%p0 bra done;
mul.wide.u32 %d2,%r6,4; add.u64 %d2,%d1,%d2; mul.wide.u32 %d3,%r7,4; add.u64 %d3,%d1,%d3;
ld.global.u32 %r8,[%d2]; ld.global.u32 %r9,[%d3]; setp.gt.u32 %p1,%r8,%r9;
setp.eq.u32 %p2,%r8,0xffffffff; setp.eq.u32 %p3,%r9,0xffffffff; or.pred %p4,%p2,%p3; @%p4 bra decide;
mul.wide.u32 %d4,%r8,20; add.u64 %d4,%d0,%d4; mul.wide.u32 %d5,%r9,20; add.u64 %d5,%d0,%d5;
mov.u32 %r10,0;
scan: ld.global.u32 %r11,[%d4]; ld.global.u32 %r12,[%d5]; setp.ne.u32 %p5,%r11,%r12;
@%p5 setp.gt.u32 %p1,%r11,%r12; @%p5 bra decide;
add.u64 %d4,%d4,4; add.u64 %d5,%d5,4; add.u32 %r10,%r10,1; setp.lt.u32 %p5,%r10,5; @%p5 bra scan;
decide: and.b32 %r13,%r6,%r2; setp.ne.u32 %p6,%r13,0; xor.pred %p7,%p1,%p6; @!%p7 bra done;
st.global.u32 [%d2],%r9; st.global.u32 [%d3],%r8;
done: ret;
})PTX";
        if(!load(&module,ptx))find(&kernel,module,"compare_stage");
        Context old;pop(&old);
    }
};
template<class Row>bool propose(const std::vector<Row>& rows,std::vector<uint32_t>& order){
    static_assert(sizeof(Row)==20);
    if(rows.size()<192||rows.size()>12000||std::getenv("ZAIZAI_CPU_ONLY"))return false;
    uint32_t count=1;while(count<rows.size())count*=2;
    const auto budget=rows.size()*20+count*4;
    gpu_safety::Ticket ticket;if(!ticket.active)return false;
    gpu_safety::Monitor monitor;
    if(!monitor.admit(budget,true))return false;
    Driver d;
    if(!d.kernel||d.push(d.ctx))return false;
    struct Scoped{Driver& d;Address rows=0,order=0;~Scoped(){if(rows)d.free(rows);if(order)d.free(order);Context old;d.pop(&old);}} mem{d};
    if(!monitor.admit(budget))return false;
    std::vector<uint32_t> ids(count,UINT32_MAX);
    for(uint32_t i=0;i<rows.size();++i)ids[i]=i;
    auto begin=std::chrono::steady_clock::now();
    if(d.alloc(&mem.rows,rows.size()*20)||d.alloc(&mem.order,count*4)||
       d.upload(mem.rows,rows.data(),rows.size()*20)||d.upload(mem.order,ids.data(),count*4))return false;
    for(uint32_t span=2;span<=count;span*=2){
        if(!monitor.admit(budget))return false;
        for(uint32_t step=span/2;step;step/=2){
            void* args[]={&mem.rows,&mem.order,&count,&step,&span};
            if(d.launch(d.kernel,(count+127)/128,1,1,128,1,1,0,nullptr,args,nullptr))return false;
        }
    }
    if(d.download(ids.data(),mem.order,rows.size()*4))return false;
    ids.resize(rows.size());order.swap(ids);
    if(std::getenv("ZAIZAI_GPU_TRACE")){
        const auto us=std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now()-begin).count();
        std::fprintf(stderr,"cuda_rows=%zu allocated_bytes=%zu elapsed_us=%lld\n",rows.size(),rows.size()*20+count*4,static_cast<long long>(us));
    }
    return true;
}
}
