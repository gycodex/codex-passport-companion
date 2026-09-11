cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)

# Preserve the factory Recovery entry gesture when the USB flash replaces the
# bootloader. Holding UP for five seconds jumps to the protected image at 0x700000.
idf_build_set_property(
    BOOTLOADER_EXTRA_COMPONENT_DIRS
    "${CMAKE_CURRENT_LIST_DIR}/bootloader_components/"
    APPEND)

set(PROJECT_VER "0.2.1")
project(FoloToy-AI-Passport)
