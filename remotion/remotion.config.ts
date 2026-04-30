import {Config} from '@remotion/cli/config';
import path from 'node:path';

const projectDir = process.cwd();
const activeThemeDir = path.resolve(projectDir, '_active_theme');

Config.setVideoImageFormat('jpeg');
Config.setOverwriteOutput(true);
Config.overrideWebpackConfig((currentConfiguration) => ({
  ...currentConfiguration,
  resolve: {
    ...currentConfiguration.resolve,
    alias: {
      ...currentConfiguration.resolve?.alias,
      // Keep in sync with tools/remotion/webpack-alias.mjs.
      '@workspace-effects': path.resolve(projectDir, '../../effects'),
      '@theme-effects': path.resolve(activeThemeDir, 'effects'),
      '@workspace-animations': path.resolve(projectDir, '../../animations'),
      '@theme-animations': path.resolve(activeThemeDir, 'animations'),
      '@workspace-transitions': path.resolve(projectDir, '../../transitions'),
      '@theme-transitions': path.resolve(activeThemeDir, 'transitions'),
    },
    modules: [
      ...(currentConfiguration.resolve?.modules ?? ['node_modules']),
      path.resolve(projectDir, 'node_modules'),
    ],
  },
}));
