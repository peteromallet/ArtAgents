import type {ReactElement} from 'react';
import {Composition} from 'remotion';
import {
  TimelineComposition,
  getTimelineDurationInFrames,
} from '@banodoco/timeline-composition';
import type {TimelineCompositionProps} from '@banodoco/timeline-composition';
import './fonts';

const DEFAULT_PROPS: TimelineCompositionProps = {
  timeline: {
    theme: 'banodoco-default',
    theme_overrides: {
      visual: {
        canvas: {
          width: 1920,
          height: 1080,
          fps: 30,
        },
      },
    },
    clips: [],
  },
  assets: {
    assets: {},
  },
};

const DEFAULT_CANVAS = {width: 1920, height: 1080, fps: 30};

const getCanvas = (props: TimelineCompositionProps) => {
  const overrides = (props.timeline.theme_overrides ?? {}) as {
    visual?: {canvas?: {width?: number; height?: number; fps?: number}};
  };
  return (
    overrides.visual?.canvas ??
    props.theme?.visual?.canvas ??
    DEFAULT_CANVAS
  );
};

export const Root = (): ReactElement => {
  return (
    <Composition
      id="TimelineComposition"
      component={TimelineComposition}
      defaultProps={DEFAULT_PROPS}
      calculateMetadata={async ({props}) => {
        const typedProps = props as TimelineCompositionProps;
        const canvas = getCanvas(typedProps);
        const fps = canvas.fps ?? 30;
        return {
          width: canvas.width ?? 1920,
          height: canvas.height ?? 1080,
          fps,
          durationInFrames: getTimelineDurationInFrames(typedProps.timeline, fps),
        };
      }}
    />
  );
};
