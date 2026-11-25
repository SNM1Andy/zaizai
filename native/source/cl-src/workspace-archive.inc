constexpr size_t workspace_archive_cap=16*1024*1024;
struct WorkspaceArchive {WorkspaceInput input;string ir,report;};
string package_workspace(const WorkspaceInput& input,const string& ir,const string& report){
    IRWriter w;
    package_cell(w,input.lock,64*1024);package_cell(w,input.app,256*1024);
    w.number(input.data.has_value()?1:0);
    if(input.data)package_cell(w,*input.data,256*1024);
    w.number(input.packages.size());
    for(const auto& [path,bytes]:input.packages){
        package_cell(w,path,96);package_cell(w,bytes,package_limit);
        require(w.bytes.size()<=workspace_archive_cap,"workspace archive exceeds 16 MiB");
    }
    package_cell(w,ir,ir_size_limit);package_cell(w,report,64);
    const auto output=string(input.scoped_ids?"CLWPACK-2\n":"CLWPACK-1\n")+sha256(w.bytes)+"\n"+w.bytes;
    require(output.size()<=workspace_archive_cap,"workspace archive exceeds 16 MiB");
    return output;
}
WorkspaceArchive decode_workspace(const string& bytes){
    const bool scoped=bytes.starts_with("CLWPACK-2\n");
    const string header=scoped?"CLWPACK-2\n":"CLWPACK-1\n";
    require(bytes.starts_with(header)&&bytes.size()>=header.size()+65&&bytes.size()<=workspace_archive_cap,
            "unsupported or truncated CL workspace archive");
    const auto body=bytes.substr(header.size()+65);
    require(bytes[header.size()+64]=='\n'&&sha256(body)==bytes.substr(header.size(),64),"workspace archive body digest mismatch");
    IRReader r{body};
    WorkspaceArchive result;
    result.input.scoped_ids=scoped;
    result.input.lock=package_get(r,64*1024);result.input.app=package_get(r,256*1024);
    if(r.number(1))result.input.data=package_get(r,256*1024);
    auto n=r.number(16);
    string previous;
    while(n--){
        auto name=package_get(r,96);
        require(package_filename(name)&&name.ends_with(".clpkg")&&name>previous,"noncanonical local workspace archive member");
        previous=name;result.input.packages.emplace(move(name),package_get(r,package_limit));
    }
    result.ir=package_get(r,ir_size_limit);result.report=package_get(r,64);
    require(r.offset==body.size()&&workspace_digest(result.report),"invalid workspace archive audit receipt or trailing bytes");
    return result;
}
