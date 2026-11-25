#include "cl-c-api.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static cl_slice_v1 text(const char* bytes){return (cl_slice_v1){(const unsigned char*)bytes,strlen(bytes)};}
static cl_slice_v1 load(const char* name){
    FILE* in=fopen(name,"rb");assert(in&&fseek(in,0,SEEK_END)==0);
    const long n=ftell(in);assert(n>0&&n<=2*1024*1024&&fseek(in,0,SEEK_SET)==0);
    unsigned char* bytes=malloc((size_t)n);assert(bytes&&fread(bytes,1,(size_t)n,in)==(size_t)n);
    assert(fclose(in)==0);
    return (cl_slice_v1){bytes,(size_t)n};
}
static cl_buffer_v1 command(cl_evidence_session_v1* session,const char* frame){
    cl_buffer_v1 result={0},error={0};
    assert(cl_evidence_session_command_v1(session,text(frame),&result,&error)==CL_OK_V1);
    assert(result.size&&!error.size);
    return result;
}
static void emit(cl_buffer_v1* buffer){
    assert(fwrite(buffer->bytes,1,buffer->size,stdout)==buffer->size);
    fflush(stdout);cl_free_v1(buffer);
}
int main(int argc,char** argv){
    assert(argc==2);
    const cl_slice_v1 package=load("package"),goals=load("goals"),pin=text(argv[1]),path=text("journal");
    cl_evidence_session_v1* session=NULL;
    cl_buffer_v1 error={0};
    assert(cl_evidence_session_open_v1(package,pin,goals,path,1,&session,&error)==CL_OK_V1&&session&&!error.size);
    cl_buffer_v1 before=command(session,"c view");emit(&before);
    cl_evidence_session_v1* rival=NULL;
    assert(cl_evidence_session_open_v1(package,pin,goals,path,0,&rival,&error)==CL_REJECTED_V1&&!rival&&error.size);
    cl_free_v1(&error);
    const char* frame="c batch stable 0 ; observe exposure sample(x) ; observe incoming claims(coal,extra,25@cny_cent)";
    cl_buffer_v1 receipt=command(session,frame);emit(&receipt);
    assert(getchar()=='r');
    cl_evidence_session_close_v1(&session);assert(!session);
    assert(cl_evidence_session_open_v1(package,pin,goals,path,0,&session,&error)==CL_OK_V1&&session&&!error.size);
    receipt=command(session,"c receipt stable");emit(&receipt);
    cl_buffer_v1 result=command(session,"c check");emit(&result);
    result=command(session,frame);emit(&result);
    cl_evidence_session_close_v1(&session);assert(!session);
    cl_evidence_session_close_v1(&rival);
    free((void*)package.bytes);free((void*)goals.bytes);
    return 0;
}
