// GUI-only camera transport. Never publishes robot or object commands.
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <csignal>
#include <thread>
#include <gz/transport/Node.hh>
#include <gz/msgs/cameratrack.pb.h>
#include <gz/msgs/double.pb.h>

namespace {
std::atomic<double> distance{2.2};
volatile std::sig_atomic_t running = 1;
void Stop(int) { running = 0; }
void Distance(const gz::msgs::Double &msg) {
  if (std::isfinite(msg.data()))
    distance = std::clamp(msg.data(), .40, 3.5);
}
}

int main() {
  std::signal(SIGINT, Stop);
  std::signal(SIGTERM, Stop);
  gz::transport::Node node;
  node.Subscribe("/manual/camera_distance", Distance);
  auto publisher = node.Advertise<gz::msgs::CameraTrack>("/gui/track");
  double previous = -1;
  int tick = 0;
  while (running) {
    const double d = distance.load();
    // Retry during scene initialization; otherwise update only on zoom input.
    if (publisher.HasConnections() &&
        (std::abs(d-previous) > .003 || (tick < 600 && tick % 20 == 0))) {
      gz::msgs::CameraTrack message;
      message.set_track_mode(gz::msgs::CameraTrack::FOLLOW);
      message.mutable_follow_target()->set_name("mobil_manipulator::gripper_link_v2_1");
      auto offset = message.mutable_follow_offset();
      offset->set_x(-.8*d);
      offset->set_y(-.6*d);
      offset->set_z(.5*d);
      message.set_follow_pgain(.08);
      message.set_track_pgain(.08);
      publisher.Publish(message);
      previous = d;
    }
    ++tick;
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
  }
}
