#include "cl-c-api.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <pthread.h>

static cl_slice_v1 entry(const char* path){
    FILE* f=fopen(path,"rb");
    assert(f && !fseek(f,0,SEEK_END));
    const long size=ftell(f);
    assert(size>0 && !fseek(f,0,SEEK_SET));
    unsigned char* bytes=malloc((size_t)size);
    assert(bytes && fread(bytes,1,(size_t)size,f)==(size_t)size);
    assert(!fclose(f));
    return (cl_slice_v1){bytes,(size_t)size};
}
static cl_slice_v1 ascii(const char* text){return (cl_slice_v1){(const unsigned char*)text,strlen(text)};}
static void same(cl_buffer_v1 actual,cl_slice_v1 expected){
    assert(actual.size==expected.size && !memcmp(actual.bytes,expected.bytes,expected.size));
}
struct ProofCase {cl_slice_v1 pkg,digest,goals,expected;};
static void* independent(void* data){
    const struct ProofCase* p=data;
    for(int i=0;i<12;++i){
        cl_buffer_v1 out={0},why={0};
        assert(cl_package_proof_v1(p->pkg,p->digest,p->goals,&out,&why)==CL_OK_V1 && !why.bytes);
        same(out,p->expected);
        cl_free_v1(&out);
        assert(!out.bytes && !out.size);
    }
    return NULL;
}
int main(int argc,char** argv){
    assert(argc==10 && cl_abi_version_v1()==1);
    cl_slice_v1 bundle=entry(argv[1]),pkg_hash=ascii(argv[2]),ir=entry(argv[3]),goals=entry(argv[4]),
        proof=entry(argv[5]),profile=entry(argv[6]),profile_pin=ascii(argv[7]),source=entry(argv[8]),source_pin=ascii(argv[9]);
    cl_buffer_v1 success={0}, error={0};
    assert(cl_package_ir_v1(bundle,pkg_hash,&success,&error)==CL_OK_V1 && !error.bytes);
    same(success,ir);
    unsigned char* prior=success.bytes;
    assert(cl_package_ir_v1(bundle,pkg_hash,&success,&error)==CL_INVALID_V1 && success.bytes==prior && !error.bytes);
    cl_free_v1(&success);
    assert(cl_profile_compile_v1(profile,profile_pin,source,source_pin,&success,&error)==CL_OK_V1);
    assert(success.bytes && success.size>13 && !memcmp(success.bytes,"CLIR",4));
    if(getenv("CL_SDK_CAPTURE"))assert(fwrite(success.bytes,1,success.size,stdout)==success.size);
    cl_free_v1(&success);
    const cl_slice_v1 bad=ascii("deliberately wrong");
    assert(cl_package_ir_v1(bundle,bad,&success,&error)==CL_REJECTED_V1 && !success.bytes && error.size);
    cl_free_v1(&error);
    assert(cl_profile_compile_v1(profile,profile_pin,source,bad,&success,&error)==CL_REJECTED_V1 && !success.bytes && error.size);
    cl_free_v1(&error);
    assert(cl_package_proof_v1((cl_slice_v1){NULL,1},pkg_hash,goals,&success,&error)==CL_INVALID_V1 && !success.bytes && error.size);
    cl_free_v1(&error);
    const cl_eval_v1 enough={128,12000,2000000,2000000};
    cl_eval_v1 tiny=enough;
    tiny.facts=1;
    assert(cl_package_proof_bounded_v1(bundle,pkg_hash,goals,tiny,&success,&error)==CL_RESOURCE_V1 && !success.bytes && error.size);
    cl_free_v1(&error);
    tiny.facts=0;
    assert(cl_package_proof_bounded_v1(bundle,pkg_hash,goals,tiny,&success,&error)==CL_INVALID_V1 && !success.bytes);
    cl_free_v1(&error);
    assert(cl_package_proof_bounded_v1(bundle,pkg_hash,goals,enough,&success,&error)==CL_OK_V1 && !error.size);
    same(success,proof);
    cl_free_v1(&success);
    struct ProofCase work={bundle,pkg_hash,goals,proof};
    pthread_t threads[4];
    for(int i=0;i<4;++i)assert(!pthread_create(&threads[i],NULL,independent,&work));
    for(int i=0;i<4;++i)assert(!pthread_join(threads[i],NULL));
    free((void*)bundle.bytes);free((void*)ir.bytes);free((void*)goals.bytes);free((void*)proof.bytes);
    free((void*)profile.bytes);free((void*)source.bytes);
    return 0;
}
