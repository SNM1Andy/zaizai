#include "cl-memory-api.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static cl_slice_v1 text(const char* p){return (cl_slice_v1){(const unsigned char*)p,strlen(p)};}
static cl_slice_v1 bytes(const char* p){
    FILE* f=fopen(p,"rb");assert(f&&!fseek(f,0,SEEK_END));
    const long n=ftell(f);assert(n>0&&!fseek(f,0,SEEK_SET));
    unsigned char* s=malloc((size_t)n);
    assert(s&&fread(s,1,(size_t)n,f)==(size_t)n&&!fclose(f));
    return (cl_slice_v1){s,(size_t)n};
}
static void same(cl_buffer_v1 b,cl_slice_v1 s){
    assert(b.size==s.size&&b.size&&!memcmp(b.bytes,s.bytes,s.size));
}
static cl_slice_v1 slice(cl_buffer_v1 b){return (cl_slice_v1){b.bytes,b.size};}
int main(int argc,char** argv){
    assert(argc==11&&cl_abi_version_v1()==1&&cl_runtime_features_v1()==(CL_BUFFER_OPERATIONS_V1|CL_EVIDENCE_TRANSITIONS_V1|CL_CHECKPOINT_AUDIT_V1|CL_PROFILE_REBUILD_V1|CL_PREPARED_WORKSPACE_V1|CL_FROZEN_INTEGRITY_V1));
    cl_slice_v1 package=bytes(argv[1]),package_pin=text(argv[2]),goal=bytes(argv[3]),old=bytes(argv[4]),
        journal=bytes(argv[5]),journal_pin=text(argv[6]),seal=bytes(argv[7]),seal_pin=text(argv[8]),
        actual=bytes(argv[9]),profile=bytes(argv[10]);
    cl_buffer_v1 out={0},err={0},artifact={0};
    cl_eval_v1 cap={128,12000,2000000,2000000};
    assert(cl_package_proof_v1(package,package_pin,goal,&out,&err)==CL_OK_V1);
    same(out,old);cl_free_v1(&out);
    assert(cl_evidence_freeze_v1(package,package_pin,goal,journal,journal_pin,&artifact,&err)==CL_OK_V1);
    same(artifact,seal);
    assert(cl_evidence_verify_v1(slice(artifact),seal_pin,package_pin,journal_pin,&out,&err)==CL_OK_V1);
    same(out,actual);cl_free_v1(&out);cl_free_v1(&artifact);
    assert(cl_package_profile_v1(package,package_pin,goal,cap,&out,&err)==CL_OK_V1);
    same(out,profile);cl_free_v1(&out);
    assert(cl_evidence_freeze_v1(package,package_pin,goal,journal,text("not a digest"),&out,&err)==CL_REJECTED_V1);
    assert(!out.bytes&&err.size);cl_free_v1(&err);
    const cl_slice_v1 readings[]={package,goal,old,journal,seal,actual,profile};
    for(size_t i=0;i<sizeof readings/sizeof(*readings);++i)free((void*)readings[i].bytes);
}
