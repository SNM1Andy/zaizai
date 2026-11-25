#include "cl-memory-api.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static cl_slice_v1 input(const char* path){
    FILE* f=fopen(path,"rb");assert(f);
    assert(fseek(f,0,SEEK_END)==0);const long n=ftell(f);
    assert(n>0&&n<=8*1024*1024);
    assert(fseek(f,0,SEEK_SET)==0);
    unsigned char* out=malloc((size_t)n);assert(out);
    assert(fread(out,1,(size_t)n,f)==(size_t)n);assert(fclose(f)==0);
    return (cl_slice_v1){out,(size_t)n};
}
static cl_slice_v1 text(const char* s){return (cl_slice_v1){(const unsigned char*)s,strlen(s)};}
int main(int argc,char** argv){
    assert(argc==7 && cl_abi_version_v1()==1);
    assert((cl_runtime_features_v1()&CL_CHECKPOINT_AUDIT_V1)!=0);
    assert((cl_runtime_features_v1()&CL_DURABLE_FILE_OPERATIONS_V1)==0);
    const cl_slice_v1 p=input(argv[2]), goals=input(argv[4]), checkpoint=input(argv[5]);
    cl_buffer_v1 result={0},why={0};
    const cl_eval_v1 cap={128,12000,2000000,2000000};
    const int code=cl_package_checkpoint_audit_v1(p,text(argv[3]),goals,checkpoint,text(argv[6]),cap,&result,&why);
    if(strcmp(argv[1],"valid")==0){
        assert(code==CL_OK_V1&&result.size&&!why.size);
        assert(fwrite(result.bytes,1,result.size,stdout)==result.size);
    }else{
        assert(strcmp(argv[1],"invalid")==0&&code==CL_REJECTED_V1&&!result.bytes&&why.size);
        assert(fwrite(why.bytes,1,why.size,stderr)==why.size);
    }
    free((void*)p.bytes);free((void*)goals.bytes);free((void*)checkpoint.bytes);
    cl_free_v1(&result);cl_free_v1(&why);return 0;
}
