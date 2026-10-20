/**
 * Typed storyboard contract shared by the Python agent pipeline and the
 * Remotion renderer. Every field here is produced by StoryboardAgent and
 * validated with JSON Schema on the Python side before render.
 */

export const TEMPLATE_IDS = [
  'KineticTypography',
  'MotionComic',
  'EducationalExplainer',
  'HistoricalTimeline',
  'ParallaxStory',
  'InfographicMotion',
] as const;

export type TemplateId = (typeof TEMPLATE_IDS)[number];

export interface TextStyleSpec {
  role: 'title' | 'highlight' | 'body' | 'caption' | 'kicker';
  /** 0..1 vertical anchor inside the safe area. */
  y?: number;
  size?: number;
  color?: string;
  uppercase?: boolean;
  align?: 'left' | 'center' | 'right';
  maxCharsPerLine?: number;
}

export interface TextElementSpec {
  id: string;
  text: string;
  style: TextStyleSpec;
  /** Frame offset relative to scene start. */
  inFrame?: number;
  outFrame?: number;
}

export interface AnimationSpec {
  /** Preset name from themes/presets.ts. */
  preset: 'popIn' | 'slideUp' | 'wordByWord' | 'wipeIn' | 'countUp' | 'fadeIn';
  durationInFrames?: number;
  /** 0..1, direction/strength hint per preset. */
  intensity?: number;
}

export type TransitionType = 'none' | 'fade' | 'slideUp' | 'wipe' | 'zoom';

export interface SceneSpec {
  sceneId: string;
  template: TemplateId;
  /** Narrative segment this scene carries (verbatim from script). */
  segment: string;
  assetRefs: string[];
  text: TextElementSpec[];
  animation: AnimationSpec;
  transition: {type: TransitionType; durationInFrames?: number};
  audio?: {src: string; volume?: number};
  /** Timing is recalculated from real narration duration before render. */
  startFrame: number;
  durationInFrames: number;
  /** Optional data payload used by data-driven templates. */
  data?: Record<string, unknown>;
}

export interface SubtitleCue {
  id: string;
  text: string;
  startMs: number;
  endMs: number;
}

export interface ThemeSpec {
  id: string;
  background: string;
  backgroundAccent: string;
  primary: string;
  secondary: string;
  accent: string;
  fontHeading: string;
  fontBody: string;
}

export interface StoryboardSpec {
  id: string;
  language: string;
  width: number;
  height: number;
  fps: number;
  theme: ThemeSpec;
  scenes: SceneSpec[];
  subtitles: SubtitleCue[];
  narration?: {src: string; durationMs: number; volume?: number};
  backgroundMusic?: {src: string; volume?: number};
  watermark?: {text: string; opacity?: number};
}

export const isTemplateId = (value: string): value is TemplateId =>
  (TEMPLATE_IDS as readonly string[]).includes(value);
