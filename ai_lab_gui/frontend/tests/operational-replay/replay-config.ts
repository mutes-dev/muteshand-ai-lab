export interface ReplayConfig {
  testTimeout: number;
  pollTimeout: number;
  pollIntervals: number[];
  visualWaitTimeout: number;
  networkIdleTimeout: number;
  slowMo: number;
  headed: boolean;
  debug: boolean;
}

export const DEFAULT_REPLAY_CONFIG: ReplayConfig = {
  testTimeout: 90000,        // 90s max per replay
  pollTimeout: 30000,        // 30s for runtime polling
  pollIntervals: [1000, 2000], // 1s then 2s intervals
  visualWaitTimeout: 30000,  // 30s for visual state
  networkIdleTimeout: 10000, // 10s for network idle
  slowMo: 0,                 // No slow motion by default
  headed: false,             // Headless by default
  debug: false,              // No debug by default
};

export const DEBUG_REPLAY_CONFIG: ReplayConfig = {
  ...DEFAULT_REPLAY_CONFIG,
  slowMo: 500,               // 500ms between actions
  headed: true,              // Run headed
  debug: true,               // Enable debug features
  pollTimeout: 60000,        // Longer timeout for debugging
  visualWaitTimeout: 60000,  // Longer visual wait
};

export const getReplayConfig = (): ReplayConfig => {
  if (process.env.DEBUG_REPLAY === 'true') {
    return DEBUG_REPLAY_CONFIG;
  }
  
  const slowMo = process.env.REPLAY_SLOW_MO ? parseInt(process.env.REPLAY_SLOW_MO) : 0;
  if (slowMo > 0) {
    return {
      ...DEFAULT_REPLAY_CONFIG,
      slowMo,
    };
  }
  
  return DEFAULT_REPLAY_CONFIG;
};

export const LEGAL_LIFECYCLE_STATES = {
  ACTIVE: 'ACTIVE',
  COMPLETED: 'COMPLETED',
  PAUSED: 'PAUSED',
  FAILED: 'FAILED',
  CANCELLED: 'CANCELLED',
  PENDING_RECOVERY: 'PENDING_RECOVERY',
} as const;

export const CONTINUITY_LEGAL_STATES = [
  LEGAL_LIFECYCLE_STATES.ACTIVE,
  LEGAL_LIFECYCLE_STATES.COMPLETED,
  LEGAL_LIFECYCLE_STATES.PAUSED,
];

export const TERMINAL_STATES = [
  LEGAL_LIFECYCLE_STATES.COMPLETED,
  LEGAL_LIFECYCLE_STATES.FAILED,
  LEGAL_LIFECYCLE_STATES.CANCELLED,
];

export const ACTIVE_STATES = [
  LEGAL_LIFECYCLE_STATES.ACTIVE,
  LEGAL_LIFECYCLE_STATES.PAUSED,
];

export const WORKFLOW_PROMPTS = {
  SHORT_ARITHMETIC: 'Add 100 and 200.\nMultiply by 3.',
  LONGER_PROCESSING: 'Analyze the following text and provide a detailed summary:\n"Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat. Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia deserunt mollit anim id est laborum."\n\nExtract key themes and provide insights.',
  FAILURE_PRONE: 'Attempt to divide by zero in a mathematical calculation.',
  EDIT_MUTATION: 'Calculate the square of 42.',
  MULTI_STEP: 'Step 1: Generate a random number between 1 and 100.\nStep 2: Calculate its square root.\nStep 3: Multiply by 10.\nStep 4: Round to nearest integer.',
} as const;

export const SELECTORS = {
  CHAT_INPUT: '.chat-input',
  SEND_BUTTON: '.chat-input-row button',
  PAUSE_BUTTON: 'button[aria-label*="Pause"], button:has-text("Pause")',
  RESUME_BUTTON: 'button[aria-label*="Resume"], button:has-text("Resume")',
  CANCEL_BUTTON: 'button[aria-label*="Cancel"], button:has-text("Cancel")',
  TASK_HUB_BUTTON: 'button:has-text("Task Hub")',
  EDIT_MODE_BUTTON: 'button[aria-label*="Edit"], button:has-text("Edit")',
  WORKFLOW_SURFACE: '.workflow-surface',
  WORKFLOW_STATUS: '.workflow-surface-status',
  STEP_LIST: '.step-list',
  STEP_ITEM: '.step-item',
  ACTIVE_STEP: '.step-item--active',
  EDITABLE_FIELD: '[contenteditable="true"], input[type="text"], textarea',
} as const;
