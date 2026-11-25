#include "../source/gpu-safety-win.hpp"
#include <cstdio>
namespace {
unsigned temperature_value=86, utilization_value=99;
unsigned long long free_value=gpu_safety::reserve;
int read_memory(void*,gpu_safety::Memory* m){m->free=free_value;return 0;}
int read_temperature(void*,unsigned,unsigned* t){*t=temperature_value;return 0;}
int read_utilization(void*,gpu_safety::Load* u){u->gpu=utilization_value;return 0;}
}
int main(){
    gpu_safety::Monitor m;
    m.gpu=&m;
    m.memory=&read_memory;m.temperature=&read_temperature;m.utilization=&read_utilization;
    if(!m.admit(0))return 1;
    free_value-=1;
    if(m.admit(0))return 2;
    free_value=gpu_safety::reserve+512*gpu_safety::MiB+1024;
    if(!m.admit(1024,true))return 3;
    temperature_value=87;if(m.admit(0))return 4;
    temperature_value=86;utilization_value=100;if(!m.admit(1024,true))return 5;
    if(gpu_safety::pacing_us(99,25)!=0 || gpu_safety::pacing_us(100,25)!=250)return 6;
    std::puts("sample injection: reserve boundary; 86C accepted, 87C stopped; 99% submitted, 100% paced");
    return 0;
}
