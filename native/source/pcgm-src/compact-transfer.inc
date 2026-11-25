string compact_transfer_state(const Continuity& state){
    require(!state.archives.empty(),"compact transfer needs sealed history");
    string payload=state.id+"\n"+to_string(state.archives.size())+"\n";
    for(const auto& part:state.archives)payload+=part.digest+"\n";
    for(size_t i=state.archives.back().last;i<state.events.size();++i)payload+=state.events[i]+"\n";
    payload+="source\n"+state.source;
    const auto image="PCGM-COMPACT-1\n"+sha256(payload)+"\n"+payload;
    require(image.size()<=compact_file_limit,"compact physical state exceeds 2 MiB; seal another history range");
    return image;
}
SegmentStamp segment_stamp(int fd){
    const auto i=native_os::info(fd);
    FILE_BASIC_INFO basic{};
    require(GetFileInformationByHandleEx(native_os::handle(fd),FileBasicInfo,&basic,sizeof basic),"archive attributes unavailable");
    uint64_t size=(uint64_t(i.nFileSizeHigh)<<32)|i.nFileSizeLow;
    require(!(i.dwFileAttributes&FILE_ATTRIBUTE_DIRECTORY)&&size<=archive_segment_limit,"invalid archive");
    return {i.dwVolumeSerialNumber,(uint64_t(i.nFileIndexHigh)<<32)|i.nFileIndexLow,int64_t(size),
            basic.LastWriteTime.QuadPart,0,basic.ChangeTime.QuadPart,0};
}
shared_ptr<const string> verified_segment_bytes(int directory,const string& digest,SegmentReadCache* cache){
    const auto filename=digest+".logseg";
    if(!cache){
        auto bytes=native_os::read_confined_component(directory,filename,archive_segment_limit,archive_words);
        require(sha256(bytes)==digest,"compact transfer segment digest mismatch");
        return make_shared<const string>(move(bytes));
    }
    Descriptor file(native_os::open_input(native_os::child(directory,filename)));
    require(file.fd>=0,"cannot open archive segment");
    const auto stamp=segment_stamp(file.fd);
    if(const auto saved=cache->entries.find(digest);saved!=cache->entries.end()){
        if(saved->second.stamp==stamp){
            ++cache->hits;saved->second.recent=++cache->tick;return saved->second.bytes;
        }
        cache->held-=saved->second.bytes->size();cache->entries.erase(saved);
    }
    string data;
    data.reserve(static_cast<size_t>(stamp.size));
    char buffer[16384];
    for(;;){
        const auto n= _read(file.fd,buffer,sizeof buffer);
        if(n<0&&errno==EINTR)continue;
        require(n>=0,"archive segment read failed");
        if(!n)break;
        require(data.size()+static_cast<size_t>(n)<=archive_segment_limit,"archive segment read limit");
        data.append(buffer,static_cast<size_t>(n));
    }
    require(segment_stamp(file.fd)==stamp&&data.size()==static_cast<size_t>(stamp.size),"archive segment changed during read");
    require(sha256(data)==digest,"compact transfer segment digest mismatch");
    ++cache->reads;cache->verified_bytes+=data.size();
    constexpr size_t limit=16*1024*1024;
    while(cache->held+data.size()>limit&&!cache->entries.empty()){
        const auto oldest=min_element(cache->entries.begin(),cache->entries.end(),
            [](const auto& a,const auto& b){return a.second.recent<b.second.recent;});
        cache->held-=oldest->second.bytes->size();cache->entries.erase(oldest);
    }
    cache->held+=data.size();
    auto bytes=make_shared<const string>(move(data));
    cache->entries.emplace(digest,SegmentCacheEntry{stamp,bytes,++cache->tick});
    return bytes;
}
string expand_compact_transfer(int history,const string& compact,SegmentReadCache* cache){
    require(compact.size()<=compact_file_limit,"compact physical state exceeds 2 MiB");
    size_t cursor=0;
    auto readline=[&](const string& stream,size_t& at){
        const auto nl=stream.find('\n',at);require(nl!=string::npos,"truncated compact transfer");
        auto line=stream.substr(at,nl-at);at=nl+1;return line;
    };
    require(readline(compact,cursor)=="PCGM-COMPACT-1","invalid compact transfer marker");
    const auto checked=readline(compact,cursor);
    require(checked.size()==64&&sha256(compact.substr(cursor))==checked,"compact transfer envelope digest mismatch");
    const auto id=readline(compact,cursor);
    require(valid_identity(id),"invalid compact transfer identity");
    const auto count=sequence_number(readline(compact,cursor));
    require(count>0&&count<=archive_count_limit,"invalid compact transfer archive count");
    string full=id+"\n",prior(64,'0');
    unsigned next=1;
    for(size_t i=0;i<count;++i){
        const auto digest=readline(compact,cursor);
        require(digest.size()==64&&hex_chars(digest),"invalid compact transfer segment reference");
        const auto file=verified_segment_bytes(history,digest,cache);
        const auto& shard=*file;
        size_t head=0;
        require(readline(shard,head)=="PCGM-HISTORY-1"&&readline(shard,head)==id,"compact segment has wrong identity");
        istringstream cells(readline(shard,head));
        string from,through,prev,sha,extra;
        require(bool(cells>>from>>through>>prev>>sha)&&!(cells>>extra)&&sha.size()==64&&hex_chars(sha)&&prev==prior,
            "compact segment chain linkage mismatch");
        const auto lo=sequence_number(from),hi=sequence_number(through);
        require(lo==next&&hi>=lo&&hi-lo<128&&hi<=history_event_limit,"compact segment is not a contiguous archive");
        const auto first=head;
        for(unsigned k=lo;k<=hi;++k)(void)readline(shard,head);
        require(head==shard.size(),"compact segment has incorrect event count");
        full.append(shard,first,head-first);
        require(full.size()<=state_limit,"expanded journal exceeds limit");
        next=hi+1;prior=digest;
    }
    full.append(compact,cursor,compact.size()-cursor);
    require(full.size()<=state_limit,"expanded state exceeds limit");
    return "PCGM-STATE-1\n"+checksum(full)+"\n"+full;
}

string expand_compact_transfer(const fs::path& history,const string& compact){
    Descriptor folder(native_os::open_directory(history));
    require(folder.fd>=0,"cannot open archive directory");
    return expand_compact_transfer(folder.fd,compact);
}
