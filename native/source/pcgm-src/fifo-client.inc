void verify_private_endpoint(int fd,mode_t kind){
    struct stat card{};
    require(fd>=0&&fstat(fd,&card)==0&&(card.st_mode&S_IFMT)==kind&&card.st_uid==geteuid()&&
            (card.st_mode&(S_IRWXG|S_IRWXO))==0,"local PCGM endpoint is absent or not privately owned");
}
int fifo_query(const fs::path& folder,unsigned lane,const string& command){
    require(lane>0&&lane<=4,"invalid native read lane");
    require(!command.empty()&&command.find_first_of("\r\n")==string::npos&&command.size()<=478,"invalid bounded FIFO request");
    Descriptor dir(open(folder.c_str(),O_RDONLY|O_DIRECTORY|O_NOFOLLOW|O_CLOEXEC));
    verify_private_endpoint(dir.fd,S_IFDIR);
    const auto id=to_string(lane);
    Descriptor lease(openat(dir.fd,("lane_"+id+".lock").c_str(),O_RDWR|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC));
    verify_private_endpoint(lease.fd,S_IFREG);
    require(flock(lease.fd,LOCK_EX|LOCK_NB)==0,"native PCGM lane is busy");
    Descriptor data_in(openat(dir.fd,("reply_"+id).c_str(),O_RDONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC));
    verify_private_endpoint(data_in.fd,S_IFIFO);
    Descriptor data_out(openat(dir.fd,("request_"+id).c_str(),O_WRONLY|O_NONBLOCK|O_NOFOLLOW|O_CLOEXEC));
    verify_private_endpoint(data_out.fd,S_IFIFO);
    signal(SIGPIPE,SIG_IGN);
    const auto token="f"+new_id();
    const auto request=token+" "+command+"\n";
    require(write(data_out.fd,request.data(),request.size())==static_cast<ssize_t>(request.size()),"local PCGM request could not be delivered whole");
    const auto prefix="{\"protocol\":\"pcgm-read-v1\",\"id\":"+quote_json(token)+",";
    const auto until=chrono::steady_clock::now()+chrono::seconds(6);
    string pending;
    size_t unrelated=0;
    while(chrono::steady_clock::now()<until){
        pollfd ready{data_in.fd,POLLIN,0};
        const auto more=poll(&ready,1,150);
        if(more<0&&errno==EINTR)continue;
        require(more>=0,"native PCGM pipe read failed");
        if(!more)continue;
        char b[4096];
        const auto n=read(data_in.fd,b,sizeof b);
        if(n<0&&(errno==EAGAIN||errno==EINTR))continue;
        require(n>0,"local PCGM reader closed without a receipt");
        pending.append(b,static_cast<size_t>(n));
        require(pending.size()<=2*1024*1024+4096,"native PCGM reply exceeds limit");
        for(size_t end;(end=pending.find('\n'))!=string::npos;){
            auto frame=pending.substr(0,end);
            pending.erase(0,end+1);
            if(frame.starts_with(prefix)){
                cout<<frame<<'\n';
                return frame.starts_with(prefix+"\"ok\":true,")?0:2;
            }
            require(++unrelated<=64,"native PCGM lane has too many stale frames");
        }
    }
    throw runtime_error("no correlated native PCGM receipt within six seconds");
}
