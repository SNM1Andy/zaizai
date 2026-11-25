#pragma once
#include "native-os.hpp"

namespace native_os {
class AnchoredAssets {
    int parent_;
    std::string leaf_;
    Descriptor folder_;
    static int open_folder(int parent,const std::string& child,bool create,bool optional){
        if(!leaf(child))throw std::runtime_error("invalid durable asset folder name");
        const auto path=native_os::child(parent,child);
        if(create)std::filesystem::create_directory(path);
        const int fd=open_directory(path);
        if(fd<0&&!(optional&&!create&&!std::filesystem::exists(path)))throw std::runtime_error("asset directory unavailable");
        return fd;
    }
public:
    AnchoredAssets(int parent,std::string child,bool create=false,bool optional=false)
       :parent_(parent),leaf_(std::move(child)),folder_(open_folder(parent_,leaf_,create,optional)){}
    bool present() const{return folder_.fd>=0;}
    void confirm() const {
        confirm_directory(folder_.fd,native_os::child(parent_,leaf_),"asset directory changed");
    }
    int confirmed_descriptor()const{confirm();return folder_.fd;}
    bool contains(const std::string& name)const{
        if(!leaf(name))throw std::runtime_error("invalid durable asset member name");
        confirm();
        return std::filesystem::exists(child(folder_.fd,name));
    }
    std::string read(const std::string& name,std::size_t limit,const ReadMessages& messages)const{
        confirm();
        auto bytes=read_confined_component(folder_.fd,name,limit,messages);
        confirm();return bytes;
    }
    void put_exact(const std::string& name,const std::string& bytes,std::size_t cap,const ReadMessages& words)const{
        if(bytes.size()>cap)throw std::runtime_error(words.limit);
        if(!contains(name))
            atomic_local_commit(name,folder_.fd,bytes,".pcgm-asset-",true,{
                "cannot create pending durable asset","cannot write pending durable asset","cannot flush pending durable asset",
                "durable asset destination already exists; reopen and reconcile","cannot replace immutable durable asset",
                "durable asset visibility uncertain; reopen and reconcile"});
        if(read(name,cap,words)!=bytes)throw std::runtime_error("immutable durable asset differs from expected bytes");
        // Even a previously existing asset may be the result of an uncertain publication.

        confirm();
    }
};
}
