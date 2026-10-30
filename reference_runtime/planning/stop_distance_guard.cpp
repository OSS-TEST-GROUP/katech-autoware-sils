// Narrow domain guard for the existing native stopping-distance function.
// Valid inputs are forwarded byte-for-byte to the original implementation.
// No exception masks, signal handlers, control outputs or success fabrication.
#include <cmath>
#include <cstdint>
#include <cstring>
#include <dlfcn.h>
#include <cstdio>
#include <vector>
#include <atomic>
#include <cstdlib>
namespace autoware::velocity_smoother::analytical_velocity_planning_utils {
static bool finite_bits(double x) {
  uint64_t bits; std::memcpy(&bits,&x,sizeof(bits));
  return (bits & 0x7ff0000000000000ULL)!=0x7ff0000000000000ULL;
}
bool calcStopDistWithJerkAndAccConstraints(
  double v0,double a0,double ja,double jd,double amin,double target,
  int &type,std::vector<double> &times,double &distance) {
  auto reject=[&](const char *reason) {
    static std::atomic<unsigned> count{0}; const auto c=++count;
    if(c<=5 || c%1000==0) std::fprintf(stderr,
      "[CTRACK_STOP_DOMAIN] rejected=%s v=%g a=%g ja=%g jd=%g min=%g target=%g count=%u\n",
      reason,v0,a0,ja,jd,amin,target,c);
    return false;
  };
  for(double x:{v0,a0,ja,jd,amin,target})if(!finite_bits(x))return reject("nonfinite");
  if(!(ja>0 && jd<0 && amin<0))return reject("jerk_or_acc_domain");
  // Exact original expression and branch condition, checked before sqrt.
  const double tmin=(target-v0-0.5*(0-a0)/jd*a0-0.5*amin/jd*amin-0.5*(0-amin)/ja*amin)/amin;
  if(!finite_bits(tmin))return reject("nonfinite_time");
  if(!(tmin>0)) {
    const double needed=0.5*(0-a0)/ja*a0-(target-v0);
    if(needed>0 || a0>0) {
      const double square=(target-v0-0.5*(0-a0)/jd*a0)*(2*ja*jd/(ja-jd));
      if(!finite_bits(square)||square<0)return reject("negative_sqrt_domain");
    }
  }
  using Fn=bool(*)(double,double,double,double,double,double,int&,std::vector<double>&,double&);
  static auto original=[]() -> Fn {
    const char *symbol="_ZN8autoware17velocity_smoother34analytical_velocity_planning_utils37calcStopDistWithJerkAndAccConstraintsEddddddRiRSt6vectorIdSaIdEERd";
    // ROS loads components RTLD_LOCAL; RTLD_NEXT from a global preload cannot
    // see their dependency scope. Resolve the already-loaded exact native DSO.
    void *handle=dlopen("/opt/autoware/lib/libsmoother.so",RTLD_NOW|RTLD_NOLOAD);
    auto fn=handle?reinterpret_cast<Fn>(dlsym(handle,symbol)):nullptr;
    Dl_info info{};
    if(!fn||fn==&calcStopDistWithJerkAndAccConstraints||!dladdr(reinterpret_cast<void*>(fn),&info)) {
      std::fprintf(stderr,"[CTRACK_STOP_DOMAIN] FATAL original symbol unavailable; no planning fallback allowed\n");
      std::abort(); // Native child supervisor requests STOP; never silently degrade.
    }
    std::fprintf(stderr,"[CTRACK_STOP_DOMAIN] forwarding verified native function in %s\n",info.dli_fname);
    return fn; // Retain the handle so the function cannot be unloaded underneath us.
  }();
  return original(v0,a0,ja,jd,amin,target,type,times,distance);
}
}
