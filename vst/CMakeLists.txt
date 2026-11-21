cmake_minimum_required(VERSION 3.22)

project(EightBallVST VERSION 0.1.0 LANGUAGES C CXX)

# Link the MSVC runtime statically so Eight Ball.exe and Eight Ball.vst3 run on PCs
# without the Visual C++ Redistributable installed.
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ---------------------------------------------------------------------------
# JUCE: use a local checkout if EIGHTBALL_JUCE_DIR is given, otherwise fetch it.
# (build.bat passes an existing download from a sibling project when there is one.)
# ---------------------------------------------------------------------------
set(EIGHTBALL_JUCE_DIR "" CACHE PATH "Optional path to a local JUCE checkout")
set(EIGHTBALL_JUCE_TAG "8.0.17-security" CACHE STRING "JUCE git tag to fetch")

if(EIGHTBALL_JUCE_DIR AND EXISTS "${EIGHTBALL_JUCE_DIR}/CMakeLists.txt")
    add_subdirectory("${EIGHTBALL_JUCE_DIR}" JUCE)
else()
    include(FetchContent)
    FetchContent_Declare(JUCE
        GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
        GIT_TAG        ${EIGHTBALL_JUCE_TAG}
        GIT_SHALLOW    TRUE
        GIT_PROGRESS   TRUE)
    FetchContent_MakeAvailable(JUCE)
endif()

# ---------------------------------------------------------------------------
# Plugin: VST3 + Standalone
# ---------------------------------------------------------------------------
juce_add_plugin(EightBallVST
    COMPANY_NAME            "EightBall"
    PRODUCT_NAME            "Eight Ball"
    PLUGIN_MANUFACTURER_CODE Ebal
    PLUGIN_CODE             Eb8b
    FORMATS                 VST3 Standalone
    IS_SYNTH                TRUE
    NEEDS_MIDI_INPUT        TRUE
    NEEDS_MIDI_OUTPUT       FALSE
    IS_MIDI_EFFECT          FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS TRUE
    VST3_CATEGORIES         Instrument Synth
    NEEDS_WEBVIEW2          TRUE
    ICON_BIG                "${CMAKE_CURRENT_SOURCE_DIR}/icon/eight-ball-256.png"
    ICON_SMALL              "${CMAKE_CURRENT_SOURCE_DIR}/icon/eight-ball-32.png"
    COPY_PLUGIN_AFTER_BUILD FALSE)

# The UI (HTML/CSS/JS/SVG) and the factory presets are compiled into the binary.
file(GLOB_RECURSE EIGHTBALL_UI_FILES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/ui/*.html"
    "${CMAKE_CURRENT_SOURCE_DIR}/ui/*.css"
    "${CMAKE_CURRENT_SOURCE_DIR}/ui/*.js"
    "${CMAKE_CURRENT_SOURCE_DIR}/ui/*.svg")
juce_add_binary_data(EightBallUI SOURCES ${EIGHTBALL_UI_FILES} presets/factory_presets.json)

target_sources(EightBallVST PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginEditor.cpp
    Source/PresetManager.cpp
    Source/ModelStore.cpp)

target_include_directories(EightBallVST PRIVATE Source)

target_compile_definitions(EightBallVST PUBLIC
    JUCE_WEB_BROWSER=1
    JUCE_USE_WIN_WEBVIEW2_WITH_STATIC_LINKING=1
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_DISPLAY_SPLASH_SCREEN=0)

target_link_libraries(EightBallVST
    PRIVATE
        EightBallUI
        juce::juce_audio_utils
        juce::juce_gui_extra
        juce::juce_dsp
    PUBLIC
        juce::juce_recommended_config_flags
        juce::juce_recommended_lto_flags
        juce::juce_recommended_warning_flags)

# ---------------------------------------------------------------------------
# Console tests + engine tools:  --target EightBallTests
# ---------------------------------------------------------------------------
juce_add_console_app(EightBallTests PRODUCT_NAME "EightBallTests")
target_sources(EightBallTests PRIVATE
    tests/PresetTests.cpp tests/EngineTests.cpp tests/EngineTools.cpp tests/HostCheck.cpp
    Source/PresetManager.cpp Source/ModelStore.cpp)
target_include_directories(EightBallTests PRIVATE Source)
# JUCE_PLUGINHOST_VST3: --host-check loads the built .vst3 like a DAW would
target_compile_definitions(EightBallTests PRIVATE JUCE_USE_CURL=0 JUCE_WEB_BROWSER=0 JUCE_PLUGINHOST_VST3=1)
target_link_libraries(EightBallTests PRIVATE EightBallUI juce::juce_audio_processors juce::juce_audio_formats juce::juce_gui_basics
    PUBLIC juce::juce_recommended_config_flags juce::juce_recommended_warning_flags)
