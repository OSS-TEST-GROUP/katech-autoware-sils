#define _GNU_SOURCE
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cfenv>
#include <dlfcn.h>
#include <vector>
#include <sys/wait.h>
#include <unistd.h>
namespace autoware::velocity_smoother::analytical_velocity_planning_utils {
bool calcStopDistWithJerkAndAccConstraints(double,double,double,double,double,double,int&,std::vector<double>&,double&);
}
using autoware::velocity_smoother::analytical_velocity_planning_utils::calcStopDistWithJerkAndAccConstraints;
using Fn=bool(*)(double,double,double,double,double,double,int&,std::vector<double>&,double&);
int main() {
  void *lib=dlopen("libsmoother.so",RTLD_NOW);if(!lib)return 2;
  auto native=reinterpret_cast<Fn>(dlsym(lib,"_ZN8autoware17velocity_smoother34analytical_velocity_planning_utils37calcStopDistWithJerkAndAccConstraintsEddddddRiRSt6vectorIdSaIdEERd"));
  if(!native)return 3;
  // Real-domain reproducer: positive acceleration and target above current speed
  // enter original type-2 branch with a negative square-root argument.
  pid_t child=fork();if(child==0){feenableexcept(FE_INVALID|FE_DIVBYZERO);int t=0;double d=0;std::vector<double> ts;native(.1,.2,1.,-1.,-1.,.5,t,ts,d);_exit(0);}
  int status;waitpid(child,&status,0);if(!WIFSIGNALED(status)||WTERMSIG(status)!=SIGFPE)return 4;
  feenableexcept(FE_INVALID|FE_DIVBYZERO);
  int t=99;double d=99;std::vector<double> ts{99};
  if(calcStopDistWithJerkAndAccConstraints(.1,.2,1.,-1.,-1.,.5,t,ts,d))return 5;
  if(t!=99||d!=99||ts!=std::vector<double>{99})return 6;
  if(calcStopDistWithJerkAndAccConstraints(.1,.2,0.,-1.,-1.,0.,t,ts,d))return 7;
  unsigned checked=0;
  for(double v:{0.,.1,.5,1.,2.,5.,10.,15.})for(double a:{-2.,-1.,-.2,0.,.2,1.,2.})
  for(double ja:{.1,.5,1.,2.})for(double amin:{-1.,-2.,-4.})for(double target:{0.,.1,.5,1.,2.,5.}) {
    const double jd=-ja;
    const double tm=(target-v-.5*(0-a)/jd*a-.5*amin/jd*amin-.5*(0-amin)/ja*amin)/amin;
    const double needed=.5*(0-a)/ja*a-(target-v);
    const double sq=(target-v-.5*(0-a)/jd*a)*(2*ja*jd/(ja-jd));
    if(tm<=0&&(needed>0||a>0)&&sq<0)continue;
    int t1=0,t2=0;double d1=0,d2=0;std::vector<double> ts1,ts2;
    bool b1=native(v,a,ja,jd,amin,target,t1,ts1,d1);
    bool b2=calcStopDistWithJerkAndAccConstraints(v,a,ja,jd,amin,target,t2,ts2,d2);
    if(b1!=b2||t1!=t2||ts1!=ts2||d1!=d2)return 8;
    ++checked;
  }
  std::printf("PASS: native negative-domain SIGFPE reproduced; guard rejects; %u safe inputs exactly match native; traps remain enabled\n",checked);
}
