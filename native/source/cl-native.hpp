#pragma once
#include <string>
#include <stdexcept>
#include <cstddef>
#include <vector>
#include <memory>
namespace cl_native {
struct EvaluationLimit : std::runtime_error {using std::runtime_error::runtime_error;};
struct EvaluationCeilings {std::size_t rounds, facts, probes, indexed;};
enum class EvidenceSign {Positive,Negative,Conflict,Unknown};
// Compile a bounded in-memory CL slice and prove its declared goals in CL order.
std::vector<std::string> checked_repair_statuses(const std::string& source);
struct SingleGoalProof {EvidenceSign sign;std::string receipt;};
std::string verify_frozen_integrity(const std::string& raw,const std::string& trusted_artifact,
                                    const std::string& trusted_package,const std::string& trusted_snapshot);
struct CheckedFrozenIntegrity {
    EvidenceSign sign;
    bool clean_single;
    std::string signed_receipt, integrity_receipt;
};
CheckedFrozenIntegrity offline_frozen_integrity_single_goal(const std::string& raw,
    const std::string& artifact, const std::string& package, const std::string& snapshot, const std::string& goal);

SingleGoalProof offline_single_goal_bounded(const std::string& package,const std::string& expected,const std::string& goal,
                                            const EvaluationCeilings& ceilings);
std::string audit_package_checkpoint(const std::string& package,const std::string& trusted_package,
                const std::string& goals,const std::string& saved,const std::string& trusted_checkpoint,
                const EvaluationCeilings& limits);
std::string offline_proof_bounded_bytes(const std::string& package,const std::string& expected,const std::string& goals,
                                        const EvaluationCeilings& ceilings);
std::string offline_proof_bytes(const std::string& package,const std::string& expected,const std::string& goals);
SingleGoalProof offline_frozen_single_goal(const std::string& artifact,const std::string& expected_artifact,
        const std::string& expected_package,const std::string& expected_snapshot,const std::string& exact_goal);
struct EvidenceBufferTransition {std::string snapshot,receipt,proof;};
std::string init_evidence_buffer(const std::string& package,const std::string& trusted_package,const std::string& goals);
EvidenceBufferTransition evolve_evidence_buffer(const std::string& package,const std::string& trusted_package,
             const std::string& goals,const std::string& prior,const std::string& trusted_prior,const std::string& frame);
std::string seal_frozen_evidence(const std::string& package,const std::string& trusted_package,const std::string& goals,
                                 const std::string& journal,const std::string& trusted_snapshot);
std::string verify_frozen_evidence(const std::string& artifact,const std::string& trusted_artifact,
                                   const std::string& trusted_package,const std::string& trusted_snapshot);
std::string compare_verified_packages(const std::string& old_bytes,const std::string& old_pin,
        const std::string& new_bytes,const std::string& new_pin,const std::string& goals,const EvaluationCeilings& ceilings);
std::string profile_package_cost(const std::string& package,const std::string& pin,const std::string& goals,
                               const EvaluationCeilings& limits);
std::string profile_workspace_cost(const std::string& archive,const std::string& pin,const std::string& lock,
                                  const std::string& goals,const EvaluationCeilings& limits);
struct VerifiedPackage {
    std::string ir;
    std::string package_sha256;
    std::string ir_sha256;
    std::string api_sha256;
    std::string scope_policy_sha256;
    std::string scope_report_sha256;
    std::string workspace_lock_sha256;
    std::string workspace_audit_sha256;
};
std::string pinned_package_ir_bytes(const std::string& bytes,const std::string& expected);
VerifiedPackage verify_package_bytes(const std::string& bytes);
VerifiedPackage verify_workspace_bytes(const std::string& bytes,const std::string& required_lock);
struct WorkspacePackageBuffer {std::string name,bytes;};
std::string pack_workspace_buffers(const std::string& source,const std::string& lock,
       const std::string& expected_lock,const std::string& data,bool has_data,
       std::vector<WorkspacePackageBuffer> packages);
std::string pinned_workspace_ir_bytes(const std::string& archive,const std::string& archive_pin,const std::string& lock_pin);
std::string workspace_proof_bounded_bytes(const std::string& archive,const std::string& archive_pin,
       const std::string& lock_pin,const std::string& goals, const EvaluationCeilings& ceilings);
struct PreparedWorkspace {
    virtual ~PreparedWorkspace()=default;
    virtual std::string proof(const std::string& expected_archive,const std::string& goals) const=0;
};
std::unique_ptr<const PreparedWorkspace> prepare_workspace(const std::string& archive,const std::string& archive_pin,
    const std::string& lock_pin,const EvaluationCeilings& limits);
SingleGoalProof workspace_single_goal_bounded(const std::string& archive,const std::string& archive_pin,
       const std::string& lock_pin,const std::string& goal, const EvaluationCeilings& ceilings);
struct WorkspaceRebuild {
    std::string archive;
    std::string source_sha256;
    VerifiedPackage product;
};
std::string fork_workspace_additive(const std::string& archive,const std::string& archive_expected,
       const std::string& lock,const std::string& candidate,const std::string& source_expected,
       const std::string& goals,const std::string& goals_pin);
WorkspaceRebuild rebuild_workspace_source(const std::string& archive,const std::string& archive_sha256,
       const std::string& dependency_lock_sha256,const std::string& candidate,const std::string& source_sha256);
WorkspaceRebuild synthesize_workspace_quantity(const std::string& original,const std::string& expected,
        const std::string& lock,const std::string& recipe,const std::string& recipe_pin,const std::string& boundary,
        const std::string& boundary_pin,const std::string& evidence);
struct WorkspaceEvidencePort {std::string name, source, predicate, unit;};
std::vector<WorkspaceEvidencePort> workspace_evidence_ports(const std::string& boundary);
struct EvidenceCommitUncertain : std::runtime_error {using std::runtime_error::runtime_error;};
struct EvidenceSession {
    virtual ~EvidenceSession()=default;
    virtual std::string command(const std::string& frame)=0;
};
std::unique_ptr<EvidenceSession> open_evidence_session(const std::string& package,const std::string& trusted_package,
                        const std::string& goals,const std::string& journal_path,bool create);
std::unique_ptr<EvidenceSession> open_evidence_audit(const std::string& package,const std::string& trusted_package,
                        const std::string& goals,const std::string& journal_path);
struct ProfileProduct {
    std::string ir;
    std::string profile_sha256;
    std::string source_sha256;
    std::string ir_sha256;
};
ProfileProduct build_profile_bytes(const std::string& profile,const std::string& expected_profile,
                                   const std::string& source,const std::string& expected_source);
struct PinnedProfileInput {std::string contents,pin;};
struct ProfileRebuildInputs {
    PinnedProfileInput baseline,grammar,types,lower,smoke;
    std::string smoke_ir_pin;
};
struct ProfileRebuildProduct {std::string candidate,receipt;};
ProfileRebuildProduct rebuild_compiler_profile_bytes(const ProfileRebuildInputs& input);
std::string audit_rebuilt_compiler_profile_bytes(const ProfileRebuildInputs& input,
        const PinnedProfileInput& candidate,const PinnedProfileInput& receipt);

struct EvidenceProduct {
    ProfileProduct product;
    std::string generator_sha256;
    std::string scope_sha256;
    std::string evidence_sha256;
};
EvidenceProduct synthesize_profile_bytes(const std::string& profile,const std::string& profile_digest,
        const std::string& base,const std::string& base_digest,const std::string& generator,
        const std::string& generator_digest,const std::string& scope,const std::string& scope_digest,
        const std::string& evidence);
}
