#include "cl-c-api.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static cl_slice_v1 str(const char* p){return (cl_slice_v1){(const unsigned char*)p,strlen(p)};}
static cl_slice_v1 load(const char* path){
    FILE* f=fopen(path,"rb");
    assert(f&&!fseek(f,0,SEEK_END));
    const long n=ftell(f);
    assert(n>=0&&!fseek(f,0,SEEK_SET));
    unsigned char* p=malloc((size_t)n+1);
    assert(p&&fread(p,1,(size_t)n,f)==(size_t)n&&!fclose(f));
    return (cl_slice_v1){p,(size_t)n};
}
static cl_slice_v1 slice(cl_buffer_v1 b){return (cl_slice_v1){b.bytes,b.size};}
static void equal(cl_buffer_v1 b,cl_slice_v1 c){assert(b.size==c.size&&b.size&&!memcmp(b.bytes,c.bytes,c.size));}
static void absent(cl_buffer_v1 b){assert(!b.bytes&&!b.size);}
static const cl_eval_v1 enough={128,12000,2000000,2000000};
struct Data {
    cl_slice_v1 source,lock,lock_pin,data,archive,archive_pin,ir,goals,proof,changed,changed_pin,rebuild,api_change,api_change_pin;
    cl_workspace_dependency_v1 deps[2];
};
static void* exercise(void* raw){
    struct Data* d=raw;
    for(int iteration=0;iteration<3;++iteration){
        cl_buffer_v1 packed={0},out={0},err={0};
        assert(cl_workspace_pack_v1(d->source,d->lock,d->lock_pin,d->data,1,d->deps,2,&packed,&err)==CL_OK_V1);
        absent(err);equal(packed,d->archive);
        assert(cl_workspace_ir_v1(slice(packed),d->archive_pin,d->lock_pin,&out,&err)==CL_OK_V1);
        equal(out,d->ir);cl_free_v1(&out);
        assert(cl_workspace_proof_v1(slice(packed),d->archive_pin,d->lock_pin,d->goals,enough,&out,&err)==CL_OK_V1);
        equal(out,d->proof);cl_free_v1(&out);
        assert(cl_workspace_rebuild_v1(slice(packed),d->archive_pin,d->lock_pin,d->changed,d->changed_pin,&out,&err)==CL_OK_V1);
        equal(out,d->rebuild);cl_free_v1(&out);cl_free_v1(&packed);
        absent(err);
    }
    return NULL;
}
int main(int argc,char** argv){
    assert(argc==17);
    struct Data d={load(argv[1]),load(argv[2]),str(argv[3]),load(argv[4]),load(argv[5]),str(argv[6]),load(argv[7]),
                   load(argv[8]),load(argv[9]),load(argv[10]),str(argv[11]),load(argv[12]),load(argv[13]),str(argv[14]),
                   {{str("grants.clpkg"),load(argv[15])},{str("costs.clpkg"),load(argv[16])}}};
    const cl_slice_v1 bad=str("0000000000000000000000000000000000000000000000000000000000000000");
    cl_buffer_v1 out={0},err={0};
    cl_workspace_dependency_v1 dup[]={d.deps[0],d.deps[0]}, swapped[]={d.deps[0],d.deps[1]};
    swapped[0].package=d.deps[1].package;
    assert(cl_workspace_pack_v1(d.source,d.lock,d.lock_pin,d.data,1,dup,2,&out,&err)==CL_REJECTED_V1);
    absent(out);cl_free_v1(&err);
    assert(cl_workspace_pack_v1(d.source,d.lock,d.lock_pin,d.data,1,d.deps,1,&out,&err)==CL_REJECTED_V1);
    absent(out);cl_free_v1(&err);
    assert(cl_workspace_pack_v1(d.source,d.lock,d.lock_pin,d.data,1,swapped,2,&out,&err)==CL_REJECTED_V1);
    absent(out);cl_free_v1(&err);
    assert(cl_workspace_pack_v1(d.source,d.lock,d.lock_pin,d.data,0,d.deps,2,&out,&err)==CL_INVALID_V1);
    absent(out);cl_free_v1(&err);
    assert(cl_workspace_pack_v1(d.source,d.lock,d.lock_pin,d.data,1,NULL,2,&out,&err)==CL_INVALID_V1);
    absent(out);
    assert(cl_workspace_pack_v1(d.source,d.lock,bad,d.data,1,d.deps,2,&out,&err)==CL_REJECTED_V1);
    absent(out);cl_free_v1(&err);
    assert(cl_workspace_ir_v1(d.archive,bad,d.lock_pin,&out,&err)==CL_REJECTED_V1);
    absent(out);cl_free_v1(&err);
    assert(cl_workspace_ir_v1(d.archive,d.archive_pin,bad,&out,&err)==CL_REJECTED_V1);
    absent(out);cl_free_v1(&err);
    assert(cl_workspace_rebuild_v1(d.archive,d.archive_pin,d.lock_pin,d.changed,bad,&out,&err)==CL_REJECTED_V1);
    absent(out);cl_free_v1(&err);
    assert(cl_workspace_rebuild_v1(d.archive,d.archive_pin,d.lock_pin,d.api_change,d.api_change_pin,&out,&err)==CL_REJECTED_V1);
    absent(out);cl_free_v1(&err);
    cl_eval_v1 tiny=enough;tiny.facts=1;
    assert(cl_workspace_proof_v1(d.archive,d.archive_pin,d.lock_pin,d.goals,tiny,&out,&err)==CL_RESOURCE_V1);
    absent(out);cl_free_v1(&err);
    tiny.facts=0;
    assert(cl_workspace_proof_v1(d.archive,d.archive_pin,d.lock_pin,d.goals,tiny,&out,&err)==CL_INVALID_V1);
    absent(out);cl_free_v1(&err);
    pthread_t group[4];
    for(size_t i=0;i<4;++i)assert(!pthread_create(group+i,NULL,exercise,&d));
    for(size_t i=0;i<4;++i)assert(!pthread_join(group[i],NULL));
    const cl_slice_v1 files[]={d.source,d.lock,d.data,d.archive,d.ir,d.goals,d.proof,d.changed,d.rebuild,
        d.api_change,d.deps[0].package,d.deps[1].package};
    for(size_t i=0;i<sizeof files/sizeof(*files);++i)free((void*)files[i].bytes);
    return 0;
}
