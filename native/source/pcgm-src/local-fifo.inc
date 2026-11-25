static_assert(atomic<bool>::is_always_lock_free);
atomic<bool> fifo_service_stop{false};
void fifo_service_signal(int){fifo_service_stop.store(true);}
struct FifoBridgeBuffer : streambuf {
    int input,output;
    char bytes[4096];
    FifoBridgeBuffer(int in,int out):input(in),output(out){}
    int_type underflow() override{
        if(gptr()&&gptr()<egptr())return traits_type::to_int_type(*gptr());
        while(!fifo_service_stop){
            pollfd wait{input,POLLIN,0};
            const auto checked=poll(&wait,1,200);
            if(checked<0&&errno==EINTR)continue;
            if(checked<0)return traits_type::eof();
            if(!checked)continue;
            const auto got=read(input,bytes,sizeof bytes);
            if(got<0&&(errno==EINTR||errno==EAGAIN))continue;
            if(got<=0)return traits_type::eof();
            setg(bytes,bytes,bytes+got);
            return traits_type::to_int_type(*gptr());
        }
        return traits_type::eof();
    }
    streamsize xsputn(const char* start,streamsize size) override{
        streamsize written=0;
        while(written<size&&!fifo_service_stop){
            const auto n=write(output,start+written,static_cast<size_t>(size-written));
            if(n>0){written+=n;continue;}
            if(n<0&&errno==EINTR)continue;
            if(n<0&&errno==EAGAIN){
                pollfd wait{output,POLLOUT,0};
                if(poll(&wait,1,1500)>0)continue;
            }
            break;
        }
        return written;
    }
    int_type overflow(int_type c) override{
        if(traits_type::eq_int_type(c,traits_type::eof()))return traits_type::not_eof(c);
        auto byte=traits_type::to_char_type(c);
        return xsputn(&byte,1)==1?c:traits_type::eof();
    }
};
int serve_fifo_reader(const fs::path& state_path,const fs::path& root,unsigned lanes){
    require(lanes>0&&lanes<=4,"local reader supports one through four lanes");
    const auto state=fs::canonical(fs::absolute(state_path).parent_path())/state_path.filename();
    const auto directory=fs::canonical(fs::absolute(root).parent_path())/root.filename();
    require(directory.parent_path()==state.parent_path()&&directory.filename()!=state.filename(),"reader directory must be beside state");
    StateStore entry(state,false);
    const auto individual=entry.load().id;
    require(mkdir(directory.c_str(),0700)==0,"reader directory must be new");
    struct Owned{fs::path path;dev_t device;ino_t inode;mode_t kind;};
    struct Cleanup{
        Owned root;vector<Owned> paths;
        static bool same(const Owned& object,mode_t kind){
            struct stat st{};
            return lstat(object.path.c_str(),&st)==0&&(st.st_mode&S_IFMT)==kind&&
                   st.st_dev==object.device&&st.st_ino==object.inode;
        }
        ~Cleanup(){
            for(const auto& item:paths)if(same(item,item.kind))unlink(item.path.c_str());
            if(same(root,S_IFDIR))rmdir(root.path.c_str());
        }
    };
    struct stat root_stamp{};
    require(lstat(directory.c_str(),&root_stamp)==0&&S_ISDIR(root_stamp.st_mode),"private reader folder identity");
    Cleanup cleanup{{directory,root_stamp.st_dev,root_stamp.st_ino,S_IFDIR},{}};
    vector<pair<fs::path,fs::path>> lanes_paths;
    for(size_t i=1;i<=lanes;++i){
        auto input=directory/("request_"+to_string(i));
        auto output=directory/("reply_"+to_string(i));
        for(const auto& p:{input,output}){
            require(mkfifo(p.c_str(),0600)==0,"cannot create private read channel");
            struct stat stamp{};
            require(lstat(p.c_str(),&stamp)==0&&S_ISFIFO(stamp.st_mode),"private reader FIFO identity");
            cleanup.paths.push_back({p,stamp.st_dev,stamp.st_ino,S_IFIFO});
        }
        const auto lock_path=directory/("lane_"+to_string(i)+".lock");
        Descriptor owned(open(lock_path.c_str(),O_CREAT|O_EXCL|O_RDWR|O_NOFOLLOW|O_CLOEXEC,0600));
        struct stat stamp{};
        require(owned.fd>=0&&fstat(owned.fd,&stamp)==0&&S_ISREG(stamp.st_mode),"cannot create private lane lease");
        cleanup.paths.push_back({lock_path,stamp.st_dev,stamp.st_ino,S_IFREG});
        lanes_paths.emplace_back(input,output);
    }
    struct sigaction stop{};
    stop.sa_handler=fifo_service_signal;sigemptyset(&stop.sa_mask);
    require(sigaction(SIGTERM,&stop,nullptr)==0&&sigaction(SIGINT,&stop,nullptr)==0,"cannot install local reader signal handlers");
    vector<jthread> jobs;
    try{for(const auto& [request,response]:lanes_paths)jobs.emplace_back([=](){
        Descriptor input(open(request.c_str(),O_RDWR|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC));
        Descriptor output(open(response.c_str(),O_RDWR|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC));
        if(input.fd<0||output.fd<0)return;
        while(!fifo_service_stop){
            FifoBridgeBuffer buffer(input.fd,output.fd);
            istream in(&buffer);ostream out(&buffer);
            try{read_channel(state,in,out,individual);}
            catch(const exception& error){
                out<<"{\"protocol\":\"pcgm-read-v1\",\"id\":null,\"ok\":false,\"error\":"<<quote_json(error.what())<<"}\n";
                // Retire this lane rather than producing unrelated or repeated frames.
                return;
            }
        }
    });}catch(...){fifo_service_stop.store(true);throw;}
    cout<<"reader_listening individual="<<individual<<" lanes="<<lanes<<'\n'<<flush;
    for(auto& job:jobs)job.join();
    return 0;
}
