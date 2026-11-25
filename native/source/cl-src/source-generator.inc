struct SyntaxAtom { optional<pair<string,string>> name; map<unsigned,string> args; };
using SyntaxTree=map<string,map<unsigned,SyntaxAtom>>;
struct SyntaxScope {set<string> inputs,outputs;};
SyntaxScope read_syntax_scope(const string& input){
    istringstream in(input);string line;
    require(getline(in,line)&&line=="CL-AST-SCOPE-1","expected CL-AST-SCOPE-1");
    SyntaxScope scope;
    while(getline(in,line)){
        Parser p{line};const auto mode=p.name(),pred=p.name();p.end();
        require(mode=="read"||mode=="write","scope must list read or write");
        auto& l=mode=="read"?scope.inputs:scope.outputs;
        require(l.size()<128&&l.insert(pred).second,"duplicate or oversized source scope");
        require(mode=="read"||!comparison(pred),"builtin cannot be a writable relation");
    }
    require(!scope.outputs.empty(),"source scope needs a writable relation");
    return scope;
}
bool generation_evidence(const Table& t,const Atom& root){
    const auto& proof=t.facts.at(root);
    if(!proof.origin.starts_with("r")||proof.parents.empty())return false;
    vector<Atom> q{root};set<Atom> seen;
    for(size_t i=0;i<q.size();++i){
        const auto f=q[i];if(!seen.insert(f).second)continue;
        if(seen.size()>512||q.size()>4096)return false;
        auto contrary=f;contrary.pred=f.pred.starts_with('!')?f.pred.substr(1):"!"+f.pred;
        if(t.facts.contains(contrary))return false;
        const auto& p=t.facts.at(f);
        q.insert(q.end(),p.parents.begin(),p.parents.end());
    }
    return true;
}
pair<string,Program> generate_source(const string& meta,const string& base,const string& expected,const string& scope_text){
    require(sha256(base)==expected,"source digest mismatch");
    const auto scope=read_syntax_scope(scope_text);
    const auto g=compile(meta);
    const auto b=compile(base);
    const map<string,vector<Kind>> signatures{
        {"ast_literal",{"sym","i64","sym","sym"}},
        {"ast_var",{"sym","i64","i64","sym"}},
        {"ast_symbol",{"sym","i64","i64","sym"}},
        {"ast_int",{"sym","i64","i64","i64"}},
        {"ast_amount",{"sym","i64","i64","i64"}},
        {"ast_unit",{"sym","i64","i64","sym"}},
    };
    for(const auto& [name,type]:signatures)
        if(g.signatures.contains(name))
            require(g.signatures.at(name)==type,"metaprogram signature mismatch: "+name);
    for(const auto& name:scope.outputs)require(b.signatures.contains(name),"writable predicate needs a signature: "+name);
    for(const auto& name:scope.inputs)
        require(b.signatures.contains(name)||comparison(name),"readable predicate needs a signature: "+name);
    const auto facts=run(g);
    SyntaxTree tree;
    map<tuple<string,unsigned,unsigned>,string> units;
    set<tuple<string,unsigned,unsigned>> amounts;
    string evidence;
    for(const auto& [atom,p]:facts.facts){
        const auto name=base_name(atom);
        if(!signatures.contains(name))continue;
        require(!atom.pred.starts_with('!'),"negative syntax fact "+show(atom));
        require(g.signatures.contains(name)&&atom.args.size()==4,"syntax predicate needs its explicit signature");
        require(generation_evidence(facts,atom),"syntax must be derived from non-conflicting evidence: "+show(atom));
        const auto& id=atom.args[0];
        const auto raw=integer(atom.args[1]);
        require(raw>=0&&raw<=8,"literal position must be 0 through 8");
        const auto pos=static_cast<unsigned>(raw);
        auto& lit=tree[id][pos];
        require(tree.size()<=16,"generated rule count limit");
        if(name=="ast_literal"){
            require(!lit.name,"multiple definitions of a literal");
            const auto& sign=atom.args[3];
            require(sign=="pos"||sign=="neg","invalid literal sign");
            lit.name=make_pair(atom.args[2],sign);
        }else{
            const auto ix=integer(atom.args[2]);
            require(ix>=1&&ix<=4,"argument index must be 1 through 4");
            const auto index=static_cast<unsigned>(ix);
            auto key=make_tuple(id,pos,index);
            if(name=="ast_unit"){
                require(units.emplace(key,atom.args[3]).second,"ambiguous quantity unit");
            }else{
                const auto val=name=="ast_var"?"$"+atom.args[3]:atom.args[3];
                require(lit.args.emplace(index,val).second,"ambiguous argument");
                if(name=="ast_amount")amounts.insert(key);
            }
        }
        evidence+="# generated from "+show(atom)+" <= "+describe(p)+"\n";
        require(evidence.size()<=96*1024,"source generation evidence exceeded its bound");
    }
    require(!tree.empty()&&units.size()==amounts.size(),"no derived syntax or mismatched quantity metadata");
    for(const auto& [key,unit]:units){
        require(amounts.contains(key),"quantity unit has no magnitude");
        const auto& [id,pos,index]=key;
        tree.at(id).at(pos).args.at(index)+="@"+unit;
    }
    const auto meta_hash=sha256(meta), scope_hash=sha256(scope_text);
    auto patch=base+"\n# CL-GENERATED-1 base="+expected+" meta="+meta_hash+" scope="+scope_hash+"\n"+evidence;
    set<string> generated;
    vector<string> labels;
    for(const auto& [id,lits]:tree){
        require(lits.size()>=2,"generated rule lacks a head or body: "+id);
        string rule; unsigned step=0;
        for(const auto& [pos,lit]:lits){
            require(pos==step++&&lit.name&&!lit.args.empty(),"incomplete or unordered syntax: "+id);
            const auto [name,sign]=*lit.name;
            require((pos==0?scope.outputs:scope.inputs).contains(name),"predicate outside source scope: "+name);
            Atom a{(sign=="neg"?"!":"")+name,{}};
            unsigned index=1;
            for(const auto& [i,value]:lit.args){
                require(i==index++,"gap in argument indices");
                a.args.push_back(value);
            }
            if(pos==1)rule+=" <- ";else if(pos>1)rule+=" & ";
            rule+=show(a);
        }
        rule+=".";
        require(generated.insert(rule).second,"duplicate generated rule");
        patch+=rule+"\n";
        labels.push_back("generated:"+meta_hash+":"+scope_hash+":"+id);
    }
    auto compiled=compile(patch);
    require(compiled.rules.size()==b.rules.size()+generated.size(),"generated rule count mismatch");
    set<Rule> distinct;
    for(size_t i=0;i<compiled.rules.size();++i)
        if(!distinct.insert(compiled.rules[i]).second)
            require(i<b.rules.size(),"generated rule already exists");
    for(size_t i=0;i<b.rules.size();++i)compiled.rule_labels.push_back("base:"+expected+":"+to_string(b.rule_lines[i]));
    compiled.rule_labels.insert(compiled.rule_labels.end(),labels.begin(),labels.end());
    run(compiled);
    return {move(patch),move(compiled)};
}
