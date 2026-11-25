constexpr size_t artifact_version_limit=4;
struct ArtifactSpan { size_t first,last; };
string artifact_marker(string kind,const string& alias,const string& digest){
    return "# "+kind+" CLIR "+alias+" "+digest+"\n";
}
size_t artifact_line(const string& source,const string& marker,size_t from=0){
    for(auto at=source.find(marker,from);at!=string::npos;at=source.find(marker,at+1))
        if(!at||source[at-1]=='\n')return at;
    return string::npos;
}
ArtifactSpan artifact_span(const string& source,const string& alias,const string& digest){
    const auto open=artifact_marker("installed",alias,digest),end=artifact_marker("end",alias,digest);
    const auto begin=artifact_line(source,open);
    require(begin!=string::npos,"missing installed artifact marker");
    const auto limit=artifact_line(source,end,begin+open.size());
    require(limit!=string::npos,"legacy artifact has no revision boundary; not switched");
    const size_t finish=limit+end.size();
    require(artifact_line(source,open,begin+open.size())==string::npos&&
            artifact_line(source,end,finish)==string::npos,"duplicate artifact boundary");
    const auto payload=source.substr(begin+open.size(),limit-(begin+open.size()));
    require(!payload.starts_with("# installed CLIR ")&&payload.find("\n# installed CLIR ")==string::npos&&
            !payload.starts_with("# end CLIR ")&&payload.find("\n# end CLIR ")==string::npos,
            "overlapping artifact boundaries");
    return {begin,finish};
}
string effective_artifact_source(const Continuity& state){
    auto text=state.source;
    for(const auto& [name,retained]:state.artifact_versions){
        if(retained.size()<2)continue;
        const auto active=state.artifacts.at(name);
        require(retained.contains(active),"missing active artifact receipt");
        for(const auto& digest:retained){
            const auto span=artifact_span(state.source,name,digest);
            if(digest!=active)
                for(size_t n=span.first;n<span.last;++n)if(text[n]!='\n')text[n]=' ';
        }
    }
    return text;
}
