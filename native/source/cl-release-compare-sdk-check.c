#include "cl-c-api.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static cl_slice_v1 sl(const char* s){return (cl_slice_v1){(const unsigned char*)s,strlen(s)};}
static cl_slice_v1 read_file(const char* p){
    FILE* f=fopen(p,"rb");assert(f&&!fseek(f,0,SEEK_END));
    long n=ftell(f);assert(n>0&&!fseek(f,0,SEEK_SET));
    unsigned char* bytes=malloc((size_t)n);
    assert(bytes&&fread(bytes,1,(size_t)n,f)==(size_t)n&&!fclose(f));
    return (cl_slice_v1){bytes,(size_t)n};
}
int main(int argc,char** argv){
    assert(argc==7);
    cl_slice_v1 base=read_file(argv[1]),old=sl(argv[2]),cand=read_file(argv[3]),next=sl(argv[4]),
        goals=read_file(argv[5]),expected=read_file(argv[6]);
    cl_eval_v1 full={128,12000,2000000,2000000};
    cl_buffer_v1 o={0},e={0};
    assert(cl_compare_packages_v1(base,old,cand,next,goals,full,&o,&e)==CL_OK_V1);
    assert(!e.bytes&&o.size==expected.size&&!memcmp(o.bytes,expected.bytes,o.size));
    cl_free_v1(&o);
    assert(cl_compare_packages_v1(base,next,cand,next,goals,full,&o,&e)==CL_REJECTED_V1&&!o.bytes&&e.size);
    cl_free_v1(&e);
    full.facts=1;
    assert(cl_compare_packages_v1(base,old,cand,next,goals,full,&o,&e)==CL_RESOURCE_V1&&!o.bytes&&e.size);
    cl_free_v1(&e);
    full.facts=0;
    assert(cl_compare_packages_v1(base,old,cand,next,goals,full,&o,&e)==CL_INVALID_V1&&!o.bytes&&e.size);
    cl_free_v1(&e);
    const cl_slice_v1 bytes[]={base,cand,goals,expected};
    for(size_t i=0;i<sizeof bytes/sizeof(*bytes);++i)free((void*)bytes[i].bytes);
}
