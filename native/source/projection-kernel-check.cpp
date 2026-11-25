#include "native-projection.hpp"
#include <cassert>
#include <chrono>
#include <iostream>
#include <string_view>
#include <map>
#include <numeric>
#include <string>
#include <vector>
using native_projection::Row;

void parity(std::size_t n,unsigned width){
    std::vector<Row> input;
    std::map<std::array<std::uint32_t,4>,std::vector<std::uint32_t>> scalar;
    for(std::size_t i=0;i<n;++i){
        Row r;
        r.ticket=static_cast<std::uint32_t>(i);
        for(unsigned j=0;j<width;++j)
            r.key[j]=static_cast<std::uint32_t>(1+(i*(j+5)+n*(j+3))%(j==1?7:13));
        scalar[r.key].push_back(r.ticket);
        input.push_back(r);
    }
    auto sequential=input,adaptive=input;
    native_projection::group_cpu(sequential,width,false);
    native_projection::group_cpu(adaptive,width,true);
    std::size_t i=0;
    for(const auto& [key,ids]:scalar)
        for(const auto id:ids){
            assert(sequential[i].key==key&&sequential[i].ticket==id);
            assert(adaptive[i].key==key&&adaptive[i].ticket==id);
            ++i;
        }
    assert(i==n);
}
std::vector<Row> workload(std::size_t n,unsigned width,unsigned scenario){
    std::vector<Row> out;
    out.reserve(n);
    std::uint32_t pseudorandom=9860521;
    for(std::size_t i=0;i<n;++i){
        Row one;
        one.ticket=static_cast<std::uint32_t>(i);
        for(unsigned c=0;c<width;++c){
            pseudorandom^=pseudorandom<<13;pseudorandom^=pseudorandom>>17;pseudorandom^=pseudorandom<<5;
            switch(scenario){
                case 0: one.key[c]=1U+(pseudorandom%static_cast<std::uint32_t>(n));break;
                case 1: one.key[c]=i%37?0x10001U:std::max(1U,pseudorandom);break;
                case 2: one.key[c]=std::max(1U,pseudorandom);break;
                default: one.key[c]=1U+static_cast<std::uint32_t>((n-i)/(1U+c));break;
            }
        }
        out.push_back(one);
    }
    return out;
}
bool same(const std::vector<Row>& a,const std::vector<Row>& b){
    return a.size()==b.size()&&std::equal(a.begin(),a.end(),b.begin(),
        [](const Row& l,const Row& r){return l.key==r.key&&l.ticket==r.ticket;});
}
void stress(std::size_t n,unsigned width,unsigned scenario,bool require_backend){
    auto input=workload(n,width,scenario), ordered=input, serial=input, adaptive=input;
    std::sort(ordered.begin(),ordered.end(),native_projection::Less{});
    const auto str=native_projection::group_cpu(serial,width,false);
    const auto used=native_projection::group_cpu(adaptive,width,true);
    assert(same(ordered,serial)&&same(ordered,adaptive));
    if(n>=native_projection::rank_min)assert(str==(scenario==3?native_projection::CpuStrategy::ordered:native_projection::CpuStrategy::stable_rank));
    if(require_backend && scenario!=3 && n>=native_projection::two_worker_min&&std::thread::hardware_concurrency()>1)
        assert(used==native_projection::CpuStrategy::parallel_rank);
}
void benchmark(){
    using clock=std::chrono::steady_clock;
    for(const auto rows:{512U,2048U,8192U,12000U})for(unsigned caseid=0;caseid<4;++caseid){
        auto source=workload(rows,2,caseid);
        std::array<std::vector<long long>,3> times;
        for(unsigned rep=0;rep<43;++rep)for(unsigned stage=0;stage<3;++stage){
            const unsigned impl=(rep+stage)%3;
            auto data=source;
            const auto before=clock::now();
            if(impl==0)std::sort(data.begin(),data.end(),native_projection::Less{});
            else native_projection::group_cpu(data,2,impl==2);
            const auto duration=std::chrono::duration_cast<std::chrono::nanoseconds>(clock::now()-before);
            assert(std::is_sorted(data.begin(),data.end(),native_projection::Less{}));
            times[impl].push_back(duration.count());
        }
        std::cout<<"rows="<<rows<<" case="<<caseid;
        for(unsigned impl=0;impl<times.size();++impl){
            std::ranges::sort(times[impl]);std::cout<<" median_ns_"<<impl<<"="<<times[impl][21];
        }
        std::cout<<'\n';
    }
}
template<typename F> void rejects(F f){try{f();assert(false);}catch(const std::invalid_argument&){}}
int main(int argc,char** argv){
    if(argc==2&&std::string_view(argv[1])=="--benchmark"){benchmark();return 0;}
    assert(argc==1);
    for(auto n:{511U,512U,1023U,1024U,1025U,2048U,8191U,8192U,8193U,12000U})
        for(unsigned w=1;w<=4;++w)for(unsigned scenario=0;scenario<4;++scenario)stress(n,w,scenario,true);
    std::vector<std::jthread> workers;
    for(unsigned i=0;i<4;++i)workers.emplace_back([i]{
        for(unsigned t=0;t<16;++t)stress(12000,4,(i+t)%4,false);
    });
    for(auto& worker:workers)worker.join();
    for(auto limit:{0U,1U,191U,192U,193U,2047U,2048U,2049U,12000U})
        for(unsigned width=1;width<=4;++width)parity(limit,width);
    std::vector<Row> malformed{{{1,0,0,0},2}};
    rejects([&]{native_projection::group_cpu(malformed,1);});
    malformed.front().ticket=0;
    rejects([&]{native_projection::group_cpu(malformed,0);});
    rejects([&]{native_projection::group_cpu(malformed,2);});
    rejects([&]{native_projection::group_cpu(malformed,5);});
    malformed[0].key={1,1,0,0};
    rejects([&]{native_projection::group_cpu(malformed,1);});
    std::vector<Row> too_large(12001);
    rejects([&]{native_projection::group_cpu(too_large,1);});
}
