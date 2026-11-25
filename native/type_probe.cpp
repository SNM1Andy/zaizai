// Exercise the exact Windows descriptor reader used by the release with finite local inputs.
#include "native-os-win.hpp"
#include <fstream>
#include <iostream>
using namespace native_os;

static const ReadMessages messages{"directory","open","regular file required","read","limit"};

static void refused(Descriptor &descriptor, DWORD expected_type) {
    if (descriptor.fd < 0 || GetFileType(handle(descriptor.fd)) != expected_type)
        throw std::runtime_error("wrong fixture type");
    try {
        read_owned_descriptor(descriptor.fd, 128, messages);
    } catch (const std::runtime_error &err) {
        if (std::string(err.what()) == messages.kind) return;
        throw;
    }
    throw std::runtime_error("non-regular fixture accepted");
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    const fs::path dir=fs::u8path(argv[1]), path=dir/"source.txt";
    const std::string bytes="frozen source\n";
    { std::ofstream file(path,std::ios::binary);file.write(bytes.data(),bytes.size());if (!file) return 3; }
    if (read_regular_input(path,bytes.size(),messages) != bytes) return 4;
    Descriptor folder(open_directory(dir));
    refused(folder,FILE_TYPE_DISK);
    Descriptor character(open_input(L"NUL"));
    refused(character,FILE_TYPE_CHAR);
    HANDLE read_end, write_end;
    if (!CreatePipe(&read_end,&write_end,nullptr,0)) return 5;
    if (!CloseHandle(write_end)) return 6; // A read on this test pipe is already at EOF.
    Descriptor pipe(descriptor(read_end));
    refused(pipe,FILE_TYPE_PIPE);
    std::cout<<"disk bytes exact; directory, character device and closed anonymous pipe rejected before reading\n";
}
