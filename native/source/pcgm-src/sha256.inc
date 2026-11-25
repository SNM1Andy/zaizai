#include <array>
#include <bit>

string sha256(const string& input){
    constexpr array<uint32_t,64> k{
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
    array<uint32_t,8> state{0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                           0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    auto block=[&](const unsigned char* b){
        array<uint32_t,64> w{};
        for(size_t i=0;i<16;++i)
            for(size_t j=0;j<4;++j)w[i]=(w[i]<<8)|b[4*i+j];
        for(size_t i=16;i<64;++i){
            const auto x=w[i-15],y=w[i-2];
            w[i]=(rotr(x,7)^rotr(x,18)^(x>>3))+w[i-16]+
                 (rotr(y,17)^rotr(y,19)^(y>>10))+w[i-7];
        }
        auto [a,b0,c,d,e,f,g,h]=state;
        for(size_t i=0;i<64;++i){
            const uint32_t x=h+(rotr(e,6)^rotr(e,11)^rotr(e,25))+((e&f)^((~e)&g))+k[i]+w[i];
            const uint32_t y=(rotr(a,2)^rotr(a,13)^rotr(a,22))+((a&b0)^(a&c)^(b0&c));
            h=g;g=f;f=e;e=d+x;d=c;c=b0;b0=a;a=x+y;
        }
        const array<uint32_t,8> worked{a,b0,c,d,e,f,g,h};
        for(size_t i=0;i<state.size();++i)state[i]+=worked[i];
    };
    const auto* data=reinterpret_cast<const unsigned char*>(input.data());
    const auto size=input.size();
    for(size_t i=0;i<size/64;++i)block(data+i*64);
    array<unsigned char,128> tail{};
    const auto rem=size%64;
    copy_n(data+(size-rem),rem,tail.data());
    tail[rem]=0x80;
    const auto end=rem<56?64:128;
    auto bits=uint64_t(size)*8;
    for(int i=0;i<8;++i)tail[end-i-1]=static_cast<unsigned char>(bits>>(8*i));
    block(tail.data());if(end==128)block(tail.data()+64);
    constexpr char hex[]="0123456789abcdef";
    string out;out.reserve(64);
    for(auto word:state)for(int n=28;n>=0;n-=4)out+=hex[(word>>n)&15];
    return out;
}
