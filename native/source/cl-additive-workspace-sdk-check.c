#include "cl-c-api.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static cl_slice_v1 s(const char* p){return (cl_slice_v1){(const unsigned char*)p,strlen(p)};}
static cl_slice_v1 file(const char* p){
    FILE* r=fopen(p,"rb");assert(r&&!fseek(r,0,SEEK_END));
    long n=ftell(r);assert(n>0&&!fseek(r,0,SEEK_SET));
    unsigned char* bytes=malloc((size_t)n);
    assert(bytes&&fread(bytes,1,(size_t)n,r)==(size_t)n&&!fclose(r));
    return (cl_slice_v1){bytes,(size_t)n};
}
int main(int argc,char** argv){
    assert(argc==9);
    cl_slice_v1 base=file(argv[1]),source=file(argv[4]),goals=file(argv[6]),expected=file(argv[8]);
    cl_buffer_v1 out={0},err={0};
    int result=cl_workspace_branch_additive_v1(base,s(argv[2]),s(argv[3]),source,s(argv[5]),goals,s(argv[7]),&out,&err);
    assert(result==CL_OK_V1&&!err.bytes&&out.size==expected.size&&!memcmp(out.bytes,expected.bytes,out.size));
    cl_free_v1(&out);
    assert(cl_workspace_rebuild_v1(base,s(argv[2]),s(argv[3]),source,s(argv[5]),&out,&err)==CL_REJECTED_V1);
    assert(!out.bytes&&err.size);cl_free_v1(&err);
    assert(cl_workspace_branch_additive_v1(base,s(argv[2]),s(argv[3]),source,s(argv[5]),goals,s("bad"),
                     &out,&err)==CL_REJECTED_V1&&!out.bytes&&err.size);
    cl_free_v1(&err);
    const cl_slice_v1 own[]={base,source,goals,expected};
    for(size_t i=0;i<sizeof own/sizeof(*own);++i)free((void*)own[i].bytes);
}
