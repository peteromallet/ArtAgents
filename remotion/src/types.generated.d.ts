export interface AnimationReferenceObject {
    durationFrames?: number;
    easing?: string;
    id?: string;
    params?: Record<string, unknown>;
}
export interface Arrangement {
    brief_sha256?: string;
    brief_slug?: string;
    brief_text?: string;
    clips?: ArrangementClip[];
    generated_at?: string;
    pool_sha256?: string;
    source_slug?: string;
    target_duration_sec?: number;
    version?: number;
}
export interface ArrangementAudioSource {
    pool_id: string;
    trim_sub_range: number[];
}
export interface ArrangementClip {
    audio_source: ArrangementAudioSource | null;
    order: number;
    rationale: string;
    text_overlay?: ArrangementTextOverlay | null;
    uuid: string;
    visual_source: ArrangementVisualSource;
}
export interface ArrangementTextOverlay {
    content?: string;
    style_preset?: string;
}
export interface ArrangementVisualSource {
    params?: Record<string, unknown>;
    pool_id: string;
    role: 'overlay' | 'primary' | 'stinger';
}
export interface AssetEntry {
    content_sha256: unknown;
    duration: unknown;
    etag: unknown;
    file: unknown;
    fps: unknown;
    generationId: unknown;
    resolution: unknown;
    thumbnailUrl: unknown;
    type: unknown;
    url: unknown;
    url_expires_at: unknown;
    variantId: unknown;
}
export interface AssetRegistry {
    assets: Record<string, AssetEntry>;
}
export interface AssetRegistryEntry {
    content_sha256: unknown;
    duration: unknown;
    etag: unknown;
    file: unknown;
    fps: unknown;
    generationId: unknown;
    resolution: unknown;
    thumbnailUrl: unknown;
    type: unknown;
    url: unknown;
    url_expires_at: unknown;
    variantId: unknown;
}
export interface AudioBindingValue {
    max: number;
    min: number;
    source: 'amplitude' | 'bass' | 'mid' | 'treble';
}
export interface ClipContinuous {
    intensity?: number;
    params?: Record<string, unknown>;
    type?: string;
}
export interface ClipEntrance {
    duration?: number;
    intensity?: number;
    params?: Record<string, unknown>;
    type?: string;
}
export interface ClipExit {
    duration?: number;
    intensity?: number;
    params?: Record<string, unknown>;
    type?: string;
}
export interface ClipTransition {
    duration: number;
    type: string;
}
export interface ClipTransitionReference {
    duration?: number;
    durationFrames?: number;
    id?: string;
    params?: Record<string, unknown>;
    type?: string;
}
export interface ParameterDefinition {
    default?: unknown;
    description: string;
    label: string;
    max?: number;
    min?: number;
    name: string;
    options?: ParameterOption[];
    step?: number;
    type: 'audio-binding' | 'boolean' | 'color' | 'number' | 'select';
}
export interface ParameterOption {
    label: string;
    value: string;
}
export interface PipelineMetadata {
    clips: Record<string, PipelineMetadataClipEntry>;
    generated_at: string;
    pipeline: Record<string, unknown>;
    sources: Record<string, Record<string, unknown>>;
    version: number;
}
export interface PipelineMetadataClipEntry {
    arrangement_notes?: null | string;
    caption_kind?: 'dialogue' | 'visual';
    pick_rationale?: string;
    picked_by?: string;
    pool_id?: null | string;
    pool_kind?: 'applause' | 'dialogue' | 'music' | 'reaction' | 'text' | 'visual';
    score?: number;
    source_ids?: SourceIds;
    source_scene_id?: string;
    source_transcript_text?: null | string;
    source_uuid?: string;
    text_overlay_content?: string;
}
export interface Pool {
    entries?: PoolEntry[];
    generated_at?: string;
    source_slug?: string;
    version?: number;
}
export interface PoolEntry {
    asset?: string;
    bed_kind?: string;
    camera?: string;
    category: 'applause' | 'dialogue' | 'music' | 'reaction' | 'visual';
    defaults?: Record<string, unknown>;
    duration: number;
    effect_id?: string;
    energy?: number;
    event_label?: string;
    excluded: boolean;
    excluded_reason?: null | string;
    id: string;
    intensity?: number;
    kind: 'generative' | 'source';
    meta?: Record<string, unknown>;
    mood_tags?: string[];
    motion_tags?: string[];
    param_schema?: Record<string, unknown>;
    quote_kind?: string;
    scores: PoolScores;
    source_ids?: SourceIds;
    speaker?: null | string;
    src_end?: number;
    src_start?: number;
    subject?: string;
    text?: string;
}
export interface PoolScores {
    deep?: number;
    quotability?: number;
    triage?: number;
}
export interface SharedAssetEntry {
    content_sha256: unknown;
    duration: unknown;
    etag: unknown;
    file: unknown;
    fps: unknown;
    generationId: unknown;
    resolution: unknown;
    thumbnailUrl: unknown;
    type: unknown;
    url: unknown;
    url_expires_at: unknown;
    variantId: unknown;
}
export interface SharedTheme {
    audio: unknown;
    generation: unknown;
    id: string;
    pacing: unknown;
    visual: unknown;
    voice: unknown;
}
export interface SharedThemeOverrides {
    audio: unknown;
    generation: unknown;
    pacing: unknown;
    visual: unknown;
    voice: unknown;
}
export interface SharedTimelineClip {
    asset?: unknown;
    at: number;
    clipType?: unknown;
    clip_order?: unknown;
    continuous?: unknown;
    cropBottom?: unknown;
    cropLeft?: unknown;
    cropRight?: unknown;
    cropTop?: unknown;
    effects?: unknown;
    entrance?: unknown;
    exit?: unknown;
    from?: unknown;
    generation?: unknown;
    height?: unknown;
    hold?: unknown;
    id: string;
    opacity?: unknown;
    params?: unknown;
    pool_id?: unknown;
    source_uuid?: unknown;
    speed?: unknown;
    text?: unknown;
    to?: unknown;
    track: string;
    transition?: unknown;
    volume?: unknown;
    width?: unknown;
    x?: unknown;
    y?: unknown;
}
export interface SharedTimelineConfig {
    clips: Clip[];
    output: unknown;
    pinnedShotGroups: unknown;
    theme: string;
    theme_overrides: unknown;
    tracks: unknown;
}
export interface SharedTimelineOutput {
    background: unknown;
    background_scale: unknown;
    file: string;
    fps: number;
    resolution: string;
}
export interface SourceIds {
    scene_id?: string;
    segment_ids?: number[];
}
export interface TextClipData {
    align?: 'center' | 'left' | 'right';
    bold?: boolean;
    color?: string;
    content?: string;
    fontFamily?: string;
    fontSize?: number;
    italic?: boolean;
}
export interface Theme {
    audio: unknown;
    generation: unknown;
    id: string;
    pacing: unknown;
    visual: unknown;
    voice: unknown;
}
export interface ThemeOverrides {
    audio: unknown;
    generation: unknown;
    pacing: unknown;
    visual: unknown;
    voice: unknown;
}
export interface TimelineClip {
    asset?: unknown;
    at: number;
    clipType?: unknown;
    clip_order?: unknown;
    continuous?: unknown;
    cropBottom?: unknown;
    cropLeft?: unknown;
    cropRight?: unknown;
    cropTop?: unknown;
    effects?: unknown;
    entrance?: unknown;
    exit?: unknown;
    from?: unknown;
    generation?: unknown;
    height?: unknown;
    hold?: unknown;
    id: string;
    opacity?: unknown;
    params?: unknown;
    pool_id?: unknown;
    source_uuid?: unknown;
    speed?: unknown;
    text?: unknown;
    to?: unknown;
    track: string;
    transition?: unknown;
    volume?: unknown;
    width?: unknown;
    x?: unknown;
    y?: unknown;
}
export interface TimelineConfig {
    clips: Clip[];
    output: unknown;
    pinnedShotGroups: unknown;
    theme: string;
    theme_overrides: unknown;
    tracks: unknown;
}
export interface TimelineEffect {
    fade_in?: number;
    fade_out?: number;
}
export interface TimelineOutput {
    background: unknown;
    background_scale: unknown;
    file: string;
    fps: number;
    resolution: string;
}
export interface TrackDefinition {
    blendMode?: 'darken' | 'hard-light' | 'lighten' | 'multiply' | 'normal' | 'overlay' | 'screen' | 'soft-light';
    fit?: 'contain' | 'cover' | 'manual';
    id: string;
    kind: 'audio' | 'visual';
    label: string;
    muted?: boolean;
    opacity?: number;
    scale?: number;
    volume?: number;
}
export declare const _ASSET_ENTRY_ALLOWED: readonly ["content_sha256", "duration", "etag", "file", "fps", "generationId", "resolution", "thumbnailUrl", "type", "url", "url_expires_at", "variantId"];
export declare const _CLIP_ALLOWED: readonly ["asset", "at", "clipType", "clip_order", "continuous", "cropBottom", "cropLeft", "cropRight", "cropTop", "effects", "entrance", "exit", "from", "generation", "height", "hold", "id", "opacity", "params", "pool_id", "source_uuid", "speed", "text", "to", "track", "transition", "volume", "width", "x", "y"];
export declare const _THEME_OVERRIDES_ALLOWED: readonly ["audio", "generation", "pacing", "visual", "voice"];
export declare const _TIMELINE_TOP_ALLOWED: readonly ["clips", "pinnedShotGroups", "theme", "theme_overrides", "tracks"];
export declare const _TRACK_ALLOWED: readonly ["blendMode", "fit", "id", "kind", "label", "muted", "opacity", "scale", "volume"];
//# sourceMappingURL=types.generated.d.ts.map