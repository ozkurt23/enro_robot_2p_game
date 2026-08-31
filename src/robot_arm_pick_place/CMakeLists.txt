cmake_minimum_required(VERSION 3.8)
project(robot_arm_pick_place)

find_package(ament_cmake REQUIRED)

install(PROGRAMS
  scripts/pick_place_terminal.py
  scripts/mobile_object_case.py
  scripts/start_pick_place.sh
  DESTINATION lib/${PROJECT_NAME}
)
install(DIRECTORY launch/
  DESTINATION share/${PROJECT_NAME}/launch
)

ament_package()
