#include "protected_turn_policy.hpp"
#include "movement_test_cases.hpp"
#include <iostream>
#include <stdexcept>
#include <limits>

using namespace ctrack_protected;
using E=autoware_perception_msgs::msg::TrafficLightElement;
using S=autoware_perception_msgs::msg::TrafficLightGroup;
int checks=0;
void require(bool value, const char * reason) {
  ++checks;
  if (!value) throw std::runtime_error(reason);
}
E lamp(uint8_t color, uint8_t shape) {
  E e; e.color=color; e.shape=shape; e.status=E::SOLID_ON; e.confidence=0.95f; return e;
}
S lamps(std::initializer_list<E> values) { S s; s.elements=values; return s; }
int main() {
  const auto green=lamp(E::GREEN,E::CIRCLE), left=lamp(E::GREEN,E::LEFT_ARROW);
  const auto red=lamp(E::RED,E::CIRCLE), yellow=lamp(E::AMBER,E::CIRCLE);
  for (const auto & c : movement_cases) {
    require(managed(c.signal),"Signal must be managed");
    const auto t=resolve(c.signal,c.lanes);
    require(t==c.turn,"Route maneuver mismatch");
    require(allowed(t,lamps({green}))==(t==Turn::Straight || t==Turn::Right),"Green-only maneuver policy");
    require(allowed(t,lamps({green,left})),"Measured green plus left must permit resolved movement");
    require(!allowed(t,lamps({red})),"Red must stop");
    require(!allowed(t,lamps({yellow})),"Yellow must stop");
    require(!allowed(t,lamps({left})),"Arrow without circle is outside requested policy");
    require(allowed(t,lamps({red,left}))==(t==Turn::Left),"Red plus left permits only left");
    require(!allowed(t,lamps({red,green,left})),"Conflicting circles stop even with arrow");
    require(!allowed(t,lamps({yellow,left})),"Amber plus arrow is not a supported permissive state");
    require(!allowed(t,lamps({red,lamp(E::RED,E::LEFT_ARROW)})),"Red arrow cannot permit left");
    require(!allowed(t,lamps({green,red})),"Contradictory red/green must stop");
    require(!allowed(t,S{}),"Missing observation must stop");
    auto bad=left;bad.color=E::UNKNOWN;
    require(!allowed(t,lamps({green,bad})),"Unknown arrow must stop");
    bad=left;bad.status=E::FLASHING;
    require(!allowed(t,lamps({green,bad})),"Flashing arrow must stop");
    bad=left;bad.confidence=0;
    require(!allowed(t,lamps({green,bad})),"Zero confidence must stop");
    bad=left;bad.confidence=std::numeric_limits<float>::quiet_NaN();
    require(!allowed(t,lamps({green,bad})),"NaN confidence must stop");
  }
  require(resolve(36071,{4906,4922,8618,8625,6375,6364})==Turn::Left,"Reported user route is protected left");
  require(resolve(36071,{4906,4922})==Turn::Unknown,"Approach marked straight cannot imply straight route");
  require(resolve(36071,{8618,9213})==Turn::Unknown,"Ambiguous left/straight must stop");
  require(!allowed(Turn::Unknown,lamps({green,left})),"Unresolved route must stop even on arrows");
  require(!allowed(Turn::Unknown,lamps({red,left})),"Unresolved route must stop on red plus arrow");
  require(!managed(999999),"Unrelated signals must not be patched");
  std::cout<<"PASS "<<checks<<" checks across "<<movement_cases.size()<<" signal-specific lanelet paths\n";
}
