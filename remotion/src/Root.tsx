import type {ReactElement} from 'react';
import {Composition} from 'remotion';
import './fonts';
import {
  DEFAULT_THEME,
  TimelineComposition,
  getTimelineDurationInFrames,
  type TimelineCompositionProps,
} from '@banodoco/timeline-composition';

const DEFAULT_PROPS: TimelineCompositionProps = {
  timeline: {
    theme: 'banodoco-default',
    tracks: [
      {
        id: 'v1',
        kind: 'visual',
        label: 'Video',
      },
    ],
    clips: [],
  },
  assets: {
    assets: {},
  },
  theme: undefined,
};

export const Root = (): ReactElement => {
  return (
    <Composition
      // Sprint 5 rename: HypeComposition → TimelineComposition.
      // Banodoco's render path passes the new id; old callers that pass
      // "HypeComposition" should migrate (the python CLI default is updated).
      id="TimelineComposition"
      component={TimelineComposition}
      defaultProps={DEFAULT_PROPS}
      calculateMetadata={async ({props}) => {
        const themeForCanvas = props.theme ?? DEFAULT_THEME;
        const canvas = themeForCanvas.visual.canvas;
        return {
          width: canvas.width,
          height: canvas.height,
          fps: canvas.fps,
          durationInFrames: getTimelineDurationInFrames(props.timeline, canvas.fps),
        };
      }}
    />
  );
};
