#include <iomanip>
#include "field.hpp"
#include "primordial.hpp"
#include "field_assets.inc"

struct GeometricRuntime {
    static constexpr const char* init_event="field_v11_glyph64_s8";
    static constexpr std::array<const char*,3> actions{"inspect","work","wait"};
    static constexpr std::array<const char*,3> contexts{"inflow","quiet","outflow"};
    instinct::Solver solver{64,8,false,"glyph",geometry_glyph};
    instinct::Field field=solver.birth(73);
    int ticks=0, budget=7, previous=2, completed=0;
    static int index(const std::array<const char*,3>& choices,const string& value){
        for(int i=0;i<3;++i) if(value==choices[i]) return i;
        throw runtime_error("invalid geometry context or action");
    }
    static double input(int ctx){return (1-ctx)*.72;}
    void apply(int action){
        budget=min(10,budget-(action==0?1:action==1?2:0)+(action==2?3:0));
        require(budget>=0,"geometry action exceeds budget");
        completed+=action==1;
        previous=action;
        solver.advance(field,std::array<double,3>{.20,-.22,.08}[action],instinct::tick_dt/2);
        ++ticks;
        solver.observe(field);
    }
    void begin(int ctx){solver.advance(field,input(ctx),instinct::tick_dt/2);}
    void replay(const vector<string>& events){
        bool started=false;
        for(const auto& e:events){
            if(e==init_event){require(!started,"duplicate geometry initialization"); started=true;}
            if(!e.starts_with("field_tick "))continue;
            require(started,"geometry tick before initialization");
            istringstream in(e.substr(11));
            string ctx,action,extra;
            require(bool(in>>ctx>>action)&&!(in>>extra),"invalid geometry event");
            begin(index(contexts,ctx));
            apply(index(actions,action));
        }
    }
    template<class A> static string nums(const A& a){
        ostringstream o; o<<setprecision(17)<<'[';
        bool first=true;
        for(auto x:a){if(!first)o<<',';first=false;o<<x;}
        o<<']';return o.str();
    }
    string status() const {
        return "field_tick="+to_string(ticks)+" budget="+to_string(budget)+
          " completed="+to_string(completed)+" features="+nums(solver.observe(field));
    }
    std::pair<int,string> select(const Program& epoch,const set<string>& inactive,int ctx){
        begin(ctx);
        const auto f=solver.observe(field);
        instinct::Features z;
        for(size_t j=0;j<z.size();++j)z[j]=clamp((f[j]-field_mean[j])/field_scale[j],-3.,3.);
        const std::array<double,3> b{
            tanh(.48*z[2]-.21*z[1]+.28*z[5]),tanh(.32*z[1]-.28*z[5]+.15*z[4]),
            tanh(-.48*z[2]+.22*z[5]-.15*z[0])};
        auto program=epoch;
        for(const auto& [id,_]:program.observations)
            require(!id.starts_with("geom_sensor_"),"geometry sensor ID is reserved");
        auto add=[&](const string& id,const string& pred,const string& v){
            program.observations.emplace("geom_sensor_"+id,Atom{pred,{v}});
        };
        if(budget>=1)add("inspect","geom_afford","inspect");
        if(budget>=2)add("work","geom_afford","work");
        if(ctx==2)add("block","geom_blocked","work");
        if(ctx==0)add("visible","geom_visible","signal");
        if(ctx==1)add("queue","geom_ready","task");
        const auto t=run(program,inactive);
        const auto has=[&](const string& pred,const string& a){return t.facts.contains({pred,{a}});};
        int pick=-1, base_pick=-1;
        double best=-1e20,best_base=-1e20;
        ostringstream out;
        out<<setprecision(17)<<"geometry context="<<contexts[ctx]<<" field_bias="<<nums(b);
        for(int i=0;i<3;++i){
            const auto a=actions[i];
            const bool yes=has("geom_permitted",a),no=has("!geom_permitted",a);
            const bool budget_ok=i==2 || budget>=(i==0?1:2);
            const bool eligible=yes&&!no&&budget_ok;
            const double base=.5+.09*has("geom_priority",a)+.045*(i==1)+.07*(budget<4&&i==2);
            const double bias=(i==0?.55*b[0]:0)+(i==previous?.45*b[1]:.45*b[2]);
            const double score=base+.20*bias;
            if(eligible&&base>best_base){best_base=base;base_pick=i;}
            if(eligible&&score>best){best=score;pick=i;}
            out<<" "<<a<<":truth="<<(yes?(no?"CONFLICT":"POSITIVE"):(no?"NEGATIVE":"UNKNOWN"))
               <<",eligible="<<eligible<<",base="<<base<<",score="<<score;
        }
        require(pick>=0,"no eligible geometry action");
        out<<" selected="<<actions[pick]<<" baseline="<<actions[base_pick];
        return {pick,out.str()};
    }
};
