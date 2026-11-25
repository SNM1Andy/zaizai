"""Apply this build's Win32 port to the known upstream source archive."""
import re
from pathlib import Path
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parents[1]
SRC=ROOT/"source"
UPSTREAM=ROOT/"upstream"/"CL-PCGM-0.159-linux-source.zip"
archive=ZipFile(UPSTREAM)

def change(name,transform):
    old=archive.read(name).decode()
    new=transform(old)
    (SRC/name).write_bytes(new.encode())

def replace_func(s,start,end,body):
    a=s.index(start)
    b=s.index(end,a)
    return s[:a]+body+"\n"+s[b:]

change("native-os.hpp",lambda s:'#ifdef _WIN32\n#include "native-os-win.hpp"\n#else\n'+s+'\n#endif\n')
def assets(s):
    s=replace_func(s,"        if(create&&","    }\npublic:",'''        const auto path=native_os::child(parent,child);
        if(create)std::filesystem::create_directory(path);
        const int fd=open_directory(path);
        if(fd<0&&!(optional&&!create&&!std::filesystem::exists(path)))throw std::runtime_error("asset directory unavailable");
        return fd;''')
    s=replace_func(s,'        struct stat original','    }\n    int confirmed', '''        confirm_directory(folder_.fd,native_os::child(parent_,leaf_),"asset directory changed");''')
    s=replace_func(s,'        struct stat entry','    }\n    std::string read','''        return std::filesystem::exists(child(folder_.fd,name));''')
    return replace_func(s,'        if(::fsync','        confirm();','')
change("anchored-assets.hpp",assets)
change("cl-src/cl.cpp",lambda s:s.replace("#include <sys/file.h>","").replace("#include <unistd.h>","#include <io.h>").replace("return cl_native::driver(argc,argv);","_setmode(0,_O_BINARY);_setmode(1,_O_BINARY);return cl_native::driver(argc,argv);"))
change("cl-c-api.h",lambda s:s.replace("#if defined(__GNUC__)","#if defined(_WIN32) && defined(CL_BUILD_DLL)\n#define CL_API __declspec(dllexport)\n#elif defined(__GNUC__)"))
def pcgm(s):
    s=s.replace("#include <poll.h>","").replace("#include <unistd.h>","").replace('#include "local-fifo.inc"\n#include "fifo-client.inc"','#include "win-pipe.inc"')
    s=replace_func(s,'    string temp=(dst.parent_path()', '}\nstring describe', '''    native_os::Descriptor parent(native_os::open_directory(fs::absolute(dst).parent_path()));
    native_os::atomic_local_commit(dst.filename().string(),parent.fd,body,".pcgm-new-",true,
       {"temp creation failed","write failed","flush failed","source already exists","replace failed","directory sync failed"});''')
    s=s.replace("int main(int argc,char** argv) {","int main(int argc,char** argv) {\n    _setmode(0,_O_BINARY);_setmode(1,_O_BINARY);")
    s=s.replace('const bool managed=argc==4 && string(argv[1])=="--init-managed";','const bool importing=argc==5 && string(argv[1])=="--import-managed";\n        const bool managed=importing || (argc==4 && string(argv[1])=="--init-managed");')
    s=s.replace("if(init) state.id=new_id();","if(init) state.id=importing?string(argv[4]):new_id();\n            if(importing)require(valid_identity(state.id),\"malformed imported identity\");")
    return s
change("pcgm-src/cl.cpp",pcgm)
def continuity(s):
    s=re.sub(r'#include <sys/(file|random|stat).h>\n','',s)
    s=replace_func(s,'struct Descriptor {','constexpr size_t state_limit','using Descriptor=native_os::Descriptor;')
    s=s.replace('dev_t device;', 'uint64_t device;').replace('ino_t inode;', 'uint64_t inode;').replace('off_t size;', 'int64_t size;')
    s=replace_func(s,'    size_t done=0;\n    while(done<sizeof(bytes))','    constexpr char hex', '    native_os::random_bytes(bytes,sizeof(bytes));')
    s=s.replace('string to_hex(','''bool valid_identity(const string& id){
    auto core=id.starts_with("TEST-R28-")?id.substr(9):id;
    return core.size()==32&&hex_chars(core);
}
string to_hex(''')
    return s.replace('c.id.size()==32 && c.id.find_first_not_of("0123456789abcdef")==string::npos','valid_identity(c.id)')
change("pcgm-src/continuity.inc",continuity)
def compact(s):
    s=replace_func(s,'    struct stat s{};', '}\nshared_ptr', '''    const auto i=native_os::info(fd);
    FILE_BASIC_INFO basic{};
    require(GetFileInformationByHandleEx(native_os::handle(fd),FileBasicInfo,&basic,sizeof basic),"archive attributes unavailable");
    uint64_t size=(uint64_t(i.nFileSizeHigh)<<32)|i.nFileSizeLow;
    require(!(i.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY)&&size<=archive_segment_limit,"invalid archive");
    return {i.dwVolumeSerialNumber,(uint64_t(i.nFileIndexHigh)<<32)|i.nFileIndexLow,int64_t(size),
            basic.LastWriteTime.QuadPart,0,basic.ChangeTime.QuadPart,0};''')
    return s.replace('openat(directory,filename.c_str(),O_RDONLY|O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC)','native_os::open_input(native_os::child(directory,filename))').replace('=read(file.fd','= _read(file.fd').replace('id.size()==32&&hex_chars(id)','valid_identity(id)')
change("pcgm-src/compact-transfer.inc",compact)
for name in ["question-wire.inc","sensor-ingress.inc"]:
    change("pcgm-src/"+name,lambda s:re.sub(r'(\bid|individual)\.size\(\)==32&&hex_chars\(\1\)',r'valid_identity(\1)',s))
change("pcgm-src/cycle.inc",lambda s:replace_func(s,'    Descriptor fd(open(dir.c_str()', '}\n\nsize_t stage_questions','''    return native_os::read_confined_component(dir,file+".packet",32768,{"incoming directory unavailable",
        "packet unavailable","invalid packet","packet read failed","packet too large"});'''))
change("pcgm-src/ready.inc",lambda s:replace_func(s,'    if(mkdir','        publish(','''    fs::create_directory(dir);
    const auto body=ticket_body(candidate,binary,snapshot);
    const auto name=sha256(body)+".ready";
    if(!fs::exists(dir/name)){'''))
change("pcgm-src/transfer.inc",lambda s:re.sub(r'mkdir\((\w+)\.c_str\(\),0700\)==0',r'fs::create_directory(\1)',s))

