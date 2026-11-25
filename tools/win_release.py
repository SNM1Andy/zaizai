"""Rebuild the deployed Windows source from the upstream package and local port."""
from final_port import edit
from port_sources import SRC
edit("pcgm-src/cl.cpp",[
    ('require(current=="open"&&question_pin(state,packet.ticket,q->second,current,&epoch,&table)==packet.pin,',
     '''const bool counter=(current=="answered" && packet.evidence==opposite_of(q->second.fact)) ||
                                       (current=="opposed" && packet.evidence==q->second.fact);
                    const bool independent=std::ranges::none_of(state.wire_receipts,[&](const auto& item){
                        return item.second.ticket==packet.ticket && item.second.source==packet.source;
                    });
                    require((current=="open" || (counter&&independent)) &&
                            question_pin(state,packet.ticket,q->second,current,&epoch,&table)==packet.pin,'''),
    (r'\"evaluation_backend\":\"cpu\",',r'\"evaluation_backend\":\"cpu\",\"projection_backend\":\"guarded_cuda_or_cpu\",\"gpu_policy\":{\"reserve_mib\":3072,\"stop_c\":87,\"load_target\":99},')])
edit("cl-src/capabilities.inc",[(r'\"evaluation_backend\":\"cpu\",',r'\"evaluation_backend\":\"cpu\",\"projection_backend\":\"guarded_cuda_or_cpu\",\"gpu_policy\":{\"reserve_mib\":3072,\"stop_c\":87,\"load_target\":99},')])

