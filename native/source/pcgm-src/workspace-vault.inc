constexpr size_t retained_workspace_limit=16*1024*1024;
constexpr native_os::ReadMessages workspace_words{
    "cannot open workspace vault","cannot open immutable local workspace","local workspace is not a regular file",
    "cannot read local workspace","local workspace archive size limit"};
string workspace_archive_name(const string& digest){
    require(digest.size()==64&&hex_chars(digest),"invalid stored CL workspace digest");
    return digest+".clw";
}
void keep_workspace_archive(StateStore& owner,const string& digest,const string& exact){
    require(exact.size()<=retained_workspace_limit&&sha256(exact)==digest,"stored CL workspace archive digest mismatch");
    owner.keep_asset(".workspaces",workspace_archive_name(digest),exact,retained_workspace_limit,workspace_words);
}
string read_retained_workspace(StateStore& owner,const string& alias,const string& digest){
    const auto name=workspace_archive_name(digest);
    const auto folder=owner.asset_folder(".workspaces",false,true);
    if(folder.present()&&folder.contains(name)){
        auto exact=folder.read(name,retained_workspace_limit,workspace_words);
        owner.check_directory();
        require(sha256(exact)==digest,"immutable local workspace archive digest mismatch");
        return exact;
    }
    const auto baseline=owner.input_folder("imports").read(alias+".clw",retained_workspace_limit,workspace_words);
    owner.check_directory();
    require(sha256(baseline)==digest,"fallback workspace archive digest mismatch");
    return baseline;
}
