#include "cl-c-api.h"
#include "cl-native.hpp"
#include "native-projection.hpp"
#include <cstdlib>
#include <cstring>
#include <new>
#include <stdexcept>
#include <string>
namespace {
std::string bytes(cl_slice_v1 range, size_t max){
    if(range.size>max || (!range.bytes&&range.size))throw std::invalid_argument("invalid CL input buffer or size");
    return range.size?std::string(reinterpret_cast<const char*>(range.bytes),range.size):std::string{};
}
void set(cl_buffer_v1* dst,const char* value,size_t size){
    if(!dst||!size)return;
    auto* p=static_cast<unsigned char*>(std::malloc(size));
    if(!p)throw std::bad_alloc();
    std::memcpy(p,value,size);
    dst->bytes=p;dst->size=size;
}
int error(cl_buffer_v1* diagnostic,const char* message,int code) noexcept{
    try {set(diagnostic,message,std::strlen(message));return code;}
    catch(...){return CL_MEMORY_V1;}
}
template<class Fn> int invoke(cl_buffer_v1* out,cl_buffer_v1* diagnostic,Fn fn) noexcept{
    if(!out||out==diagnostic||out->bytes||out->size||(diagnostic&&(diagnostic->bytes||diagnostic->size)))
        return CL_INVALID_V1;
    try{const auto result=fn();set(out,result.data(),result.size());return CL_OK_V1;}
    catch(const std::bad_alloc&){return CL_MEMORY_V1;}
    catch(const cl_native::EvidenceCommitUncertain& e){return error(diagnostic,e.what(),CL_UNCERTAIN_V1);}
    catch(const cl_native::EvaluationLimit& e){return error(diagnostic,e.what(),CL_RESOURCE_V1);}
    catch(const std::invalid_argument& e){return error(diagnostic,e.what(),CL_INVALID_V1);}
    catch(const std::exception& e){return error(diagnostic,e.what(),CL_REJECTED_V1);}
    catch(...){return error(diagnostic,"unknown CL engine error",CL_REJECTED_V1);}
}
}
uint32_t cl_abi_version_v1(void){return 1;}
uint32_t cl_runtime_features_v1(void){
#ifdef CL_PORTABLE_MEMORY_CORE
    return CL_BUFFER_OPERATIONS_V1|CL_EVIDENCE_TRANSITIONS_V1|CL_CHECKPOINT_AUDIT_V1|CL_PROFILE_REBUILD_V1|CL_PREPARED_WORKSPACE_V1|CL_FROZEN_INTEGRITY_V1;
#else
    return CL_BUFFER_OPERATIONS_V1|CL_DURABLE_FILE_OPERATIONS_V1|CL_EVIDENCE_TRANSITIONS_V1|CL_CHECKPOINT_AUDIT_V1|CL_PROFILE_REBUILD_V1|CL_PREPARED_WORKSPACE_V1|CL_FROZEN_INTEGRITY_V1;
#endif
}
void cl_free_v1(cl_buffer_v1* buf){if(buf){std::free(buf->bytes);*buf={nullptr,0};}}
int cl_package_ir_v1(cl_slice_v1 package,cl_slice_v1 expected,cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{
        return cl_native::pinned_package_ir_bytes(bytes(package,2*1024*1024),bytes(expected,64));
    });
}
int cl_profile_compile_v1(cl_slice_v1 profile,cl_slice_v1 profile_pin,cl_slice_v1 source,cl_slice_v1 source_pin,
                         cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{
        auto result=cl_native::build_profile_bytes(bytes(profile,2*1024*1024),bytes(profile_pin,64),
                                                    bytes(source,256*1024),bytes(source_pin,64));
        return result.ir;
    });
}
namespace {
cl_native::PinnedProfileInput profile_pin(cl_pinned_buffer_v1 in, size_t max){
    return {bytes(in.contents,max), bytes(in.pin,64)};
}
cl_native::ProfileRebuildInputs rebuild_inputs(const cl_profile_rebuild_inputs_v1* in){
    if(!in)throw std::invalid_argument("missing CL profile rebuild inputs");
    constexpr size_t text=256*1024;
    return {profile_pin(in->baseline,1024*1024),profile_pin(in->grammar,text),profile_pin(in->types,text),
            profile_pin(in->lower,text),profile_pin(in->smoke,text),bytes(in->smoke_ir_pin,64)};
}
bool empty_output(cl_buffer_v1* out){return out&&!out->bytes&&!out->size;}
}
int cl_profile_rebuild_v1(const cl_profile_rebuild_inputs_v1* inputs,
                          cl_buffer_v1* candidate,cl_buffer_v1* receipt,cl_buffer_v1* why){
    if(!empty_output(candidate)||!empty_output(receipt)||candidate==receipt||
       (why&&(!empty_output(why)||why==candidate||why==receipt)))return CL_INVALID_V1;
    cl_buffer_v1 unused{};
    return invoke(&unused,why,[&]{
        const auto result=cl_native::rebuild_compiler_profile_bytes(rebuild_inputs(inputs));
        struct Pending{
            cl_buffer_v1 candidate{},receipt{};
            ~Pending(){cl_free_v1(&candidate);cl_free_v1(&receipt);}
        } pending;
        set(&pending.candidate,result.candidate.data(),result.candidate.size());
        set(&pending.receipt,result.receipt.data(),result.receipt.size());
        const std::string done;
        *candidate=pending.candidate;*receipt=pending.receipt;
        pending.candidate={};pending.receipt={};
        return done;
    });
}
int cl_profile_rebuild_audit_v1(const cl_profile_rebuild_inputs_v1* inputs,
              cl_pinned_buffer_v1 candidate,cl_pinned_buffer_v1 receipt,cl_buffer_v1* output,cl_buffer_v1* why){
    return invoke(output,why,[&]{
        return cl_native::audit_rebuilt_compiler_profile_bytes(rebuild_inputs(inputs),
                                    profile_pin(candidate,1024*1024),profile_pin(receipt,8192));
    });
}
int cl_package_proof_v1(cl_slice_v1 package,cl_slice_v1 expected,cl_slice_v1 goals,cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{
        auto receipt=cl_native::offline_proof_bytes(bytes(package,2*1024*1024),bytes(expected,64),bytes(goals,32*1024));
        if(receipt.size()>4*1024*1024)throw std::runtime_error("CL receipt exceeds size limit");
        return receipt;
    });
}
int cl_package_proof_bounded_v1(cl_slice_v1 package,cl_slice_v1 expected,cl_slice_v1 goals,
                                 cl_eval_v1 cap,cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{
        auto receipt=cl_native::offline_proof_bounded_bytes(bytes(package,2*1024*1024),bytes(expected,64),
                                  bytes(goals,32*1024),{cap.rounds,cap.facts,cap.probes,cap.indexed});
        if(receipt.size()>4*1024*1024)throw std::runtime_error("CL receipt exceeds size limit");
        return receipt;
    });
}
int cl_package_checkpoint_audit_v1(cl_slice_v1 package,cl_slice_v1 package_pin,cl_slice_v1 goals,
                   cl_slice_v1 checkpoint,cl_slice_v1 checkpoint_pin,cl_eval_v1 cap,
                   cl_buffer_v1* receipt,cl_buffer_v1* why){
    return invoke(receipt,why,[&]{
        return cl_native::audit_package_checkpoint(bytes(package,2*1024*1024),bytes(package_pin,64),
               bytes(goals,32*1024),bytes(checkpoint,8*1024*1024),bytes(checkpoint_pin,64),
               {cap.rounds,cap.facts,cap.probes,cap.indexed});
    });
}
int cl_evidence_buffer_init_v1(cl_slice_v1 package,cl_slice_v1 pin,cl_slice_v1 goals,
                               cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{
        return cl_native::init_evidence_buffer(bytes(package,2*1024*1024),bytes(pin,64),bytes(goals,32*1024));
    });
}
int cl_evidence_buffer_batch_v1(cl_slice_v1 package,cl_slice_v1 pin,cl_slice_v1 goals,cl_slice_v1 prior,
                               cl_slice_v1 basis,cl_slice_v1 frame,cl_buffer_v1* out,cl_buffer_v1* receipt,
                               cl_buffer_v1* proof,cl_buffer_v1* why){
    auto empty=[](cl_buffer_v1* b){return b&&!b->bytes&&!b->size;};
    if(!empty(out)||!empty(receipt)||!empty(proof)||out==receipt||out==proof||receipt==proof||
       (why&&(!empty(why)||why==out||why==receipt||why==proof)))return CL_INVALID_V1;
    cl_buffer_v1 unused{};
    return invoke(&unused,why,[&]{
        const auto next=cl_native::evolve_evidence_buffer(bytes(package,2*1024*1024),bytes(pin,64),
                        bytes(goals,32*1024),bytes(prior,512*1024),bytes(basis,64),bytes(frame,4096));
        struct Accumulated {
            cl_buffer_v1 snapshot{},receipt{},proof{};
            ~Accumulated(){cl_free_v1(&snapshot);cl_free_v1(&receipt);cl_free_v1(&proof);}
        } pending;
        set(&pending.snapshot,next.snapshot.data(),next.snapshot.size());
        set(&pending.receipt,next.receipt.data(),next.receipt.size());
        set(&pending.proof,next.proof.data(),next.proof.size());
        const std::string done;
        *out=pending.snapshot;*receipt=pending.receipt;*proof=pending.proof;
        pending.snapshot={};pending.receipt={};pending.proof={};
        return done;
    });
}
int cl_evidence_freeze_v1(cl_slice_v1 package,cl_slice_v1 trusted_package,cl_slice_v1 goals,cl_slice_v1 journal,
                           cl_slice_v1 trusted_journal,cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{
        return cl_native::seal_frozen_evidence(bytes(package,2*1024*1024),bytes(trusted_package,64),
                bytes(goals,32*1024),bytes(journal,512*1024),bytes(trusted_journal,64));
    });
}
int cl_evidence_verify_v1(cl_slice_v1 artifact,cl_slice_v1 trusted_artifact,cl_slice_v1 trusted_package,
                           cl_slice_v1 trusted_journal,cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{
        return cl_native::verify_frozen_evidence(bytes(artifact,5*1024*1024),bytes(trusted_artifact,64),
                 bytes(trusted_package,64),bytes(trusted_journal,64));
    });
}


int cl_evidence_integrity_v1(cl_slice_v1 artifact,cl_slice_v1 trusted_artifact,cl_slice_v1 trusted_package,
                              cl_slice_v1 trusted_journal,cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{
        return cl_native::verify_frozen_integrity(bytes(artifact,5*1024*1024),bytes(trusted_artifact,64),
                  bytes(trusted_package,64),bytes(trusted_journal,64));
    });
}

#ifndef CL_PORTABLE_MEMORY_CORE
struct cl_evidence_session_v1 {std::unique_ptr<cl_native::EvidenceSession> active;};
int cl_evidence_session_open_v1(cl_slice_v1 package,cl_slice_v1 trusted,cl_slice_v1 goals,cl_slice_v1 path,
                                unsigned create,cl_evidence_session_v1** session,cl_buffer_v1* why){
    if(!session||*session||create>1)return CL_INVALID_V1;
    cl_buffer_v1 unused{};
    return invoke(&unused,why,[&]{
        auto owned=std::make_unique<cl_evidence_session_v1>();
        owned->active=cl_native::open_evidence_session(bytes(package,2*1024*1024),bytes(trusted,64),
                bytes(goals,32*1024),bytes(path,4096),create==1);
        *session=owned.release();
        return std::string{};
    });
}
int cl_evidence_session_command_v1(cl_evidence_session_v1* session,cl_slice_v1 frame,cl_buffer_v1* out,cl_buffer_v1* why){
    if(!session||!session->active)return CL_INVALID_V1;
    return invoke(out,why,[&]{return session->active->command(bytes(frame,4096));});
}
void cl_evidence_session_close_v1(cl_evidence_session_v1** session){
    if(session){delete *session;*session=nullptr;}
}

struct cl_evidence_audit_v1 {std::unique_ptr<cl_native::EvidenceSession> active;};
int cl_evidence_audit_open_v1(cl_slice_v1 package,cl_slice_v1 trusted,cl_slice_v1 goals,cl_slice_v1 path,
                              cl_evidence_audit_v1** audit,cl_buffer_v1* why){
    if(!audit||*audit)return CL_INVALID_V1;
    cl_buffer_v1 unused{};
    return invoke(&unused,why,[&]{
        auto owned=std::make_unique<cl_evidence_audit_v1>();
        owned->active=cl_native::open_evidence_audit(bytes(package,2*1024*1024),bytes(trusted,64),
                bytes(goals,32*1024),bytes(path,4096));
        *audit=owned.release();
        return std::string{};
    });
}
int cl_evidence_audit_command_v1(cl_evidence_audit_v1* audit,cl_slice_v1 frame,
                                 cl_buffer_v1* out,cl_buffer_v1* why){
    if(!audit||!audit->active)return CL_INVALID_V1;
    return invoke(out,why,[&]{return audit->active->command(bytes(frame,4096));});
}
void cl_evidence_audit_close_v1(cl_evidence_audit_v1** audit){
    if(audit){delete *audit;*audit=nullptr;}
}

#endif
int cl_workspace_pack_v1(cl_slice_v1 source,cl_slice_v1 lock,cl_slice_v1 pin,cl_slice_v1 data,
        unsigned present,const cl_workspace_dependency_v1* dependencies,size_t count,cl_buffer_v1* out,cl_buffer_v1* why){
    if(present>1||count>16||(!dependencies&&count)||(!present&&data.size))return CL_INVALID_V1;
    return invoke(out,why,[&]{
        std::vector<cl_native::WorkspacePackageBuffer> packages;
        size_t total=0;
        for(size_t i=0;i<count;++i){
            if(dependencies[i].package.size>2*1024*1024 || dependencies[i].package.size>16*1024*1024-total)
                throw std::invalid_argument("CL workspace dependency bytes exceed allocation cap");
            total+=dependencies[i].package.size;
            packages.push_back({bytes(dependencies[i].name,96),bytes(dependencies[i].package,2*1024*1024)});
        }
        return cl_native::pack_workspace_buffers(bytes(source,256*1024),bytes(lock,64*1024),bytes(pin,64),
                        bytes(data,256*1024),present!=0,std::move(packages));
    });
}
int cl_workspace_ir_v1(cl_slice_v1 archive,cl_slice_v1 archive_pin,cl_slice_v1 lock_pin,cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{return cl_native::pinned_workspace_ir_bytes(bytes(archive,16*1024*1024),
                 bytes(archive_pin,64),bytes(lock_pin,64));});
}
int cl_workspace_proof_v1(cl_slice_v1 archive,cl_slice_v1 archive_pin,cl_slice_v1 lock_pin,cl_slice_v1 goals,
                         cl_eval_v1 cap,cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{return cl_native::workspace_proof_bounded_bytes(bytes(archive,16*1024*1024),
                 bytes(archive_pin,64),bytes(lock_pin,64),bytes(goals,32*1024),{cap.rounds,cap.facts,cap.probes,cap.indexed});});
}
struct cl_prepared_workspace_v1 {std::unique_ptr<const cl_native::PreparedWorkspace> impl;};
int cl_workspace_prepare_v1(cl_slice_v1 archive,cl_slice_v1 pin,cl_slice_v1 lock,cl_eval_v1 cap,
                            cl_prepared_workspace_v1** handle,cl_buffer_v1* why){
    if(!handle||*handle)return CL_INVALID_V1;
    cl_buffer_v1 unused{};
    return invoke(&unused,why,[&]{
        auto ready=cl_native::prepare_workspace(bytes(archive,16*1024*1024),bytes(pin,64),bytes(lock,64),
                                                {cap.rounds,cap.facts,cap.probes,cap.indexed});
        auto owned=std::make_unique<cl_prepared_workspace_v1>();
        owned->impl=std::move(ready);
        const std::string done;
        *handle=owned.release();
        return done;
    });
}
int cl_prepared_workspace_proof_v1(const cl_prepared_workspace_v1* handle,cl_slice_v1 expected,cl_slice_v1 goals,
                                   cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{
        if(!handle)throw std::invalid_argument("missing prepared workspace handle");
        return handle->impl->proof(bytes(expected,64),bytes(goals,32*1024));
    });
}
void cl_prepared_workspace_close_v1(cl_prepared_workspace_v1** handle){
    if(handle){delete *handle;*handle=nullptr;}
}
int cl_workspace_rebuild_v1(cl_slice_v1 archive,cl_slice_v1 archive_pin,cl_slice_v1 lock_pin,
                         cl_slice_v1 source,cl_slice_v1 source_pin,cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{return cl_native::rebuild_workspace_source(bytes(archive,16*1024*1024),
                 bytes(archive_pin,64),bytes(lock_pin,64),bytes(source,256*1024),bytes(source_pin,64)).archive;});
}

namespace {
struct ProjectionAdapter {
    cl_projection_offer_v1 host_fn;
    void* userdata;
};
bool offer_projection(void* opaque,const std::vector<native_projection::Row>& rows,unsigned width,
                      std::vector<std::uint32_t>& order){
    const auto& callback=*static_cast<const ProjectionAdapter*>(opaque);
    std::vector<cl_projection_row_v1> outbound;
    outbound.reserve(rows.size());
    for(const auto& row:rows)
        outbound.push_back({{row.key[0],row.key[1],row.key[2],row.key[3]},row.ticket});
    try{
        return callback.host_fn(callback.userdata,outbound.data(),static_cast<std::uint32_t>(outbound.size()),
                               width,order.data())==0;
    }catch(...){
        return false;
    }
}
template<typename Fn>
int projection_call(cl_projection_offer_v1 offer,void* userdata,cl_projection_stats_v1* stats,
                    cl_buffer_v1* out,cl_buffer_v1* why,Fn fn){
    ProjectionAdapter adapter{offer,userdata};
    native_projection::Selection route{offer?offer_projection:nullptr,&adapter};
    native_projection::SelectionScope scope(&route);
    const auto result=invoke(out,why,[&]{
        auto proof=fn();
        if(proof.size()>4*1024*1024)throw std::runtime_error("CL receipt exceeds size limit");
        return proof;
    });
    if(stats)*stats={route.attempted,route.verified,route.fallback};
    return result;
}
}
int cl_package_proof_with_projection_v1(cl_slice_v1 package,cl_slice_v1 pkg_pin,cl_slice_v1 goals,
         cl_eval_v1 cap,cl_projection_offer_v1 offer,void* userdata,cl_projection_stats_v1* stats,
         cl_buffer_v1* out,cl_buffer_v1* why){
    return projection_call(offer,userdata,stats,out,why,[&]{
        return cl_native::offline_proof_bounded_bytes(bytes(package,2*1024*1024),bytes(pkg_pin,64),
                 bytes(goals,32*1024),{cap.rounds,cap.facts,cap.probes,cap.indexed});
    });
}
int cl_workspace_proof_with_projection_v1(cl_slice_v1 archive,cl_slice_v1 archive_pin,
         cl_slice_v1 lock,cl_slice_v1 goals,cl_eval_v1 cap,cl_projection_offer_v1 offer,
         void* userdata,cl_projection_stats_v1* stats,cl_buffer_v1* out,cl_buffer_v1* why){
    return projection_call(offer,userdata,stats,out,why,[&]{
        return cl_native::workspace_proof_bounded_bytes(bytes(archive,16*1024*1024),bytes(archive_pin,64),
                 bytes(lock,64),bytes(goals,32*1024),{cap.rounds,cap.facts,cap.probes,cap.indexed});
    });
}

int cl_compare_packages_v1(cl_slice_v1 baseline,cl_slice_v1 baseline_pin,cl_slice_v1 candidate,
      cl_slice_v1 candidate_pin,cl_slice_v1 goals,cl_eval_v1 cap,cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{return cl_native::compare_verified_packages(bytes(baseline,2*1024*1024),
            bytes(baseline_pin,64),bytes(candidate,2*1024*1024),bytes(candidate_pin,64),bytes(goals,32*1024),
            {cap.rounds,cap.facts,cap.probes,cap.indexed});});
}

int cl_workspace_branch_additive_v1(cl_slice_v1 baseline,cl_slice_v1 baseline_pin,cl_slice_v1 lock,
      cl_slice_v1 source,cl_slice_v1 source_pin,cl_slice_v1 goals,cl_slice_v1 goals_pin,
      cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{return cl_native::fork_workspace_additive(bytes(baseline,16*1024*1024),
            bytes(baseline_pin,64),bytes(lock,64),bytes(source,256*1024),bytes(source_pin,64),
            bytes(goals,32*1024),bytes(goals_pin,64));});
}

int cl_package_profile_v1(cl_slice_v1 package,cl_slice_v1 pin,cl_slice_v1 goals,cl_eval_v1 cap,
                          cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{return cl_native::profile_package_cost(bytes(package,2*1024*1024),bytes(pin,64),
              bytes(goals,32*1024),{cap.rounds,cap.facts,cap.probes,cap.indexed});});
}
int cl_workspace_profile_v1(cl_slice_v1 archive,cl_slice_v1 pin,cl_slice_v1 lock,cl_slice_v1 goals,cl_eval_v1 cap,
                            cl_buffer_v1* out,cl_buffer_v1* why){
    return invoke(out,why,[&]{return cl_native::profile_workspace_cost(bytes(archive,16*1024*1024),bytes(pin,64),
              bytes(lock,64),bytes(goals,32*1024),{cap.rounds,cap.facts,cap.probes,cap.indexed});});
}
