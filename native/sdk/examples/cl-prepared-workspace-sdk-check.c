#define _POSIX_C_SOURCE 200809L
#include "cl-memory-api.h"
#include <assert.h>
#include <inttypes.h>
#include "windows_reader.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

typedef struct {unsigned char* bytes;size_t size;} Owned;
static Owned read_payload(const char* path){
    FILE* f=fopen(path,"rb");assert(f);
    assert(!fseek(f,0,SEEK_END));const long n=ftell(f);assert(n>0&&n<=16*1024*1024);
    rewind(f);unsigned char* p=malloc((size_t)n);assert(p);
    assert(fread(p,1,(size_t)n,f)==(size_t)n&&!fclose(f));
    return (Owned){p,(size_t)n};
}
static cl_slice_v1 as_slice(Owned b){return (cl_slice_v1){b.bytes,b.size};}
static cl_slice_v1 text(const char* s){return (cl_slice_v1){(const unsigned char*)s,strlen(s)};}
static uint64_t ticks(void){
    LARGE_INTEGER counter, frequency;
    assert(QueryPerformanceFrequency(&frequency) && QueryPerformanceCounter(&counter));
    return (uint64_t)(counter.QuadPart/frequency.QuadPart)*UINT64_C(1000000000)
        + (uint64_t)(counter.QuadPart%frequency.QuadPart)*UINT64_C(1000000000)/(uint64_t)frequency.QuadPart;
}
static int cmp_ns(const void* lhs,const void* rhs){
    const uint64_t a=*(const uint64_t*)lhs,b=*(const uint64_t*)rhs;
    return (int)(a>b)-(int)(b>a);
}
static void equal(cl_buffer_v1 got,Owned want){
    assert(got.size==want.size&&got.bytes&&!memcmp(got.bytes,want.bytes,want.size));
}
typedef struct {
    const cl_prepared_workspace_v1* handle;
    cl_slice_v1 pin;
    Owned goals,expected;
} Job;
static void* concurrent_read(void* in){
    const Job* job=in;
    for(unsigned i=0;i<24;++i){
        cl_buffer_v1 out={0},why={0};
        assert(cl_prepared_workspace_proof_v1(job->handle,job->pin,as_slice(job->goals),&out,&why)==CL_OK_V1);
        assert(!why.bytes);equal(out,job->expected);
        cl_free_v1(&out);
    }
    return NULL;
}
int main(int argc,char** argv){
    assert(_setmode(_fileno(stdout),_O_BINARY)!=-1);
    assert(argc==11&&cl_abi_version_v1()==1);
    const uint32_t feature=cl_runtime_features_v1();
    assert((feature&CL_PREPARED_WORKSPACE_V1)&&!(feature&CL_DURABLE_FILE_OPERATIONS_V1));
    Owned a=read_payload(argv[1]),b=read_payload(argv[4]);
    const size_t a_size=a.size;
    const cl_slice_v1 pin_a=text(argv[2]),pin_b=text(argv[5]),lock=text(argv[3]);
    const cl_slice_v1 wrong=text("0000000000000000000000000000000000000000000000000000000000000000");
    const cl_eval_v1 ceiling={128,12000,2000000,2000000};
    cl_prepared_workspace_v1 *one=NULL,*two=NULL,*invalid=NULL;
    cl_buffer_v1 why={0},out={0};
    assert(cl_workspace_prepare_v1(as_slice(a),wrong,lock,ceiling,&invalid,&why)==CL_REJECTED_V1&&why.bytes&&!invalid);
    cl_free_v1(&why);
    assert(cl_workspace_prepare_v1(as_slice(a),pin_a,wrong,ceiling,&invalid,&why)==CL_REJECTED_V1&&why.bytes&&!invalid);
    cl_free_v1(&why);
    const cl_eval_v1 too_low={128,1024,2000000,2000000};
    assert(cl_workspace_prepare_v1(as_slice(a),pin_a,lock,too_low,&invalid,&why)==CL_RESOURCE_V1&&why.bytes&&!invalid);
    cl_free_v1(&why);
    const cl_eval_v1 zero={0,12000,2000000,2000000};
    assert(cl_workspace_prepare_v1(as_slice(a),pin_a,lock,zero,&invalid,&why)==CL_INVALID_V1&&why.bytes&&!invalid);
    cl_free_v1(&why);
    const uint64_t begin=ticks();
    assert(cl_workspace_prepare_v1(as_slice(a),pin_a,lock,ceiling,&one,&why)==CL_OK_V1&&one&&!why.bytes);
    const uint64_t prepare_ns=ticks()-begin;
    assert(cl_workspace_prepare_v1(as_slice(a),pin_a,lock,ceiling,&one,&why)==CL_INVALID_V1&&one);
    assert(cl_workspace_prepare_v1(as_slice(b),pin_b,lock,ceiling,&two,&why)==CL_OK_V1&&two&&!why.bytes);
    assert(cl_prepared_workspace_proof_v1(one,pin_b,text("output(x0)\n"),&out,&why)==CL_REJECTED_V1&&why.bytes&&!out.bytes);
    cl_free_v1(&why);
    assert(cl_prepared_workspace_proof_v1(one,pin_a,text("output(3)\n"),&out,&why)==CL_REJECTED_V1&&why.bytes&&!out.bytes);
    cl_free_v1(&why);
    const Owned g1=read_payload(argv[6]),a1=read_payload(argv[7]),g2=read_payload(argv[8]),
                a2=read_payload(argv[9]),b1=read_payload(argv[10]);
    enum {SAMPLES=15};
    uint64_t repeat[SAMPLES],cold[SAMPLES];
    for(size_t i=0;i<SAMPLES;++i){
        const uint64_t t=ticks();
        assert(cl_workspace_proof_v1(as_slice(a),pin_a,lock,as_slice(g1),ceiling,&out,&why)==CL_OK_V1);
        cold[i]=ticks()-t;assert(!why.bytes);equal(out,a1);cl_free_v1(&out);
        const uint64_t u=ticks();
        assert(cl_prepared_workspace_proof_v1(one,pin_a,as_slice(g1),&out,&why)==CL_OK_V1);
        repeat[i]=ticks()-u;assert(!why.bytes);equal(out,a1);cl_free_v1(&out);
    }
    memset(a.bytes,0,a.size);free(a.bytes);
    memset(b.bytes,0,b.size);free(b.bytes);
    const Job job[6]={{one,pin_a,g1,a1},{one,pin_a,g2,a2},{two,pin_b,g1,b1},
                      {one,pin_a,g2,a2},{two,pin_b,g1,b1},{one,pin_a,g1,a1}};
    HANDLE threads[6];
    for(size_t i=0;i<6;++i)assert(!start_reader(&threads[i],concurrent_read,(void*)&job[i]));
    for(size_t i=0;i<6;++i)assert(!join_reader(threads[i]));
    cl_prepared_workspace_close_v1(&one);cl_prepared_workspace_close_v1(&two);
    assert(!one&&!two);
    cl_prepared_workspace_close_v1(&one);
    assert(cl_prepared_workspace_proof_v1(one,pin_a,as_slice(g1),&out,&why)==CL_INVALID_V1&&!out.bytes);
    cl_free_v1(&why);
    free(g1.bytes);free(g2.bytes);free(a1.bytes);free(a2.bytes);free(b1.bytes);
    qsort(cold,SAMPLES,sizeof(*cold),cmp_ns);qsort(repeat,SAMPLES,sizeof(*repeat),cmp_ns);
    printf("{\"archive_bytes\":%zu,\"samples\":%d,\"prepare_ns\":%" PRIu64
           ",\"oneshot_median_ns\":%" PRIu64 ",\"prepared_median_ns\":%" PRIu64 "}\n",
           a_size,SAMPLES,prepare_ns,cold[SAMPLES/2],repeat[SAMPLES/2]);
}
