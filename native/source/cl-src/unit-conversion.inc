void check_conversion_types(const Program& p,const Atom& a,map<string,Kind>& vars){
    require(a.args.size()==4&&!variable(a.args[0])&&literal_type(a.args[0])=="sym"&&
            !variable(a.args[2])&&literal_type(a.args[2])=="sym",
            "conversion needs a literal observation relation and a literal target unit");
    const auto quote=p.signatures.find(a.args[0]);
    require(quote!=p.signatures.end()&&quote->second==vector<Kind>{"sym","sym","i64","i64"},
            "conversion source requires (sym,sym,i64,i64)");
    const auto& quantity=a.args[1];
    const auto got=variable(quantity)?(vars.contains(quantity)?vars.at(quantity):Kind{}):literal_type(quantity);
    require(got.starts_with("qty:"),"conversion input requires a bound typed quantity");
    require(got.substr(4)!=a.args[2],"conversion requires two distinct units");
    const Kind target="qty:"+a.args[2];
    const auto& out=a.args[3];
    if(variable(out)){
        const auto [prior,added]=vars.try_emplace(out,target);
        require(added||prior->second==target,"conversion result unit differs from explicit target");
    }else require(literal_type(out)==target,"conversion result unit differs from explicit target");
}
template<class Consume>
bool lookup_unit_conversion(JoinIndex& index,Atom& calc,map<string,string>& env,
                            vector<const Atom*>& witness,const Consume& consume){
    if(variable(calc.args[1]))calc.args[1]=env.at(calc.args[1]);
    const auto& tariff=calc.args[0];
    const auto& quantity=calc.args[1];
    const auto at=quantity.find('@');
    require(at!=string::npos,"conversion input lacks a unit");
    const auto source=quantity.substr(at+1),target=calc.args[2];
    const auto& offered=index.lookup({tariff,{source,target,"$numerator","$denominator"}},{});
    const auto& opposed=index.lookup({"!"+tariff,{source,target,"$numerator","$denominator"}},{});
    const Atom* winner=nullptr;
    for(const auto* rate:offered){
        consume();
        require(!winner,"conversion pair has multiple asserted rates");
        winner=rate;
    }
    if(!winner)return false;
    for(const auto* rate:opposed){
        consume();
        require(rate->args!=winner->args,"conversion rate is contradicted");
    }
    const auto n=integer(winner->args[2]),d=integer(winner->args[3]);
    require(n>0&&d>0,"conversion rate must be strictly positive");
    const auto answer=to_string(checked_proportional(integer(quantity.substr(0,at)),n,d,calc.pred.ends_with("_ceil")))+"@"+target;
    auto& slot=calc.args[3];
    bool success;
    if(variable(slot)){
        const auto [found,inserted]=env.try_emplace(slot,answer);
        slot=found->second;
        success=inserted||slot==answer;
    }else success=slot==answer;
    if(success)witness.push_back(winner);
    return success;
}
