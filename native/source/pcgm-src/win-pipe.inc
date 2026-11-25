// One message per read-only query. Closing the process releases all pipe instances.
wstring lane_name(const fs::path& folder,unsigned lane){
    require(lane>=1&&lane<=4,"invalid native read lane");
    auto key=sha256(fs::absolute(folder).lexically_normal().generic_string());
    return L"\\\\.\\pipe\\zaizai.pcgm."+wstring(key.begin(),key.end())+L"."+to_wstring(lane);
}
struct PipeHandle{
    HANDLE h;
    explicit PipeHandle(HANDLE handle):h(handle){}
    ~PipeHandle(){if(h!=INVALID_HANDLE_VALUE)CloseHandle(h);}
};
int fifo_query(const fs::path& folder,unsigned lane,const string& command){
    require(!command.empty()&&command.size()<=478&&command.find_first_of("\r\n")==string::npos,"invalid request");
    auto name=lane_name(folder,lane);
    require(WaitNamedPipeW(name.c_str(),6000)!=0,"reader not listening or busy");
    PipeHandle p(CreateFileW(name.c_str(),GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_EXISTING,0,nullptr));
    require(p.h!=INVALID_HANDLE_VALUE,"pipe unavailable");
    auto token="f"+new_id(), message=token+" "+command+"\n";
    DWORD written=0;
    require(WriteFile(p.h,message.data(),static_cast<DWORD>(message.size()),&written,nullptr)&&written==message.size(),"request write failed");
    string reply;char data[8192];DWORD n;
    while(ReadFile(p.h,data,sizeof data,&n,nullptr)&&n){
        reply.append(data,n);require(reply.size()<=2*1024*1024+4096,"reply oversized");
        if(reply.back()=='\n')break;
    }
    auto prefix="{\"protocol\":\"pcgm-read-v1\",\"id\":"+quote_json(token)+",";
    require(reply.starts_with(prefix)&&reply.ends_with("\n"),"incomplete or mismatched reply");
    cout<<reply;return reply.starts_with(prefix+"\"ok\":true")?0:2;
}
int serve_fifo_reader(const fs::path& state_path,const fs::path& root,unsigned lanes){
    require(lanes>=1&&lanes<=4,"invalid lane count");
    auto state=fs::absolute(state_path);
    string individual=StateStore(state,false).load().id;
    vector<shared_ptr<PipeHandle>> handles;
    for(unsigned lane=1;lane<=lanes;++lane){
        auto name=lane_name(root,lane);
        auto p=make_shared<PipeHandle>(CreateNamedPipeW(name.c_str(),PIPE_ACCESS_DUPLEX|FILE_FLAG_FIRST_PIPE_INSTANCE,
            PIPE_TYPE_BYTE|PIPE_READMODE_BYTE|PIPE_WAIT|PIPE_REJECT_REMOTE_CLIENTS,1,8192,1024,6000,nullptr));
        require(p->h!=INVALID_HANDLE_VALUE,"cannot create named pipe");
        handles.push_back(p);
    }
    vector<jthread> jobs;
    for(auto p:handles)jobs.emplace_back([=]{
        for(;;){
            if(!ConnectNamedPipe(p->h,nullptr)&&GetLastError()!=ERROR_PIPE_CONNECTED)return;
            string request;char data[512];DWORD n=0;
            while(request.size()<512&&ReadFile(p->h,data,sizeof data,&n,nullptr)&&n){
                request.append(data,n);if(request.find('\n')!=request.npos)break;
            }
            if(request.size()<=512&&request.ends_with("\n")&&request.find('\n')==request.size()-1){
                istringstream in(request);ostringstream out;
                try{read_channel(state,in,out,individual);}catch(const exception&){}
                auto bytes=out.str();DWORD sent=0;
                if(!bytes.empty())WriteFile(p->h,bytes.data(),static_cast<DWORD>(bytes.size()),&sent,nullptr);
            }
            FlushFileBuffers(p->h);DisconnectNamedPipe(p->h);
        }
    });
    cout<<"reader_listening individual="<<individual<<" lanes="<<lanes<<'\n'<<flush;
    for(auto& job:jobs)job.join();
    return 0;
}
