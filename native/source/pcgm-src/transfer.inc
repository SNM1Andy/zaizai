string read_transfer_file(const fs::path& root,const string& name,size_t limit){
    const auto open_error="cannot open transfer component: "+name;
    return native_os::read_confined_component(root,name,limit,{"cannot open transfer directory",open_error.c_str(),
                       "invalid transfer component","cannot read transfer component","transfer component too large"});
}
#include "workspace-vault.inc"
#include "recipe-vault.inc"
using RequiredWorkspace=tuple<string,string,string,string>;
map<string,RequiredWorkspace> transfer_workspace_requirements(const Continuity& state){
    map<string,RequiredWorkspace> out;
    for(const auto& [alias,origins]:state.workspace_origins)for(const auto& [key,scope]:origins){
        const RequiredWorkspace value{scope.profile,state.package_versions.at(alias).at(key),scope.report,
            workspace_contract_by_archive(state,alias,key)};
        const auto [existing,added]=out.emplace(key,value);
        require(added||existing->second==value,"conflicting workspace archive provenance");
    }
    return out;
}
template<class ReadWorkspace>
map<string,string> verify_transfer_workspaces(ReadWorkspace read_workspace,const map<string,RequiredWorkspace>& required){
    map<string,string> out;
    size_t total=0;
    for(const auto& [key,pins]:required){
        auto bytes=read_workspace(workspace_archive_name(key));
        require(bytes.size()<=128*1024*1024-total,"overall workspace transfer size limit");
        total+=bytes.size();
        require(sha256(bytes)==key,"transferred workspace archive digest mismatch");
        const auto rebuilt=cl_native::verify_workspace_bytes(bytes,std::get<0>(pins));
        require(rebuilt.package_sha256==key&&rebuilt.ir_sha256==std::get<1>(pins)&&rebuilt.workspace_audit_sha256==std::get<2>(pins)&&
                (std::get<3>(pins).empty()||rebuilt.api_sha256==std::get<3>(pins)),
                "transferred workspace disagrees with recorded CL provenance");
        out.emplace(key,std::move(bytes));
    }
    return out;
}
void sync_directory(const fs::path& path){
    native_os::flush_directory(path,"cannot sync transfer directory");
}
string quote_json(const string& s);
#include "event-archive.inc"
#include "compact-transfer.inc"
void ensure_history_prefix(const Continuity& primary,const Pin& pin,const string& bytes){
    const auto saved=decode(bytes);
    require(saved.id==primary.id && saved.events.size()==pin.events&&pin.events<=primary.events.size()&&
            std::equal(saved.events.begin(),saved.events.end(),primary.events.begin()),"transfer episode history mismatch");
}
void export_transfer(const fs::path& source,const fs::path& target,bool compact=false,bool complete=false,bool policies=false){
    const auto in=fs::absolute(source);
    auto dest=fs::absolute(target);
    dest=fs::canonical(dest.parent_path())/dest.filename();
    StateStore store(fs::canonical(in.parent_path())/in.filename(),false);
    const auto state=store.load();
    require(!state.pending&&state.staged_copy.empty(),"cannot export pending or unactivated state");
    const auto raw=encode(state), digest=sha256(raw);
    map<string,string> histories;
    for(const auto& pin:transferable_pins(state)){
        const auto bytes=with_verified_digest(store,pin.digest);
        ensure_history_prefix(state,pin,bytes);
        histories.emplace(pin.digest,bytes);
    }
    map<string,string> segments;
    for(const auto& part:state.archives){
        verify_archive(store,state,part);
        segments.emplace(part.digest,archive_payload(state,part));
    }
    require(!complete||!compact,"complete export uses materialized canonical state");
    const auto retained=complete?verify_transfer_workspaces([&](const string& name){
        auto bytes=store.asset_folder(".workspaces").read(name,retained_workspace_limit,workspace_words);
        store.check_directory();return bytes;
    },transfer_workspace_requirements(state)):map<string,string>{};
    require(!policies||complete,"portable recipe files require complete workspace export");
    const auto requested=policies?recipe_transfer_requirements(state):map<string,RecipeRequirement>{};
    map<string,string> pinned_policies;
    for(const auto& [name,need]:requested)pinned_policies.emplace(name,pinned_recipe_member(store,name,need.first,need.second));
    const auto payload=compact?compact_transfer_state(state):raw;
    require(fs::create_directory(dest),"transfer destination must be a new directory");
    const auto deps=dest/"episodes";
    require(fs::create_directory(deps),"cannot create transfer episode directory");
    for(const auto& [hash,bytes]:histories)publish(deps/(hash+".snap"),bytes);
    sync_directory(deps);
    if(!segments.empty()){
        const auto sealed=dest/"history";
        require(fs::create_directory(sealed),"cannot create transfer archive folder");
        for(const auto& [hash,bytes]:segments)publish(sealed/(hash+".logseg"),bytes);
        sync_directory(sealed);
    }
    if(!retained.empty()){
        const auto area=dest/"workspaces";
        require(fs::create_directory(area),"cannot create transfer workspace directory");
        for(const auto& [key,bytes]:retained)publish(area/workspace_archive_name(key),bytes);
        sync_directory(area);
    }
    if(!pinned_policies.empty()){
        const auto area=dest/"recipes";
        require(fs::create_directory(area),"cannot create transfer recipe directory");
        for(const auto& [name,bytes]:pinned_policies)publish(area/name,bytes);
        sync_directory(area);
    }
    publish(dest/"state.bundle",payload);
    const bool has_archives=!segments.empty();
    string manifest=string(policies?"PCGM_TRANSFER_5 ":complete?"PCGM_TRANSFER_4 ":compact?"PCGM_TRANSFER_3 ":has_archives?"PCGM_TRANSFER_2 ":"PCGM_TRANSFER_1 ")+state.id+" "+to_string(state.events.size())+" "+digest+"\n";
    for(const auto& [hash,_]:histories)manifest+=((has_archives||complete)?"episode ":"")+hash+"\n";
    if(has_archives)for(const auto& [hash,_]:segments)manifest+="archive "+hash+"\n";
    for(const auto& [hash,_]:retained)manifest+="workspace "+hash+"\n";
    for(const auto& [name,need]:requested)manifest+="recipe "+name+" "+need.first+"\n";
    publish(dest/"TRANSFER",manifest);
    sync_directory(dest);sync_directory(dest.parent_path());
    cout<<"transfer_exported individual="<<state.id<<" events="<<state.events.size()
        <<" episodes="<<histories.size()<<" sha256="<<digest<<'\n';
}
void restore_transfer(const fs::path& src,const fs::path& target){
    const auto from=fs::absolute(src);
    const auto encoded=read_transfer_file(from,"state.bundle",state_limit);
    istringstream manifest(read_transfer_file(from,"TRANSFER",65536));
    string head,id,n,digest,hash;
    require(bool(manifest>>head>>id>>n>>digest)&&
        (head=="PCGM_TRANSFER_1"||head=="PCGM_TRANSFER_2"||head=="PCGM_TRANSFER_3"||head=="PCGM_TRANSFER_4"||head=="PCGM_TRANSFER_5"),"invalid transfer format");
    const bool policies=head=="PCGM_TRANSFER_5";
    const bool complete=head=="PCGM_TRANSFER_4"||policies;
    const auto raw=head=="PCGM_TRANSFER_3"?expand_compact_transfer(from/"history",encoded):encoded;
    auto state=decode(raw);
    require(!state.pending&&state.staged_copy.empty(),"invalid exported state");
    require(id==state.id&&sequence_number(n)==state.events.size()&&digest==sha256(raw),
            "transfer manifest or state digest mismatch");
    set<string> refs,archive_refs,workspace_refs,expected,expected_archives,expected_workspaces;
    const bool v2=head!="PCGM_TRANSFER_1";
    string kind;
    map<string,string> observed_policies;
    while(manifest>>kind){
        if(policies&&kind=="recipe"){
            string name,pin;
            require(bool(manifest>>name>>pin)&&native_os::leaf(name)&&pin.size()==64&&hex_chars(pin)&&
                    observed_policies.emplace(name,pin).second,"invalid transfer recipe component index");
            continue;
        }
        if(v2)require(bool(manifest>>hash)&&(kind=="episode"||kind=="archive"||(complete&&kind=="workspace")),"invalid transfer component index");
        else hash=kind;
        auto& directory=complete&&kind=="workspace"?workspace_refs:(v2&&kind=="archive")?archive_refs:refs;
        require(hash.size()==64&&hex_chars(hash)&&directory.insert(hash).second,"invalid transfer reference");
    }
    for(const auto& pin:transferable_pins(state))expected.insert(pin.digest);
    for(const auto& part:state.archives)expected_archives.insert(part.digest);
    require(refs==expected&&archive_refs==expected_archives&&(complete||v2==!expected_archives.empty()),
            "transfer is missing or has extra history references");
    const auto expected_records=complete?transfer_workspace_requirements(state):map<string,RequiredWorkspace>{};
    for(const auto& [key,_]:expected_records)expected_workspaces.insert(key);
    require(workspace_refs==expected_workspaces,"transfer workspace index does not match state");
    const auto retained=verify_transfer_workspaces([&](const string& name){
        return read_transfer_file(from/"workspaces",name,retained_workspace_limit);
    },expected_records);
    map<string,string> exact_recipes;
    const auto recipe_records=policies?recipe_transfer_requirements(state):map<string,RecipeRequirement>{};
    require(observed_policies.size()==recipe_records.size(),"transfer recipe index does not match state policy");
    for(const auto& [name,need]:recipe_records){
        const auto item=observed_policies.find(name);
        require(item!=observed_policies.end()&&item->second==need.first,"transfer recipe digest does not match state policy");
        auto bytes=read_transfer_file(from/"recipes",name,need.second);
        require(sha256(bytes)==need.first,"transferred recipe authority digest mismatch");
        exact_recipes.emplace(name,std::move(bytes));
    }
    for(const auto& part:state.archives){
        const auto segment=read_transfer_file(from/"history",part.digest+".logseg",archive_segment_limit);
        require(sha256(segment)==part.digest&&segment==archive_payload(state,part),"invalid transfer archive segment");
    }
    map<string,string> histories;
    for(const auto& pin:transferable_pins(state)){
        const auto bytes=with_verified_digest(from/"episodes",pin.digest);
        ensure_history_prefix(state,pin,bytes);
        histories.emplace(pin.digest,bytes);
    }
    auto dest=fs::absolute(target);
    dest=fs::canonical(dest.parent_path())/dest.filename();
    const auto absent=[](const fs::path& p){return fs::symlink_status(p).type()==fs::file_type::not_found;};
    require(absent(dest)&&absent(fs::path(dest.string()+".episodes"))&&absent(fs::path(dest.string()+".history"))&&
            (!complete||absent(fs::path(dest.string()+".workspaces")))&&(!policies||absent(fs::path(dest.string()+".recipes"))),
            "restore target already exists");
    StateStore dst(dest);
    require(absent(dest)&&absent(episodes_directory(dst))&&absent(archive_directory(dst)),"restore target already exists");
    for(const auto& [which,bytes]:histories)publish_episode(dst,which,bytes);
    for(const auto& part:state.archives)publish_archive(dst,state,part);
    for(const auto& [key,bytes]:retained)keep_workspace_archive(dst,key,bytes);
    for(const auto& [name,bytes]:exact_recipes)
        dst.keep_asset(".recipes",name,bytes,recipe_records.at(name).second,recipe_words);
    state.staged_copy=digest;
    state.events.push_back("restored_copy "+digest);
    dst.save(state,true);
    cout<<"transfer_staged individual="<<state.id<<" episodes="<<histories.size()
        <<" sha256="<<digest<<" activation=required\n";
}
