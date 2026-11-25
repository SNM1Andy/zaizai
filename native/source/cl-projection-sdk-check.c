#include "cl-c-api.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static cl_slice_v1 ascii(const char* p){return (cl_slice_v1){(const unsigned char*)p,strlen(p)};}
static cl_slice_v1 file(const char* path){
    FILE* f=fopen(path,"rb");assert(f&&!fseek(f,0,SEEK_END));
    const long n=ftell(f);assert(n>0&&!fseek(f,0,SEEK_SET));
    unsigned char* bytes=malloc((size_t)n);
    assert(bytes&&fread(bytes,1,(size_t)n,f)==(size_t)n&&!fclose(f));
    return (cl_slice_v1){bytes,(size_t)n};
}
static void equal(cl_buffer_v1 a,cl_slice_v1 b){assert(a.size==b.size&&a.size&&!memcmp(a.bytes,b.bytes,a.size));}
static int less(const void* aa,const void* bb){
    const cl_projection_row_v1* a=aa;
    const cl_projection_row_v1* b=bb;
    for(size_t i=0;i<4;++i){if(a->key[i]!=b->key[i])return a->key[i]<b->key[i]?-1:1;}
    return (a->ticket>b->ticket)-(a->ticket<b->ticket);
}
enum Mode {proper, out_of_range, duplicate, reverse, incomplete, decline, isolated, reentrant};
struct Fixture {
    cl_slice_v1 pkg,pin,goals,pkg_proof,archive,archive_pin,lock_pin,archive_proof;
};
struct Offer {
    enum Mode mode;
    struct Fixture* data;
    unsigned count;
};
static int offer(void* opaque,const cl_projection_row_v1* rows,uint32_t n,uint32_t width,uint32_t* order){
    struct Offer* state=opaque;
    ++state->count;
    assert(rows&&order&&n>=192&&n<=12000&&width>=1&&width<=4);
    if(state->mode==decline)return 7;
    cl_projection_row_v1* reorder=malloc((size_t)n*sizeof(*reorder));assert(reorder);
    memcpy(reorder,rows,(size_t)n*sizeof(*reorder));
    qsort(reorder,n,sizeof(*reorder),less);
    for(uint32_t i=0;i<(state->mode==incomplete?n-1:n);++i)
        order[i]=reorder[state->mode==reverse?n-1-i:i].ticket;
    if(state->mode==out_of_range) order[n-1]=n+5;
    if(state->mode==duplicate) order[n-1]=order[0];
    if(state->mode==isolated){
        // This pointer references the SDK's mutable outbound copy; its private verifier retains separate rows.
        cl_projection_row_v1* exposed=(cl_projection_row_v1*)rows;
        exposed[0].key[0]=0;
        exposed[n-1].ticket=n+9;
    }
    if(state->mode==reentrant){
        cl_buffer_v1 nested={0},e={0};
        assert(cl_package_proof_v1(state->data->pkg,state->data->pin,state->data->goals,&nested,&e)==CL_OK_V1);
        equal(nested,state->data->pkg_proof);
        cl_free_v1(&nested);assert(!e.bytes);
    }
    free(reorder);return 0;
}
static const cl_eval_v1 ceilings={128,12000,2000000,2000000};
static void* exercise(void* raw){
    struct Fixture* f=raw;
    for(int i=proper;i<=reentrant;++i){
        for(int workspace=0;workspace<=1;++workspace){
            struct Offer call={(enum Mode)i,f,0};
            cl_projection_stats_v1 stats={0};
            cl_buffer_v1 out={0},e={0};
            int rc=workspace?cl_workspace_proof_with_projection_v1(f->archive,f->archive_pin,f->lock_pin,f->goals,ceilings,
                    offer,&call,&stats,&out,&e):cl_package_proof_with_projection_v1(f->pkg,f->pin,f->goals,ceilings,
                    offer,&call,&stats,&out,&e);
            assert(rc==CL_OK_V1&&!e.bytes);
            equal(out,workspace?f->archive_proof:f->pkg_proof);
            assert(stats.attempted==call.count&&call.count>0);
            if(i==proper||i==isolated||i==reentrant)assert(stats.verified==call.count&&!stats.cpu_fallback);
            else assert(!stats.verified&&stats.cpu_fallback==call.count);
            cl_free_v1(&out);
        }
    }
    cl_projection_stats_v1 stats={99,99,99};
    cl_buffer_v1 out={0},e={0};
    assert(cl_package_proof_with_projection_v1(f->pkg,f->pin,f->goals,ceilings,NULL,NULL,&stats,&out,&e)==CL_OK_V1);
    equal(out,f->pkg_proof);
    assert(!stats.attempted&&!stats.verified&&!stats.cpu_fallback&&!e.bytes);
    cl_free_v1(&out);
    struct Offer call={proper,f,0};
    cl_eval_v1 tiny=ceilings;tiny.indexed=100;
    assert(cl_package_proof_with_projection_v1(f->pkg,f->pin,f->goals,tiny,offer,&call,&stats,&out,&e)==CL_RESOURCE_V1);
    assert(!out.bytes&&!out.size&&e.size&&!stats.attempted&&!call.count);
    cl_free_v1(&e);
    return NULL;
}
int main(int argc,char** argv){
    assert(argc==9&&cl_abi_version_v1()==1);
    struct Fixture f={file(argv[1]),ascii(argv[2]),file(argv[3]),file(argv[4]),
            file(argv[5]),ascii(argv[6]),ascii(argv[7]),file(argv[8])};
    pthread_t workers[4];
    for(unsigned i=0;i<4;++i)assert(!pthread_create(&workers[i],NULL,exercise,&f));
    for(unsigned i=0;i<4;++i)assert(!pthread_join(workers[i],NULL));
    const cl_slice_v1 files[]={f.pkg,f.goals,f.pkg_proof,f.archive,f.archive_proof};
    for(unsigned i=0;i<sizeof files/sizeof(*files);++i)free((void*)files[i].bytes);
}
