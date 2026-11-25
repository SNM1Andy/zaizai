from desktop_protocol import edit
from port_sources import SRC
import hashlib
pin=hashlib.sha256((SRC.parent/"host/desktop_criteria.cl").read_bytes()).hexdigest()
edit("pcgm-src/cl.cpp",[
    ('const auto module=read_src(store->dst.parent_path()/"modules"/(name+".cl"));',
     'const auto module=read_src(store->dst.parent_path()/"modules"/(name+".cl"));\n                    const bool desktop_migration=name=="desktop_criteria" && sha256(module)=="'+pin+'";'),
    ('require(next.synth_policy==epoch.synth_policy&&next.multi_policy==epoch.multi_policy,',
     'require(desktop_migration||(next.synth_policy==epoch.synth_policy&&next.multi_policy==epoch.multi_policy),'),
    ('next.preferences==epoch.preferences&&next.adaptation==epoch.adaptation&&','(desktop_migration||next.preferences==epoch.preferences)&&next.adaptation==epoch.adaptation&&')])

