struct CLPackage {
    string entry,lock,api,data_name,data,ir,scope_policy,scope_report;
    map<string,string> files;
};
constexpr size_t package_limit=2*1024*1024;
bool package_filename(const string& s){
    return !s.empty()&&s.size()<=96&&s!="."&&s!=".."&&
        s.find_first_not_of("abcdefghijklmnopqrstuvwxyz0123456789_.-")==string::npos;
}
void package_cell(IRWriter& writer,const string& text,size_t cap){
    require(text.size()<=cap,"CL package cell limit");
    writer.number(text.size());writer.bytes+=text;
}
string package_get(IRReader& reader,size_t cap){
    const auto n=reader.number(cap);
    require(n<=reader.bytes.size()-reader.offset,"truncated CL package cell");
    auto text=reader.bytes.substr(reader.offset,n);reader.offset+=n;
    return text;
}
string encode_package(const CLPackage& value){
    IRWriter w;
    package_cell(w,value.entry,96);
    w.number(value.files.size());
    for(const auto& [file,contents]:value.files){
        package_cell(w,file,128);package_cell(w,contents,256*1024);
    }
    package_cell(w,value.lock,128*1024);
    package_cell(w,value.api,128*1024);
    package_cell(w,value.data_name,96);
    package_cell(w,value.data,256*1024);
    package_cell(w,value.ir,ir_size_limit);
    if(!value.scope_policy.empty()){
        package_cell(w,value.scope_policy,512*1024);
        require(value.scope_report.size()==64,"invalid package scope receipt");
        package_cell(w,value.scope_report,64);
    }else require(value.scope_report.empty(),"scope receipt cannot exist without a scope profile");
    auto output=string(value.scope_policy.empty()?"CLPKG-1\n":"CLPKG-2\n")+sha256(w.bytes)+"\n"+w.bytes;
    require(output.size()<=package_limit,"CL package exceeds 2 MiB");
    return output;
}
CLPackage decode_package(const string& image){
    const bool scoped=image.starts_with("CLPKG-2\n");
    const string header=scoped?"CLPKG-2\n":"CLPKG-1\n";
    require(image.starts_with(header)&&image.size()>=header.size()+65&&image.size()<=package_limit,"unsupported or truncated CL package");
    const auto body=image.substr(header.size()+65);
    require(image[header.size()+64]=='\n'&&sha256(body)==image.substr(header.size(),64),"CL package digest mismatch");
    IRReader input{body};
    CLPackage out;
    out.entry=package_get(input,96);
    require(package_filename(out.entry)&&out.entry.ends_with(".cl"),"unsafe CL package entry");
    auto objects=input.number(32);
    require(objects>0,"empty CL package");
    string prior;
    for(unsigned i=0;i<objects;++i){
        auto path=package_get(input,128);
        const auto module=path.starts_with("modules/")?path.substr(8):"";
        require(path==out.entry||(package_filename(module)&&module.ends_with(".cl")),"unsafe CL package member");
        require(path>prior,"CL package paths are not canonically ordered");
        prior=path;
        out.files.emplace(std::move(path),package_get(input,256*1024));
    }
    out.lock=package_get(input,128*1024);
    out.api=package_get(input,128*1024);
    out.data_name=package_get(input,96);
    out.data=package_get(input,256*1024);
    out.ir=package_get(input,ir_size_limit);
    if(scoped){
        out.scope_policy=package_get(input,512*1024);out.scope_report=package_get(input,64);
        require(!out.scope_policy.empty()&&out.scope_report.size()==64&&
                out.scope_report.find_first_not_of("0123456789abcdef")==string::npos,"invalid CL package scope receipt");
    }
    require(input.offset==body.size(),"trailing CL package bytes");
    require(out.data_name.empty()?out.data.empty():(package_filename(out.data_name)&&out.data_name.ends_with(".cl")),
            "unsafe CL package data label");
    return out;
}
LinkedProject packaged_tree(const CLPackage& value){
    LinkedProject project;
    const fs::path virtual_root="/clpkg";
    project.root=virtual_root/value.entry;
    function<void(string,string)> visit=[&](string file,string expected){
        const auto path=virtual_root/file;
        if(project.done.contains(path))return;
        require(project.active.insert(path).second,"CL package dependency cycle");
        const auto entry=value.files.find(file);
        require(entry!=value.files.end(),"missing CL package dependency "+file);
        auto unit=LinkedProject::load_text(path,entry->second);
        require(expected.empty()||unit.name==expected,"package module name does not match import");
        require(project.registry.emplace(unit.name,path).second,"duplicate CL package module");
        for(const auto& target:unit.imports)visit("modules/"+target+".cl",target);
        project.units.emplace(path,std::move(unit));
        project.order.push_back(path);project.done.insert(path);project.active.erase(path);
    };
    visit(value.entry,{});
    require(project.units.size()==value.files.size(),"CL package has unused members");
    return project;
}
pair<Program,string> compile_packaged(const CLPackage& value){
    auto project=packaged_tree(value);
    require(project.lock_text()==value.lock,"CL package project lock does not match reconstructed sources");
    (void)parse_api(value.api);
    string receipt;
    if(!value.scope_policy.empty()){
        project.scope_verifier=[&](const LinkedProject& subject){
            auto [ok,report]=audit_module_scope(subject,value.scope_policy,sha256(value.scope_policy));
            require(ok,"authored scope did not authorize the entire CL package");
            receipt=move(report);
        };
    }
    istringstream input(value.data);
    string line;vector<string> rows;
    while(getline(input,line))rows.push_back(line);
    auto program=project.compile_project(value.data_name.empty()?fs::path{}:fs::path("/clpkg")/value.data_name,
                                          value.data_name.empty()?nullptr:&rows);
    require(api_text(public_api(project,program))==value.api,"CL package interface does not match reconstructed sources");
    return {std::move(program),std::move(receipt)};
}
Program verify_package(const CLPackage& value){
    auto [program,receipt]=compile_packaged(value);
    require(value.scope_policy.empty()||sha256(receipt)==value.scope_report,"CL package scope report differs from independently rebuilt proof");
    const auto expected=to_image(program,{});
    require(value.ir==expected,"CL package IR does not match reconstructed source");
    (void)from_image(value.ir);
    return program;
}
CLPackage pack_project(const fs::path& root,const fs::path& lock,const fs::path& api,const fs::path& data){
    LinkedProject source(root);
    CLPackage value;
    value.entry=source.root.filename().string();
    require(package_filename(value.entry)&&value.entry.ends_with(".cl"),"invalid entry package filename");
    value.lock=input_file(lock);
    require(value.lock==source.lock_text(),"CL project lock mismatch before packaging");
    value.api=input_file(api);
    (void)parse_api(value.api);
    for(const auto& [path,unit]:source.units)value.files.emplace(path.lexically_relative(source.root.parent_path()).generic_string(),unit.bytes);
    if(!data.empty()){
        value.data_name=data.filename().string();
        require(package_filename(value.data_name)&&value.data_name.ends_with(".cl"),"invalid observation filename");
        value.data=input_file(data);
    }
    auto project=packaged_tree(value);
    vector<string> facts;
    istringstream input(value.data);
    string line;
    while(getline(input,line))facts.push_back(line);
    auto program=project.compile_project(data.empty()?fs::path{}:fs::path("/clpkg")/value.data_name,data.empty()?nullptr:&facts);
    require(api_text(public_api(project,program))==value.api,"declared public interface does not match source project");
    value.ir=to_image(program,{});
    (void)from_image(value.ir);
    return value;
}
