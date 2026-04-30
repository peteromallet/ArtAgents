import path from 'node:path';
import {fileURLToPath} from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const WORKSPACE_EFFECTS_DIR = path.resolve(__dirname, '../../effects');
const WORKSPACE_ANIMATIONS_DIR = path.resolve(__dirname, '../../animations');
const WORKSPACE_TRANSITIONS_DIR = path.resolve(__dirname, '../../transitions');
const ACTIVE_THEME_DIR = path.resolve(__dirname, '_active_theme');
// Workspace-level effects/animations/transitions/themes/* live above the
// Remotion project, so their nearest node_modules walks up past the
// tools/remotion install. Add the Remotion project's node_modules to
// resolve.modules so they can `import` npm packages like
// @remotion/layout-utils that ship with this project.
const REMOTION_NODE_MODULES = path.resolve(__dirname, 'node_modules');

const primitiveAliases = {
  '@workspace-effects': WORKSPACE_EFFECTS_DIR,
  '@theme-effects': path.resolve(ACTIVE_THEME_DIR, 'effects'),
  '@workspace-animations': WORKSPACE_ANIMATIONS_DIR,
  '@theme-animations': path.resolve(ACTIVE_THEME_DIR, 'animations'),
  '@workspace-transitions': WORKSPACE_TRANSITIONS_DIR,
  '@theme-transitions': path.resolve(ACTIVE_THEME_DIR, 'transitions'),
};

export const applyRemotionPrimitiveAliases = (currentConfiguration) => ({
  ...currentConfiguration,
  resolve: {
    ...currentConfiguration.resolve,
    alias: {
      ...currentConfiguration.resolve?.alias,
      ...primitiveAliases,
    },
    modules: [
      ...(currentConfiguration.resolve?.modules ?? ['node_modules']),
      REMOTION_NODE_MODULES,
    ],
  },
});

export const applyWorkspaceEffectsAlias = applyRemotionPrimitiveAliases;
