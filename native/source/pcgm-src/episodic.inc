fs::path episodes_directory(const StateStore& store){return fs::path(store.dst.string()+".episodes");}
constexpr native_os::ReadMessages snapshot_words{
    "cannot open the local episode directory","cannot open the pinned snapshot",
    "pinned snapshot is not a regular file","cannot read the pinned snapshot","pinned snapshot size limit"};
string episode_leaf(const string& digest){
    require(digest.size()==64&&hex_chars(digest),"invalid episode address");
    return digest+".snap";
}
string with_verified_digest(const fs::path& dir,const string& digest){
    auto bytes=native_os::read_confined_component(dir,episode_leaf(digest),state_limit,snapshot_words);
    require(sha256(bytes)==digest,"pinned snapshot digest mismatch");
    return bytes;
}
string with_verified_digest(const StateStore& store,const string& digest){
    auto bytes=store.asset_folder(".episodes").read(episode_leaf(digest),state_limit,snapshot_words);
    store.check_directory();
    require(sha256(bytes)==digest,"pinned snapshot digest mismatch");
    return bytes;
}
void publish_episode(const StateStore& store,const string& digest,const string& bytes){
    require(sha256(bytes)==digest,"pinned snapshot digest mismatch");
    store.keep_asset(".episodes",episode_leaf(digest),bytes,state_limit,snapshot_words);
}
Continuity verify_episode(const StateStore& store,const Continuity& active,const Pin& pin){
    auto saved=decode(with_verified_digest(store,pin.digest));
    require(saved.id==active.id && saved.events.size()==pin.events,"pinned snapshot identity or sequence mismatch");
    require(pin.events<=active.events.size() &&
            std::equal(saved.events.begin(),saved.events.end(),active.events.begin()),"pinned snapshot not in this history");
    return saved;
}
void validate_time_query(const Program& p,const Atom& a){
    require(!a.pred.starts_with("!")&&std::ranges::none_of(a.args,variable),"historical queries use an unsigned ground atom");
    require(p.arity.contains(a.pred)&&p.arity.at(a.pred)==a.args.size(),"relation was not declared in this state");
    map<string,Kind> vars;check_type(p,a,vars);
}
