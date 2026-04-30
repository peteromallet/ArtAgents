import type { AnimationComponent, AnimationMeta } from './effects.types';
export declare const ACTIVE_THEME_ID: null;
export declare const ANIMATION_IDS: readonly ["fade", "fade-up", "scale-in", "slide-left", "slide-up", "type-on"];
export type AnimationId = typeof ANIMATION_IDS[number];
export declare const ANIMATION_REGISTRY: Record<AnimationId, AnimationComponent>;
export declare const ANIMATION_DEFAULTS: Record<AnimationId, Record<string, unknown>>;
export declare const ANIMATION_META: Record<AnimationId, AnimationMeta>;
//# sourceMappingURL=animations.generated.d.ts.map