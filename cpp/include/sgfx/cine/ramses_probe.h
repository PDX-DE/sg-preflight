#pragma once

#include <ramses/framework/RamsesObjectTypes.h>

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <functional>
#include <string>
#include <vector>

namespace ramses
{
class LogicEngine;
class RamsesFramework;
class Scene;
}

namespace sgfx::cine
{
std::string ramses_link_probe_message();

struct RamsesProbeMetadata
{
    std::string version_string;
    int version_major{0};
    int version_minor{0};
    int version_patch{0};
    std::uint32_t feature_level{0};
};

RamsesProbeMetadata collect_ramses_probe_metadata();

enum class FrameClassification
{
    Content,
    Black,
    Undetermined,
};

std::string frame_classification_code(FrameClassification classification);

FrameClassification classify_frame_rgba8(const std::vector<std::uint8_t>& pixels, std::size_t width,
                                         std::size_t height);

struct RamsesProbeFinding
{
    std::string severity;
    std::string message;
    std::string object_type;
    std::uint64_t object_id{0};
    std::string object_name;
    std::string source_class;
};

std::string probe_finding_identity(const RamsesProbeFinding& finding);

std::string ramses_object_type_name(ramses::ERamsesObjectType type);

std::vector<RamsesProbeFinding> collect_validation_findings(const ramses::Scene& scene);

struct RamsesProbeInventoryEntry
{
    std::string object_type;
    std::size_t count{0};
};

std::vector<RamsesProbeInventoryEntry> collect_scene_inventory(const ramses::Scene& scene);

struct RamsesLogicUpdateEvidence
{
    std::string engine_name;
    bool update_succeeded{false};
    std::string error_message;
    std::vector<std::string> executed_nodes;
    std::vector<std::string> skipped_nodes;
    std::int64_t total_update_microseconds{-1};
    std::int64_t topology_sort_microseconds{-1};
};

RamsesLogicUpdateEvidence collect_logic_update_evidence(ramses::RamsesFramework& framework,
                                                        ramses::LogicEngine& engine);

enum class ProbeLifecyclePhase
{
    Available = 0,
    Ready = 1,
    Rendered = 2,
    Readback = 3,
};

std::string probe_lifecycle_phase_code(ProbeLifecyclePhase phase);

struct RamsesLifecycleEvidence
{
    bool completed{false};
    std::string failure_phase;
    std::vector<std::string> reached_phases;
    std::int64_t elapsed_microseconds{-1};
};

RamsesLifecycleEvidence drive_probe_lifecycle(const std::function<bool(ProbeLifecyclePhase)>& phase_reached,
                                              const std::function<void()>& pump,
                                              std::chrono::milliseconds budget);

struct RamsesProbeCliRequest
{
    std::string profile;
    std::string backend;
    std::filesystem::path scene_path;
    std::filesystem::path output_root;
    std::filesystem::path perspective_path;
    std::string perspective_id;
};

struct RamsesProbeCliParse
{
    bool accepted{false};
    std::string rejection;
    RamsesProbeCliRequest request;
};

RamsesProbeCliParse parse_probe_arguments(const std::vector<std::string>& arguments);

inline constexpr int kProbeExitOk = 0;
inline constexpr int kProbeExitUsage = 64;
inline constexpr int kProbeExitData = 65;
inline constexpr int kProbeExitIo = 74;

struct RamsesProbePhaseRecord
{
    std::string phase;
    std::string status;
};

struct RamsesProbeNativeReport
{
    std::string profile;
    std::string backend;
    std::string scene_path;
    bool metadata_collected{false};
    RamsesProbeMetadata metadata;
    std::vector<RamsesProbePhaseRecord> phases;
    std::string failure_phase;
    std::string failure_reason;
    std::vector<RamsesProbeFinding> findings;
    std::vector<RamsesProbeInventoryEntry> inventory;
    std::vector<RamsesLogicUpdateEvidence> logic;
};

std::string serialize_probe_report(const RamsesProbeNativeReport& report);

struct RamsesProbeWriteResult
{
    bool written{false};
    std::string rejection;
    std::filesystem::path report_path;
};

RamsesProbeWriteResult write_probe_report_atomically(const std::filesystem::path& output_root,
                                                     const std::string& report_json);

struct RamsesProbeRunOutcome
{
    int exit_code{kProbeExitIo};
    std::string classification;
    std::filesystem::path report_path;
};

RamsesProbeRunOutcome execute_probe_request(const RamsesProbeCliRequest& request);
}
