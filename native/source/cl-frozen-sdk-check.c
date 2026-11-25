#include "cl-c-api.h"
#include <assert.h>
#include <pthread.h>
#include <sched.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
typedef struct {
    cl_slice_v1 package, pkg_pin, goals, journal, snap_pin, artifact, art_pin, desired;
    atomic_int ready, start;
} Fixture;
static cl_slice_v1 as_text(const char* s){
    return (cl_slice_v1){(const unsigned char*)s,strlen(s)};
}
static cl_slice_v1 load(const char* name){
    FILE* f=fopen(name,"rb");assert(f);
    assert(fseek(f,0,SEEK_END)==0);
    const long n=ftell(f);assert(n>0&&n<=5*1024*1024);
    assert(fseek(f,0,SEEK_SET)==0);
    unsigned char* b=malloc((size_t)n);assert(b);
    assert(fread(b,1,(size_t)n,f)==(size_t)n&&fclose(f)==0);
    return (cl_slice_v1){b,(size_t)n};
}
static int same(cl_buffer_v1 out,cl_slice_v1 fixture){
    return out.size==fixture.size&&memcmp(out.bytes,fixture.bytes,out.size)==0;
}
static void* prove(void* argument){
    Fixture* f=argument;
    atomic_fetch_add(&f->ready,1);
    while(!atomic_load(&f->start))sched_yield();
    for(int i=0;i<3;++i){
        cl_buffer_v1 proof={0},error={0},sealed={0};
        assert(cl_evidence_freeze_v1(f->package,f->pkg_pin,f->goals,f->journal,f->snap_pin,&sealed,&error)==CL_OK_V1);
        assert(same(sealed,f->artifact)&&!error.size);
        cl_slice_v1 seal={sealed.bytes,sealed.size};
        assert(cl_evidence_verify_v1(seal,f->art_pin,f->pkg_pin,f->snap_pin,&proof,&error)==CL_OK_V1);
        assert(same(proof,f->desired)&&!error.size);
        cl_free_v1(&proof);cl_free_v1(&sealed);
        assert(!proof.bytes&&!proof.size&&!sealed.bytes&&!sealed.size);
    }
    return NULL;
}
int main(int argc,char** argv){
    assert(argc==4&&cl_abi_version_v1()==1);
    Fixture inputs={load("package"),as_text(argv[1]),load("goals"),load("journal"),as_text(argv[2]),
                    load("artifact"),as_text(argv[3]),load("expected"),ATOMIC_VAR_INIT(0),ATOMIC_VAR_INIT(0)};
    pthread_t readers[4];
    for(int i=0;i<4;++i)assert(pthread_create(&readers[i],NULL,prove,&inputs)==0);
    while(atomic_load(&inputs.ready)!=4)sched_yield();
    atomic_store(&inputs.start,1);
    for(int i=0;i<4;++i)assert(pthread_join(readers[i],NULL)==0);
    cl_buffer_v1 out={0},error={0};
    unsigned char zeros[64];memset(zeros,'0',sizeof zeros);
    assert(cl_evidence_verify_v1(inputs.artifact,(cl_slice_v1){zeros,sizeof zeros},inputs.pkg_pin,inputs.snap_pin,&out,&error)==CL_REJECTED_V1);
    assert(out.size==0&&error.size>0);cl_free_v1(&error);
    assert(cl_evidence_verify_v1(inputs.artifact,inputs.art_pin,inputs.pkg_pin,inputs.snap_pin,&out,&out)==CL_INVALID_V1);
    assert(cl_evidence_freeze_v1(inputs.package,inputs.pkg_pin,inputs.goals,inputs.journal,
                                 (cl_slice_v1){zeros, sizeof zeros},&out,&error)==CL_REJECTED_V1);
    assert(out.size==0&&error.size>0);cl_free_v1(&error);
    free((void*)inputs.package.bytes);free((void*)inputs.goals.bytes);free((void*)inputs.journal.bytes);
    free((void*)inputs.artifact.bytes);free((void*)inputs.desired.bytes);
    puts("independent native C proof fixture passed");
    return 0;
}
