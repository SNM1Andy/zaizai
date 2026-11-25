#ifndef ZAIZAI_WINDOWS_EXAMPLE_READER_H
#define ZAIZAI_WINDOWS_EXAMPLE_READER_H
#include <windows.h>
#include <process.h>
#include <stdint.h>
#include <stdlib.h>
#include <io.h>
#include <fcntl.h>

typedef struct {
    void *(*run)(void *);
    void *input;
} reader_job;

static unsigned __stdcall reader_entry(void *pointer) {
    reader_job job = *(reader_job *)pointer;
    free(pointer);
    job.run(job.input);
    return 0;
}

static int start_reader(HANDLE *thread, void *(*run)(void *), void *input) {
    reader_job *job = malloc(sizeof(*job));
    if (!job) return 1;
    job->run = run;
    job->input = input;
    *thread = (HANDLE)_beginthreadex(NULL, 0, reader_entry, job, 0, NULL);
    if (*thread) return 0;
    free(job);
    return 1;
}

static int join_reader(HANDLE thread) {
    DWORD status = WaitForSingleObject(thread, INFINITE);
    BOOL closed = CloseHandle(thread);
    return status == WAIT_OBJECT_0 && closed ? 0 : 1;
}
#endif
