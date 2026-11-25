struct DecisionWork {size_t lanes=0,peak=0,jobs=0;};
template<class Op>
void evaluate_options(size_t count,size_t cap,DecisionWork* stats,const Op& do_one){
    require(cap>0&&cap<=4,"PCGM decision workers must be one to four");
    const auto lanes=min(count,cap);
    if(count==0)return;
    vector<exception_ptr> faults(count);
    atomic<size_t> index{0},active{0},peak{0};
    auto work=[&](){
        for(size_t i;(i=index.fetch_add(1))<count;){
            const auto n=active.fetch_add(1)+1;
            auto prior=peak.load();
            while(n>prior&&!peak.compare_exchange_weak(prior,n)){}
            try{do_one(i);}catch(...){faults[i]=current_exception();}
            active.fetch_sub(1);
        }
    };
    vector<jthread> pool;
    for(size_t i=1;i<lanes;++i)pool.emplace_back(work);
    work();
    for(auto& helper:pool)helper.join();
    if(stats){stats->lanes=max(stats->lanes,lanes);stats->peak=max(stats->peak,peak.load());stats->jobs+=count;}
    for(const auto& fault:faults)if(fault)rethrow_exception(fault);
}
