struct CsvRecord { size_t line; vector<string> cells; };
vector<CsvRecord> parse_csv(const string& original){
    const string raw=original.starts_with("\xef\xbb\xbf")?original.substr(3):original;
    require(!raw.empty(),"empty CSV");
    require(raw.find('\0')==string::npos,"NUL in CSV");
    vector<CsvRecord> rows;
    size_t i=0,line=1;
    while(i<raw.size()){
        CsvRecord row{line,{}};
        require(rows.size()<1025,"CSV rows limit");
        while(true){
            require(row.cells.size()<32,"CSV columns limit");
            string v;
            const bool quoted=i<raw.size()&&raw[i]=='"';
            if(quoted){
                ++i;bool closed=false;
                while(i<raw.size()){
                    char c=raw[i++];
                    if(c=='"'){
                        if(i<raw.size()&&raw[i]=='"'){v+='"';++i;}
                        else{closed=true;break;}
                    }else{
                        if(c=='\n')++line;
                        v+=c;
                    }
                }
                require(closed,"CSV line "+to_string(row.line)+": unterminated quoted field");
                require(i==raw.size()||raw[i]==','||raw[i]=='\r'||raw[i]=='\n',
                        "CSV line "+to_string(row.line)+": expected delimiter after closing quote");
            }else{
                while(i<raw.size()&&raw[i]!=','&&raw[i]!='\r'&&raw[i]!='\n'){
                    require(raw[i]!='"',"CSV line "+to_string(row.line)+": quote in unquoted field");
                    v+=raw[i++];
                }
            }
            require(v.size()<=4096,"CSV field limit");
            row.cells.push_back(std::move(v));
            if(i==raw.size())break;
            if(raw[i]==','){++i;continue;}
            if(raw[i]=='\r'){
                require(i+1<raw.size()&&raw[i+1]=='\n',"CSV requires LF or CRLF");
                ++i;
            }
            ++i;++line;
            break;
        }
        rows.push_back(std::move(row));
    }
    return rows;
}

string strict_csv_symbol(const string& s){
    Parser q{s};const auto v=q.name();q.end();
    require(v==s,"CSV symbol cannot include whitespace");
    return v;
}
string csv_predicate(const string& s){
    const auto i=s.find("::");
    if(i==string::npos)return strict_csv_symbol(s);
    return strict_csv_symbol(s.substr(0,i))+"::"+strict_csv_symbol(s.substr(i+2));
}
struct CsvBinding { string target,kind,unit,column; bool global=false; };
struct CsvMapping {string key;vector<CsvBinding> fields;};
CsvMapping parse_csv_mapping(const string& data){
    istringstream in(data);string line;
    require(bool(getline(in,line)),"CSV mapping is empty");
    if(line.ends_with('\r'))line.pop_back();
    require(line=="CL-CSV-1","unsupported CSV mapping format");
    CsvMapping m;
    set<string> targets,columns;
    while(getline(in,line)){
        istringstream row(line);string op,extra;
        if(!(row>>op))continue;
        if(op=="key"){
            string k;
            require(m.key.empty()&&bool(row>>k)&&!(row>>extra),"invalid or duplicate CSV key declaration");
            m.key=strict_csv_symbol(k);continue;
        }
        require(op=="value"||op=="review"||op=="global","unknown CSV mapping directive");
        CsvBinding field;field.global=op=="global";
        require(bool(row>>field.target),"CSV mapping target missing");
        field.target=csv_predicate(field.target);
        if(op=="review")field.kind=op;
        else{
            require(bool(row>>field.kind),"CSV value type missing");
            require(field.kind=="qty"||field.kind=="i64"||field.kind=="sym","unknown CSV value type");
            if(field.kind=="qty"){
                require(bool(row>>field.unit),"CSV unit missing");
                field.unit=strict_csv_symbol(field.unit);
            }
        }
        require(bool(row>>field.column)&&!(row>>extra),"invalid or missing CSV column");
        field.column=strict_csv_symbol(field.column);
        require(targets.insert(field.target).second&&columns.insert(field.column).second&&m.fields.size()<30,
                "duplicate or excessive CSV binding");
        m.fields.push_back(std::move(field));
    }
    require(!m.key.empty()&&!m.fields.empty()&&!columns.contains(m.key),"CSV mapping requires distinct key and fields");
    return m;
}

struct CsvFacts{
    vector<string> lines;
    vector<size_t> rows;
    map<string,string> origins;
};

CsvFacts extract_csv(const fs::path& path,const string& raw,const CsvMapping& mapping){
    const auto rows=parse_csv(raw);
    const auto& header=rows.front().cells;
    map<string,size_t> index;
    for(size_t i=0;i<header.size();++i)
        require(index.emplace(strict_csv_symbol(header[i]),i).second,"duplicate CSV column");
    require(index.size()==mapping.fields.size()+1&&index.contains(mapping.key),"CSV header does not match mapping");
    for(const auto& f:mapping.fields)require(index.contains(f.column),"CSV missing mapped column: "+f.column);
    set<string> keys;
    CsvFacts out;
    for(size_t i=1;i<rows.size();++i){
        const auto& row=rows[i];
        const auto where=path.filename().string()+":"+to_string(row.line);
        require(row.cells.size()==header.size(),where+": number of columns does not match header");
        string key;
        try{key=strict_csv_symbol(row.cells[index.at(mapping.key)]);}
        catch(const exception& e){throw runtime_error(where+":"+mapping.key+": "+e.what());}
        require(keys.insert(key).second,where+": duplicate row key");
        for(size_t j=0;j<mapping.fields.size();++j){
            const auto& f=mapping.fields[j];
            const auto& v=row.cells[index.at(f.column)];
            if(v.empty())continue; // Unknown, not a false or zero value.
            const auto origin=where+":"+f.column;
            const auto id="csv_"+key+"_"+to_string(j);
            require(id.size()<=46,origin+": observation ID exceeds length limit");
            auto emit=[&](const string& tag,const string& predicate,const string& term){
                const auto full=id+tag;
                out.lines.push_back("& "+full+" "+predicate+"("+(f.global?term:key+term)+").");
                out.rows.push_back(row.line);
                out.origins.emplace(full,origin);
            };
            try{
                if(f.kind=="review"){
                    require(v=="yes"||v=="no"||v=="conflict","expected yes, no, conflict or blank");
                    if(v!="no")emit("_p",f.target,"");
                    if(v!="yes")emit("_n","!"+f.target,"");
                }else{
                    const auto parsed=f.kind=="sym"?strict_csv_symbol(v):to_string(integer(v));
                    require(parsed==v,"noncanonical CSV integer");
                    emit("",f.target,(f.global?"":",")+parsed+(f.kind=="qty"?"@"+f.unit:""));
                }
            }catch(const exception& e){throw runtime_error(origin+": "+e.what());}
        }
    }
    return out;
}
