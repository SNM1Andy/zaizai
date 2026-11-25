#include "cl-memory-api.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static cl_slice_v1 input(const char* path){
    FILE* f=fopen(path,"rb");assert(f);
    assert(fseek(f,0,SEEK_END)==0);const long n=ftell(f);
    assert(n>0&&n<16*1024*1024);
    assert(fseek(f,0,SEEK_SET)==0);
    unsigned char* out=malloc((size_t)n);assert(out);
    assert(fread(out,1,(size_t)n,f)==(size_t)n);assert(fclose(f)==0);
    return (cl_slice_v1){out,(size_t)n};
}
static cl_slice_v1 text(const char* s){return (cl_slice_v1){(const unsigned char*)s,strlen(s)};}
int main(int argc,char** argv){
    assert(argc==5&&cl_abi_version_v1()==1&&!(cl_runtime_features_v1()&CL_DURABLE_FILE_OPERATIONS_V1));
    const cl_slice_v1 workspace=input(argv[1]),goals=input(argv[4]);
    cl_buffer_v1 receipt={0},why={0};
    const cl_eval_v1 cap={128,12000,2000000,2000000};
    assert(cl_workspace_proof_v1(workspace,text(argv[2]),text(argv[3]),goals,cap,&receipt,&why)==CL_OK_V1);
    assert(fwrite(receipt.bytes,1,receipt.size,stdout)==receipt.size);
    cl_free_v1(&receipt);cl_free_v1(&why);
    free((void*)workspace.bytes);free((void*)goals.bytes);return 0;
}
