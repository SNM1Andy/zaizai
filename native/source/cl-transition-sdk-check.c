#include "cl-memory-api.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static cl_slice_v1 input(const char* path){
    FILE *f=fopen(path,"rb");assert(f);
    assert(fseek(f,0,SEEK_END)==0);
    const long n=ftell(f);assert(n>0&&n<=2*1024*1024);
    assert(fseek(f,0,SEEK_SET)==0);
    unsigned char* out=malloc((size_t)n);assert(out);
    assert(fread(out,1,(size_t)n,f)==(size_t)n);assert(fclose(f)==0);
    return (cl_slice_v1){out,(size_t)n};
}
static cl_slice_v1 text(const char* s){return (cl_slice_v1){(const unsigned char*)s,strlen(s)};}
static void dump(cl_buffer_v1* v){
    assert(v->bytes&&v->size);
    assert(printf("%zu\n",v->size)>0);
    assert(fwrite(v->bytes,1,v->size,stdout)==v->size);
    cl_free_v1(v);
}
int main(int argc,char** argv){
    assert((argc==5||argc==8)&&cl_abi_version_v1()==1);
    assert((cl_runtime_features_v1()&CL_EVIDENCE_TRANSITIONS_V1)!=0);
    assert((cl_runtime_features_v1()&CL_DURABLE_FILE_OPERATIONS_V1)==0);
    const cl_slice_v1 pkg=input(argv[2]), pin=text(argv[3]), goals=input(argv[4]);
    cl_buffer_v1 out={0},receipt={0},proof={0},why={0};
    if(argc==5){
        assert(strcmp(argv[1],"init")==0);
        int code=cl_evidence_buffer_init_v1(pkg,pin,goals,&out,&why);
        if(code!=CL_OK_V1){fprintf(stderr,"%.*s\n",(int)why.size,why.bytes);return 1;}
        dump(&out);
    }else{
        const cl_slice_v1 prior=input(argv[5]), basis=text(argv[6]), frame=text(argv[7]);
        if(strcmp(argv[1],"seal")==0){
            assert(cl_evidence_freeze_v1(pkg,pin,goals,prior,basis,&out,&why)==CL_OK_V1);
            dump(&out);
        }else if(strcmp(argv[1],"verify")==0){
            assert(cl_evidence_verify_v1(prior,basis,pin,frame,&out,&why)==CL_OK_V1);
            dump(&out);
        }else{
            assert(cl_evidence_buffer_batch_v1(pkg,pin,goals,prior,basis,frame,&out,&out,&proof,&why)==CL_INVALID_V1);
            const int code=cl_evidence_buffer_batch_v1(pkg,pin,goals,prior,basis,frame,&out,&receipt,&proof,&why);
            if(strcmp(argv[1],"reject")==0){
                assert(code!=CL_OK_V1&&!out.bytes&&!out.size&&!receipt.bytes&&!receipt.size&&!proof.bytes&&!proof.size);
                dump(&why);
            }else{
                assert(strcmp(argv[1],"batch")==0);
                if(code!=CL_OK_V1){fprintf(stderr,"%.*s\n",(int)why.size,why.bytes);return 1;}
                dump(&out);dump(&receipt);dump(&proof);
            }
        }
        free((void*)prior.bytes);
    }
    cl_free_v1(&why);free((void*)pkg.bytes);free((void*)goals.bytes);
    return 0;
}
