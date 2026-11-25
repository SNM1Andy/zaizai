#pragma once
#include <algorithm>
#include <array>
#include <atomic>
#include <barrier>
#include <bit>
#include <cstdint>
#include <stdexcept>
#include <system_error>
#include "cuda-order-win.hpp"
#include <string_view>
#include <thread>
#include <type_traits>
#include <unordered_map>
#include <vector>

namespace native_projection {
inline constexpr std::size_t packed_min=192;
inline constexpr std::size_t batch_max=12000;
struct Row {
    std::array<std::uint32_t,4> key{};
    std::uint32_t ticket=0;
};
static_assert(std::is_trivially_copyable_v<Row> && sizeof(Row)==20);
struct Less {
    bool operator()(const Row& a,const Row& b)const noexcept{
        if(a.key==b.key)return a.ticket<b.ticket;
        return a.key<b.key;
    }
};
// The callback sees only a copy of this batch, never the verifier's canonical rows.
using ProposeOrder=bool(*)(void*,const std::vector<Row>&,unsigned,std::vector<std::uint32_t>&);
struct Selection {ProposeOrder propose;void* context;unsigned attempted=0,verified=0,fallback=0;};
inline thread_local Selection* active_selection=nullptr;
class SelectionScope {
    Selection* previous_;
public:
    explicit SelectionScope(Selection* sett)noexcept:previous_(active_selection){active_selection=sett;}
    ~SelectionScope(){active_selection=previous_;}
    SelectionScope(const SelectionScope&)=delete;
    SelectionScope& operator=(const SelectionScope&)=delete;
};
inline bool verified_projection(const std::vector<Row>& rows,const std::vector<std::uint32_t>& order,
                                std::vector<Row>& verified){
    if(order.size()!=rows.size())return false;
    std::vector<bool> used(rows.size());
    std::vector<Row> candidate;candidate.reserve(rows.size());
    for(const auto ticket:order){
        if(ticket>=rows.size()||used[ticket])return false;
        const auto& row=rows[ticket];
        if(!candidate.empty()&&!Less{}(candidate.back(),row))return false;
        used[ticket]=true;candidate.push_back(row);
    }
    verified.swap(candidate);
    return true;
}
inline std::atomic_flag helper_in_use=ATOMIC_FLAG_INIT;
inline constexpr std::size_t rank_min=1024;
inline constexpr std::size_t two_worker_min=8192;
enum class CpuStrategy { compare,ordered,stable_rank,parallel_rank };
struct RankPass {unsigned column,shift;};
using Histogram=std::array<std::size_t,256>;
struct RankJob {
    std::vector<Row>& rows;
    std::vector<Row> scratch;
    std::array<RankPass,16> digits{};
    std::size_t count=0;
    explicit RankJob(std::vector<Row>& original,const std::array<std::uint32_t,4>& wide,unsigned width)
        :rows(original),scratch(original.size()){
        for(unsigned c=width;c>0;--c){
            const auto col=c-1;
            for(unsigned shift=0;shift<32;shift+=8)
                if(((wide[col]>>shift)&255U)!=0)digits[count++]={col,shift};
        }
    }
    const std::vector<Row>& source(std::size_t pass)const{return pass%2?scratch:rows;}
    std::vector<Row>& target(std::size_t pass){return pass%2?rows:scratch;}
    unsigned digit(std::size_t pass,const Row& row)const noexcept{
        return (row.key[digits[pass].column]>>digits[pass].shift)&255U;
    }
    void tally(std::size_t pass,std::size_t from,std::size_t end,Histogram& bins)const noexcept{
        bins.fill(0);
        const auto& in=source(pass);
        for(auto i=from;i<end;++i)++bins[digit(pass,in[i])];
    }
    void scatter(std::size_t pass,std::size_t from,std::size_t end,Histogram& offsets)noexcept{
        const auto& in=source(pass);
        auto& out=target(pass);
        for(auto i=from;i<end;++i)out[offsets[digit(pass,in[i])]++]=in[i];
    }
    void finish(){if(count%2)rows.swap(scratch);}
    void sequential()noexcept{
        Histogram bins{};
        for(std::size_t pass=0;pass<count;++pass){
            tally(pass,0,rows.size(),bins);
            for(std::size_t at=0,i=0;i<bins.size();++i){const auto n=bins[i];bins[i]=at;at+=n;}
            scatter(pass,0,rows.size(),bins);
        }
        finish();
    }
    void both(){
        // Every worker sees the same immutable input for a pass and writes a disjoint
        // interval per digit. Left-block ranks always precede right-block ranks.
        const auto end=rows.size(),mid=end/2;
        std::barrier stage(2);
        struct alignas(64) WorkerBins {Histogram bins;};
        std::array<WorkerBins,2> counts{};
        std::jthread helper([&]{
            for(std::size_t pass=0;pass<count;++pass){
                tally(pass,mid,end,counts[1].bins);
                stage.arrive_and_wait();
                stage.arrive_and_wait();
                scatter(pass,mid,end,counts[1].bins);
                stage.arrive_and_wait();
            }
        });
        for(std::size_t pass=0;pass<count;++pass){
            tally(pass,0,mid,counts[0].bins);
            stage.arrive_and_wait();
            auto& left=counts[0].bins;
            auto& right=counts[1].bins;
            for(std::size_t at=0,i=0;i<left.size();++i){
                const auto nleft=left[i],nright=right[i];
                left[i]=at;right[i]=at+nleft;at+=nleft+nright;
            }
            stage.arrive_and_wait();
            scatter(pass,0,mid,left);
            stage.arrive_and_wait();
        }
        helper.join();
        finish();
    }
};
inline CpuStrategy group_cpu(std::vector<Row>& rows,unsigned width,bool can_parallel=false){
    if(width<1||width>4||rows.size()>batch_max)throw std::invalid_argument("invalid projection shape");
    std::array<std::uint32_t,4> bits{};
    bool ascending=true,descending=true;
    for(std::size_t i=0;i<rows.size();++i){
        if(rows[i].ticket!=i)throw std::invalid_argument("projection tickets must be dense and ordered");
        for(unsigned column=0;column<4;++column){
            if((rows[i].key[column]!=0)!=(column<width))
                throw std::invalid_argument("invalid projection key padding or missing column");
            bits[column]|=rows[i].key[column];
        }
        if(i){
            ascending=ascending&&!(rows[i].key<rows[i-1].key);
            descending=descending&&!(rows[i-1].key<rows[i].key);
        }
    }
    if(ascending)return CpuStrategy::ordered;
    if(descending){
        std::reverse(rows.begin(),rows.end());
        for(auto begin=rows.begin();begin!=rows.end();){
            auto end=begin+1;
            while(end!=rows.end()&&end->key==begin->key)++end;
            std::reverse(begin,end);begin=end;
        }
        return CpuStrategy::ordered;
    }
    if(rows.size()>=rank_min){
        try{
            RankJob job(rows,bits,width);
            if(can_parallel&&rows.size()>=two_worker_min&&std::thread::hardware_concurrency()>1&&
                    !helper_in_use.test_and_set(std::memory_order_acquire)){
                struct Release {~Release(){helper_in_use.clear(std::memory_order_release);}} release;
                try{job.both();return CpuStrategy::parallel_rank;}
                catch(const std::system_error&){/* Setup failed before processing; use the same ranks on one worker. */}
            }
            job.sequential();
            return CpuStrategy::stable_rank;
        }catch(const std::bad_alloc&){/* Scratch unavailable; comparison sort has no shared scratch allocation. */}
    }
    std::sort(rows.begin(),rows.end(),Less{});
    return CpuStrategy::compare;
}

inline void group_with_policy(std::vector<Row>& rows,unsigned width){
    auto* selection=active_selection;
    if(!selection&&rows.size()>=packed_min){
        std::vector<std::uint32_t> order;
        if(win_cuda::propose(rows,order)&&verified_projection(rows,order,rows))return;
    }
    if(selection&&selection->propose){
        ++selection->attempted;
        std::vector<std::uint32_t> proposed(rows.size(),static_cast<std::uint32_t>(rows.size()));
        bool furnished=false;
        {
            SelectionScope prevent_inherited_reentry(nullptr);
            furnished=selection->propose(selection->context,rows,width,proposed);
        }
        if(furnished&&verified_projection(rows,proposed,rows)){++selection->verified;return;}
        ++selection->fallback;
    }
#ifdef CL_RANK_TWO_WORKER_REFERENCE
    group_cpu(rows,width,true);
#else
    // In the measured 12,000-row envelope a freshly scheduled helper cost more
    // than its share of the radix passes. Keep the bounded two-worker reference
    // available for parity without imposing that cost on ordinary evaluation.
    group_cpu(rows,width,false);
#endif
}

template<typename Rows,typename Destination,typename Project>
void build(const Rows& src,unsigned mask,Destination& out,Project project){
#ifndef CL_DIRECT_PROJECTION
    if(src.size()>=packed_min&&src.size()<=batch_max){
        const auto width=static_cast<unsigned>(std::popcount(mask));
        std::vector<Row> batch;batch.reserve(src.size());
        std::unordered_map<std::string_view,std::uint32_t> ids;
        for(std::size_t i=0;i<src.size();++i){
            Row row;
            row.ticket=static_cast<std::uint32_t>(i);
            unsigned column=0;
            for(unsigned source=0;source<src[i]->args.size();++source)
                if(mask&(1U<<source)){
                    const auto key=std::string_view(src[i]->args[source]);
                    const auto match=ids.try_emplace(key,static_cast<std::uint32_t>(ids.size()+1)).first;
                    row.key[column++]=match->second;
                }
            batch.push_back(row);
        }
        group_with_policy(batch,width);
        for(std::size_t first=0;first<batch.size();){
            std::size_t last=first+1;
            while(last<batch.size()&&batch[last].key==batch[first].key)++last;
            auto& results=out[project(*src[batch[first].ticket],mask)];
            results.reserve(last-first);
            for(auto i=first;i<last;++i)results.push_back(src[batch[i].ticket]);
            first=last;
        }
        return;
    }
#endif
    for(const auto* item:src)out[project(*item,mask)].push_back(item);
}
}
