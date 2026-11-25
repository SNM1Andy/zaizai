#pragma once
#define NOMINMAX
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <bcrypt.h>
#include <io.h>
#include <fcntl.h>
#include <filesystem>
#include <stdexcept>
#include <string>
#include <vector>
#include <algorithm>
#include <climits>
#pragma comment(lib,"bcrypt.lib")
namespace native_os {
namespace fs=std::filesystem;
struct Descriptor {
    int fd;
    explicit Descriptor(int value):fd(value){}
    Descriptor(const Descriptor&)=delete;
    ~Descriptor(){if(fd>=0)_close(fd);}
};
inline HANDLE handle(int fd){return reinterpret_cast<HANDLE>(_get_osfhandle(fd));}
inline int descriptor(HANDLE h){
    if(h==INVALID_HANDLE_VALUE)return -1;
    auto fd=_open_osfhandle(reinterpret_cast<intptr_t>(h),_O_BINARY|_O_NOINHERIT);
    if(fd<0)CloseHandle(h);
    return fd;
}
inline int open_directory(const fs::path& p){
    return descriptor(CreateFileW(p.c_str(),FILE_READ_ATTRIBUTES,FILE_SHARE_READ|FILE_SHARE_WRITE,
        nullptr,OPEN_EXISTING,FILE_FLAG_BACKUP_SEMANTICS,nullptr));
}
inline fs::path directory_path(int dir){
    if(dir<0)throw std::runtime_error("directory unavailable");
    std::vector<wchar_t> buffer(32768);
    auto n=GetFinalPathNameByHandleW(handle(dir),buffer.data(),static_cast<DWORD>(buffer.size()),0);
    if(!n||n>=buffer.size())throw std::runtime_error("cannot resolve directory handle");
    return std::wstring(buffer.data(),n);
}
inline BY_HANDLE_FILE_INFORMATION info(int fd){
    BY_HANDLE_FILE_INFORMATION i{};
    if(fd<0||!GetFileInformationByHandle(handle(fd),&i))throw std::runtime_error("file identity unavailable");
    return i;
}
inline void confirm_directory(int fd,const fs::path& path,const char* error){
    Descriptor other(open_directory(path));
    auto a=info(fd),b=info(other.fd);
    if(a.dwVolumeSerialNumber!=b.dwVolumeSerialNumber||a.nFileIndexHigh!=b.nFileIndexHigh||
        a.nFileIndexLow!=b.nFileIndexLow||!(b.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY))throw std::runtime_error(error);
}
inline bool leaf(const std::string& n){return !n.empty()&&n!="."&&n!=".."&&n.find_first_of("/\\:")==n.npos&&n.find('\0')==n.npos;}
inline fs::path child(int dir,const std::string& n){
    if(!leaf(n))throw std::runtime_error("invalid component");
    return directory_path(dir)/fs::u8path(n);
}
inline int open_input(const fs::path& p){
    return descriptor(CreateFileW(p.c_str(),GENERIC_READ,FILE_SHARE_READ|FILE_SHARE_DELETE,
                                  nullptr,OPEN_EXISTING,FILE_ATTRIBUTE_NORMAL,nullptr));
}
struct ReadMessages {const char *directory,*open,*kind,*read,*limit;};
inline std::string read_owned_descriptor(int fd,size_t cap,const ReadMessages& msg){
    if(fd<0)throw std::runtime_error(msg.open);
    if(GetFileType(handle(fd))!=FILE_TYPE_DISK)throw std::runtime_error(msg.kind);
    if(info(fd).dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY)throw std::runtime_error(msg.kind);
    std::string out; char buf[16384]; int n;
    while((n=_read(fd,buf,sizeof buf))>0){
        if(static_cast<size_t>(n)>cap-out.size())throw std::runtime_error(msg.limit);
        out.append(buf,n);
    }
    if(n<0)throw std::runtime_error(msg.read);
    return out;
}
inline std::string read_regular_input(const fs::path& p,size_t cap,const ReadMessages& msg){
    Descriptor f(open_input(p));return read_owned_descriptor(f.fd,cap,msg);
}
inline std::string read_confined_component(int d,const std::string& n,size_t cap,const ReadMessages& m){
    return read_regular_input(child(d,n),cap,m);
}
inline std::string read_confined_component(const fs::path& d,const std::string& n,size_t cap,const ReadMessages& m){
    Descriptor dir(open_directory(d));if(dir.fd<0)throw std::runtime_error(m.directory);
    return read_confined_component(dir.fd,n,cap,m);
}
inline int open_lock(int d,const std::string& n){
    return descriptor(CreateFileW(child(d,n).c_str(),GENERIC_READ|GENERIC_WRITE,FILE_SHARE_READ|FILE_SHARE_WRITE,
        nullptr,OPEN_ALWAYS,FILE_ATTRIBUTE_NORMAL,nullptr));
}
inline void acquire_lock(int fd,const char* open,const char* kind,const char* busy){
    if(fd<0)throw std::runtime_error(open);
    if(info(fd).dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY)throw std::runtime_error(kind);
    OVERLAPPED pos{};
    if(!LockFileEx(handle(fd),LOCKFILE_EXCLUSIVE_LOCK|LOCKFILE_FAIL_IMMEDIATELY,0,1,0,&pos))throw std::runtime_error(busy);
}
inline void flush_directory(const fs::path& p,const char* err){
    Descriptor d(open_directory(p));if(d.fd<0)throw std::runtime_error(err);
    // Publication below uses a flushed file and a same-volume write-through move.
}
inline std::string running_executable(size_t cap,const ReadMessages& msg){
    std::vector<wchar_t> p(32768);auto n=GetModuleFileNameW(nullptr,p.data(),static_cast<DWORD>(p.size()));
    if(!n||n>=p.size())throw std::runtime_error(msg.open);
    return read_regular_input(std::wstring(p.data(),n),cap,msg);
}
inline void random_bytes(unsigned char* b,size_t n){
    if(BCryptGenRandom(nullptr,b,static_cast<ULONG>(n),BCRYPT_USE_SYSTEM_PREFERRED_RNG)!=0)
        throw std::runtime_error("Windows random source failed");
}
class UncertainCommit:public std::runtime_error{public:using std::runtime_error::runtime_error;};
struct CommitMessages{const char *temporary,*write,*flush_file,*create,*replace,*flush_directory;};
inline void atomic_local_commit(const std::string& name,int dir,const std::string& bytes,
                                const std::string& prefix,bool create_only,const CommitMessages& m){
    unsigned char nonce[16];random_bytes(nonce,sizeof nonce);
    std::string n=prefix;for(auto c:nonce){n+="0123456789abcdef"[c>>4];n+="0123456789abcdef"[c&15];}
    auto tmp=child(dir,n),dst=child(dir,name);
    HANDLE raw=CreateFileW(tmp.c_str(),GENERIC_WRITE,0,nullptr,CREATE_NEW,FILE_ATTRIBUTE_NORMAL,nullptr);
    if(raw==INVALID_HANDLE_VALUE)throw std::runtime_error(m.temporary);
    struct Cleanup{const fs::path& p;~Cleanup(){DeleteFileW(p.c_str());}} cleanup{tmp};
    {
        Descriptor f(descriptor(raw));if(f.fd<0)throw std::runtime_error(m.temporary);
        for(size_t at=0;at<bytes.size();){
            auto part=static_cast<unsigned>(std::min<size_t>(bytes.size()-at,1<<20));
            int done=_write(f.fd,bytes.data()+at,part);if(done<=0)throw std::runtime_error(m.write);at+=done;
        }
        if(!FlushFileBuffers(handle(f.fd)))throw std::runtime_error(m.flush_file);
    }
    if(!MoveFileExW(tmp.c_str(),dst.c_str(),MOVEFILE_WRITE_THROUGH|(create_only?0:MOVEFILE_REPLACE_EXISTING)))
        throw std::runtime_error(create_only?m.create:m.replace);
}
}

