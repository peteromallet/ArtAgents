import path from 'node:path';
import {fileURLToPath} from 'node:url';

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const ACTIVE_THEME_DIR = path.resolve(__dirname, '_active_theme');
const ARTAGENTS_DIR = path.resolve(__dirname, '..');
const OVERRIDE_ELEMENTS_DIR = path.resolve(ARTAGENTS_DIR, '.artagents/elements/overrides');
const MANAGED_ELEMENTS_DIR = path.resolve(ARTAGENTS_DIR, '.artagents/elements/managed');
const BUILTIN_PACK_ELEMENTS_DIR = path.resolve(ARTAGENTS_DIR, 'artagents/packs/builtin/elements');
// Workspace-level effects/animations/transitions/themes/* live above the
// Remotion project, so their nearest node_modules walks up past the
// tools/remotion install. Add the Remotion project's node_modules to
// resolve.modules so they can `import` npm packages like
// @remotion/layout-utils that ship with this project.
const REMOTION_NODE_MODULES = path.resolve(__dirname, 'node_modules');

const primitiveAliases = {
  '@theme-elements-effects': path.resolve(ACTIVE_THEME_DIR, 'elements/effects'),
  '@theme-effects': path.resolve(ACTIVE_THEME_DIR, 'effects'),
  '@override-elements-effects': path.resolve(OVERRIDE_ELEMENTS_DIR, 'effects'),
  '@managed-elements-effects': path.resolve(MANAGED_ELEMENTS_DIR, 'effects'),
  '@pack-builtin-elements-effects': path.resolve(BUILTIN_PACK_ELEMENTS_DIR, 'effects'),
  '@theme-elements-animations': path.resolve(ACTIVE_THEME_DIR, 'elements/animations'),
  '@theme-animations': path.resolve(ACTIVE_THEME_DIR, 'animations'),
  '@override-elements-animations': path.resolve(OVERRIDE_ELEMENTS_DIR, 'animations'),
  '@managed-elements-animations': path.resolve(MANAGED_ELEMENTS_DIR, 'animations'),
  '@pack-builtin-elements-animations': path.resolve(BUILTIN_PACK_ELEMENTS_DIR, 'animations'),
  '@theme-elements-transitions': path.resolve(ACTIVE_THEME_DIR, 'elements/transitions'),
  '@theme-transitions': path.resolve(ACTIVE_THEME_DIR, 'transitions'),
  '@override-elements-transitions': path.resolve(OVERRIDE_ELEMENTS_DIR, 'transitions'),
  '@managed-elements-transitions': path.resolve(MANAGED_ELEMENTS_DIR, 'transitions'),
  '@pack-builtin-elements-transitions': path.resolve(BUILTIN_PACK_ELEMENTS_DIR, 'transitions'),
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
