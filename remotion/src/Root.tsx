import type {ReactElement, CSSProperties} from 'react';
import {
  AbsoluteFill,
  Composition,
  Img,
  Sequence,
  Video,
  interpolate,
  spring,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';
import './fonts';

type AssetRegistry = {
  assets?: Record<string, {file?: string; type?: string; duration?: number}>;
};

type TimelineClip = {
  id: string;
  at: number;
  track: string;
  clipType?: string;
  asset?: string;
  from?: number;
  to?: number;
  hold?: number;
  volume?: number;
  opacity?: number;
  x?: number;
  y?: number;
  width?: number;
  height?: number;
  text?: {
    content?: string;
    fontFamily?: string;
    fontSize?: number;
    color?: string;
    align?: 'left' | 'center' | 'right';
    bold?: boolean;
    italic?: boolean;
  };
  params?: Record<string, unknown>;
};

type TimelineConfig = {
  theme?: string;
  theme_overrides?: {
    visual?: {
      canvas?: {
        width?: number;
        height?: number;
        fps?: number;
      };
    };
  };
  clips?: TimelineClip[];
};

type TimelineCompositionProps = {
  timeline: TimelineConfig;
  assets: AssetRegistry;
  theme?: {
    visual?: {
      canvas?: {
        width?: number;
        height?: number;
        fps?: number;
      };
    };
  };
};

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

const getCanvas = (props: TimelineCompositionProps) =>
  props.timeline.theme_overrides?.visual?.canvas ?? props.theme?.visual?.canvas ?? DEFAULT_CANVAS;

const assetSrc = (assets: AssetRegistry, key: unknown): string | undefined => {
  if (typeof key !== 'string') {
    return undefined;
  }
  return assets.assets?.[key]?.file;
};

const clipDurationFrames = (clip: TimelineClip, fps: number): number => {
  if (typeof clip.hold === 'number') {
    return Math.max(1, Math.round(clip.hold * fps));
  }
  if (typeof clip.to === 'number') {
    const from = typeof clip.from === 'number' ? clip.from : 0;
    return Math.max(1, Math.round(Math.max(0, clip.to - from) * fps));
  }
  return Math.round(5 * fps);
};

const getTimelineDurationInFrames = (timeline: TimelineConfig, fps: number): number => {
  const clips = timeline.clips ?? [];
  if (clips.length === 0) {
    return fps;
  }
  return Math.max(
    fps,
    ...clips.map((clip) => Math.round((clip.at ?? 0) * fps) + clipDurationFrames(clip, fps)),
  );
};

const isVisualAsset = (src: string | undefined): boolean =>
  Boolean(src && !/\.(mp3|wav|m4a|aac|flac|ogg)(\?|$)/i.test(src));

const px = (value: number | undefined, fallback: number): number =>
  typeof value === 'number' ? value : fallback;

const TimelineComposition = ({timeline, assets}: TimelineCompositionProps): ReactElement => {
  const {fps, width, height} = useVideoConfig();
  const clips = [...(timeline.clips ?? [])].sort((a, b) => (a.at ?? 0) - (b.at ?? 0));
  return (
    <AbsoluteFill style={{background: '#0d0d10'}}>
      {clips.map((clip) => {
        const fromFrame = Math.round((clip.at ?? 0) * fps);
        const durationFrames = clipDurationFrames(clip, fps);
        return (
          <Sequence key={clip.id} from={fromFrame} durationInFrames={durationFrames}>
            <RenderClip clip={clip} assets={assets} canvasWidth={width} canvasHeight={height} />
          </Sequence>
        );
      })}
    </AbsoluteFill>
  );
};

const RenderClip = ({
  clip,
  assets,
  canvasWidth,
  canvasHeight,
}: {
  clip: TimelineClip;
  assets: AssetRegistry;
  canvasWidth: number;
  canvasHeight: number;
}): ReactElement | null => {
  const clipType = clip.clipType ?? 'media';
  if (clipType === 'media') {
    const src = assetSrc(assets, clip.asset);
    if (!isVisualAsset(src)) {
      return null;
    }
    const style: CSSProperties = {
      position: 'absolute',
      left: px(clip.x, 0),
      top: px(clip.y, 0),
      width: px(clip.width, canvasWidth),
      height: px(clip.height, canvasHeight),
      objectFit: 'contain',
      opacity: clip.opacity ?? 1,
    };
    return (
      <Video
        src={src as string}
        startFrom={Math.round((clip.from ?? 0) * useVideoConfig().fps)}
        endAt={typeof clip.to === 'number' ? Math.round(clip.to * useVideoConfig().fps) : undefined}
        volume={clip.volume ?? 1}
        style={style}
      />
    );
  }
  if (clipType === 'text') {
    const text = clip.text ?? {};
    return (
      <div
        style={{
          position: 'absolute',
          left: px(clip.x, 0),
          top: px(clip.y, 0),
          width: px(clip.width, canvasWidth),
          height: px(clip.height, canvasHeight),
          color: text.color ?? '#f7f7f7',
          fontFamily: text.fontFamily ?? 'Inter, Arial, sans-serif',
          fontSize: text.fontSize ?? 48,
          fontWeight: text.bold ? 700 : 400,
          fontStyle: text.italic ? 'italic' : 'normal',
          textAlign: text.align ?? 'left',
          opacity: clip.opacity ?? 1,
          lineHeight: 1.05,
          whiteSpace: 'pre-wrap',
        }}
      >
        {text.content ?? ''}
      </div>
    );
  }
  if (clipType === 'effect-layer') {
    const kind = clip.params?.kind;
    if (kind === 'ados-card') {
      return <AdosCard params={clip.params ?? {}} assets={assets} />;
    }
    if (kind === 'ados-lower-third') {
      return <AdosLowerThird params={clip.params ?? {}} />;
    }
    if (kind === 'ados-corner-logo') {
      return <CornerLogo params={clip.params ?? {}} assets={assets} />;
    }
  }
  return null;
};

const assetFontCss = (assets: AssetRegistry, family: string, key: unknown): string => {
  const src = assetSrc(assets, key);
  if (!src) {
    return '';
  }
  return `@font-face{font-family:${family};src:url("${src}")}`;
};

const AdosCard = ({params, assets}: {params: Record<string, unknown>; assets: AssetRegistry}): ReactElement => {
  const frame = useCurrentFrame();
  const {fps, durationInFrames} = useVideoConfig();
  const title = String(params.title ?? '');
  const speaker = String(params.speaker ?? '');
  const variant = params.variant === 'outro' ? 'outro' : 'intro';
  const backgroundVideo = assetSrc(assets, params.backgroundVideoAsset);
  const sponsorAssets = Array.isArray(params.sponsorAssets) ? params.sponsorAssets : [];
  const drop = spring({frame, fps, config: {damping: 17, stiffness: 105, mass: 0.72}});
  const fade = interpolate(frame, [0, 18], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const titleY = interpolate(drop, [0, 1], [120, 0]);
  const lineScale = interpolate(frame, [6, 42], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const sponsorY = interpolate(frame, [10, 38], [-34, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const shimmerX = interpolate(frame, [0, fps * 5], [-420, 2200], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  const bgAudioVolume =
    variant === 'intro'
      ? 0.16
      : interpolate(frame, [0, 18, Math.max(18, durationInFrames - 42), durationInFrames - 1], [0, 0.16, 0.16, 0], {
          extrapolateLeft: 'clamp',
          extrapolateRight: 'clamp',
        });
  const titleText = variant === 'intro' ? title : 'THANK YOU';
  return (
    <AbsoluteFill style={{background: '#0d0d10', color: '#f7f7f7', overflow: 'hidden'}}>
      <style>
        {assetFontCss(assets, 'AdosDisplay', params.displayFontAsset)}
        {assetFontCss(assets, 'AdosBody', params.bodyFontAsset)}
        {assetFontCss(assets, 'AdosTitle', params.titleFontAsset)}
      </style>
      {backgroundVideo ? (
        <Video
          src={backgroundVideo}
          volume={bgAudioVolume}
          startFrom={variant === 'intro' ? 0 : 210}
          style={{
            position: 'absolute',
            inset: 0,
            width: '100%',
            height: '100%',
            objectFit: 'cover',
            filter: 'grayscale(1) contrast(1.22) brightness(0.66) blur(0.45px)',
            transform: 'scale(1.06)',
            opacity: 0.76,
          }}
        />
      ) : null}
      <div
        style={{
          position: 'absolute',
          inset: 0,
          background:
            'linear-gradient(90deg, rgba(0,0,0,0.72) 0%, rgba(0,0,0,0.42) 44%, rgba(0,0,0,0.76) 100%), radial-gradient(circle at 78% 20%, rgba(56,189,248,0.14), transparent 34%), radial-gradient(circle at 20% 76%, rgba(251,191,36,0.10), transparent 38%)',
          opacity: 0.95,
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: shimmerX,
          top: 0,
          width: 260,
          height: 1080,
          background: 'linear-gradient(90deg, transparent, rgba(255,255,255,0.08), transparent)',
          transform: 'skewX(-18deg)',
          opacity: 0.75,
        }}
      />
      <div style={{position: 'absolute', left: 118, top: 154, width: 5, height: 724, background: '#38bdf8'}} />
      <div
        style={{
          position: 'absolute',
          left: 148,
          top: 154,
          width: 390,
          height: 5,
          background: '#a78bfa',
          transform: `scaleX(${lineScale})`,
          transformOrigin: 'left',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 148,
          top: 873,
          width: 570,
          height: 5,
          background: '#fbbf24',
          transform: `scaleX(${lineScale})`,
          transformOrigin: 'left',
        }}
      />
      <div
        style={{
          position: 'absolute',
          left: 160,
          top: 128 + titleY,
          opacity: fade,
          fontFamily: 'AdosDisplay, Inter, Arial, sans-serif',
          fontSize: 188,
          letterSpacing: 0,
          lineHeight: 0.86,
        }}
      >
        ADOS
      </div>
      <div
        style={{
          position: 'absolute',
          left: 165,
          top: 334,
          color: 'rgba(56,189,248,0.82)',
          fontFamily: 'AdosBody, Inter, Arial, sans-serif',
          fontSize: 26,
          opacity: fade,
          letterSpacing: '0.32em',
        }}
      >
        PARIS 2026
      </div>
      <div
        style={{
          position: 'absolute',
          left: 160,
          top: variant === 'intro' ? 722 + titleY * 0.25 : 614 + titleY * 0.2,
          width: 1240,
          opacity: fade,
          fontFamily: variant === 'intro' ? 'AdosTitle, AdosBody, Inter, Arial, sans-serif' : 'AdosBody, Inter, Arial, sans-serif',
          fontSize: variant === 'intro' ? 76 : 108,
          lineHeight: variant === 'intro' ? 1 : 1,
          textTransform: 'uppercase',
          letterSpacing: variant === 'intro' ? '0.02em' : '0.04em',
        }}
      >
        {titleText}
      </div>
      <div
        style={{
          position: 'absolute',
          left: 164,
          top: variant === 'intro' ? 920 : 738,
          color: variant === 'intro' ? '#38bdf8' : 'rgba(247,247,247,0.72)',
          opacity: fade,
          fontFamily: 'AdosBody, Inter, Arial, sans-serif',
          fontSize: variant === 'intro' ? 40 : 38,
          textTransform: 'uppercase',
        }}
      >
        {speaker}
      </div>
      <div
        style={{
          position: 'absolute',
          left: 164,
          bottom: 68,
          color: 'rgba(247,247,247,0.68)',
          opacity: fade,
          fontFamily: 'AdosBody, Inter, Arial, sans-serif',
          fontSize: 26,
          letterSpacing: '0.24em',
        }}
      >
        ADOS.EVENTS
      </div>
      <div
        style={{
          position: 'absolute',
          right: 86,
          top: 82 + sponsorY,
          width: 790,
          height: 102,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'flex-end',
          gap: 34,
          opacity: fade,
        }}
      >
        {sponsorAssets.map((key, index) => {
          const src = assetSrc(assets, key);
          if (!src) {
            return null;
          }
          const width = [62, 116, 170, 132][index] ?? 138;
          return (
            <Img
              key={String(key)}
              src={src}
              style={{
                width,
                maxHeight: index === 0 ? 54 : 58,
                objectFit: 'contain',
                filter: 'drop-shadow(0 8px 22px rgba(0,0,0,0.45))',
              }}
            />
          );
        })}
      </div>
    </AbsoluteFill>
  );
};

const AdosLowerThird = ({params}: {params: Record<string, unknown>}): ReactElement => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const progress = spring({frame, fps, config: {damping: 18, stiffness: 120, mass: 0.7}});
  const x = interpolate(progress, [0, 1], [980, 0]);
  return (
    <div
      style={{
        position: 'absolute',
        right: 38 - x,
        bottom: 48,
        width: 960,
        height: 78,
        background: 'rgba(13,13,16,0.74)',
        color: '#f7f7f7',
        borderLeft: '8px solid #22f7d4',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'flex-end',
        padding: '0 70px 0 36px',
        fontFamily: 'AdosBody, Inter, Arial, sans-serif',
        fontSize: 30,
        whiteSpace: 'nowrap',
      }}
    >
      <span style={{overflow: 'hidden', textOverflow: 'ellipsis'}}>
        {String(params.speaker ?? '').toUpperCase()} / {String(params.title ?? '')}
      </span>
    </div>
  );
};

const CornerLogo = ({params, assets}: {params: Record<string, unknown>; assets: AssetRegistry}): ReactElement | null => {
  const src = assetSrc(assets, params.logoAsset);
  if (!src) {
    return null;
  }
  return <Img src={src} style={{position: 'absolute', right: 44, top: 34, width: 128, opacity: 0.95}} />;
};

export const Root = (): ReactElement => {
  return (
    <Composition
      id="TimelineComposition"
      component={TimelineComposition}
      defaultProps={DEFAULT_PROPS}
      calculateMetadata={async ({props}) => {
        const canvas = getCanvas(props as TimelineCompositionProps);
        const fps = canvas.fps ?? 30;
        return {
          width: canvas.width ?? 1920,
          height: canvas.height ?? 1080,
          fps,
          durationInFrames: getTimelineDurationInFrames((props as TimelineCompositionProps).timeline, fps),
        };
      }}
    />
  );
};
