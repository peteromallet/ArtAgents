import {Config} from '@remotion/cli/config';
import path from 'node:path';

const projectDir = process.cwd();
const activeThemeDir = path.resolve(projectDir, '_active_theme');
const artagentsDir = path.resolve(projectDir, '..');
const builtinPackElementsDir = path.resolve(artagentsDir, 'artagents/packs/builtin/elements');
const localPackElementsDir = path.resolve(artagentsDir, 'artagents/packs/local/elements');

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
      '@pack-local-elements-effects': path.resolve(localPackElementsDir, 'effects'),
      '@pack-builtin-elements-effects': path.resolve(builtinPackElementsDir, 'effects'),
      '@theme-elements-animations': path.resolve(activeThemeDir, 'elements/animations'),
      '@theme-animations': path.resolve(activeThemeDir, 'animations'),
      '@pack-local-elements-animations': path.resolve(localPackElementsDir, 'animations'),
      '@pack-builtin-elements-animations': path.resolve(builtinPackElementsDir, 'animations'),
      '@theme-elements-transitions': path.resolve(activeThemeDir, 'elements/transitions'),
      '@theme-transitions': path.resolve(activeThemeDir, 'transitions'),
      '@pack-local-elements-transitions': path.resolve(localPackElementsDir, 'transitions'),
      '@pack-builtin-elements-transitions': path.resolve(builtinPackElementsDir, 'transitions'),
      '@workspace-animations': path.resolve(builtinPackElementsDir, 'animations'),
      '@workspace-effects': path.resolve(builtinPackElementsDir, 'effects'),
      '@workspace-transitions': path.resolve(builtinPackElementsDir, 'transitions'),
    },
    modules: [
      ...(currentConfiguration.resolve?.modules ?? ['node_modules']),
      path.resolve(projectDir, 'node_modules'),
    ],
  },
}));
