#include "localization.hpp"

#include <algorithm>

namespace sg_preflight::native_shell {
namespace {

using enum ShellLanguage;
using enum UiText;

constexpr std::array<LanguageOption, 4> kSupportedLanguages = {{
    {ShellLanguage::English, "EN"},
    {ShellLanguage::Spanish, "ES"},
    {ShellLanguage::German, "DE"},
    {ShellLanguage::Romanian, "RO"},
}};

const char* TranslateEnglish(UiText text) {
    switch (text) {
    case HeaderPreflight: return "SERGFX QA Review";
    case HeaderChecking: return "SERGFX QA Review";
    case ImageSlotReserved: return "";
    case Continue: return "Continue";
    case Review: return "Review";
    case Run: return "Run";
    case Wait: return "Wait";
    case OpenFirst: return "Open First";
    case Files: return "Files";
    case Stages: return "Stages";
    case Environment: return "Environment";
    case Return: return "Return";
    case Next: return "Next";
    case Back: return "Back";
    case Quit: return "Quit";
    case Help: return "Help";
    case Select: return "Select";
    case RawLog: return "Raw Log";
    case Report: return "Report";
    case OpenFile: return "Open File";
    case Reveal: return "Reveal";
    case CopyJira: return "Copy Jira";
    case CopyQaHero: return "Copy QA Hero";
    case CopyHandoff: return "Copy Handoff";
    case Yes: return "Yes";
    case No: return "No";
    case Ok: return "OK";
    case CurrentDefault: return "CURRENT SELECTION";
    case LiveSlices: return "AVAILABLE SLICES";
    case SelectedSlice: return "SELECTED SLICE";
    case ActionPath: return "CHECK TO RUN";
    case ReadyBlocked: return "READY STATUS";
    case CurrentExecution: return "CURRENT EXECUTION";
    case ActionSignalLog: return "ACTION SIGNAL LOG";
    case LinkedResult: return "LINKED RESULT";
    case RecentLocalHistory: return "RECENT LOCAL HISTORY";
    case SelectedTarget: return "SELECTED TARGET";
    case FollowUp: return "FOLLOW-UP";
    case OpenFirstPaths: return "OPEN FIRST PATHS";
    case GeneratedFiles: return "GENERATED FILES";
    case BlockedStageStatus: return "BLOCKED STAGE STATUS";
    case ManualReview: return "MANUAL REVIEW";
    case DisplayMode: return "DISPLAY MODE";
    case ShellAudio: return "SHELL AUDIO";
    case UiSoundEffects: return "UI sound effects";
    case UiSoundEffectsSummary: return "Menu sounds stay on so navigation, confirm, cancel, and prompt feedback are always audible.";
    case InstallerBackgroundMusic: return "Installer background music";
    case InstallerBackgroundMusicSummary: return "Plays background music while the shell is open. It stays off by default unless enabled in imgui.ini or here.";
    case Summary: return "SUMMARY";
    case Snapshot: return "SNAPSHOT";
    case GroupedFindings: return "GROUPED FINDINGS";
    case RunNotes: return "RUN NOTES";
    case RecentActions: return "RECENT ACTIONS";
    case RecentResults: return "RECENT RESULTS";
    case Finding: return "FINDING";
    case ArtifactsReports: return "ARTIFACTS / REPORTS";
    case CopyExport: return "COPY / EXPORT";
    case CurrentAction: return "CURRENT ACTION";
    case ActionSummary: return "ACTION SUMMARY";
    case SignalLog: return "SIGNAL LOG";
    case ResultDrilldown: return "RESULT DRILLDOWN";
    case OpenSelected: return "OPEN SELECTED";
    case RevealSelected: return "REVEAL SELECTED";
    case OpenHtmlReport: return "OPEN HTML REPORT";
    case LocalState: return "LOCAL STATE";
    case LocalStateReady: return "LOCAL STATE READY";
    case LanguageSelection: return "LANGUAGE SELECTION";
    case CurrentSelection: return "CURRENT SELECTION";
    case AvailableLanguages: return "AVAILABLE LANGUAGES";
    case LanguageScreenTitle: return "Please select a language.";
    case LanguageScreenBody: return "Choose the language used by the shell interface.";
    case LanguageScreenHint: return "This only changes the shell text. Project data and generated results stay the same.";
    case IntroWelcome: return "Welcome to SERGFX.";
    case IntroBodyPrimary: return "SERGFX is the local desktop operator shell for SG-side 3D Car QA review.\n\nIt brings slice selection, SG checker execution, evidence capture, reports, exports, and follow-up material into one operator flow.";
    case IntroBodySecondary: return "Use it from left to right: choose the slice, choose the local check, review what will run, start the run, then open the first files, reports, exports, and blocked/manual follow-up collected for you.\n\nIt does not replace Blender visual review, RaCo / RaCoHeadless, rack sessions, or BMW screenshot smoke.";
    case SelectLoadingTitle: return "Loading local project data.";
    case SelectLoadingBody: return "The shell is loading the available slices, checks, and recent local results so you can choose what to run.";
    case SelectTitle: return "Choose the slice and local check for this run.";
    case SelectDailyMatrixBody: return "Run the recommended check flow across all ready slices and collect one shared review surface.";
    case NoActionMetadata: return "No action metadata is available for the current selection.";
    case ReviewLoadingTitle: return "Loading the selected slice and check.";
    case ReviewLoadingBody: return "This step is preparing the selected slice, the chosen check, and the most recent local results.";
    case ReviewTitle: return "Review the selected check before you start it.";
    case NoCommandPreview: return "No extra run details are available for this check yet.";
    case RunTitle: return "Run the selected local check and watch its live status.";
    case EvidenceTitle: return "Open the first result that needs attention.";
    case FilesTitle: return "Open generated files, reports, and exports.";
    case StagesTitle: return "Review blocked BMW/manual steps, follow-up, display mode, and audio settings.";
    case ReadyToRun: return "This local SG action is ready to run.";
    case ActionNotReady: return "This action is not ready on the current machine.";
    case CurrentOutputHelp: return "Default startup uses the current monitor size. Use --windowed --width <n> --height <n> if you want an override.";
    case NoProfilesDiscovered: return "No ready live profiles were discovered locally.";
    case NoEvidenceAvailable: return "No file-backed checker evidence is available for the current action.";
    case NoArtifactsAvailable: return "No artifact or report is attached to the current selection.";
    case NoGeneratedArtifacts: return "No generated artifacts were attached to this selection.";
    case NoLinkedRunSnapshot: return "No linked run snapshot is available yet.";
    case NoActionLog: return "No action log is available until a run is queued.";
    case NoSummaryLines: return "No summary lines yet.";
    case NoActiveActionOrRun: return "No action or run snapshot loaded.";
    case NoActiveActionLoaded: return "No active action or linked run is loaded yet.";
    case NoRecentActions: return "No recent actions yet for this selection.";
    case NoRecentRuns: return "No recent run records yet for this profile.";
    case NoRecentResults: return "No recent run records yet for this profile.";
    case NoManualFollowUp: return "No additional manual follow-up is attached to the current evidence selection.";
    case PromptQuitTitle: return "QUIT SERGFX";
    case PromptQuitMessage: return "Are you sure you want to quit?";
    case PromptQuitRunningMessage: return "Are you sure you want to quit? The current check will keep running in the background.";
    case PromptLeaveRunTitle: return "LEAVE RUN SCREEN";
    case PromptLeaveRunMessage: return "The current check is still running. Leave this page anyway? The check will keep running in the background.";
    }
    return "";
}

const char* TranslateSpanish(UiText text);
const char* TranslateGerman(UiText text);
const char* TranslateRomanian(UiText text);

const char* TranslateSpanish(UiText text) {
    switch (text) {
    case HeaderPreflight: return "SERGFX QA Review";
    case HeaderChecking: return "SERGFX QA Review";
    case ImageSlotReserved: return "ESPACIO DE IMAGEN RESERVADO";
    case Continue: return "CONTINUAR";
    case Review: return "REVISAR";
    case Run: return "EJECUTAR";
    case Wait: return "ESPERAR";
    case OpenFirst: return "ABRIR PRIMERO";
    case Files: return "ARCHIVOS";
    case Stages: return "ETAPAS";
    case Environment: return "ENTORNO";
    case Return: return "VOLVER";
    case Next: return "SIGUIENTE";
    case Back: return "ATRAS";
    case Quit: return "SALIR";
    case Help: return "AYUDA";
    case Select: return "SELECCIONAR";
    case RawLog: return "LOG EN BRUTO";
    case Report: return "REPORTE";
    case OpenFile: return "ABRIR ARCHIVO";
    case Reveal: return "MOSTRAR";
    case CopyJira: return "COPIAR JIRA";
    case CopyQaHero: return "COPIAR QA HERO";
    case CopyHandoff: return "COPIAR HANDOFF";
    case Yes: return "SI";
    case No: return "NO";
    case Ok: return "OK";
    case CurrentDefault: return "VALOR ACTUAL";
    case LiveSlices: return "SLICES ACTIVAS";
    case SelectedSlice: return "SLICE SELECCIONADA";
    case ActionPath: return "RUTA DE ACCION";
    case ReadyBlocked: return "LISTO / BLOQUEADO";
    case CurrentExecution: return "EJECUCION ACTUAL";
    case ActionSignalLog: return "LOG DE SENALES";
    case LinkedResult: return "RESULTADO VINCULADO";
    case RecentLocalHistory: return "HISTORIAL LOCAL";
    case SelectedTarget: return "OBJETIVO SELECCIONADO";
    case FollowUp: return "SEGUIMIENTO";
    case OpenFirstPaths: return "RUTAS OPEN FIRST";
    case GeneratedFiles: return "ARCHIVOS GENERADOS";
    case BlockedStageStatus: return "ESTADO DE BLOQUEOS";
    case ManualReview: return "REVISION MANUAL";
    case DisplayMode: return "MODO DE PANTALLA";
    case ShellAudio: return "AUDIO DEL SHELL";
    case UiSoundEffects: return "Efectos de sonido";
    case UiSoundEffectsSummary: return "Los sonidos de menu siguen activos para que navegar, confirmar, cancelar y responder a ventanas siempre se escuche.";
    case InstallerBackgroundMusic: return "Musica del instalador";
    case InstallerBackgroundMusicSummary: return "Reproduce en bucle la musica WAV local del instalador mientras el shell esta abierto.";
    case Summary: return "RESUMEN";
    case Snapshot: return "SNAPSHOT";
    case GroupedFindings: return "HALLAZGOS AGRUPADOS";
    case RunNotes: return "NOTAS DE EJECUCION";
    case RecentActions: return "ACCIONES RECIENTES";
    case RecentResults: return "RESULTADOS RECIENTES";
    case Finding: return "HALLAZGO";
    case ArtifactsReports: return "ARTEFACTOS / REPORTES";
    case CopyExport: return "COPIAR / EXPORTAR";
    case CurrentAction: return "ACCION ACTUAL";
    case ActionSummary: return "RESUMEN DE LA ACCION";
    case SignalLog: return "LOG DE SENALES";
    case ResultDrilldown: return "DETALLE DEL RESULTADO";
    case OpenSelected: return "ABRIR SELECCIONADO";
    case RevealSelected: return "MOSTRAR SELECCIONADO";
    case OpenHtmlReport: return "ABRIR REPORTE HTML";
    case LocalState: return "ESTADO LOCAL";
    case LocalStateReady: return "ESTADO LOCAL LISTO";
    case LanguageSelection: return "SELECCION DE IDIOMA";
    case CurrentSelection: return "SELECCION ACTUAL";
    case AvailableLanguages: return "IDIOMAS DISPONIBLES";
    case LanguageScreenTitle: return "Seleccione un idioma.";
    case LanguageScreenBody: return "Elija primero el idioma del shell y luego continue al flujo SG.";
    case LanguageScreenHint: return "Solo se traduce el texto del shell. Los datos reales de SG y la salida de checkers siguen tal cual.";
    case IntroWelcome: return "Bienvenido a SERGFX.";
    case IntroBodyPrimary: return "Seleccione la slice SG, confirme la preparacion local, ejecute una vez la accion real con checkers SG y luego siga Open First, Archivos y el seguimiento bloqueado/manual en orden.";
    case IntroBodySecondary: return "Este shell nativo sigue siendo solo una capa sobre el backend de Python. El flujo web, los packs deterministas, la evidencia SG y la honestidad sobre bloqueos BMW siguen intactos.";
    case SelectLoadingTitle: return "Cargando el estado SG.";
    case SelectLoadingBody: return "El shell nativo ahora pinta primero y carga el backend compartido en segundo plano para evitar la ventana blanca colgada al arrancar.";
    case SelectTitle: return "Elija la slice SG activa y la ruta de accion para esta ejecucion.";
    case SelectDailyMatrixBody: return "Ejecute el stack QA recomendado sobre todas las slices activas listas y recopile una superficie Open First compartida.";
    case NoActionMetadata: return "No hay metadatos de accion para la seleccion actual.";
    case ReviewLoadingTitle: return "Revise el objetivo seleccionado.";
    case ReviewLoadingBody: return "La etapa de confirmacion espera el mismo estado SG compartido del flujo web.";
    case ReviewTitle: return "Confirme la ejecucion SG local antes de lanzarla.";
    case NoCommandPreview: return "No hay vista previa del comando para esta accion.";
    case RunTitle: return "Ejecute o refresque la accion SG actual.";
    case EvidenceTitle: return "Abra primero la evidencia SG mas fuerte.";
    case FilesTitle: return "Revise archivos y reportes generados.";
    case StagesTitle: return "Mantenga visibles las etapas BMW bloqueadas/manuales y ajuste el shell sin ocultar los bloqueos reales.";
    case ReadyToRun: return "Esta accion SG local esta lista para ejecutarse.";
    case ActionNotReady: return "Esta accion no esta lista en esta maquina.";
    case CurrentOutputHelp: return "El arranque por defecto usa el tamano actual del monitor. Use --windowed --width <n> --height <n> si quiere forzarlo.";
    case NoProfilesDiscovered: return "No se encontraron perfiles activos listos localmente.";
    case NoEvidenceAvailable: return "No hay evidencia de checker asociada a la accion actual.";
    case NoArtifactsAvailable: return "No hay artefacto o reporte asociado a la seleccion actual.";
    case NoGeneratedArtifacts: return "No se adjuntaron artefactos generados a esta seleccion.";
    case NoLinkedRunSnapshot: return "Todavia no hay un snapshot de ejecucion vinculado.";
    case NoActionLog: return "No hay log de accion hasta que se lance una ejecucion.";
    case NoSummaryLines: return "Todavia no hay lineas de resumen.";
    case NoActiveActionOrRun: return "No hay snapshot de accion o ejecucion cargado.";
    case NoActiveActionLoaded: return "Todavia no hay una accion activa o un resultado vinculado.";
    case NoRecentActions: return "Todavia no hay acciones recientes para esta seleccion.";
    case NoRecentRuns: return "Todavia no hay registros recientes para este perfil.";
    case NoRecentResults: return "Todavia no hay resultados recientes para este perfil.";
    case NoManualFollowUp: return "No hay seguimiento manual adicional para la evidencia actual.";
    case PromptQuitTitle: return "SALIR DE SERGFX";
    case PromptQuitMessage: return "Cerrar SERGFX ahora?";
    case PromptQuitRunningMessage: return "Cerrar el shell ahora? La accion SG actual seguira ejecutandose en segundo plano.";
    case PromptLeaveRunTitle: return "SALIR DE LA PANTALLA";
    case PromptLeaveRunMessage: return "La accion SG actual sigue ejecutandose. Salir de esta pagina de todos modos? La accion seguira en segundo plano.";
    }
    return "";
}

const char* TranslateGerman(UiText text) {
    switch (text) {
    case HeaderPreflight: return "SERGFX QA Review";
    case HeaderChecking: return "SERGFX QA Review";
    case ImageSlotReserved: return "BILDPLATZ RESERVIERT";
    case Continue: return "WEITER";
    case Review: return "PRUEFEN";
    case Run: return "STARTEN";
    case Wait: return "WARTEN";
    case OpenFirst: return "ZUERST OEFFNEN";
    case Files: return "DATEIEN";
    case Stages: return "STUFEN";
    case Environment: return "UMGEBUNG";
    case Return: return "ZURUECK";
    case Next: return "WEITER";
    case Back: return "ZURUECK";
    case Quit: return "BEENDEN";
    case Help: return "HILFE";
    case Select: return "AUSWAHL";
    case RawLog: return "ROHLOG";
    case Report: return "BERICHT";
    case OpenFile: return "DATEI OEFFNEN";
    case Reveal: return "ANZEIGEN";
    case CopyJira: return "JIRA KOPIEREN";
    case CopyQaHero: return "QA HERO KOPIEREN";
    case CopyHandoff: return "HANDOFF KOPIEREN";
    case Yes: return "JA";
    case No: return "NEIN";
    case Ok: return "OK";
    case CurrentDefault: return "AKTUELLE VORGABE";
    case LiveSlices: return "LIVE-SLICES";
    case SelectedSlice: return "GEWAEHLTE SLICE";
    case ActionPath: return "AKTIONSPFAD";
    case ReadyBlocked: return "BEREIT / BLOCKIERT";
    case CurrentExecution: return "AKTUELLE AUSFUEHRUNG";
    case ActionSignalLog: return "SIGNALPROTOKOLL";
    case LinkedResult: return "VERKNUEPFTES ERGEBNIS";
    case RecentLocalHistory: return "LOKALE HISTORIE";
    case SelectedTarget: return "GEWAEHLTES ZIEL";
    case FollowUp: return "NACHARBEIT";
    case OpenFirstPaths: return "OPEN-FIRST-PFADE";
    case GeneratedFiles: return "ERZEUGTE DATEIEN";
    case BlockedStageStatus: return "BLOCKIERTE STUFEN";
    case ManualReview: return "MANUELLE PRUEFUNG";
    case DisplayMode: return "ANZEIGEMODUS";
    case ShellAudio: return "SHELL-AUDIO";
    case UiSoundEffects: return "UI-Soundeffekte";
    case UiSoundEffectsSummary: return "Menuklaenge bleiben aktiv, damit Navigation, Bestaetigung, Abbruch und Dialoge immer hoerbar sind.";
    case InstallerBackgroundMusic: return "Installer-Hintergrundmusik";
    case InstallerBackgroundMusicSummary: return "Spielt die lokale Installer-WAV in Schleife, waehrend das Shell offen ist.";
    case Summary: return "ZUSAMMENFASSUNG";
    case Snapshot: return "SNAPSHOT";
    case GroupedFindings: return "GRUPPIERTE FUNDE";
    case RunNotes: return "LAUFNOTIZEN";
    case RecentActions: return "LETZTE AKTIONEN";
    case RecentResults: return "LETZTE ERGEBNISSE";
    case Finding: return "FUND";
    case ArtifactsReports: return "ARTEFAKTE / BERICHTE";
    case CopyExport: return "KOPIEREN / EXPORT";
    case CurrentAction: return "AKTUELLE AKTION";
    case ActionSummary: return "AKTIONSZUSAMMENFASSUNG";
    case SignalLog: return "SIGNALPROTOKOLL";
    case ResultDrilldown: return "ERGEBNIS-DETAIL";
    case OpenSelected: return "AUSWAHL OEFFNEN";
    case RevealSelected: return "AUSWAHL ZEIGEN";
    case OpenHtmlReport: return "HTML-BERICHT OEFFNEN";
    case LocalState: return "LOKALER STATUS";
    case LocalStateReady: return "LOKALER STATUS BEREIT";
    case LanguageSelection: return "SPRACHAUSWAHL";
    case CurrentSelection: return "AKTUELLE AUSWAHL";
    case AvailableLanguages: return "VERFUEGBARE SPRACHEN";
    case LanguageScreenTitle: return "Bitte waehlen Sie eine Sprache.";
    case LanguageScreenBody: return "Waehlen Sie zuerst die Shell-Sprache und gehen Sie dann in den SG-Operatorfluss.";
    case LanguageScreenHint: return "Nur Shell-eigener Text wird uebersetzt. Echte SG-Daten und Checker-Ausgaben bleiben original.";
    case IntroWelcome: return "Willkommen bei SERGFX.";
    case IntroBodyPrimary: return "Waehlen Sie die SG-Slice, bestaetigen Sie die lokale Bereitschaft, starten Sie die echte SG-Checker-Aktion einmal und gehen Sie dann durch Open First, Dateien und blockierte/manuelle Nacharbeit.";
    case IntroBodySecondary: return "Dieses native Shell bleibt nur eine Huelle ueber dem Python-Backend. Browserfluss, deterministische Packs, SG-Evidence und BMW-Blocker-Ehrlichkeit bleiben erhalten.";
    case SelectLoadingTitle: return "SG-Status wird geladen.";
    case SelectLoadingBody: return "Das native Shell zeichnet jetzt zuerst und laedt den gemeinsamen Backend-Zustand im Hintergrund, damit kein weisses haengendes Fenster mehr erscheint.";
    case SelectTitle: return "Waehlen Sie die Live-SG-Slice und den Aktionspfad fuer diesen Lauf.";
    case SelectDailyMatrixBody: return "Fuehren Sie den empfohlenen SG-QA-Stack ueber alle bereiten Live-Profile aus und sammeln Sie eine gemeinsame Open-First-Flaeche.";
    case NoActionMetadata: return "Keine Aktionsmetadaten fuer die aktuelle Auswahl verfuegbar.";
    case ReviewLoadingTitle: return "Pruefen Sie das ausgewaehlte Ziel.";
    case ReviewLoadingBody: return "Der Bestaetigungsschritt wartet auf denselben Python-gestuetzten SG-Status wie der Browserfluss.";
    case ReviewTitle: return "Bestaetigen Sie den lokalen SG-Lauf vor dem Start.";
    case NoCommandPreview: return "Keine Befehlsvorschau fuer diese Aktion verfuegbar.";
    case RunTitle: return "Aktuelle SG-Aktion starten oder aktualisieren.";
    case EvidenceTitle: return "Oeffnen Sie zuerst die staerkste SG-Evidence.";
    case FilesTitle: return "Erzeugte Dateien und Berichte pruefen.";
    case StagesTitle: return "Halten Sie blockierte/manuelle BMW-Stufen sichtbar und passen Sie das Shell-Verhalten an, ohne reale Blocker zu verstecken.";
    case ReadyToRun: return "Diese lokale SG-Aktion ist startbereit.";
    case ActionNotReady: return "Diese Aktion ist auf diesem Rechner nicht bereit.";
    case CurrentOutputHelp: return "Der Standardstart nutzt die aktuelle Monitoraufloesung. Verwenden Sie --windowed --width <n> --height <n> fuer einen Override.";
    case NoProfilesDiscovered: return "Lokal wurden keine bereiten Live-Profile gefunden.";
    case NoEvidenceAvailable: return "Keine dateibasierte Checker-Evidence fuer die aktuelle Aktion verfuegbar.";
    case NoArtifactsAvailable: return "Kein Artefakt oder Bericht an die aktuelle Auswahl angehaengt.";
    case NoGeneratedArtifacts: return "Keine erzeugten Artefakte an diese Auswahl angehaengt.";
    case NoLinkedRunSnapshot: return "Noch kein verknuepfter Lauf-Snapshot verfuegbar.";
    case NoActionLog: return "Kein Aktionsprotokoll verfuegbar, bis ein Lauf gestartet wird.";
    case NoSummaryLines: return "Noch keine Zusammenfassungszeilen.";
    case NoActiveActionOrRun: return "Kein Aktions- oder Lauf-Snapshot geladen.";
    case NoActiveActionLoaded: return "Noch keine aktive Aktion oder kein verknuepftes Ergebnis geladen.";
    case NoRecentActions: return "Noch keine letzten Aktionen fuer diese Auswahl.";
    case NoRecentRuns: return "Noch keine letzten Laufdaten fuer dieses Profil.";
    case NoRecentResults: return "Noch keine letzten Ergebnisse fuer dieses Profil.";
    case NoManualFollowUp: return "Keine zusaetzliche manuelle Nacharbeit an diese Evidence angehaengt.";
    case PromptQuitTitle: return "SERGFX BEENDEN";
    case PromptQuitMessage: return "SERGFX jetzt schliessen?";
    case PromptQuitRunningMessage: return "Shell jetzt schliessen? Die aktuelle SG-Aktion laeuft im Hintergrund weiter.";
    case PromptLeaveRunTitle: return "LAUFSEITE VERLASSEN";
    case PromptLeaveRunMessage: return "Die aktuelle SG-Aktion laeuft noch. Diese Seite trotzdem verlassen? Die Aktion laeuft im Hintergrund weiter.";
    }
    return "";
}

const char* TranslateRomanian(UiText text) {
    switch (text) {
    case HeaderPreflight: return "SERGFX QA Review";
    case HeaderChecking: return "SERGFX QA Review";
    case ImageSlotReserved: return "SPATIU IMAGINE REZERVAT";
    case Continue: return "CONTINUA";
    case Review: return "REVIZUIRE";
    case Run: return "RULARE";
    case Wait: return "ASTEAPTA";
    case OpenFirst: return "DESCHIDE INTII";
    case Files: return "FISIERE";
    case Stages: return "ETAPE";
    case Environment: return "MEDIU";
    case Return: return "INAPOI";
    case Next: return "URMATORUL";
    case Back: return "INAPOI";
    case Quit: return "IESIRE";
    case Help: return "AJUTOR";
    case Select: return "SELECTEAZA";
    case RawLog: return "LOG BRUT";
    case Report: return "RAPORT";
    case OpenFile: return "DESCHIDE FISIER";
    case Reveal: return "ARATA";
    case CopyJira: return "COPIAZA JIRA";
    case CopyQaHero: return "COPIAZA QA HERO";
    case CopyHandoff: return "COPIAZA HANDOFF";
    case Yes: return "DA";
    case No: return "NU";
    case Ok: return "OK";
    case CurrentDefault: return "IMPLICIT ACUM";
    case LiveSlices: return "SLICE-URI LIVE";
    case SelectedSlice: return "SLICE SELECTAT";
    case ActionPath: return "CALE ACTIUNE";
    case ReadyBlocked: return "GATA / BLOCAT";
    case CurrentExecution: return "EXECUTIE CURENTA";
    case ActionSignalLog: return "LOG SEMNALE";
    case LinkedResult: return "REZULTAT LEGAT";
    case RecentLocalHistory: return "ISTORIC LOCAL";
    case SelectedTarget: return "TINTA SELECTATA";
    case FollowUp: return "URMARIRE";
    case OpenFirstPaths: return "CAI OPEN FIRST";
    case GeneratedFiles: return "FISIERE GENERATE";
    case BlockedStageStatus: return "ETAPE BLOCATE";
    case ManualReview: return "REVIZIE MANUALA";
    case DisplayMode: return "MOD AFISARE";
    case ShellAudio: return "AUDIO SHELL";
    case UiSoundEffects: return "Efecte sonore UI";
    case UiSoundEffectsSummary: return "Sunetele de meniu raman active, astfel incat navigarea, confirmarea, anularea si ferestrele sa fie mereu audibile.";
    case InstallerBackgroundMusic: return "Muzica instalatorului";
    case InstallerBackgroundMusicSummary: return "Ruleaza in bucla muzica WAV a instalatorului cat timp shell-ul este deschis.";
    case Summary: return "REZUMAT";
    case Snapshot: return "SNAPSHOT";
    case GroupedFindings: return "CONSTATARI GRUPATE";
    case RunNotes: return "NOTE RULARE";
    case RecentActions: return "ACTIUNI RECENTE";
    case RecentResults: return "REZULTATE RECENTE";
    case Finding: return "CONSTATATE";
    case ArtifactsReports: return "ARTEFACTE / RAPOARTE";
    case CopyExport: return "COPIERE / EXPORT";
    case CurrentAction: return "ACTIUNE CURENTA";
    case ActionSummary: return "REZUMAT ACTIUNE";
    case SignalLog: return "LOG SEMNAL";
    case ResultDrilldown: return "DETALIU REZULTAT";
    case OpenSelected: return "DESCHIDE SELECTIA";
    case RevealSelected: return "ARATA SELECTIA";
    case OpenHtmlReport: return "DESCHIDE RAPORT HTML";
    case LocalState: return "STARE LOCALA";
    case LocalStateReady: return "STARE LOCALA GATA";
    case LanguageSelection: return "SELECTIE LIMBA";
    case CurrentSelection: return "SELECTIA CURENTA";
    case AvailableLanguages: return "LIMBI DISPONIBILE";
    case LanguageScreenTitle: return "Selectati o limba.";
    case LanguageScreenBody: return "Alegeti mai intai limba shell-ului, apoi continuati in fluxul operator SG.";
    case LanguageScreenHint: return "Se traduce doar textul shell-ului. Datele SG reale si iesirea checkerelor raman in forma originala.";
    case IntroWelcome: return "Bine ati venit la SERGFX.";
    case IntroBodyPrimary: return "Alegeti slice-ul SG, confirmati pregatirea locala, rulati o singura data actiunea reala cu checkere SG, apoi treceti prin Open First, Fisiere si urmarirea blocata/manuala.";
    case IntroBodySecondary: return "Acest shell nativ ramane doar o interfata peste backend-ul Python. Fluxul din browser, pachetele deterministe, evidenta SG si onestitatea fata de blocajele BMW raman intacte.";
    case SelectLoadingTitle: return "Se incarca starea SG.";
    case SelectLoadingBody: return "Shell-ul nativ deseneaza acum primul si incarca backend-ul partajat in fundal, astfel incat pornirea sa nu mai arate o fereastra alba blocata.";
    case SelectTitle: return "Alegeti slice-ul SG live si calea de actiune pentru aceasta rulare.";
    case SelectDailyMatrixBody: return "Rulati stiva QA SG recomandata pe toate profilele live pregatite si colectati o singura suprafata Open First.";
    case NoActionMetadata: return "Nu exista metadate de actiune pentru selectia curenta.";
    case ReviewLoadingTitle: return "Revizuiti tinta selectata.";
    case ReviewLoadingBody: return "Pasul de confirmare asteapta aceeasi stare SG sustinuta de Python ca si fluxul din browser.";
    case ReviewTitle: return "Confirmati rularea locala SG inainte de lansare.";
    case NoCommandPreview: return "Nu exista previzualizare de comanda pentru aceasta actiune.";
    case RunTitle: return "Rulati sau reimprospatati actiunea SG curenta.";
    case EvidenceTitle: return "Deschideti mai intai cea mai puternica evidenta SG.";
    case FilesTitle: return "Revizuiti fisierele si rapoartele generate.";
    case StagesTitle: return "Pastrati vizibile etapele BMW blocate/manuale si ajustati shell-ul fara sa ascundeti blocajele reale.";
    case ReadyToRun: return "Aceasta actiune SG locala este gata de rulare.";
    case ActionNotReady: return "Aceasta actiune nu este gata pe aceasta masina.";
    case CurrentOutputHelp: return "Pornirea implicita foloseste dimensiunea monitorului curent. Folositi --windowed --width <n> --height <n> daca doriti o suprascriere.";
    case NoProfilesDiscovered: return "Nu au fost descoperite local profile live pregatite.";
    case NoEvidenceAvailable: return "Nu exista evidenta de checker bazata pe fisiere pentru actiunea curenta.";
    case NoArtifactsAvailable: return "Nu exista artefact sau raport atasat selectiei curente.";
    case NoGeneratedArtifacts: return "Nu exista artefacte generate atasate acestei selectii.";
    case NoLinkedRunSnapshot: return "Nu exista inca un snapshot de rulare legat.";
    case NoActionLog: return "Nu exista log de actiune pana nu este pusa in coada o rulare.";
    case NoSummaryLines: return "Nu exista inca linii de rezumat.";
    case NoActiveActionOrRun: return "Nu exista snapshot de actiune sau rulare incarcat.";
    case NoActiveActionLoaded: return "Nu exista inca o actiune activa sau un rezultat legat.";
    case NoRecentActions: return "Nu exista inca actiuni recente pentru aceasta selectie.";
    case NoRecentRuns: return "Nu exista inca inregistrari recente pentru acest profil.";
    case NoRecentResults: return "Nu exista inca rezultate recente pentru acest profil.";
    case NoManualFollowUp: return "Nu exista urmarire manuala suplimentara atasata selectiei curente.";
    case PromptQuitTitle: return "IESIRE DIN SERGFX";
    case PromptQuitMessage: return "Inchideti SERGFX acum?";
    case PromptQuitRunningMessage: return "Inchideti shell-ul acum? Actiunea SG curenta va continua in fundal.";
    case PromptLeaveRunTitle: return "PARASIRE ECRAN RULARE";
    case PromptLeaveRunMessage: return "Actiunea SG curenta ruleaza inca. Parasiti totusi aceasta pagina? Actiunea va continua in fundal.";
    }
    return "";
}

const char* TranslateSwitch(UiText text, ShellLanguage language) {
    switch (language) {
    case English:
        return TranslateEnglish(text);
    case Spanish:
        return TranslateSpanish(text);
    case German:
        return TranslateGerman(text);
    case Romanian:
        return TranslateRomanian(text);
    }
    return TranslateEnglish(text);
}

}  // namespace

const std::array<LanguageOption, 4>& SupportedLanguages() {
    return kSupportedLanguages;
}

const char* Translate(UiText text, ShellLanguage language) {
    return TranslateSwitch(text, language);
}

const char* LanguageCode(ShellLanguage language) {
    switch (language) {
    case English: return "EN";
    case Spanish: return "ES";
    case German: return "DE";
    case Romanian: return "RO";
    }
    return "EN";
}

const char* LanguageNativeName(ShellLanguage language) {
    switch (language) {
    case English: return "English";
    case Spanish: return "Espa\xC3\xB1ol";
    case German: return "Deutsch";
    case Romanian: return "Romana";
    }
    return "English";
}

int LanguageIndex(ShellLanguage language) {
    const auto& languages = SupportedLanguages();
    for (size_t index = 0; index < languages.size(); ++index) {
        if (languages[index].language == language) {
            return static_cast<int>(index);
        }
    }
    return 0;
}

ShellLanguage LanguageFromIndex(int index) {
    const auto& languages = SupportedLanguages();
    const int clamped = std::clamp(index, 0, static_cast<int>(languages.size()) - 1);
    return languages[static_cast<size_t>(clamped)].language;
}

std::string FormatReadyForNextActionStatus(ShellLanguage language) {
    switch (language) {
    case English: return "Ready to choose the next check.";
    case Spanish: return "Listo para la siguiente accion SG QA.";
    case German: return "Bereit fuer die naechste SG-QA-Aktion.";
    case Romanian: return "Gata pentru urmatoarea actiune SG QA.";
    }
    return "Ready for the next SG QA action.";
}

std::string FormatInitialLoadFailedStatus(ShellLanguage language) {
    switch (language) {
    case English: return "Loading local project data failed.";
    case Spanish: return "Fallo la carga inicial del estado SG.";
    case German: return "Der initiale SG-Desktopstatus konnte nicht geladen werden.";
    case Romanian: return "Incarcarea initiala a starii SG a esuat.";
    }
    return "Initial SG desktop-state load failed.";
}

std::string FormatNoProfilesDiscoveredStatus(ShellLanguage language) {
    switch (language) {
    case English: return "No ready slices were found in the current workspace.";
    case Spanish: return "No se descubrieron perfiles SG listos en el workspace actual.";
    case German: return "Im aktuellen Workspace wurden keine bereiten SG-Live-Profile gefunden.";
    case Romanian: return "Nu au fost descoperite profile SG live pregatite in workspace-ul curent.";
    }
    return "No ready SG live profiles were discovered in the current workspace.";
}

std::string FormatLoadedDesktopStateStatus(ShellLanguage language, std::string_view profile_id) {
    switch (language) {
    case English: return "Ready to choose a check for " + std::string(profile_id) + ".";
    case Spanish: return "Estado SG cargado para " + std::string(profile_id) + ".";
    case German: return "SG-Desktopstatus fuer " + std::string(profile_id) + " geladen.";
    case Romanian: return "Starea SG a fost incarcata pentru " + std::string(profile_id) + ".";
    }
    return "Loaded SG desktop state for " + std::string(profile_id) + ".";
}

std::string FormatQueuedActionStatus(ShellLanguage language, std::string_view action_id) {
    switch (language) {
    case English: return "Started the " + std::string(action_id) + " check.";
    case Spanish: return "Accion " + std::string(action_id) + " puesta en cola localmente.";
    case German: return std::string(action_id) + " lokal in die Warteschlange gestellt.";
    case Romanian: return "Actiunea " + std::string(action_id) + " a fost pusa local in coada.";
    }
    return "Queued " + std::string(action_id) + " locally.";
}

std::string FormatRefreshedRunStateStatus(ShellLanguage language) {
    switch (language) {
    case English: return "Refreshed the current run status.";
    case Spanish: return "Estado local de ejecucion refrescado.";
    case German: return "Lokaler Laufstatus aktualisiert.";
    case Romanian: return "Starea locala a rularii a fost actualizata.";
    }
    return "Refreshed local run state.";
}

std::string FormatCopiedItemStatus(ShellLanguage language, std::string_view label) {
    switch (language) {
    case English: return "Copied " + std::string(label) + ".";
    case Spanish: return "Copiado: " + std::string(label) + ".";
    case German: return std::string(label) + " kopiert.";
    case Romanian: return "Copiat: " + std::string(label) + ".";
    }
    return "Copied " + std::string(label) + ".";
}

std::string FormatCopiedJiraStatus(ShellLanguage language) {
    switch (language) {
    case English: return "Copied Jira note.";
    case Spanish: return "Nota de Jira copiada.";
    case German: return "Jira-Notiz kopiert.";
    case Romanian: return "Nota Jira a fost copiata.";
    }
    return "Copied Jira note.";
}

std::string FormatCopiedQaHeroStatus(ShellLanguage language) {
    switch (language) {
    case English: return "Copied QA Hero note.";
    case Spanish: return "Nota de QA Hero copiada.";
    case German: return "QA-Hero-Notiz kopiert.";
    case Romanian: return "Nota QA Hero a fost copiata.";
    }
    return "Copied QA Hero note.";
}

std::string FormatCopiedHandoffStatus(ShellLanguage language) {
    switch (language) {
    case English: return "Copied handoff note.";
    case Spanish: return "Nota de handoff copiada.";
    case German: return "Handoff-Notiz kopiert.";
    case Romanian: return "Nota de handoff a fost copiata.";
    }
    return "Copied handoff note.";
}

std::string FormatSfxStatus(ShellLanguage language, bool enabled) {
    switch (language) {
    case English: return std::string("UI sound effects ") + (enabled ? "enabled." : "disabled.");
    case Spanish: return std::string("Efectos de sonido ") + (enabled ? "activados." : "desactivados.");
    case German: return std::string("UI-Soundeffekte ") + (enabled ? "aktiviert." : "deaktiviert.");
    case Romanian: return std::string("Efectele UI sunt ") + (enabled ? "activate." : "dezactivate.");
    }
    return std::string("UI sound effects ") + (enabled ? "enabled." : "disabled.");
}

std::string FormatMusicStatus(ShellLanguage language, bool enabled) {
    switch (language) {
    case English: return std::string("Background music ") + (enabled ? "enabled." : "disabled.");
    case Spanish: return std::string("Musica del instalador ") + (enabled ? "activada." : "desactivada.");
    case German: return std::string("Installer-Hintergrundmusik ") + (enabled ? "aktiviert." : "deaktiviert.");
    case Romanian: return std::string("Muzica instalatorului este ") + (enabled ? "activata." : "dezactivata.");
    }
    return std::string("Installer background music ") + (enabled ? "enabled." : "disabled.");
}

std::string FormatDisplayModeStatus(ShellLanguage language, bool work_mode) {
    switch (language) {
    case English:
        return work_mode ? "Display mode set to Work. Background music stays off." : "Display mode set to Cinematic.";
    case Spanish:
        return work_mode ? "Modo de pantalla cambiado a Trabajo. La musica queda desactivada." : "Modo de pantalla cambiado a Cinematico.";
    case German:
        return work_mode ? "Anzeigemodus auf Arbeit gesetzt. Hintergrundmusik bleibt aus." : "Anzeigemodus auf Cinematic gesetzt.";
    case Romanian:
        return work_mode ? "Modul de afisare a fost setat pe Work. Muzica de fundal ramane oprita." : "Modul de afisare a fost setat pe Cinematic.";
    }
    return work_mode ? "Display mode set to Work. Background music stays off." : "Display mode set to Cinematic.";
}

std::string FormatLoadedChromeStatus(ShellLanguage language) {
    switch (language) {
    case English: return "Loading local project data.";
    case Spanish: return "Se cargaron los recursos visuales del shell.";
    case German: return "Die Oberflaechenressourcen des Shells wurden geladen.";
    case Romanian: return "Au fost incarcate resursele vizuale ale shell-ului.";
    }
    return "Loaded the shell interface assets.";
}

std::string FormatFallbackChromeStatus(ShellLanguage language, std::string_view error) {
    switch (language) {
    case English: return "Fallback interface active: " + std::string(error);
    case Spanish: return "Chrome de reserva activo: " + std::string(error);
    case German: return "Fallback-Chrome aktiv: " + std::string(error);
    case Romanian: return "Chrome de rezerva activ: " + std::string(error);
    }
    return "Fallback chrome active: " + std::string(error);
}

std::string FormatDisplayModeLine(ShellLanguage language, float width, float height, bool using_warp) {
    const std::string renderer = using_warp
        ? (language == English ? "software renderer fallback (WARP)" :
           language == Spanish ? "renderizador software de reserva (WARP)" :
           language == German ? "Software-Renderer-Fallback (WARP)" :
           "randare software de rezerva (WARP)")
        : (language == English ? "hardware D3D12" :
           language == Spanish ? "hardware D3D12" :
           language == German ? "D3D12-Hardware" :
           "hardware D3D12");
    switch (language) {
    case English:
        return "Current output: " + std::to_string(static_cast<int>(width)) + "x" + std::to_string(static_cast<int>(height)) + " | " + renderer;
    case Spanish:
        return "Salida actual: " + std::to_string(static_cast<int>(width)) + "x" + std::to_string(static_cast<int>(height)) + " | " + renderer;
    case German:
        return "Aktuelle Ausgabe: " + std::to_string(static_cast<int>(width)) + "x" + std::to_string(static_cast<int>(height)) + " | " + renderer;
    case Romanian:
        return "Iesire curenta: " + std::to_string(static_cast<int>(width)) + "x" + std::to_string(static_cast<int>(height)) + " | " + renderer;
    }
    return "Current output: " + std::to_string(static_cast<int>(width)) + "x" + std::to_string(static_cast<int>(height)) + " | " + renderer;
}

std::string FormatLanguageAppliedStatus(ShellLanguage active_language, ShellLanguage selected_language) {
    const std::string language_name = LanguageNativeName(selected_language);
    switch (active_language) {
    case English: return "Shell language set to " + language_name + ".";
    case Spanish: return "Idioma del shell cambiado a " + language_name + ".";
    case German: return "Shell-Sprache auf " + language_name + " gesetzt.";
    case Romanian: return "Limba shell-ului a fost schimbata in " + language_name + ".";
    }
    return "Shell language set to " + language_name + ".";
}

std::string FormatActionLabel(ShellLanguage language, std::string_view label) {
    switch (language) {
    case English: return "Selected check: " + std::string(label);
    case Spanish: return "Accion: " + std::string(label);
    case German: return "Aktion: " + std::string(label);
    case Romanian: return "Actiune: " + std::string(label);
    }
    return "Action: " + std::string(label);
}

std::string FormatCommandLabel(ShellLanguage language, std::string_view command) {
    switch (language) {
    case English: return "Command: " + std::string(command);
    case Spanish: return "Comando: " + std::string(command);
    case German: return "Befehl: " + std::string(command);
    case Romanian: return "Comanda: " + std::string(command);
    }
    return "Command: " + std::string(command);
}

std::string FormatCheckerLabel(ShellLanguage language, std::string_view checker) {
    switch (language) {
    case English: return "Checker: " + std::string(checker);
    case Spanish: return "Checker: " + std::string(checker);
    case German: return "Checker: " + std::string(checker);
    case Romanian: return "Checker: " + std::string(checker);
    }
    return "Checker: " + std::string(checker);
}

std::string FormatLineNumberLabel(ShellLanguage language, int line) {
    switch (language) {
    case English: return "Line " + std::to_string(line);
    case Spanish: return "Linea " + std::to_string(line);
    case German: return "Zeile " + std::to_string(line);
    case Romanian: return "Linia " + std::to_string(line);
    }
    return "Line " + std::to_string(line);
}

}  // namespace sg_preflight::native_shell
