// Per-window renderer control: shared physics, independent cameras.
#include "PlayerCamera.hh"
#include <algorithm>
#include <cmath>
#include <fstream>
#include <QQuickWindow>
#include <QScreen>
#include <QTimer>
#include <gz/gui/Application.hh>
#include <gz/gui/MainWindow.hh>
#include <gz/gui/GuiEvents.hh>
#include <gz/plugin/Register.hh>
#include <gz/rendering/RenderingIface.hh>
#include <gz/rendering/Scene.hh>
#include <gz/rendering/Camera.hh>
#include <gz/msgs/cameratrack.pb.h>

void PlayerCamera::LoadConfig(const tinyxml2::XMLElement *config) {
  int player = 1;
  if (auto p = config->FirstChildElement("player")) p->QueryIntText(&player);
  target = "robot_p" + std::to_string(player) + "::gripper_link_v2_1";
  const auto prefix = "/p" + std::to_string(player);
  node.Subscribe(prefix + "/manual/camera_distance", &PlayerCamera::OnDistance, this);
  state = node.Advertise<gz::msgs::CameraTrack>(prefix + "/camera/state");
  title = "Oyuncu " + std::to_string(player);
  if (auto p = config->FirstChildElement("ready_file"))
    if (p->GetText()) readyFile = p->GetText();
  auto main = gz::gui::App()->findChild<gz::gui::MainWindow *>();
  main->installEventFilter(this);
  QTimer::singleShot(1500, main, [main, player]() {
    auto window = main->QuickWindow();
    auto area = window->screen()->availableGeometry();
    const int half = area.width()/2;
    window->setWindowState(Qt::WindowNoState);
    window->setFlags(window->flags() | Qt::FramelessWindowHint);
    window->setTitle(player == 1 ? "ENRO — Oyuncu 1 / MAVİ" : "ENRO — Oyuncu 2 / TURUNCU");
    window->setGeometry(area.x()+(player-1)*half, area.y(),
                        player == 1 ? half : area.width()-half, area.height());
    window->show();
  });
}

void PlayerCamera::OnDistance(const gz::msgs::Double &msg) {
  if (std::isfinite(msg.data())) distance = std::clamp(msg.data(), .40, 3.5);
}

bool PlayerCamera::eventFilter(QObject *object, QEvent *event) {
  if (event->type() == gz::gui::events::Render::kType) {
    if (!scene) scene = gz::rendering::sceneFromFirstRenderEngine();
    if (scene && !camera) {
      for (unsigned int i=0; i<scene->NodeCount(); ++i) {
        camera = std::dynamic_pointer_cast<gz::rendering::Camera>(scene->NodeByIndex(i));
        if (camera) break;
      }
    }
    if (camera) {
      auto nodeTarget = scene->NodeByName(target);
      double d = distance.load();
      if (nodeTarget && (previous < 0 || std::abs(d-previous) > .003)) {
        camera->SetFollowTarget(nodeTarget, gz::math::Vector3d(-.8*d, -.6*d, .5*d), false);
        camera->SetTrackTarget(nodeTarget);
        camera->SetFollowPGain(.08);
        camera->SetTrackPGain(.08);
        previous = d;
      }
      if (nodeTarget && !readyWritten && !readyFile.empty()) {
        std::ofstream output(readyFile);
        output << "ready\n";
        readyWritten = output.good();
      }
      if (nodeTarget && state.HasConnections()) {
        gz::msgs::CameraTrack message;
        message.set_track_mode(gz::msgs::CameraTrack::FOLLOW);
        message.mutable_follow_target()->set_name(target);
        message.mutable_follow_offset()->set_x(-.8*d);
        message.mutable_follow_offset()->set_y(-.6*d);
        message.mutable_follow_offset()->set_z(.5*d);
        state.Publish(message);
      }
    }
  }
  return QObject::eventFilter(object, event);
}
GZ_ADD_PLUGIN(PlayerCamera, gz::gui::Plugin)
