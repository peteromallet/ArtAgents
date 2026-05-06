import type {CSSProperties, ReactElement} from 'react';
import {useCallback} from 'react';
import {
  HtmlInCanvas,
  type HtmlInCanvasOnPaint,
  interpolate,
  useCurrentFrame,
  useVideoConfig,
} from 'remotion';

type EffectParams = {
  content?: string;
  subtitle?: string;
  width?: number;
  height?: number;
  background?: string;
  foreground?: string;
  accent?: string;
  postProcess?: 'none' | 'soft-blur' | 'glow' | 'vignette';
};

const cardShell: CSSProperties = {
  boxSizing: 'border-box',
  display: 'flex',
  flexDirection: 'column',
  justifyContent: 'space-between',
  height: '100%',
  width: '100%',
  padding: 40,
  fontFamily: 'Inter, system-ui, sans-serif',
};

const CanvasCard = ({params}: {params: EffectParams}): ReactElement => {
  const accent = params.accent ?? '#7dd3fc';
  return (
    <div
      style={{
        ...cardShell,
        background: params.background ?? 'rgba(15, 23, 42, 0.92)',
        color: params.foreground ?? '#ffffff',
        border: `1px solid ${accent}`,
        boxShadow: `0 24px 80px rgba(0, 0, 0, 0.35), inset 0 1px 0 ${accent}`,
      }}
    >
      <div
        style={{
          fontSize: 54,
          fontWeight: 750,
          lineHeight: 1,
        }}
      >
        {params.content ?? 'HTML in Canvas'}
      </div>
      <div
        style={{
          color: 'rgba(255, 255, 255, 0.78)',
          fontSize: 22,
          lineHeight: 1.3,
        }}
      >
        {params.subtitle ?? 'DOM layout, captured and post-processed as a canvas texture.'}
      </div>
    </div>
  );
};

export default function HtmlCanvasEffect(props: {
  clip: any;
  params: unknown;
  theme: unknown;
  fps: number;
}): ReactElement {
  const frame = useCurrentFrame();
  const {width: compositionWidth, height: compositionHeight} = useVideoConfig();
  const params = (props.params ?? {}) as EffectParams;
  const width = params.width ?? Math.min(900, compositionWidth);
  const height = params.height ?? Math.min(520, compositionHeight);
  const opacity = interpolate(frame, [0, 12], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const onPaint: HtmlInCanvasOnPaint = useCallback(
    ({canvas, element, elementImage}) => {
      const ctx = canvas.getContext('2d');
      if (!ctx) {
        throw new Error('Failed to acquire 2D canvas context');
      }
      ctx.reset();
      const mode = params.postProcess ?? 'glow';
      if (mode === 'soft-blur') {
        ctx.filter = 'blur(1.2px) saturate(1.08)';
      } else if (mode === 'glow') {
        ctx.shadowColor = params.accent ?? '#7dd3fc';
        ctx.shadowBlur = 28;
      }
      const transform = ctx.drawElementImage(elementImage, 0, 0);
      if (mode === 'vignette') {
        const gradient = ctx.createRadialGradient(
          canvas.width / 2,
          canvas.height / 2,
          canvas.width * 0.15,
          canvas.width / 2,
          canvas.height / 2,
          canvas.width * 0.7,
        );
        gradient.addColorStop(0, 'rgba(255, 255, 255, 0)');
        gradient.addColorStop(1, 'rgba(0, 0, 0, 0.42)');
        ctx.fillStyle = gradient;
        ctx.fillRect(0, 0, canvas.width, canvas.height);
      }
      element.style.transform = transform.toString();
    },
    [params.accent, params.postProcess],
  );

  return (
    <div
      style={{
        alignItems: 'center',
        display: 'flex',
        height: '100%',
        justifyContent: 'center',
        opacity,
        pointerEvents: 'none',
        position: 'relative',
        width: '100%',
      }}
    >
      <div
        style={{
          height,
          position: 'absolute',
          width,
        }}
      >
        <CanvasCard params={params} />
      </div>
      <div
        style={{
          height,
          position: 'relative',
          width,
        }}
      >
        <HtmlInCanvas width={width} height={height} onPaint={onPaint}>
          <CanvasCard params={params} />
        </HtmlInCanvas>
      </div>
    </div>
  );
}
