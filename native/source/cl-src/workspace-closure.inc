bool workspace_digest(const string& text){
    return text.size()==64&&text.find_first_not_of("0123456789abcdef")==string::npos;
}
struct WorkspaceMember {string module,file,package,policy;};
vector<WorkspaceMember> workspace_members(const string& bytes){
    istringstream in(bytes);
    string line;
    require(bool(getline(in,line))&&line=="CLWORK-1","invalid CL workspace lock header");
    vector<WorkspaceMember> rows;
    string canonical="CLWORK-1\n",prior;
    set<string> paths;
    while(getline(in,line)){
        WorkspaceMember item;
        istringstream row(line);
        string extra;
        require(bool(row>>item.module>>item.file>>item.package>>item.policy)&&!(row>>extra),"invalid CL workspace member");
        Parser name{item.module};require(name.name()==item.module&&valid_module(item.module),"invalid CL workspace module name");name.end();
        require(item.module>prior&&paths.insert(item.file).second&&package_filename(item.file)&&item.file.ends_with(".clpkg"),
                "workspace members not canonical or outside local package directory");
        require(workspace_digest(item.package)&&(item.policy=="-"||workspace_digest(item.policy))&&rows.size()<16,
                "workspace package or policy digest invalid");
        prior=item.module;canonical+=item.module+" "+item.file+" "+item.package+" "+item.policy+"\n";
        rows.push_back(move(item));
    }
    require(!rows.empty()&&canonical==bytes,"CL workspace lock is empty or not canonical");
    return rows;
}
struct WorkspaceProduct {Program program;string receipt,api_digest,api;};
struct WorkspaceInput {
    string lock,app;
    optional<string> data;
    map<string,string> packages;
    bool scoped_ids=true;
};
#ifndef CL_PORTABLE_MEMORY_CORE
WorkspaceInput read_workspace(const fs::path& root,const fs::path& lock,const string& trusted,const fs::path& data){
    require(workspace_digest(trusted),"an independent workspace lock SHA-256 is required");
    static const native_os::ReadMessages words{"cannot open workspace directory","cannot open workspace input",
        "workspace input must be a regular file","cannot read workspace input","workspace input size limit"};
    WorkspaceInput input;
    input.lock=native_os::read_regular_input(lock,64*1024,words);
    require(sha256(input.lock)==trusted,"workspace lock does not match supplied SHA-256");
    input.app=native_os::read_regular_input(root,256*1024,words);
    if(!data.empty())input.data=native_os::read_regular_input(data,256*1024,words);
    const auto folder=fs::absolute(lock).parent_path();
    for(const auto& member:workspace_members(input.lock)){
        const auto bytes=native_os::read_confined_component(folder,member.file,package_limit,{
            "cannot open the workspace package directory","cannot open pinned workspace package","workspace package must be a regular file",
            "cannot read workspace package","workspace package size limit"});
        input.packages.emplace(member.file,bytes);
    }
    return input;
}
#endif
WorkspaceProduct assemble_workspace_bytes(const WorkspaceInput& input,const string& trusted){
    require(workspace_digest(trusted)&&sha256(input.lock)==trusted,"workspace lock does not match supplied SHA-256");
    const auto members=workspace_members(input.lock);
    require(input.packages.size()==members.size(),"workspace archive dependency contents do not match lock");
    const auto& app_bytes=input.app;
    const auto root=fs::path("/clpkg/application.cl");
    const auto app=LinkedProject::load_text(root,app_bytes);
    CLPackage closure;
    closure.entry=app.name+".cl";
    closure.files.emplace(closure.entry,app_bytes);
    map<string,string> providers;
    size_t shared=0;
    ostringstream receipt;
    receipt<<"{\"schema\":\"cl-workspace-v1\",\"lock_sha256\":"<<quote_json(trusted)<<",\"root_sha256\":"
           <<quote_json(sha256(app_bytes))<<",\"libraries\":[";
    for(size_t i=0;i<members.size();++i){
        const auto& name=members[i];
        const auto package=input.packages.find(name.file);
        require(package!=input.packages.end(),"workspace archive is missing a locked package");
        const auto& bytes=package->second;
        require(sha256(bytes)==name.package,"workspace library package digest mismatch: "+name.module);
        const auto bundle=decode_package(bytes);
        const auto pin=bundle.scope_policy.empty()?string("-"):sha256(bundle.scope_policy);
        require(pin==name.policy,"workspace library required CL module policy differs: "+name.module);
        const auto verified=verify_package(bundle);
        require(bundle.data_name.empty()&&verified.goals.empty(),
                "reusable CL workspace library cannot carry data or report goals");
        const auto module=LinkedProject::load_text(bundle.entry,bundle.files.at(bundle.entry)).name;
        require(module==name.module&&app.imports.contains(module),"workspace library name is not an explicit application import: "+name.module);
        for(const auto& [relative,source]:bundle.files){
            const auto unit=LinkedProject::load_text(relative,source);
            require(unit.name!=app.name,"library defines the application module name");
            const auto path="modules/"+unit.name+".cl";
            const auto [old,added]=closure.files.emplace(path,source);
            if(!added)require(old->second==source,
                    "conflicting versions of workspace module "+unit.name+" from "+providers.at(path)+" and "+name.module);
            if(added){
                require(closure.files.size()<=32,"workspace module closure exceeds limit");
                providers.emplace(path,name.module);
            }else ++shared;
        }
        if(i)receipt<<',';
        receipt<<"{\"module\":"<<quote_json(module)<<",\"package_sha256\":"<<quote_json(name.package)
            <<",\"profile_sha256\":"<<(pin=="-"?string("null"):quote_json(pin))<<"}";
    }
    require(app.imports.size()==members.size(),"workspace lock does not pin every explicit application import");
    auto linked=packaged_tree(closure);
    linked.namespace_observation_ids=input.scoped_ids;
    vector<string> rows;
    string data_stamp;
    if(input.data){
        data_stamp=sha256(*input.data);
        istringstream lines(*input.data);string line;
        while(getline(lines,line))rows.push_back(line);
    }
    const auto program=linked.compile_project(input.data?fs::path("/clpkg/workspace_data.cl"):fs::path{},input.data?&rows:nullptr);
    const auto ir=to_image(program,{});
    receipt<<"],\"source_units\":"<<closure.files.size()<<",\"identical_shared_modules\":"<<shared
           <<",\"data_sha256\":"<<(!input.data?string("null"):quote_json(data_stamp))
           <<",\"ir_sha256\":"<<quote_json(sha256(ir))<<"}";
    const auto api=api_text(public_api(linked,program));
    return {program,receipt.str(),sha256(api),api};
}
#ifndef CL_PORTABLE_MEMORY_CORE
WorkspaceProduct assemble_workspace(const fs::path& root,const fs::path& lock,const string& trusted,const fs::path& data){
    return assemble_workspace_bytes(read_workspace(root,lock,trusted,data),trusted);
}

#endif
