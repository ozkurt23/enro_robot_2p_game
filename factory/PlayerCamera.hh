#pragma once
#include <atomic>
#include <gz/gui/Plugin.hh>
#include <gz/transport/Node.hh>
#include <gz/rendering/RenderTypes.hh>
#include <gz/msgs/double.pb.h>

class PlayerCamera : public gz::gui::Plugin {
  Q_OBJECT
 public: void LoadConfig(const tinyxml2::XMLElement *) override;
 protected: bool eventFilter(QObject *, QEvent *) override;
 private:
  void OnDistance(const gz::msgs::Double &);
  gz::transport::Node node;
  gz::transport::Node::Publisher state;
  gz::rendering::ScenePtr scene;
  gz::rendering::CameraPtr camera;
  std::atomic<double> distance{2.2};
  double previous{-1};
  std::string target;
  std::string readyFile;
  bool readyWritten{false};
};
