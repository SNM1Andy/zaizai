#include "cl-memory-api.h"
#include <assert.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static cl_slice_v1 from_file(const char* path){
    FILE* f=fopen(path,"rb");assert(f);
    assert(!fseek(f,0,SEEK_END));
    const long n=ftell(f);assert(n>=0&&n<=1024*1024);
    rewind(f);
    unsigned char* p=malloc((size_t)n+1);assert(p);
    assert(fread(p,1,(size_t)n,f)==(size_t)n&&!fclose(f));
    return (cl_slice_v1){p,(size_t)n};
}
static cl_slice_v1 from_text(const char* p){
    return (cl_slice_v1){(const unsigned char*)p,strlen(p)};
}
static cl_pinned_buffer_v1 pinned(const char* data,const char* pin){
    return (cl_pinned_buffer_v1){from_file(data),from_text(pin)};
}
static void destroy(cl_pinned_buffer_v1 in){
    free((void*)in.contents.bytes);
}
static int equal(cl_buffer_v1 a,cl_buffer_v1 b){
    return a.size==b.size&&!memcmp(a.bytes,b.bytes,a.size);
}
static void emit(const char* file,cl_buffer_v1 data){
    FILE* f=fopen(file,"wb");assert(f);
    assert(fwrite(data.bytes,1,data.size,f)==data.size&&!fclose(f));
}
static int has_message(cl_buffer_v1 why,const char* message){
    const size_t n=strlen(message);
    for(size_t i=0;i+n<=why.size;++i)if(!memcmp(why.bytes+i,message,n))return 1;
    return 0;
}
typedef struct {
    const cl_profile_rebuild_inputs_v1* inputs;
    cl_buffer_v1 candidate, receipt, why;
    int code;
} work;
static void* rebuild(void* raw){
    work* w=raw;
    w->code=cl_profile_rebuild_v1(w->inputs,&w->candidate,&w->receipt,&w->why);
    return NULL;
}

int main(int argc,char** argv){
    assert(argc>=13);
    assert(cl_abi_version_v1()==1);
    const uint32_t features=cl_runtime_features_v1();
    assert((features&CL_PROFILE_REBUILD_V1)&&!(features&CL_DURABLE_FILE_OPERATIONS_V1));
    const cl_profile_rebuild_inputs_v1 in={
        pinned(argv[2],argv[3]),pinned(argv[4],argv[5]),pinned(argv[6],argv[7]),
        pinned(argv[8],argv[9]),pinned(argv[10],argv[11]),from_text(argv[12])
    };
    cl_buffer_v1 data={0},receipt={0},err={0};
    if(!strcmp(argv[1],"rebuild")){
        assert(argc==18);
        assert(cl_profile_rebuild_v1(&in,&data,&data,&err)==CL_INVALID_V1&&!data.bytes&&!err.bytes);
        assert(cl_profile_rebuild_v1(&in,&data,&receipt,&receipt)==CL_INVALID_V1&&!receipt.bytes);
        cl_buffer_v1 occupied={NULL,4};
        assert(cl_profile_rebuild_v1(&in,&occupied,&receipt,&err)==CL_INVALID_V1&&occupied.size==4);
        assert(cl_profile_rebuild_v1(NULL,&data,&receipt,&err)==CL_INVALID_V1&&!data.bytes&&!receipt.bytes&&err.bytes);
        cl_free_v1(&err);
        pthread_t pool[4];
        work jobs[4]={0};
        for(size_t i=0;i<4;++i){jobs[i].inputs=&in;assert(!pthread_create(&pool[i],NULL,rebuild,&jobs[i]));}
        for(size_t i=0;i<4;++i){assert(!pthread_join(pool[i],NULL));assert(jobs[i].code==CL_OK_V1&&!jobs[i].why.bytes);}
        for(size_t i=1;i<4;++i){
            assert(equal(jobs[i].candidate,jobs[0].candidate)&&equal(jobs[i].receipt,jobs[0].receipt));
            cl_free_v1(&jobs[i].candidate);cl_free_v1(&jobs[i].receipt);
        }
        data=jobs[0].candidate;receipt=jobs[0].receipt;
        emit(argv[13],data);emit(argv[14],receipt);
        const cl_pinned_buffer_v1 runtime=pinned(argv[15],argv[16]);
        cl_buffer_v1 product={0};
        assert(cl_profile_compile_v1((cl_slice_v1){data.bytes,data.size},from_text(argv[17]),
                    runtime.contents,runtime.pin,&product,&err)==CL_OK_V1&&!err.bytes&&product.size>7);
        assert(!memcmp(product.bytes,"CLIR-7\n",7));
        assert(fwrite(product.bytes,1,product.size,stdout)==product.size);
        cl_free_v1(&product);destroy(runtime);
    }else if(!strcmp(argv[1],"refuse")){
        assert(argc==14);
        assert(cl_profile_rebuild_v1(&in,&data,&receipt,&err)==CL_REJECTED_V1);
        if(!has_message(err,argv[13]))fwrite(err.bytes,1,err.size,stderr);
        assert(!data.bytes&&!receipt.bytes&&has_message(err,argv[13]));
    }else{
        assert((argc==17&&!strcmp(argv[1],"audit"))||(argc==18&&!strcmp(argv[1],"refuse-audit")));
        const cl_pinned_buffer_v1 candidate=pinned(argv[13],argv[14]), remote=pinned(argv[15],argv[16]);
        const int code=cl_profile_rebuild_audit_v1(&in,candidate,remote,&receipt,&err);
        if(argc==17){
            assert(code==CL_OK_V1&&!err.bytes&&receipt.size==remote.contents.size);
            assert(!memcmp(receipt.bytes,remote.contents.bytes,receipt.size));
        }else{
            if(!has_message(err,argv[17]))fwrite(err.bytes,1,err.size,stderr);
            assert(code==CL_REJECTED_V1&&!receipt.bytes&&has_message(err,argv[17]));
        }
        destroy(candidate);destroy(remote);
    }
    cl_free_v1(&data);cl_free_v1(&receipt);cl_free_v1(&err);
    destroy(in.baseline);destroy(in.grammar);destroy(in.types);destroy(in.lower);destroy(in.smoke);
    return 0;
}
