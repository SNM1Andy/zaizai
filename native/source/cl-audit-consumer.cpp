#include "cl-c-api.h"
#include "native-os.hpp"
#include <algorithm>
#include <charconv>
#include <iostream>
#include <sstream>
#include <string_view>
#include <vector>

namespace {
using std::string;
void expect(bool test,const char* why){if(!test)throw std::runtime_error(why);}
cl_slice_v1 slice(const string& s){return {reinterpret_cast<const unsigned char*>(s.data()),s.size()};}
struct Buffer {
    cl_buffer_v1 value{};
    ~Buffer(){cl_free_v1(&value);}
    string copy()const{return value.size?string(reinterpret_cast<const char*>(value.bytes),value.size):string{};}
};
struct Reader {
    cl_evidence_audit_v1* p=nullptr;
    ~Reader(){cl_evidence_audit_close_v1(&p);}
};
constexpr native_os::ReadMessages read_words{
    "cannot open input directory","cannot open input file","invalid input file type","cannot read input","input is too large"};
bool digest(const string& s){
    return s.size()==64&&std::all_of(s.begin(),s.end(),[](char c){return(c>='0'&&c<='9')||(c>='a'&&c<='f');});
}
bool identifier(const string& s){
    return !s.empty()&&s.size()<=48&&s.front()>='a'&&s.front()<='z'&&
        std::all_of(s.begin(),s.end(),[](char c){return(c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='_';});
}
unsigned exact_number(std::string_view s){
    unsigned n=0;
    auto r=std::from_chars(s.data(),s.data()+s.size(),n);
    expect(r.ec==std::errc{}&&r.ptr==s.data()+s.size()&&std::to_string(n)==s,"noncanonical cursor");
    return n;
}
struct Checkpoint {
    unsigned cursor=0;
    string prefix="origin";
    std::vector<string> ledger;
};
string encode(const Checkpoint& t){
    string raw="CL-AUDIT-CONSUMER-1\n"+std::to_string(t.cursor)+"\n"+t.prefix+'\n';
    for(const auto& id:t.ledger)raw+=id+'\n';
    return raw;
}
Checkpoint decode(const string& raw){
    std::istringstream in(raw);
    Checkpoint t;string line;
    expect(bool(std::getline(in,line))&&line=="CL-AUDIT-CONSUMER-1","unrecognized audit checkpoint");
    expect(bool(std::getline(in,line)),"missing audit cursor");t.cursor=exact_number(line);
    expect(bool(std::getline(in,t.prefix))&&digest(t.prefix),"missing audit prefix");
    while(std::getline(in,line)){
        expect(identifier(line)&&t.ledger.size()<128&&std::find(t.ledger.begin(),t.ledger.end(),line)==t.ledger.end(),
                "invalid acknowledged local receipt");
        t.ledger.push_back(line);
    }
    expect(encode(t)==raw,"noncanonical audit checkpoint");
    return t;
}
// Parse only fixed fields in this SDK ABI's canonical JSON, not arbitrary external JSON.
// Transaction identifiers are restricted by the audit engine and never include escapes or punctuation.
void consume(Checkpoint& t,const string& response){
    expect(response.find("\"ok\":true")!=string::npos,response.c_str());
    const string ep="\"result\":{\"events\":[";
    const string nc="],\"next_cursor\":";
    const string np=",\"next_prefix_sha256\":\"";
    auto at=response.find(ep),end=response.find(nc),pre=response.find(np);
    expect(at!=string::npos&&end!=string::npos&&pre!=string::npos&&at<end&&end<pre,"unexpected audit response");
    auto ns=end+nc.size(),ne=response.find(',',ns);
    expect(ne!=string::npos&&ne<pre,"missing cursor in audit response");
    const auto next=exact_number(std::string_view(response).substr(ns,ne-ns));
    const auto prefix=response.substr(pre+np.size(),64);
    expect(next>=t.cursor&&digest(prefix),"out-of-order audit receipt");
    const string key="\"transaction\":\"";
    for(auto i=response.find(key,at+ep.size());i!=string::npos&&i<end;i=response.find(key,i+key.size())){
        const auto begin=i+key.size(),finish=response.find('"',begin);
        expect(finish!=string::npos&&finish<end,"bad transaction ID");
        const auto id=response.substr(begin,finish-begin);
        expect(identifier(id)&&t.ledger.size()<128&&std::find(t.ledger.begin(),t.ledger.end(),id)==t.ledger.end(),
               "duplicate or malformed transaction in resumed audit");
        t.ledger.push_back(id);
    }
    t.cursor=next;t.prefix=prefix;
}
}
int main(int argc,char** argv){
    try{
        expect(argc==7||argc==8,"usage: cl-audit-consumer package pin goals journal checkpoint page-size [hold]");
        if(argc==8)expect(string(argv[7])=="hold","unknown option");
        const string pkg=native_os::read_regular_input(argv[1],2*1024*1024,read_words);
        const string pin=argv[2],goals=native_os::read_regular_input(argv[3],32768,read_words),journal=argv[4];
        const auto limit=exact_number(argv[6]);expect(limit>0&&limit<=32,"invalid page size");
        const std::filesystem::path chosen=argv[5];
        const auto home=std::filesystem::canonical(std::filesystem::absolute(chosen).parent_path());
        const auto leaf=chosen.filename().string();
        const std::filesystem::path journal_path=journal;
        const auto journal_home=std::filesystem::canonical(std::filesystem::absolute(journal_path).parent_path());
        const auto journal_leaf=journal_path.filename().string();
        const string lease_name=journal_leaf+".lock", checkpoint_lock=leaf+".consumer-lock";
        expect(home!=journal_home||(leaf!=journal_leaf&&leaf!=lease_name&&
                checkpoint_lock!=journal_leaf&&checkpoint_lock!=lease_name),
                "consumer checkpoint must not alias a writer journal or lease");
        std::error_code alias_error;
        const bool alias=std::filesystem::equivalent(home/leaf,journal_home/journal_leaf,alias_error);
        expect(!alias,"consumer checkpoint aliases the writer journal");
        native_os::Descriptor dir(native_os::open_directory(home));
        expect(dir.fd>=0&&native_os::leaf(leaf),"invalid checkpoint path");
        native_os::Descriptor lock(native_os::open_lock(dir.fd,leaf+".consumer-lock"));
        native_os::acquire_lock(lock.fd,"cannot open checkpoint lock","invalid checkpoint lock","checkpoint already has a reader");
        Checkpoint t;bool create=false;
        {
            native_os::Descriptor previous(::openat(dir.fd,leaf.c_str(),O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC));
            if(previous.fd>=0)t=decode(native_os::read_owned_descriptor(previous.fd,16384,read_words));
            else{expect(errno==ENOENT,"cannot read checkpoint");create=true;}
        }
        Reader reader;Buffer error,reply;
        auto code=cl_evidence_audit_open_v1(slice(pkg),slice(pin),slice(goals),slice(journal),&reader.p,&error.value);
        if(code!=CL_OK_V1)throw std::runtime_error(error.copy());
        const string frame="app resume latest "+std::to_string(t.cursor)+" "+t.prefix+" "+std::to_string(limit);
        code=cl_evidence_audit_command_v1(reader.p,slice(frame),&reply.value,&error.value);
        if(code!=CL_OK_V1)throw std::runtime_error(error.copy());
        const auto result=reply.copy();consume(t,result);
        native_os::confirm_directory(dir.fd,home,"checkpoint directory moved");
        native_os::atomic_local_commit(leaf,dir.fd,encode(t),".cl-consumer-pending-",create,{
            "cannot create checkpoint temp","cannot write checkpoint","cannot flush checkpoint temp",
            "checkpoint appeared","cannot replace checkpoint","checkpoint outcome uncertain; reopen"});
        if(argc==8){string gate;std::getline(std::cin,gate);}
        std::cout<<result;
        return 0;
    }catch(const std::exception& e){std::cerr<<e.what()<<'\n';return 2;}
}
