#pragma once
#include <array>
#include <cmath>
#include <complex>
#include <algorithm>
#include <vector>
#include <numeric>
#include <stdexcept>

namespace instinct {
using C = std::complex<double>;
using Field = std::vector<C>;
using Features = std::array<double,6>;
constexpr double domain = 64.0, tick_dt = 0.5;
struct Solver {
    int n, substeps;
    bool reflect;
    double dx;
    std::vector<double> plate, stimulus;
    std::vector<std::array<int,4>> adj;

    Solver(int size, int sub, bool wall, const std::string& shape, const std::vector<int>& glyph)
        : n(size), substeps(sub), reflect(wall), dx(domain/n), plate(n*n), stimulus(n*n), adj(n*n) {
        auto axis=[&](int x){return reflect?std::clamp(x,0,n-1):(x+n)%n;};
        // Coordinates at cell centers. Both grids sample the same continuous plate.
        for(int y=0;y<n;++y) for(int x=0;x<n;++x){
            int i=y*n+x;
            adj[i]={axis(x-1)+n*y,axis(x+1)+n*y,x+n*axis(y-1),x+n*axis(y+1)};
            double X=(x+.5)*dx, Y=(y+.5)*dx;
            if(shape=="glyph"){
                double u=X-.5,v=Y-.5;
                int k=std::floor(u),l=std::floor(v);
                auto sample=[&](int a,int b){return glyph[((b+64)%64)*64+(a+64)%64]/255.;};
                double a=u-k,b=v-l;
                plate[i]=(1-b)*((1-a)*sample(k,l)+a*sample(k+1,l))+b*((1-a)*sample(k,l+1)+a*sample(k+1,l+1));
            } else if(shape=="rings"){
                double r=std::hypot(X-32,Y-32);
                plate[i]=std::exp(-std::pow((r-10)/1.6,2))+std::exp(-std::pow((r-21)/1.6,2));
            }
            stimulus[i]=std::exp(-((X-33)*(X-33)+(Y-32)*(Y-32))/98.);
        }
        double mean=std::accumulate(plate.begin(),plate.end(),0.)/plate.size(), peak=0;
        for(auto& v:plate){v-=mean;peak=std::max(peak,std::abs(v));}
        if(peak>0) for(auto& v:plate) v/=peak;
    }
    Field birth(int seed) const {
        Field p(n*n);
        double cx=31+1.5*std::sin(seed), cy=32+1.5*std::cos(seed);
        for(int i=0;i<n*n;++i){
            double x=(i%n+.5)*dx-cx,y=(i/n+.5)*dx-cy;
            p[i]=std::polar(.65*std::exp(-(x*x+y*y)/128.),.09*x+.04*y);
        }
        return p;
    }
    Features observe(const Field& p) const {
        Features f={0,0,0,1e100,0,0};
        for(int i=0;i<n*n;++i){
            double a=std::abs(p[i]);
            f[0]+=a*a;f[1]+=a;f[2]=std::max(f[2],a);f[3]=std::min(f[3],a);
            f[5]+=(std::norm(p[adj[i][1]]-p[i])+std::norm(p[adj[i][3]]-p[i]))/(dx*dx);
        }
        for(int k:{0,1,5}) f[k]/=p.size();
        f[4]=std::max(0.,f[0]-f[1]*f[1]);
        for(double v:f) if(!std::isfinite(v)) throw std::runtime_error("nonfinite field");
        return f;
    }
    void slope(const Field& p, double drive, Field& out) const {
        double E=0;
        for(auto v:p) E+=std::norm(v);
        E/=p.size();
        for(int i=0;i<n*n;++i){
            auto a=adj[i]; C v=p[i],lap=(p[a[0]]+p[a[1]]+p[a[2]]+p[a[3]]-4.*v)/(dx*dx);
            out[i]=(C(.015,.08)+.35*(.045-E)+.16*plate[i]-C(.45,.09)*std::norm(v))*v
                +C(.60,.13)*lap + .42*drive*stimulus[i];
        }
    }
    void advance(Field& p,double drive,double span) const {
        Field k(p.size()),mid(p.size()); double h=span/substeps;
        for(int j=0;j<substeps;++j){
            slope(p,drive,k);
            for(size_t i=0;i<p.size();++i) mid[i]=p[i]+.5*h*k[i];
            slope(mid,drive,k);
            for(size_t i=0;i<p.size();++i) p[i]+=h*k[i];
        }
    }
};
}
