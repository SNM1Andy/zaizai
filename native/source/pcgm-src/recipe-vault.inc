constexpr native_os::ReadMessages recipe_words{
    "cannot open local recipe vault","cannot open exact transferred recipe file",
    "transferred recipe must be regular","transferred recipe read failed","transferred recipe size limit"};
string pinned_recipe_member(const StateStore& actor,const string& name,const string& digest,size_t limit){
    require(native_os::leaf(name)&&digest.size()==64&&hex_chars(digest),"invalid pinned workspace recipe address");
    const auto chosen=actor.asset_folder(".recipes",false,true);
    const auto bytes=chosen.present()?chosen.read(name,limit,recipe_words)
                                     :actor.input_folder("build_inputs").read(name,limit,recipe_words);
    actor.check_directory();
    require(sha256(bytes)==digest,"workspace recipe authority digest mismatch");
    return bytes;
}
using RecipeRequirement=pair<string,size_t>;
map<string,RecipeRequirement> recipe_transfer_requirements(const Continuity& state){
    map<string,RecipeRequirement> result;
    const auto source=compile_active(state);
    const auto require_one=[&](const string& name,const string& hash,size_t limit){
        const auto [it,fresh]=result.emplace(name,RecipeRequirement{hash,limit});
        require(fresh||it->second==RecipeRequirement{hash,limit},"ambiguous name for already pinned workspace recipe authority");
    };
    for(const auto& [_,phases]:source.workspace_recipes)for(const auto& rule:phases){
        const bool shared=phases.size()>1;
        require_one(shared?rule.alias+"."+rule.recipe+".clir":rule.alias+".recipe.clir",rule.recipe,256*1024);
        require_one(shared?rule.alias+"."+rule.scope+".scope":rule.alias+".recipe.scope",rule.scope,16*1024);
    }
    return result;
}
