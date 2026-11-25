constexpr size_t choice_capsule_limit=state_limit+decision_trace_limit+512;
struct ChoiceCapsule {string id,kind,basis,receipt;};
bool capsule_pin(const string& pin){return pin.size()==64&&hex_chars(pin);}
bool capsule_id(const string& id){return id.size()==33&&id.front()=='d'&&hex_chars(id.substr(1));}
string encode_choice_capsule(const ChoiceCapsule& c){
    require(capsule_id(c.id)&&(c.kind=="committed"||c.kind=="unchanged")&&
            !c.basis.empty()&&c.basis.size()<=state_limit&&!c.receipt.empty()&&c.receipt.size()<=decision_trace_limit,
            "invalid choice capsule shape");
    IRWriter out;
    out.text(c.id);out.text(c.kind);
    out.number(c.basis.size());out.bytes+=c.basis;
    out.number(c.receipt.size());out.bytes+=c.receipt;
    return "PCGMC-1\n"+sha256(out.bytes)+"\n"+out.bytes;
}
ChoiceCapsule decode_choice_capsule(const string& bytes){
    constexpr size_t offset=8;
    require(bytes.size()>=offset+65&&bytes.size()<=choice_capsule_limit&&bytes.starts_with("PCGMC-1\n")&&
            bytes[offset+64]=='\n',"unsupported or truncated choice capsule");
    const auto payload=bytes.substr(offset+65);
    require(sha256(payload)==bytes.substr(offset,64),"choice capsule body digest mismatch");
    IRReader r{payload};
    ChoiceCapsule result;result.id=r.text();result.kind=r.text();
    auto cell=[&](size_t cap){
        const auto length=r.number(cap);
        require(length<=payload.size()-r.offset,"truncated choice capsule cell");
        auto part=payload.substr(r.offset,length);r.offset+=length;return part;
    };
    result.basis=cell(state_limit);result.receipt=cell(decision_trace_limit);
    require(r.offset==payload.size()&&encode_choice_capsule(result)==bytes,"noncanonical choice capsule");
    return result;
}
void confirm_choice_capsule(const ChoiceCapsule& capsule,const Continuity& basis,const StateStore& readonly){
    const auto program=compile_active(basis);
    const auto prior=run_frozen_choice(basis,program,run(program,basis.inactive),readonly);
    const bool changes=prior.selected&&prior.options.at(*prior.selected).name!="stay";
    require(changes==(capsule.kind=="committed"),"choice capsule outcome kind differs");
    const auto exact=render_decision(basis,prior.options,prior.selected,changes,"live_job:"+capsule.id);
    require(exact==capsule.receipt,"choice capsule receipt differs from independent native replay");
}
string export_choice_capsule(const fs::path& source,const string& id,const string& head){
    require(capsule_id(id)&&capsule_pin(head),"choice capsule requires exact outcome address and head pin");
    const auto path=fs::absolute(source);
    StateStore readonly(fs::canonical(path.parent_path())/path.filename(),false);
    string actual_head;
    const auto saved=readonly.load(&actual_head);
    require(actual_head==head,"choice capsule export head digest mismatch");
    const auto old=saved.choice_outcomes.find(id);
    const auto basis=saved.pins.find("basis_"+id);
    require(old!=saved.choice_outcomes.end()&&saved.choice_bases.contains(id)&&
            basis!=saved.pins.end()&&basis->second.digest==old->second.basis,
            "choice capsule requires a retained explained outcome");
    const auto exact=verify_episode(readonly,saved,basis->second);
    const ChoiceCapsule c{id,old->second.kind,encode(exact),old->second.receipt};
    require(sha256(c.basis)==old->second.basis,"choice capsule basis not canonical");
    confirm_choice_capsule(c,exact,readonly);
    return encode_choice_capsule(c);
}
string check_choice_capsule(const fs::path& file,const string& pin,const string& basis_pin,const string& receipt_pin){
    require(capsule_pin(pin)&&capsule_pin(basis_pin)&&capsule_pin(receipt_pin),
            "choice capsule requires independent capsule, basis and receipt pins");
    const auto raw=native_os::read_regular_input(file,choice_capsule_limit,{
        "cannot open choice capsule directory","cannot open choice capsule","choice capsule must be regular",
        "cannot read choice capsule","choice capsule exceeds size limit"});
    require(sha256(raw)==pin,"choice capsule external digest mismatch");
    const auto c=decode_choice_capsule(raw);
    require(sha256(c.basis)==basis_pin,"choice capsule basis pin mismatch");
    require(sha256(c.receipt)==receipt_pin,"choice capsule receipt pin mismatch");
    const auto basis=decode(c.basis);
    require(encode(basis)==c.basis,"noncanonical choice capsule historical basis");
    // Score only variants already retained within the basis. The read-only path is not a state store
    // publication and creates no file, writer lease, or independent individual.
    const auto home=fs::canonical(fs::absolute(file).parent_path());
    StateStore readonly(home/".pcgm-detached-audit",false);
    confirm_choice_capsule(c,basis,readonly);
    return "{\"schema\":\"pcgm-detached-choice-audit-v1\",\"status\":\"verified\",\"id\":"+quote_json(c.id)+
        ",\"individual\":"+quote_json(basis.id)+",\"capsule_sha256\":"+quote_json(pin)+
        ",\"basis_sha256\":"+quote_json(basis_pin)+",\"receipt_sha256\":"+quote_json(receipt_pin)+
        ",\"committable\":false,\"decision\":"+c.receipt+"}";
}
