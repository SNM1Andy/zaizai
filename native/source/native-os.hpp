#ifdef _WIN32
#include "native-os-win.hpp"
#else
#pragma once
#include <cerrno>
#include <cstddef>
#include <filesystem>
#include <cstdio>
#include <cstdlib>
#include <fcntl.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <sys/random.h>
#include <stdexcept>
#include <string>
#include <unistd.h>

namespace native_os {
struct Descriptor {
    int fd;
    explicit Descriptor(int value):fd(value){}
    Descriptor(const Descriptor&)=delete;
    Descriptor& operator=(const Descriptor&)=delete;
    ~Descriptor(){if(fd>=0)::close(fd);}
};
struct ReadMessages {
    const char* directory;
    const char* open;
    const char* kind;
    const char* read;
    const char* limit;
};
inline std::string read_owned_descriptor(int fd,std::size_t limit,const ReadMessages& words){
    struct stat file{};
    if(fd<0)throw std::runtime_error(words.open);
    if(::fstat(fd,&file)!=0||!S_ISREG(file.st_mode))throw std::runtime_error(words.kind);
    std::string content;char data[16384];
    for(;;){
        const auto n=::read(fd,data,sizeof data);
        if(n<0&&errno==EINTR)continue;
        if(n<0)throw std::runtime_error(words.read);
        if(n==0)break;
        if(static_cast<std::size_t>(n)>limit-content.size())throw std::runtime_error(words.limit);
        content.append(data,static_cast<std::size_t>(n));
    }
    return content;
}
inline std::string read_regular_input(const std::filesystem::path& path,std::size_t cap,const ReadMessages& words){
    Descriptor descriptor(::open(path.c_str(),O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC));
    return read_owned_descriptor(descriptor.fd,cap,words);
}
inline int open_directory(const std::filesystem::path& path){
    return ::open(path.c_str(),O_RDONLY|O_NOFOLLOW|O_DIRECTORY|O_CLOEXEC);
}
inline void confirm_directory(int fd,const std::filesystem::path& path,const char* error){
    Descriptor current(open_directory(path));
    struct stat a{},b{};
    if(current.fd<0||::fstat(fd,&a)!=0||::fstat(current.fd,&b)!=0||
       a.st_dev!=b.st_dev||a.st_ino!=b.st_ino)throw std::runtime_error(error);
}
inline bool leaf(const std::string& name){
    return !name.empty()&&name!="."&&name!=".."&&name.find_first_of("/\\")==std::string::npos&&
           name.find('\0')==std::string::npos;
}
inline std::string read_confined_component(int dir,const std::string& name,std::size_t limit,const ReadMessages& words){
    if(!leaf(name))throw std::runtime_error(words.open);
    Descriptor input(::openat(dir,name.c_str(),O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC));
    return read_owned_descriptor(input.fd,limit,words);
}
inline std::string read_confined_component(const std::filesystem::path& folder,const std::string& name,
                                           std::size_t limit,const ReadMessages& words){
    Descriptor directory(open_directory(folder));
    if(directory.fd<0)throw std::runtime_error(words.directory);
    return read_confined_component(directory.fd,name,limit,words);
}
inline int open_lock(int dir,const std::string& name){
    if(!leaf(name))return -1;
    return ::openat(dir,name.c_str(),O_CREAT|O_RDWR|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC,0600);
}
inline void acquire_lock(int fd,const char* open,const char* kind,const char* busy){
    if(fd<0)throw std::runtime_error(open);
    struct stat file{};
    if(::fstat(fd,&file)!=0||!S_ISREG(file.st_mode))throw std::runtime_error(kind);
    if(::flock(fd,LOCK_EX|LOCK_NB)!=0)throw std::runtime_error(busy);
}
inline void flush_directory(const std::filesystem::path& path,const char* error){
    Descriptor fd(open_directory(path));
    if(fd.fd<0||::fsync(fd.fd)!=0)throw std::runtime_error(error);
}
inline std::string running_executable(std::size_t limit,const ReadMessages& words){
    // The Linux proc link addresses the running image even if its launch path was renamed.
    Descriptor fd(::open("/proc/self/exe",O_RDONLY|O_CLOEXEC));
    return read_owned_descriptor(fd.fd,limit,words);
}
class UncertainCommit : public std::runtime_error {
public:
    using std::runtime_error::runtime_error;
};
struct CommitMessages {
    const char* temporary;
    const char* write;
    const char* flush_file;
    const char* create;
    const char* replace;
    const char* flush_directory;
};
inline void atomic_local_commit(const std::string& target,int dir,const std::string& bytes,
                                const std::string& prefix,bool create_only,const CommitMessages& words){
    if(!leaf(target)||!leaf(prefix))throw std::runtime_error(words.temporary);
    std::string tmp;
    int created=-1;
    for(unsigned attempt=0;attempt<32;++attempt){
        unsigned char nonce[12];
        std::size_t at=0;
        while(at<sizeof nonce){
            const auto n=::getrandom(nonce+at,sizeof nonce-at,0);
            if(n<0&&errno==EINTR)continue;
            if(n<=0)throw std::runtime_error(words.temporary);
            at+=static_cast<std::size_t>(n);
        }
        tmp=prefix;
        for(const auto c:nonce){tmp+="0123456789abcdef"[c>>4];tmp+="0123456789abcdef"[c&15];}
        created=::openat(dir,tmp.c_str(),O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC,0600);
        if(created>=0)break;
        if(errno!=EEXIST)throw std::runtime_error(words.temporary);
    }
    Descriptor file(created);
    if(file.fd<0)throw std::runtime_error(words.temporary);
    struct Remove {int dir;const std::string& name;~Remove(){::unlinkat(dir,name.c_str(),0);}} cleanup{dir,tmp};
    std::size_t at=0;
    while(at<bytes.size()){
        const auto wrote=::write(file.fd,bytes.data()+at,bytes.size()-at);
        if(wrote<0&&errno==EINTR)continue;
        if(wrote<=0)throw std::runtime_error(words.write);
        at+=static_cast<std::size_t>(wrote);
    }
    if(::fsync(file.fd)!=0)throw std::runtime_error(words.flush_file);
    const auto published=create_only?::linkat(dir,tmp.c_str(),dir,target.c_str(),0)
                                    : ::renameat(dir,tmp.c_str(),dir,target.c_str());
    if(published!=0)throw std::runtime_error(create_only?words.create:words.replace);
    if(::fsync(dir)!=0)throw UncertainCommit(words.flush_directory);
}
}

#endif
