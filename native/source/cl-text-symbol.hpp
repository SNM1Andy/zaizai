#pragma once
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <string_view>
#include <utility>

namespace cl_text_symbol {
inline constexpr std::size_t byte_limit=96;
inline constexpr std::string_view prefix="~u";
inline bool comparison_name(std::string_view name)noexcept{return name=="sym_eq"||name=="sym_ne";}
inline bool is_wire(std::string_view term)noexcept{return term.starts_with(prefix);}
inline void verify(std::string_view value){
    if(value.empty()||value.size()>byte_limit)throw std::runtime_error("quoted CL symbol size limit");
    for(std::size_t i=0;i<value.size();){
        const auto b=static_cast<unsigned char>(value[i]);
        std::size_t n=1;
        std::uint32_t scalar=b;
        if(b>=128){
            if(b>=0xc2U&&b<=0xdfU){n=2;scalar=b&0x1fU;}
            else if(b>=0xe0U&&b<=0xefU){n=3;scalar=b&0xfU;}
            else if(b>=0xf0U&&b<=0xf4U){n=4;scalar=b&0x7U;}
            else throw std::runtime_error("invalid UTF-8 in quoted CL symbol");
            if(n>value.size()-i)throw std::runtime_error("truncated UTF-8 in quoted CL symbol");
            for(std::size_t x=1;x<n;++x){
                const auto next=static_cast<unsigned char>(value[i+x]);
                if((next&0xc0U)!=0x80U)throw std::runtime_error("invalid UTF-8 in quoted CL symbol");
                scalar=(scalar<<6)|(next&0x3fU);
            }
            if((n==3&&scalar<0x800U)||(n==4&&scalar<0x10000U)||(scalar>=0xd800U&&scalar<=0xdfffU)||scalar>0x10ffffU)
                throw std::runtime_error("non-scalar or noncanonical UTF-8 in quoted CL symbol");
        }
        if(scalar<0x20U||(scalar>=0x7fU&&scalar<=0x9fU)||scalar==0x2028U||scalar==0x2029U||
           (scalar>=0x202aU&&scalar<=0x202eU)||(scalar>=0x2066U&&scalar<=0x2069U)||scalar==0xfeffU)
            throw std::runtime_error("control character in quoted CL symbol");
        i+=n;
    }
}
inline int nibble(char c)noexcept{
    if(c>='0'&&c<='9')return c-'0';
    if(c>='a'&&c<='f')return c-'a'+10;
    return -1;
}
inline std::string to_wire(std::string_view value){
    verify(value);
    const char digits[]="0123456789abcdef";
    std::string result(prefix);
    result.reserve(prefix.size()+value.size()*2);
    for(const unsigned char c:value){result+=digits[c>>4];result+=digits[c&15U];}
    return result;
}
inline std::string from_wire(std::string_view wire){
    if(!is_wire(wire)||wire.size()<=prefix.size()||wire.size()%2||wire.size()>prefix.size()+byte_limit*2)
        throw std::runtime_error("malformed quoted CL wire symbol");
    std::string value;
    for(std::size_t i=prefix.size();i<wire.size();i+=2){
        const int a=nibble(wire[i]),b=nibble(wire[i+1]);
        if(a<0||b<0)throw std::runtime_error("malformed quoted CL wire symbol");
        value+=static_cast<char>((a<<4)|b);
    }
    verify(value);return value;
}
inline std::string term(std::string_view line,std::size_t& i){
    const auto start=i;
    if(line[i]=='"'){
        ++i;
        std::string value;
        while(i<line.size()){
            char c=line[i++];
            if(c=='"')return to_wire(value);
            if(c=='\\'){
                if(i>=line.size()||(line[i]!='\\'&&line[i]!='"'))
                    throw std::runtime_error("unknown quoted CL symbol escape");
                c=line[i++];
            }
            value+=c;
            if(value.size()>byte_limit)throw std::runtime_error("quoted CL symbol size limit");
        }
        throw std::runtime_error("unterminated quoted CL symbol");
    }
    i+=prefix.size();
    while(i<line.size()&&nibble(line[i])>=0)++i;
    auto wire=std::string(line.substr(start,i-start));
    (void)from_wire(wire);return wire;
}
}
