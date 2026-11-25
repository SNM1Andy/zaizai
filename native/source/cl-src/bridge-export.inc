#include <cctype>
string safe_origin(const string& s){
    constexpr char hex[]="0123456789abcdef";
    string out;
    const auto last=s.rfind(':'), penultimate=last==string::npos?string::npos:s.rfind(':',last-1);
    require(last!=string::npos&&penultimate!=string::npos,"invalid CSV origin");
    for(size_t i=0;i<s.size();++i){
        const auto c=static_cast<unsigned char>(s[i]);
        if((std::isalnum(c)&&c<128)||c=='.'||c=='-'||c=='_'||i==last||i==penultimate)out+=static_cast<char>(c);
        else {out+='%';out+=hex[c>>4];out+=hex[c&15];}
    }
    return out;
}
void export_packet(const Program& p,const CsvFacts& csv,const string& id,const string& seq,const string& digest){
    require(strict_csv_symbol(id)==id&&id.size()<=16,"source identifier limit");
    const auto n=integer(seq);
    require(n>=1&&n<=1000000&&to_string(n)==seq,"source sequence must be canonical and between 1 and 1000000");
    map<string,string> routes;
    map<Atom,string> unique;
    for(const auto& [obs,loc]:csv.origins){
        auto atom=p.observations.at(obs);
        const bool neg=atom.pred.starts_with("!");
        const auto original=base_name(atom);
        const auto split=original.find("__");
        const auto name=split==string::npos?original:original.substr(split+2);
        auto [it,inserted]=routes.emplace(name,original);
        require(inserted||it->second==original,"compiled predicate names collide on packet boundary");
        atom.pred=(neg?"!":"")+name;
        const auto origin=safe_origin(loc)+"@"+digest;
        require(origin.size()<=240,"packet origin too long");
        unique.try_emplace(atom,origin);
    }
    require(!unique.empty()&&unique.size()<=64,"packet requires 1..64 distinct observations");
    cout<<"source "<<id<<" "<<seq<<'\n';
    for(const auto& [atom,origin]:unique)cout<<"# trace "<<origin<<'\n'<<show(atom)<<'\n';
}
