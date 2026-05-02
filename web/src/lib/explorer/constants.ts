export const COLD_OPEN_FADE_MS = 520;
export const COLD_OPEN_QUESTION_DELAY_MS = 1700;
export const COLD_OPEN_PROMPT_DELAY_MS = 4000;
export const COLD_OPEN_PRIMARY_REVEAL_DELAY_MS = 80;
export const COLD_OPEN_WHEEL_GESTURE_IDLE_MS = 55;
export const COLD_OPEN_WHEEL_ACTIVE_DELTA_MIN = 0.35;
export const COLD_OPEN_SESSION_SEEN_KEY = "climate.coldOpenSeen";

export const DEFAULT_OVERLAY_BASE_PATH = "/";

export const CHART_ANIMATION_DURATION_MS = 700;
export const HOME_FLY_DURATION_MS = 1200;

export const CLIMATE_DATA_LOAD_ERROR = "Couldn't load climate data.";

// Minimum recent warming (in display units) to show the "of which X since 1979" clause
// in the air temperature headline — suppresses near-zero deltas that read as noise.
export const AIR_TEMP_RECENT_THRESHOLD = 0.05;

export const DEFAULT_TITLE_ACTION_TEXT = "human activities have caused";
export const PREINDUSTRIAL_TITLE_SUFFIX = "since 1850-1900.";
export const PANEL_TITLE_INFO_PREINDUSTRIAL =
  "Local warming since pre-industrial (1850-1900 baseline) is estimated by combining observed local warming from ERA5 (1979-2025) with a CMIP6-based offset for 1850-1979, computed from 5 models. Source: CDS.";
export const PANEL_TITLE_INFO_RECENT =
  "Local warming is computed from recent annual means relative to the configured baseline year for the selected layer.";

export const MIN_PANEL_VIEWPORT_HEIGHT_FOR_TWO_GRAPHS = 600;
export const WHEEL_STEP_THRESHOLD = 130;
export const WHEEL_GESTURE_GAP_MS = 160;
export const WHEEL_SUSTAIN_REPEAT_MS = 520;
export const WHEEL_REPEAT_KICK_THRESHOLD = 55;
export const TOUCH_SWIPE_THRESHOLD_PX = 44;
export const TOUCH_SWIPE_MIN_VELOCITY_PX_MS = 0.7;
export const TOUCH_CLOSE_PANEL_THRESHOLD_PX = 72;
export const TOUCH_PANEL_LIFT_MAX_PX = 24;
export const TOUCH_PANEL_PULL_MAX_PX = 240;

// MapLibreGlobe — layout
export const PANEL_BREAKPOINT_PX = 900;
export const DESKTOP_PANEL_WIDTH_RATIO = 0.62;
export const MOBILE_PANEL_HEIGHT_RATIO = 0.6;

// Chat drawer — layout (must match ChatDrawer.module.css)
export const CHAT_DRAWER_BREAKPOINT_PX = 768;
export const CHAT_DRAWER_DESKTOP_RIGHT_PX = 380; // 360px width + 20px right offset
export const CHAT_DRAWER_MOBILE_HEIGHT_RATIO = 0.75; // min(75vh, 600px)
export const CHAT_DRAWER_MOBILE_HEIGHT_MAX_PX = 600;
export const CHAT_DRAWER_MOBILE_BOTTOM_PX = 14;

// MapLibreGlobe — zoom / navigation
export const DEFAULT_BASE_ZOOM = 2.5;
export const FOCUS_LOCATION_ZOOM = 5.5;
export const FOCUS_FLY_DURATION_MS = 1900;
export const FOCUS_RECENTER_DURATION_MS = 650;
export const PANEL_TRANSITION_MS = 300;

// MapLibreGlobe — geography
export const MERCATOR_MAX_LAT = 85.05112878;
// Tiny dateline overdraw hides wrap seams from compressed textures while
// keeping grid alignment error far below a 0.05° cell.
export const DATELINE_OVERDRAW_DEG = 1e-4;

// MapLibreGlobe — layer / source IDs
export const TEXTURE_SOURCE_ID = "climateTextureSource";
export const TEXTURE_LAYER_ID = "climateTextureLayer";
export const DEBUG_BBOX_SOURCE_ID = "debugPanelBboxSource";
export const DEBUG_BBOX_FILL_LAYER_ID = "debugPanelBboxFillLayer";
export const DEBUG_BBOX_LAYER_ID = "debugPanelBboxLayer";

// MapLibreGlobe — colors
export const BACKDROP_BLUE = "#0000ff";
export const BACKDROP_WHITE = "#ffffff";
export const BACKDROP_DARK_MODE = "#181818";
export const MARKER_COLOR = "#ff0000";

// MapLibreGlobe — city snap
export const CITY_SNAP_MAX_ZOOM = 6;
export const CITY_SNAP_RADIUS_PX = 28;
export const CITY_SNAP_LAYER_IDS = [
  "label_city_capital",
  "label_city",
] as const;

// MapLibreGlobe — layer menu
export const LAYER_MENU_AUTO_CLOSE_MS = 800;
export const LAYER_MENU_FADE_MS = 500;

// MapLibreGlobe — misc
export const MOBILE_TEXTURE_FALLBACK_LIMIT = 4096;
export const AUTO_ROTATE_DEG_PER_SEC = 3;

// Chat feature flag
export const CHAT_FEATURE_FLAG_KEY = "climate.chatBotEnabled";
export const CHAT_OPT_OUT_KEY = "climate.chatOptOut";
export const CHAT_MODEL_OVERRIDE_KEY = "climate.chatModelOverride";

// Chat question tree
export const CHAT_QUESTIONS_API_PATH = "/api/chat/questions";
export const CHAT_ROOT_CHIP_CAP = 8; // max chips shown in initial display
export const CHAT_FOLLOWUP_CHIP_CAP = 3; // max chips shown after an answer

export const CHAT_PRIVACY_NOTICE =
  "Your questions may be reviewed to improve the assistant.";
