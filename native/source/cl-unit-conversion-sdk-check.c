#include "cl-c-api.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static cl_slice_v1 text(const char* p){return (cl_slice_v1){(const unsigned char*)p,strlen(p)};}
static cl_slice_v1 load(const char* p){
    FILE* f=fopen(p,"rb");assert(f&&!fseek(f,0,SEEK_END));
    long n=ftell(f);assert(n>0&&!fseek(f,0,SEEK_SET));
    unsigned char* bytes=malloc((size_t)n);
    assert(bytes&&fread(bytes,1,(size_t)n,f)==(size_t)n&&!fclose(f));
    return (cl_slice_v1){bytes,(size_t)n};
}
int main(int argc,char** argv){
    assert(argc==6);
    cl_slice_v1 archive=load(argv[1]),goals=load(argv[4]),want=load(argv[5]);
    cl_eval_v1 cap={128,12000,2000000,2000000};
    cl_buffer_v1 out={0},err={0};
    assert(cl_workspace_proof_v1(archive,text(argv[2]),text(argv[3]),goals,cap,&out,&err)==CL_OK_V1);
    assert(!err.bytes&&out.size==want.size&&!memcmp(out.bytes,want.bytes,out.size));
    cl_free_v1(&out);
    cap.indexed=1;
    assert(cl_workspace_proof_v1(archive,text(argv[2]),text(argv[3]),goals,cap,&out,&err)==CL_RESOURCE_V1);
    assert(!out.bytes&&err.size);
    cl_free_v1(&err);
    free((void*)archive.bytes);free((void*)goals.bytes);free((void*)want.bytes);
}
