from features import edit,change
# Bind an independent result to the current request within the native dialogue transaction.
change("pcgm-src/dialogue.inc",lambda s:s.replace('    }else require(q.action==', '''    }else if(q.action=="record"){
        p.ws();string digest=p.s.substr(p.i);p.i=p.s.size();
        require(digest.size()==65&&digest[0]=='h'&&hex_chars(digest.substr(1)),"invalid desktop result hash");
        q.canonical+=" "+digest;
    }else require(q.action==''').replace('    if(q.action=="clear"){','''    if(q.action=="record")return "recorded "+q.canonical.substr(7)+"\\n";
    if(q.action=="clear"){'''))
edit("pcgm-src/cl.cpp",[('        if(argc>=2&&string(argv[1])=="--frozen-question-review"){','''        if(argc==3&&string(argv[1])=="--desktop-snapshot"){
            StateStore store(fs::absolute(argv[2]),false);
            string head;auto s=store.load(&head);
            cout<<"{\\"individual\\":"<<quote_json(s.id)<<",\\"owner\\":"<<quote_json(s.owner)
                <<",\\"head\\":"<<quote_json(head)<<",\\"source\\":"<<quote_json(s.source)<<",\\"inactive\\":[";
            bool first=true;for(const auto& id:s.inactive){if(!first)cout<<',';cout<<quote_json(id);first=false;}
            cout<<"]}\\n";return 0;
        }
        if(argc>=2&&string(argv[1])=="--frozen-question-review"){''')])


