#include <vector>
namespace autoware::velocity_smoother::analytical_velocity_planning_utils {
bool calcStopDistWithJerkAndAccConstraints(double,double,double,double,double,double,int&,std::vector<double>&,double&);
}
extern "C" bool probe(bool invalid) {
  int type=0;double dist=0;std::vector<double> times;
  return autoware::velocity_smoother::analytical_velocity_planning_utils::calcStopDistWithJerkAndAccConstraints(
    invalid?.1:5.,invalid?.2:0.,1.,-1.,-1.,invalid?.5:0.,type,times,dist);
}
