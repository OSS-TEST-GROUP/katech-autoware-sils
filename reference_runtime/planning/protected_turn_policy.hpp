// Simulator-specific protected-turn policy. Input is measured recognition only.
#pragma once
#include "movement_bindings.hpp"
#include <autoware_perception_msgs/msg/traffic_light_group.hpp>
#include <cmath>
#include <set>
#include <vector>

namespace ctrack_protected {
inline bool managed(int64_t signal) {
  for (const auto & b : bindings) if (b.signal == signal) return true;
  return false;
}
inline Turn resolve(int64_t signal, const std::vector<int64_t> & path_lane_ids) {
  std::set<Turn> found;
  for (const auto & b : bindings) {
    if (b.signal != signal) continue;
    for (auto id : path_lane_ids) if (id == b.lane) found.insert(b.turn);
  }
  return found.size() == 1 ? *found.begin() : Turn::Unknown;
}
inline const char * name(Turn t) {
  switch(t) {
    case Turn::Left: return "left";
    case Turn::Right: return "right";
    case Turn::Straight: return "straight";
    default: return "unknown";
  }
}
inline bool allowed(Turn turn, const autoware_perception_msgs::msg::TrafficLightGroup & signal) {
  using E = autoware_perception_msgs::msg::TrafficLightElement;
  if (turn == Turn::Unknown || signal.elements.empty()) return false;
  bool green_circle = false, red_circle = false, left = false;
  for (const auto & e : signal.elements) {
    if (!std::isfinite(e.confidence) || e.confidence <= 0.f ||
        e.confidence > 1.f || e.status != E::SOLID_ON) return false;
    if (e.shape == E::CIRCLE && e.color == E::GREEN) green_circle = true;
    else if (e.shape == E::CIRCLE && e.color == E::RED) red_circle = true;
    else if (e.shape == E::LEFT_ARROW && e.color == E::GREEN) left = true;
    else return false;
  }
  if (green_circle == red_circle) return false; // Missing or contradictory circles.
  if (turn == Turn::Left) return left;
  return green_circle; // Red+left never permits straight or right here.
}
}  // namespace ctrack_protected
