constexpr size_t release_file_limit=16*1024*1024;
string hash_file(const fs::path& path){
    require(fs::is_regular_file(path),"digest requires a regular file");
    ifstream in(path,ios::binary);require(bool(in),"cannot read "+path.string());
    string data;char buf[32768];
    while(in.read(buf,sizeof buf)||in.gcount()>0){
        require(data.size()+static_cast<size_t>(in.gcount())<=release_file_limit,"digest input exceeds 16 MiB");
        data.append(buf,static_cast<size_t>(in.gcount()));
    }
    require(!in.bad()&&in.eof(),"digest input read failed");
    return sha256(data);
}
bool manifest_name(const string& rel){
    if(rel.empty()||rel.size()>240||rel.front()=='/'||rel.back()=='/')return false;
    size_t start=0;
    for(size_t i=0;i<=rel.size();++i){
        if(i==rel.size()||rel[i]=='/'){
            const auto x=rel.substr(start,i-start);
            if(x.empty()||x=="."||x=="..")return false;
            start=i+1;
        }else if(!((rel[i]>='A'&&rel[i]<='Z')||identifier_tail(rel[i])||rel[i]=='.'||rel[i]=='-'))
            return false;
    }
    return true;
}
void verify_release(const fs::path& f){
    const auto manifest=fs::canonical(f);
    const auto root=manifest.parent_path();
    istringstream in(input_file(manifest));
    string line;set<string> found;
    while(getline(in,line)){
        if(line.ends_with('\r'))line.pop_back();
        require(line.size()>=67 && line.compare(64,2,"  ")==0 &&
                line.substr(0,64).find_first_not_of("0123456789abcdef")==string::npos,"invalid manifest entry");
        const auto name=line.substr(66);
        require(manifest_name(name),"invalid manifest path");
        require(found.size()<128&&found.insert(name).second,"duplicate manifest entry or entry limit");
        const auto candidate=root/fs::path(name);
        require(candidate!=manifest && fs::canonical(candidate)==candidate,"manifest entry is not a regular local path");
        require(hash_file(candidate)==line.substr(0,64),"checksum mismatch: "+name);
    }
    require(!found.empty(),"empty release manifest");
    cout<<"manifest_ok files="<<found.size()<<'\n';
}
