#include "proportional.inc"
bool fold_calculation(const string& op){
#ifdef PCGM_NO_CLOSED_FOLDS
    (void)op;return false;
#else
    return op=="qty_fold_sum"||op=="qty_fold_min"||op=="qty_fold_max"||op=="qty_fold_count";
#endif
}
bool extended_fold_calculation(const string& op){return fold_calculation(op)&&op!="qty_fold_sum";}
bool unit_conversion(const string& op){return op=="qty_convert_floor"||op=="qty_convert_ceil";}
bool sealed_calculation(const string& op){return fold_calculation(op)||unit_conversion(op);}
bool quantity_calculation(const string& op){return op=="qty_add"||op=="qty_sub"||proportional_calculation(op);}
bool calculation(const string& op){return op=="int_add"||op=="int_sub"||quantity_calculation(op)||sealed_calculation(op);}
bool comparison(const string& op){return binary_filter(op)||calculation(op);}
void check_builtin_binding(const Atom& a,set<string>& bound){
    const bool bind=calculation(a.pred);
    const size_t inputs=(proportional_calculation(a.pred)||unit_conversion(a.pred))?3:2;
    require(a.args.size()==inputs+(bind?1:0),bind?"invalid arithmetic arity":"comparison requires two arguments");
    for(size_t i=0;i<inputs;++i)
        require(!variable(a.args[i])||bound.contains(a.args[i]),"builtin input must be bound by an earlier premise");
    if(bind&&variable(a.args.back()))bound.insert(a.args.back());
}
void check_calculation_type(const Atom& a,map<string,Kind>& vars){
    const auto ratio=proportional_calculation(a.pred);
    require(a.args.size()==(ratio?4:3),"invalid arithmetic arity");
    auto type=[&](const string& t){
        if(!variable(t))return literal_type(t);
        const auto i=vars.find(t);require(i!=vars.end(),"untyped arithmetic operand");
        return i->second;
    };
    const auto u=type(a.args[0]),v=type(a.args[1]);
    if(ratio)require(u.starts_with("qty:")&&v=="i64"&&type(a.args[2])=="i64",
                     "ratio requires a quantity and two integer factors");
    else require(u==v&&(quantity_calculation(a.pred)?u.starts_with("qty:"):u=="i64"),
                 "arithmetic operands must be same-unit quantities or matching integers");
    const auto& out=a.args.back();
    if(variable(out)){
        const auto [it,fresh]=vars.emplace(out,u);
        require(fresh||it->second==u,"arithmetic result type mismatch");
    }else require(literal_type(out)==u,"arithmetic result type mismatch");
}
int64_t checked_arithmetic(int64_t x,int64_t y,bool subtract){
    constexpr auto hi=std::numeric_limits<int64_t>::max(),lo=std::numeric_limits<int64_t>::min();
    if(subtract){
        require(!((y>0&&x<lo+y)||(y<0&&x>hi+y)),"CL signed 64-bit subtraction overflow");
        return x-y;
    }
    require(!((y>0&&x>hi-y)||(y<0&&x<lo-y)),"CL signed 64-bit addition overflow");
    return x+y;
}
bool eval_builtin(Atom& check,map<string,string>& env){
    const auto binding=calculation(check.pred);
    const auto ratio=proportional_calculation(check.pred);
    for(size_t i=0;i<(ratio?3U:2U);++i)if(variable(check.args[i]))check.args[i]=env.at(check.args[i]);
    if(cl_text_symbol::comparison_name(check.pred)){
        const bool same=check.args[0]==check.args[1];
        return check.pred=="sym_eq"?same:!same;
    }
    auto magnitude=[](const string& s){return integer(s.substr(0,s.find('@')));};
    const auto x=magnitude(check.args[0]),y=magnitude(check.args[1]);
    if(!binding)return check.pred.ends_with("_lt")?x<y:x<=y;
    auto result=to_string(ratio?checked_proportional(x,y,magnitude(check.args[2]),check.pred.ends_with("_ceil"))
                               :checked_arithmetic(x,y,check.pred.ends_with("_sub")));
    if(quantity_calculation(check.pred))result+=check.args[0].substr(check.args[0].find('@'));
    auto& slot=check.args.back();
    if(variable(slot)){
        const auto [it,fresh]=env.emplace(slot,result);
        if(!fresh&&result!=it->second){slot=it->second;return false;}
        slot=result;return true;
    }
    return slot==result;
}
void validate_calculation_cycles(const vector<Rule>& rules){
    auto relation=[](const string& name){return name.starts_with('!')?name.substr(1):name;};
    map<string,set<string>> depends;
    for(const auto& rule:rules)
        for(const auto& a:rule.body)if(!comparison(a.pred))
            depends[relation(rule.head.pred)].insert(relation(a.pred));
    for(const auto& rule:rules){
        if(std::ranges::none_of(rule.body,[](const Atom& a){return calculation(a.pred);}))continue;
        const auto head=relation(rule.head.pred);
        set<string> seen{head};
        vector<string> todo{head};
        for(size_t i=0;i<todo.size();++i)
            if(const auto edges=depends.find(todo[i]);edges!=depends.end())
                for(const auto& node:edges->second){
                    require(node!=head,"numeric calculation in recursive relation "+head);
                    if(seen.insert(node).second)todo.push_back(node);
                }
    }
}
