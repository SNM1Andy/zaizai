#define NOMINMAX
#include <windows.h>
#include <filesystem>
#include <string>
int WINAPI wWinMain(HINSTANCE,HINSTANCE,PWSTR,int){
    wchar_t self[32768]{};
    if(!GetModuleFileNameW(nullptr,self,32768))return 1;
    auto root=std::filesystem::path(self).parent_path();
    auto python=root/L"runtime"/L"python.exe",script=root/L"host"/L"desktop.py";
    std::wstring args=L"\""+python.wstring()+L"\" -B -X utf8 \""+script.wstring()+L"\"";
    STARTUPINFOW si{};si.cb=sizeof si;
    PROCESS_INFORMATION pi{};
    if(!CreateProcessW(python.c_str(),args.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW,nullptr,root.c_str(),&si,&pi)){
        MessageBoxW(nullptr,L"无法启动再再 2.0 的本地 Python 运行时。",L"再再 2.0",MB_ICONERROR);return 1;
    }
    CloseHandle(pi.hThread);CloseHandle(pi.hProcess);return 0;
}

