struct FeedAddress {string id,individual,packet,digest;};
FeedAddress sensor_ingress_frame(const string& line,string& correlation){
    istringstream fields(line);
    string id,kind,individual,packet,digest,extra;
    require(bool(fields>>id),"sensor feed request has no correlation ID");
    Parser rid{id};require(rid.name()==id,"invalid sensor feed request ID");rid.end();
    correlation=id;
    require(bool(fields>>kind>>individual>>packet>>digest)&&!(fields>>extra)&&kind=="submit",
            "expected ID submit INDIVIDUAL PACKET_NAME PACKET_SHA256");
    require(valid_identity(individual)&&digest.size()==64&&hex_chars(digest),
            "sensor feed individual or packet hash invalid");
    Parser leaf{packet};
    require(leaf.name()==packet,"invalid confined sensor packet name");leaf.end();
    require(line==id+" submit "+individual+" "+packet+" "+digest,"sensor feed request is not canonical");
    return {id,individual,packet,digest};
}
string sensor_feed_json(const FeedAddress& request,const Continuity& state,const string& source,unsigned sequence,
                        const CycleReceipt& receipt,bool repeated,const string& workspace,const Automatic& automatic){
    string out="{\"schema\":\"pcgm-sensor-receipt-v1\",\"id\":"+quote_json(request.id)+
        ",\"ok\":true,\"individual\":"+quote_json(state.id)+",\"status\":"+
        quote_json(repeated?"already_applied":"committed")+",\"source\":"+quote_json(source)+
        ",\"sequence\":"+to_string(sequence)+",\"packet_sha256\":"+quote_json(receipt.digest)+
        ",\"observations\":"+to_string(receipt.observations)+",\"questions\":"+to_string(receipt.questions)+
        ",\"event\":"+to_string(state.events.size());
    if(!workspace.empty())out+=",\"workspace\":"+quote_json(workspace);
    if(!automatic.status.empty()){
        out+=",\"automatic_status\":"+quote_json(automatic.status);
        if(!automatic.reason.empty())out+=",\"automatic_detail\":"+quote_json(automatic.reason);
    }
    return out+"}";
}
string reconcile_sensor(const Continuity& state,const string& source,unsigned sequence,const string& digest){
    require(digest.size()==64&&hex_chars(digest)&&sequence>0,"expected exact sensor packet SHA-256 and positive sequence");
    const CycleKey key{source,sequence};
    string json="{\"schema\":\"pcgm-sensor-reconciliation-v1\",\"individual\":"+quote_json(state.id)+
        ",\"source\":"+quote_json(source)+",\"sequence\":"+to_string(sequence)+",\"packet_sha256\":"+quote_json(digest);
    const auto cycle=state.cycles.find(key);
    if(cycle==state.cycles.end())return json+",\"status\":\"not_recorded\"}";
    require(cycle->second.digest==digest,"an established sensor sequence has another packet SHA-256");
    json+=",\"status\":\"committed\",\"observations\":"+to_string(cycle->second.observations)+
        ",\"questions\":"+to_string(cycle->second.questions);
    if(const auto seen=state.sensor_responses.find(key);seen!=state.sensor_responses.end()){
        json+=",\"receipt_event\":"+to_string(seen->second.event)+",\"workspace_result\":"+
            (seen->second.workspace.empty()?string("null"):quote_json(seen->second.workspace));
    }
    if(const auto automatic=state.automatic.find(key);automatic!=state.automatic.end()){
        json+=",\"automatic_status\":"+quote_json(automatic->second.status);
        if(!automatic->second.reason.empty())json+=",\"automatic_detail\":"+quote_json(automatic->second.reason);
    }
    return json+"}";
}
