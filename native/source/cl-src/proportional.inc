bool proportional_calculation(const string& op){return op=="qty_ratio_floor"||op=="qty_ratio_ceil";}
// Accumulate exact quotient and remainder for abs(x)*abs(y) without requiring 128-bit integers.
int64_t checked_proportional(int64_t x,int64_t y,int64_t divisor,bool ceil){
    require(divisor>0,"CL ratio denominator must be positive");
    const auto absolute=[](int64_t v){return v<0?uint64_t{0}-static_cast<uint64_t>(v):static_cast<uint64_t>(v);};
    const bool negative=(x<0)!=(y<0);
    constexpr auto high=static_cast<uint64_t>(std::numeric_limits<int64_t>::max());
    const auto limit=high+(negative?1U:0U),d=static_cast<uint64_t>(divisor),a=absolute(x),b=absolute(y);
    const auto bq=b/d,br=b%d;
    uint64_t quotient=0,remainder=0;
    const auto add_remainder=[&](uint64_t fragment){
        const bool carry=remainder>=d-fragment;
        remainder=carry?remainder-(d-fragment):remainder+fragment;
        return carry?uint64_t{1}:uint64_t{0};
    };
    auto add_quotient=[&](uint64_t add){
        require(add<=limit-quotient,"CL signed 64-bit ratio overflow");
        quotient+=add;
    };
    for(int i=63;i>=0;--i){
        const auto carry=add_remainder(remainder);
        add_quotient(quotient);add_quotient(carry);
        if((a>>i)&1U){add_quotient(bq);add_quotient(add_remainder(br));}
    }
    if(remainder&&((ceil&&!negative)||(!ceil&&negative)))add_quotient(1);
    if(!negative)return static_cast<int64_t>(quotient);
    if(quotient==high+1)return std::numeric_limits<int64_t>::min();
    return -static_cast<int64_t>(quotient);
}
