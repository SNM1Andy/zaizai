"""Windows integration additions to port_sources.py (run after the base port)."""
from port_sources import SRC, archive, change
import shutil
def edit(name,pairs):
    p=SRC/name
    s=p.read_text(encoding="utf8")
    for a,b in pairs:
        if a not in s:raise ValueError((name,a))
        s=s.replace(a,b,1)
    p.write_bytes(s.encode())
def projection(s):
    s=s.replace("#include <stdexcept>","#include <stdexcept>\n#include <system_error>\n#include \"cuda-order-win.hpp\"")
    return s.replace("    auto* selection=active_selection;","""    auto* selection=active_selection;
    if(!selection&&rows.size()>=packed_min){
        std::vector<std::uint32_t> order;
        if(win_cuda::propose(rows,order)&&verified_projection(rows,order,rows))return;
    }""")
change("native-projection.hpp",projection)
pc="pcgm-src/cl.cpp"
edit(pc,[('JoinWork* work=nullptr) {','JoinWork* work=nullptr,const set<Atom>* excluded=nullptr) {'),
         ('return run(p,inactive,&base,work);','return run(p,inactive,&base,work,excluded);'),
         ('if(!inactive.contains(id)){','if(!inactive.contains(id)&&(!excluded||!excluded->contains(a))){'),
         ('if(out.facts.contains(f))return;','if(out.facts.contains(f)||(excluded&&excluded->contains(f)))return;'),
         ('#include "dialogue.inc"', '#include "proof-integrity.inc"\n#include "dialogue.inc"'),
         ('const bool explain_mode=line.starts_with(":explain ");','''if(line.starts_with(":proof_integrity ")){
                    Parser q{line.substr(17)}; auto a=q.atom();q.end();
                    IntegrityView clean(epoch,state.inactive,table);
                    proof_integrity(table,clean,a);continue;
                }
                const bool explain_mode=line.starts_with(":explain ");''')])
integrity=(SRC.parent/"reference-proof/proof-integrity.inc").read_text(encoding="utf8")
(SRC/"pcgm-src/proof-integrity.inc").write_bytes(integrity.replace("run(p,inactive,&disputed)","run(p,inactive,nullptr,nullptr,&disputed)").encode())
cl="cl-src/cl.cpp"
edit(cl,[('CostLedger* profile=nullptr;', 'CostLedger* profile=nullptr;\n    const set<Atom>* excluded=nullptr;'),
         ('JoinWork* w,CostLedger* costs=nullptr)', 'JoinWork* w,CostLedger* costs=nullptr,const set<Atom>* omit=nullptr)'),
         ('profile(costs),select(', 'profile(costs),excluded(omit),select('),
         ('if(!inactive.contains(id)){','if(!inactive.contains(id)&&(!excluded||!excluded->contains(a))){'),
         ('if(out.facts.contains(f))return;','if(out.facts.contains(f)||(excluded&&excluded->contains(f)))return;'),
         ('const JoinLimit& limits={}){\n    RoundEvaluator session(p,inactive,limits,work);',
          'const JoinLimit& limits={},const set<Atom>* excluded=nullptr){\n    RoundEvaluator session(p,inactive,limits,work,nullptr,excluded);')])
# Reject tainted frozen decisions while preserving the ordinary proof and its artifact digest.
change("cl-src/evidence-frozen.inc",lambda s:s.replace('        *sign=yes?', '''        set<Atom> disputes;
        for(const auto& [atom,_]:table.facts){
            Atom other=atom;
            if(other.pred.starts_with('!'))other.pred.erase(0,1);else other.pred="!"+other.pred;
            if(table.facts.contains(other))disputes.insert(atom);
        }
        if(!disputes.empty() && yes!=no){
            const auto clean=run(program,{},nullptr,{128,12000,2000000,2000000},&disputes);
            const Atom supported=yes?ask:Atom{"!"+ask.pred,ask.args};
            require(clean.facts.contains(supported),"frozen proof depends on disputed premises");
        }
        *sign=yes?'''))

