from win_release import edit
from port_sources import change
change("cl-src/modules.inc",lambda s:s.replace("push(units.at(root),data,lines,true);",
                                               "push(units.at(root),fs::canonical(data),lines,true);"))
edit("pcgm-src/cl.cpp",[
    ("_setmode(0,_O_BINARY);_setmode(1,_O_BINARY);","_setmode(0,_O_TEXT);_setmode(1,_O_BINARY);"),
    ('        if(argc==3&&string(argv[1])=="--desktop-snapshot"){','''        if(argc==2&&string(argv[1])=="--field-selfcheck"){
            GeometricRuntime first,replay;
            cout<<"primordial_set={";
            bool comma=false;
            for(const auto& d:instinct::primordial_directions){if(comma)cout<<",";cout<<d;comma=true;}
            cout<<"} kind=unordered direction_only\\n";
            cout<<"initial "<<first.status()<<'\\n';
            first.begin(GeometricRuntime::index(GeometricRuntime::contexts,"quiet"));
            first.apply(GeometricRuntime::index(GeometricRuntime::actions,"wait"));
            replay.replay({GeometricRuntime::init_event,"field_tick quiet wait"});
            require(first.status()==replay.status(),"geometry replay differs");
            cout<<"replayed "<<replay.status()<<'\\n';return 0;
        }
        if(argc==3&&string(argv[1])=="--desktop-snapshot"){''')])

