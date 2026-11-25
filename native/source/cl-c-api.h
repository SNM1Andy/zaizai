#ifndef CL_C_API_H
#define CL_C_API_H
#include <stddef.h>
#include <stdint.h>
#if defined(_WIN32) && defined(CL_BUILD_DLL)
#define CL_API __declspec(dllexport)
#elif defined(__GNUC__)
#define CL_API __attribute__((visibility("default")))
#else
#define CL_API
#endif
#ifdef __cplusplus
extern "C" {
#endif
typedef struct {const unsigned char* bytes; size_t size;} cl_slice_v1;
typedef struct {unsigned char* bytes; size_t size;} cl_buffer_v1;
enum cl_result_v1 {CL_OK_V1=0, CL_REJECTED_V1=1, CL_INVALID_V1=2, CL_MEMORY_V1=3, CL_RESOURCE_V1=4, CL_UNCERTAIN_V1=5};
CL_API uint32_t cl_abi_version_v1(void);
enum cl_runtime_features_v1 { CL_BUFFER_OPERATIONS_V1=1, CL_DURABLE_FILE_OPERATIONS_V1=2, CL_EVIDENCE_TRANSITIONS_V1=4, CL_CHECKPOINT_AUDIT_V1=8, CL_PROFILE_REBUILD_V1=16, CL_PREPARED_WORKSPACE_V1=32, CL_FROZEN_INTEGRITY_V1=64 };
CL_API uint32_t cl_runtime_features_v1(void);

/* Output and optional diagnostic must not alias and must initially be empty. The caller receives ownership of returned bytes; release them only with cl_free_v1. */
CL_API int cl_package_ir_v1(cl_slice_v1 package, cl_slice_v1 trusted_digest, cl_buffer_v1* output, cl_buffer_v1* error);
CL_API int cl_profile_compile_v1(cl_slice_v1 profile, cl_slice_v1 trusted_profile_digest, cl_slice_v1 source,
                                cl_slice_v1 trusted_source_digest, cl_buffer_v1* output, cl_buffer_v1* error);
/* The pure compiler produces an unapplied successor and its receipt. Callers keep
   ownership of their active profile. The offline audit independently rebuilds both
   from exact pins; neither operation validates a signer or commits state. */
typedef struct {cl_slice_v1 contents, pin;} cl_pinned_buffer_v1;
typedef struct {
    cl_pinned_buffer_v1 baseline, grammar, types, lower, smoke;
    cl_slice_v1 smoke_ir_pin;
} cl_profile_rebuild_inputs_v1;
CL_API int cl_profile_rebuild_v1(const cl_profile_rebuild_inputs_v1* inputs,
                cl_buffer_v1* candidate, cl_buffer_v1* receipt, cl_buffer_v1* error);
CL_API int cl_profile_rebuild_audit_v1(const cl_profile_rebuild_inputs_v1* inputs,
                cl_pinned_buffer_v1 candidate, cl_pinned_buffer_v1 receipt,
                cl_buffer_v1* verified_receipt, cl_buffer_v1* error);
CL_API int cl_package_proof_v1(cl_slice_v1 package, cl_slice_v1 trusted_digest, cl_slice_v1 goals,
                                cl_buffer_v1* output, cl_buffer_v1* error);
typedef struct {uint32_t rounds, facts, probes, indexed;} cl_eval_v1;
CL_API int cl_package_proof_bounded_v1(cl_slice_v1 package, cl_slice_v1 trusted_digest, cl_slice_v1 goals,
                                       cl_eval_v1 ceilings, cl_buffer_v1* output, cl_buffer_v1* error);
/* Re-run the exact unfinished prefix; receipt attests consistency, not signer identity. */
CL_API int cl_package_checkpoint_audit_v1(cl_slice_v1 package,cl_slice_v1 package_pin,cl_slice_v1 goals,
                   cl_slice_v1 checkpoint,cl_slice_v1 checkpoint_pin,cl_eval_v1 ceilings,
                   cl_buffer_v1* receipt,cl_buffer_v1* error);
/* The buffer API does not persist anything. Inputs and all output descriptors must be distinct from
 * output storage. Initialize output descriptors to zero, free successful results with cl_free_v1.
 * Apply only if the application still owns its exact expected head. All outputs stay empty on error. */
CL_API int cl_evidence_buffer_init_v1(cl_slice_v1 package, cl_slice_v1 pinned_package, cl_slice_v1 goals,
                                     cl_buffer_v1* snapshot, cl_buffer_v1* error);
CL_API int cl_evidence_buffer_batch_v1(cl_slice_v1 package, cl_slice_v1 pinned_package, cl_slice_v1 goals,
                            cl_slice_v1 prior, cl_slice_v1 pinned_prior, cl_slice_v1 frame,
                            cl_buffer_v1* snapshot, cl_buffer_v1* receipt, cl_buffer_v1* proof, cl_buffer_v1* error);
CL_API int cl_evidence_freeze_v1(cl_slice_v1 package, cl_slice_v1 trusted_package,
                                  cl_slice_v1 goals, cl_slice_v1 journal, cl_slice_v1 trusted_journal,
                                  cl_buffer_v1* output, cl_buffer_v1* error);
CL_API int cl_evidence_verify_v1(cl_slice_v1 artifact, cl_slice_v1 trusted_artifact,
                                  cl_slice_v1 trusted_package, cl_slice_v1 trusted_journal,
                                  cl_buffer_v1* output, cl_buffer_v1* error);
/* Pure buffer verification of both the signed proof and the disputed proof graph.
   The three trusted SHA-256 pins must come independently from the caller.
   Same report bytes as evidence-frozen-integrity, without a subprocess or state write. */
CL_API int cl_evidence_integrity_v1(cl_slice_v1 artifact, cl_slice_v1 trusted_artifact,
                                   cl_slice_v1 trusted_package, cl_slice_v1 trusted_journal,
                                   cl_buffer_v1* output, cl_buffer_v1* error);
#if !defined(CL_PORTABLE_MEMORY_CORE) && !defined(CL_MEMORY_HEADERS_ONLY)
typedef struct cl_evidence_session_v1 cl_evidence_session_v1;
/* Only one live writer may hold a journal. A command may return a valid JSON rejection. Do not close during a call. */
CL_API int cl_evidence_session_open_v1(cl_slice_v1 package, cl_slice_v1 trusted_package,
           cl_slice_v1 goals, cl_slice_v1 journal_path, unsigned create, cl_evidence_session_v1** session, cl_buffer_v1* error);
CL_API int cl_evidence_session_command_v1(cl_evidence_session_v1* session, cl_slice_v1 frame,
                                         cl_buffer_v1* output, cl_buffer_v1* error);
CL_API void cl_evidence_session_close_v1(cl_evidence_session_v1** session);
typedef struct cl_evidence_audit_v1 cl_evidence_audit_v1;
/* Read-only audit has no writer lock. Check command JSON and save next_cursor with next_prefix_sha256. */
CL_API int cl_evidence_audit_open_v1(cl_slice_v1 package,cl_slice_v1 trusted_package,
                       cl_slice_v1 goals,cl_slice_v1 journal_path,cl_evidence_audit_v1** audit,cl_buffer_v1* error);
CL_API int cl_evidence_audit_command_v1(cl_evidence_audit_v1* audit,cl_slice_v1 frame,
                                       cl_buffer_v1* output,cl_buffer_v1* error);
CL_API void cl_evidence_audit_close_v1(cl_evidence_audit_v1** audit);
#endif
typedef struct {cl_slice_v1 name, package;} cl_workspace_dependency_v1;
/* Dependency names are logical lock labels, never file paths. data_present distinguishes absent from empty. */
CL_API int cl_workspace_pack_v1(cl_slice_v1 source, cl_slice_v1 lock, cl_slice_v1 trusted_lock,
      cl_slice_v1 data, unsigned data_present, const cl_workspace_dependency_v1* dependencies, size_t count,
      cl_buffer_v1* output, cl_buffer_v1* error);
CL_API int cl_workspace_ir_v1(cl_slice_v1 archive, cl_slice_v1 trusted_archive, cl_slice_v1 trusted_lock,
      cl_buffer_v1* output, cl_buffer_v1* error);
CL_API int cl_workspace_proof_v1(cl_slice_v1 archive, cl_slice_v1 trusted_archive, cl_slice_v1 trusted_lock,
      cl_slice_v1 goals, cl_eval_v1 ceilings, cl_buffer_v1* output, cl_buffer_v1* error);
typedef struct cl_prepared_workspace_v1 cl_prepared_workspace_v1;
/* Performs full bounded link and inference once from owned copies of the inputs.
   Initialize *handle to NULL. Calls to proof may run concurrently; close must
   wait for them, releases the handle, and sets *handle to NULL. Every read supplies
   the expected archive pin to protect against using a distinct generation. */
CL_API int cl_workspace_prepare_v1(cl_slice_v1 archive,cl_slice_v1 trusted_archive,
      cl_slice_v1 trusted_lock,cl_eval_v1 ceilings,cl_prepared_workspace_v1** handle,cl_buffer_v1* error);
CL_API int cl_prepared_workspace_proof_v1(const cl_prepared_workspace_v1* handle,
      cl_slice_v1 trusted_archive,cl_slice_v1 goals,cl_buffer_v1* proof,cl_buffer_v1* error);
CL_API void cl_prepared_workspace_close_v1(cl_prepared_workspace_v1** handle);
CL_API int cl_workspace_rebuild_v1(cl_slice_v1 baseline, cl_slice_v1 trusted_baseline, cl_slice_v1 trusted_lock,
      cl_slice_v1 source, cl_slice_v1 trusted_source, cl_buffer_v1* output, cl_buffer_v1* error);
/* Synchronous in-process callback (trusted C code), not a sandbox. A successful callback
   returns zero and fills exactly row_count order entries. Rows and order are only valid
   during the call. Neither buffer contains source strings or an authority to apply anything. */
typedef struct {uint32_t key[4]; uint32_t ticket;} cl_projection_row_v1;
typedef int (*cl_projection_offer_v1)(void* userdata, const cl_projection_row_v1* rows,
         uint32_t row_count, uint32_t key_width, uint32_t* order);
typedef struct {uint32_t attempted,verified,cpu_fallback;} cl_projection_stats_v1;
CL_API int cl_package_proof_with_projection_v1(cl_slice_v1 package, cl_slice_v1 trusted_package, cl_slice_v1 goals,
         cl_eval_v1 ceilings, cl_projection_offer_v1 offer, void* userdata, cl_projection_stats_v1* stats,
         cl_buffer_v1* output, cl_buffer_v1* error);
CL_API int cl_workspace_proof_with_projection_v1(cl_slice_v1 archive, cl_slice_v1 trusted_archive,
         cl_slice_v1 trusted_lock, cl_slice_v1 goals, cl_eval_v1 ceilings, cl_projection_offer_v1 offer,
         void* userdata, cl_projection_stats_v1* stats, cl_buffer_v1* output, cl_buffer_v1* error);
CL_API int cl_compare_packages_v1(cl_slice_v1 baseline, cl_slice_v1 trusted_baseline, cl_slice_v1 candidate,
      cl_slice_v1 trusted_candidate, cl_slice_v1 goals, cl_eval_v1 ceilings, cl_buffer_v1* output, cl_buffer_v1* error);
CL_API int cl_workspace_branch_additive_v1(cl_slice_v1 baseline, cl_slice_v1 trusted_baseline,
      cl_slice_v1 trusted_lock, cl_slice_v1 source, cl_slice_v1 trusted_source,
      cl_slice_v1 goals, cl_slice_v1 trusted_goals, cl_buffer_v1* output, cl_buffer_v1* error);
/* A resource-limited profile is a valid diagnostic document with complete=false, not a proof. */
CL_API int cl_package_profile_v1(cl_slice_v1 package, cl_slice_v1 trusted_package, cl_slice_v1 goals,
      cl_eval_v1 ceilings, cl_buffer_v1* output, cl_buffer_v1* error);
CL_API int cl_workspace_profile_v1(cl_slice_v1 archive, cl_slice_v1 trusted_archive, cl_slice_v1 trusted_lock,
      cl_slice_v1 goals, cl_eval_v1 ceilings, cl_buffer_v1* output, cl_buffer_v1* error);
CL_API void cl_free_v1(cl_buffer_v1* buffer);
#ifdef __cplusplus
}
#endif
#endif
