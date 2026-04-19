#pragma once

#include <array>
#include <string>
#include <string_view>

namespace sg_preflight::native_shell {

enum class ShellLanguage {
    English,
    Spanish,
    German,
    Romanian,
};

enum class UiText {
    HeaderPreflight,
    HeaderChecking,
    ImageSlotReserved,
    Continue,
    Review,
    Run,
    Wait,
    OpenFirst,
    Files,
    Stages,
    Return,
    Next,
    Back,
    Quit,
    Help,
    Select,
    RawLog,
    Report,
    OpenFile,
    Reveal,
    CopyJira,
    CopyQaHero,
    CopyHandoff,
    Yes,
    No,
    Ok,
    CurrentDefault,
    LiveSlices,
    SelectedSlice,
    ActionPath,
    ReadyBlocked,
    CurrentExecution,
    ActionSignalLog,
    LinkedResult,
    RecentLocalHistory,
    SelectedTarget,
    FollowUp,
    OpenFirstPaths,
    GeneratedFiles,
    BlockedStageStatus,
    ManualReview,
    DisplayMode,
    ShellAudio,
    UiSoundEffects,
    UiSoundEffectsSummary,
    InstallerBackgroundMusic,
    InstallerBackgroundMusicSummary,
    Summary,
    Snapshot,
    GroupedFindings,
    RunNotes,
    RecentActions,
    RecentResults,
    Finding,
    ArtifactsReports,
    CopyExport,
    CurrentAction,
    ActionSummary,
    SignalLog,
    ResultDrilldown,
    OpenSelected,
    RevealSelected,
    OpenHtmlReport,
    LocalState,
    LocalStateReady,
    LanguageSelection,
    CurrentSelection,
    AvailableLanguages,
    LanguageScreenTitle,
    LanguageScreenBody,
    LanguageScreenHint,
    IntroWelcome,
    IntroBodyPrimary,
    IntroBodySecondary,
    SelectLoadingTitle,
    SelectLoadingBody,
    SelectTitle,
    SelectDailyMatrixBody,
    NoActionMetadata,
    ReviewLoadingTitle,
    ReviewLoadingBody,
    ReviewTitle,
    NoCommandPreview,
    RunTitle,
    EvidenceTitle,
    FilesTitle,
    StagesTitle,
    ReadyToRun,
    ActionNotReady,
    CurrentOutputHelp,
    NoProfilesDiscovered,
    NoEvidenceAvailable,
    NoArtifactsAvailable,
    NoGeneratedArtifacts,
    NoLinkedRunSnapshot,
    NoActionLog,
    NoSummaryLines,
    NoActiveActionOrRun,
    NoActiveActionLoaded,
    NoRecentActions,
    NoRecentRuns,
    NoRecentResults,
    NoManualFollowUp,
    PromptQuitTitle,
    PromptQuitMessage,
    PromptQuitRunningMessage,
    PromptLeaveRunTitle,
    PromptLeaveRunMessage,
};

struct LanguageOption {
    ShellLanguage language;
    const char* code;
};

const std::array<LanguageOption, 4>& SupportedLanguages();
const char* Translate(UiText text, ShellLanguage language);
const char* LanguageCode(ShellLanguage language);
const char* LanguageNativeName(ShellLanguage language);
int LanguageIndex(ShellLanguage language);
ShellLanguage LanguageFromIndex(int index);

std::string FormatReadyForNextActionStatus(ShellLanguage language);
std::string FormatInitialLoadFailedStatus(ShellLanguage language);
std::string FormatNoProfilesDiscoveredStatus(ShellLanguage language);
std::string FormatLoadedDesktopStateStatus(ShellLanguage language, std::string_view profile_id);
std::string FormatQueuedActionStatus(ShellLanguage language, std::string_view action_id);
std::string FormatRefreshedRunStateStatus(ShellLanguage language);
std::string FormatCopiedItemStatus(ShellLanguage language, std::string_view label);
std::string FormatCopiedJiraStatus(ShellLanguage language);
std::string FormatCopiedQaHeroStatus(ShellLanguage language);
std::string FormatCopiedHandoffStatus(ShellLanguage language);
std::string FormatSfxStatus(ShellLanguage language, bool enabled);
std::string FormatMusicStatus(ShellLanguage language, bool enabled);
std::string FormatLoadedChromeStatus(ShellLanguage language);
std::string FormatFallbackChromeStatus(ShellLanguage language, std::string_view error);
std::string FormatDisplayModeLine(ShellLanguage language, float width, float height, bool using_warp);
std::string FormatLanguageAppliedStatus(ShellLanguage active_language, ShellLanguage selected_language);
std::string FormatActionLabel(ShellLanguage language, std::string_view label);
std::string FormatCommandLabel(ShellLanguage language, std::string_view command);
std::string FormatCheckerLabel(ShellLanguage language, std::string_view checker);
std::string FormatLineNumberLabel(ShellLanguage language, int line);

}  // namespace sg_preflight::native_shell
