import {Config} from '@remotion/cli/config';
import path from 'node:path';

const projectDir = process.cwd();
const activeThemeDir = path.resolve(projectDir, '_active_theme');
const artagentsDir = path.resolve(projectDir, '..');
const overrideElementsDir = path.resolve(artagentsDir, '.artagents/elements/overrides');
const managedElementsDir = path.resolve(artagentsDir, '.artagents/elements/managed');
const builtinPackElementsDir = path.resolve(artagentsDir, 'artagents/packs/builtin/elements');

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
Config.overrideWebpackConfig((currentConfiguration) => ({
  ...currentConfiguration,
  resolve: {
    ...currentConfiguration.resolve,
    alias: {
      ...currentConfiguration.resolve?.alias,
      // Keep in sync with tools/remotion/webpack-alias.mjs.
      '@theme-elements-effects': path.resolve(activeThemeDir, 'elements/effects'),
      '@theme-effects': path.resolve(activeThemeDir, 'effects'),
      '@override-elements-effects': path.resolve(overrideElementsDir, 'effects'),
      '@managed-elements-effects': path.resolve(managedElementsDir, 'effects'),
      '@pack-builtin-elements-effects': path.resolve(builtinPackElementsDir, 'effects'),
      '@theme-elements-animations': path.resolve(activeThemeDir, 'elements/animations'),
      '@theme-animations': path.resolve(activeThemeDir, 'animations'),
      '@override-elements-animations': path.resolve(overrideElementsDir, 'animations'),
      '@managed-elements-animations': path.resolve(managedElementsDir, 'animations'),
      '@pack-builtin-elements-animations': path.resolve(builtinPackElementsDir, 'animations'),
      '@theme-elements-transitions': path.resolve(activeThemeDir, 'elements/transitions'),
      '@theme-transitions': path.resolve(activeThemeDir, 'transitions'),
      '@override-elements-transitions': path.resolve(overrideElementsDir, 'transitions'),
      '@managed-elements-transitions': path.resolve(managedElementsDir, 'transitions'),
      '@pack-builtin-elements-transitions': path.resolve(builtinPackElementsDir, 'transitions'),
    },
    modules: [
      ...(currentConfiguration.resolve?.modules ?? ['node_modules']),
      path.resolve(projectDir, 'node_modules'),
    ],
  },
}));
