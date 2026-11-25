Kind fold_result_kind(const Program& p,const Atom& a){
    require(a.args.size()==3&&!variable(a.args[0])&&literal_type(a.args[0])=="sym",
            "closed fold needs a literal observation relation");
    const auto at=p.signatures.find(a.args[0]);
    require(at!=p.signatures.end()&&at->second.size()==3&&at->second[0]=="sym"&&at->second[1]=="sym"
            &&at->second[2].starts_with("qty:"),"closed fold source requires (sym,sym,qty(unit))");
    return a.pred=="qty_fold_count"?Kind("i64"):at->second[2];
}
void check_fold_types(const Program& p,const Atom& a,map<string,Kind>& vars){
    const auto unit=fold_result_kind(p,a);
    const auto arg=[&](const string& term,const Kind& kind){
        if(variable(term)){
            const auto [it,fresh]=vars.try_emplace(term,kind);
            require(fresh||it->second==kind,"closed fold operand type mismatch");
        }else require(literal_type(term)==kind,"closed fold operand type mismatch");
    };
    arg(a.args[1],"sym");arg(a.args[2],unit);
}
void validate_closed_folds(const Program& p){
    set<string> produced;
    for(const auto& r:p.rules)produced.insert(base_name(r.head));
    for(const auto& r:p.rules)
        for(const auto& premise:r.body)if(sealed_calculation(premise.pred)){
            if(fold_calculation(premise.pred))(void)fold_result_kind(p,premise);
            require(!produced.contains(premise.args[0]),unit_conversion(premise.pred)?
                "conversion rate source must contain observations only":"closed fold source must contain observations only");
        }
}
// Count positive and negative magnitudes separately. Exact cancellation is possible
// even when an arbitrary summation order would temporarily exceed signed 64-bit range.
struct FoldMagnitude {uint64_t high=0,low=0;auto operator<=>(const FoldMagnitude&)const=default;};
void fold_add(FoldMagnitude& to,uint64_t value){
    const auto before=to.low;to.low+=value;
    if(to.low<before)++to.high;
}
int64_t fold_difference(FoldMagnitude positive,FoldMagnitude negative){
    const bool minus=positive<negative;
    if(minus)std::swap(positive,negative);
    const auto high=positive.high-negative.high-(positive.low<negative.low?1U:0U);
    const auto low=positive.low-negative.low;
    const auto max=static_cast<uint64_t>(std::numeric_limits<int64_t>::max());
    if(high||low>max+(minus?1U:0U))throw EvaluationLimit("CL closed fold signed 64-bit sum overflow");
    if(!minus)return static_cast<int64_t>(low);
    if(low==max+1)return std::numeric_limits<int64_t>::min();
    return -static_cast<int64_t>(low);
}
template<class Consume>
bool lookup_closed_fold(const Program& pg,JoinIndex& index,Atom& check,map<string,string>& env,
                        vector<const Atom*>& witness,const Consume& consume){
    if(variable(check.args[1]))check.args[1]=env.at(check.args[1]);
    const auto& rel=check.args[0];
    const auto& group=check.args[1];
    const auto& plus=index.lookup({rel,{group,"$item","$amount"}},{});
    const auto& minus=index.lookup({"!"+rel,{group,"$item","$amount"}},{});
    set<pair<string,string>> challenged;
    for(const auto* atom:minus){
        consume();challenged.emplace(atom->args[1],atom->args[2]);
    }
    map<string,string> items;
    FoldMagnitude positive,negative;
    optional<int64_t> extreme;
    for(const auto* atom:plus){
        consume();
        const auto& item=atom->args[1];
        const auto& amount=atom->args[2];
        require(!challenged.contains({item,amount}),"CL closed fold contains contradicted evidence");
        const auto [found,unique]=items.emplace(item,amount);
        require(unique||found->second==amount,"CL closed fold has multiple amounts for one item");
        if(!unique)continue;
        if(items.size()>64)throw EvaluationLimit("CL closed fold group exceeds 64 items");
        if(check.pred!="qty_fold_count"){
            const auto number=integer(amount.substr(0,amount.find('@')));
            if(check.pred=="qty_fold_sum"){
                if(number<0)fold_add(negative,uint64_t{0}-static_cast<uint64_t>(number));
                else fold_add(positive,static_cast<uint64_t>(number));
            }else if(!extreme||(check.pred=="qty_fold_min"?number<*extreme:number>*extreme))extreme=number;
        }
        witness.push_back(atom);
    }
    string result;
    if(check.pred=="qty_fold_count")result=to_string(items.size());
    else{
        const auto unit=fold_result_kind(pg,check).substr(4);
        if(check.pred=="qty_fold_sum")result=to_string(fold_difference(positive,negative))+"@"+unit;
        else {
            if(!extreme)return false;
            result=to_string(*extreme)+"@"+unit;
        }
    }
    auto& output=check.args[2];
    if(!variable(output))return output==result;
    const auto [slot,fresh]=env.try_emplace(output,result);
    output=slot->second;
    return fresh||slot->second==result;
}
