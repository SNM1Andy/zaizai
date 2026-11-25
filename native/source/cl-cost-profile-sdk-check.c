#include "cl-c-api.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static cl_slice_v1 read_file(const char* where){
    FILE* f=fopen(where,"rb");assert(f&&!fseek(f,0,SEEK_END));
    long n=ftell(f);assert(n>0&&!fseek(f,0,SEEK_SET));
    unsigned char* b=malloc((size_t)n);
    assert(b&&fread(b,1,(size_t)n,f)==(size_t)n&&!fclose(f));
    return (cl_slice_v1){b,(size_t)n};
}
static cl_slice_v1 text(const char* p){return (cl_slice_v1){(const unsigned char*)p,strlen(p)};}
static void same(cl_buffer_v1 out,cl_slice_v1 expected){
    assert(out.size==expected.size&&out.size&&!memcmp(out.bytes,expected.bytes,out.size));
}
int main(int argc,char** argv){
    assert(argc==10);
    cl_slice_v1 package=read_file(argv[1]),workspace=read_file(argv[3]),goals=read_file(argv[6]),
        package_expected=read_file(argv[7]),workspace_expected=read_file(argv[8]),capped=read_file(argv[9]);
    cl_eval_v1 cap={128,12000,2000000,2000000};
    cl_buffer_v1 out={0},err={0};
    assert(cl_package_profile_v1(package,text(argv[2]),goals,cap,&out,&err)==CL_OK_V1);same(out,package_expected);
    assert(!err.bytes);cl_free_v1(&out);
    assert(cl_workspace_profile_v1(workspace,text(argv[4]),text(argv[5]),goals,cap,&out,&err)==CL_OK_V1);
    same(out,workspace_expected);cl_free_v1(&out);
    cap.probes=1;
    assert(cl_package_profile_v1(package,text(argv[2]),goals,cap,&out,&err)==CL_OK_V1);same(out,capped);
    assert(!err.bytes);cl_free_v1(&out);
    assert(cl_package_profile_v1(package,text("wrong"),goals,cap,&out,&err)==CL_REJECTED_V1&&!out.bytes);
    assert(err.size);cl_free_v1(&err);
    const cl_slice_v1 buffers[]={package,workspace,goals,package_expected,workspace_expected,capped};
    for(size_t i=0;i<sizeof buffers/sizeof(*buffers);++i)free((void*)buffers[i].bytes);
}
