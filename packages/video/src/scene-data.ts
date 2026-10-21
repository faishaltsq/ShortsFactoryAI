import type {SceneSpec} from './types';

export interface ComicData {title?: string; panels: {caption: string; speaker?: string; assetRef?: string}[]}
export interface TimelineData {title?: string; events: {date: string; label: string; detail?: string}[]}
export interface ParallaxData {title: string; caption?: string; layers: {depth: number; shape?: 'ridge' | 'city' | 'circle'; assetRef?: string}[]}
export interface InfographicData {title: string; items: {label: string; value: number; unit?: string}[]; maxValue?: number; decimals?: number}

type ObjectData = Record<string, unknown>;
const object = (value: unknown, keys: string[]): ObjectData => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error('Template data must be an object');
  const data = value as ObjectData;
  if (Object.keys(data).some(k => !keys.includes(k))) throw new Error('Unsupported template data field');
  return data;
};
const text = (value: unknown, max: number, optional = false): void => {
  if (optional && value == null) return;
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error('Missing or invalid template text');
};
const items = (value: unknown, min: number, max: number): ObjectData[] => {
  if (!Array.isArray(value) || value.length < min || value.length > max) throw new Error('Invalid template item count');
  return value as ObjectData[];
};
const number = (value: unknown, min: number, max: number): void => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) throw new Error('Invalid finite template number');
};

/** Only content-addressed raster files staged by AssetAgent may become browser image requests. */
export const localImage = (src: string): string => {
  if (!/^assets\/[a-f0-9]{64}\.(png|jpe?g|webp)$/.test(src)) throw new Error('Image must be a staged local raster asset');
  return src;
};

export function validateSceneData(scene: SceneSpec): void {
  switch (scene.template) {
    case 'MotionComic': {
      const d = object(scene.data, ['title', 'panels']);
      text(d.title, 70, true);
      for (const panel of items(d.panels, 1, 3)) {
        const p = object(panel, ['caption', 'speaker', 'assetRef']);
        text(p.caption, 120); text(p.speaker, 32, true); text(p.assetRef, 200, true);
        if (p.assetRef) localImage(p.assetRef as string);
      }
      break;
    }
    case 'HistoricalTimeline': {
      const d = object(scene.data, ['title', 'events']);
      text(d.title, 70, true);
      for (const event of items(d.events, 2, 4)) {
        const e = object(event, ['date', 'label', 'detail']);
        text(e.date, 24); text(e.label, 70); text(e.detail, 100, true);
      }
      break;
    }
    case 'ParallaxStory': {
      const d = object(scene.data, ['title', 'caption', 'layers']);
      text(d.title, 70); text(d.caption, 160, true);
      for (const layer of items(d.layers, 1, 4)) {
        const l = object(layer, ['depth', 'shape', 'assetRef']);
        number(l.depth, 0.1, 1);
        if ((l.shape == null) === (l.assetRef == null)) throw new Error('Layer needs exactly one visual');
        if (l.shape != null && !['ridge', 'city', 'circle'].includes(String(l.shape))) throw new Error('Unsupported parallax shape');
        if (l.assetRef != null) {text(l.assetRef, 200); localImage(l.assetRef as string);}
      }
      break;
    }
    case 'InfographicMotion': {
      const d = object(scene.data, ['title', 'items', 'maxValue', 'decimals']);
      text(d.title, 70);
      if (d.maxValue != null) number(d.maxValue, Number.MIN_VALUE, 1e12);
      if (d.decimals != null) {number(d.decimals, 0, 2); if (!Number.isInteger(d.decimals)) throw new Error('decimals must be integer');}
      for (const item of items(d.items, 1, 4)) {
        const i = object(item, ['label', 'value', 'unit']);
        text(i.label, 52); number(i.value, 0, 1e12);
        if (i.unit !== undefined && (typeof i.unit !== 'string' || i.unit.length > 16)) throw new Error('Invalid unit');
        if (d.maxValue != null && (i.value as number) > (d.maxValue as number)) throw new Error('Scale does not cover value');
      }
      break;
    }
    case 'KineticTypography': case 'EducationalExplainer': break;
    case 'IllustratedStory': validateIllustrationData(scene.data); break;
    default: throw new Error(`Unsupported template: ${scene.template}`);
  }
  for (const ref of scene.assetRefs) localImage(ref);
}

export const SETTINGS = ['space', 'desert', 'city', 'ocean', 'forest', 'interior', 'abstract'] as const;
export const TIMES_OF_DAY = ['dawn', 'day', 'dusk', 'night'] as const;
export const POSES = ['stand', 'point', 'reach', 'walk', 'lookUp', 'shrug', 'sit'] as const;
export const PROP_KINDS = ['sun', 'moon', 'planet', 'star', 'cloud', 'mountain', 'tree', 'tower', 'gear', 'book', 'wave', 'clock', 'bulb', 'arrow'] as const;
export const EFFECTS = ['lightRays', 'dust', 'stars', 'speedLines', 'impact', 'vignette'] as const;
export const FRAMINGS = ['wide', 'medium', 'close'] as const;
export const CAMERA_MOVES = ['static', 'pushIn', 'pullOut', 'panLeft', 'panRight', 'tiltUp', 'handheld'] as const;

export type Setting = (typeof SETTINGS)[number];
export type TimeOfDay = (typeof TIMES_OF_DAY)[number];
export type Pose = (typeof POSES)[number];
export type PropKind = (typeof PROP_KINDS)[number];
export type Effect = (typeof EFFECTS)[number];
export type Framing = (typeof FRAMINGS)[number];
export type CameraMove = (typeof CAMERA_MOVES)[number];

export interface IllustrationActor {
  pose: Pose;
  x: number;
  ground: number;
  scale: number;
  facing: 'left' | 'right';
  tone: 'primary' | 'secondary' | 'accent';
  silhouette: boolean;
}

export interface IllustrationProp {kind: PropKind; x: number; y: number; scale: number}
export interface IllustrationShot {framing: Framing; camera: CameraMove; weight: number}

export interface IllustrationData {
  title?: string;
  caption?: string;
  setting: Setting;
  timeOfDay?: TimeOfDay;
  imageRef?: string;
  actors: IllustrationActor[];
  props: IllustrationProp[];
  fx: Effect[];
  shots: IllustrationShot[];
}

const ILLUSTRATION_KEYS = ['title', 'caption', 'setting', 'timeOfDay', 'imageRef', 'actors', 'props', 'fx', 'shots'];

const oneOf = <T extends string>(allowed: readonly T[], value: unknown, field: string, fallback: T): T => {
  if (value == null) return fallback;
  if (typeof value !== 'string' || !(allowed as readonly string[]).includes(value)) {
    throw new Error(`Unsupported illustration ${field}: ${String(value)}`);
  }
  return value as T;
};

const unit = (value: unknown, field: string, fallback: number, min = 0, max = 1): number => {
  if (value == null) return fallback;
  if (typeof value !== 'number' || !Number.isFinite(value) || value < min || value > max) {
    throw new Error(`Illustration ${field} must be a finite number in ${min}..${max}`);
  }
  return value;
};

const record = (value: unknown, keys: string[], label: string): Record<string, unknown> => {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`Illustration ${label} must be an object`);
  const data = value as Record<string, unknown>;
  if (Object.keys(data).some((key) => !keys.includes(key))) throw new Error(`Unsupported illustration ${label} field`);
  return data;
};

const optionalText = (value: unknown, max: number, field: string): string | undefined => {
  if (value == null) return undefined;
  if (typeof value !== 'string' || !value.trim() || value.length > max) throw new Error(`Invalid illustration ${field}`);
  return value;
};

export function validateIllustrationData(raw: unknown): IllustrationData {
  const data = record(raw, ILLUSTRATION_KEYS, 'data');
  const out: IllustrationData = {
    setting: oneOf(SETTINGS, data.setting, 'setting', 'abstract'),
    actors: [],
    props: [],
    fx: [],
    shots: [{framing: 'wide', camera: 'pushIn', weight: 1}],
  };
  const title = optionalText(data.title, 70, 'title');
  if (title) out.title = title;
  const caption = optionalText(data.caption, 90, 'caption');
  if (caption) out.caption = caption;
  if (data.timeOfDay != null) out.timeOfDay = oneOf(TIMES_OF_DAY, data.timeOfDay, 'timeOfDay', 'night');
  if (data.imageRef != null) out.imageRef = localImage(String(data.imageRef));

  if (data.actors != null) {
    if (!Array.isArray(data.actors) || data.actors.length > 3) throw new Error('Illustration actors must be an array of at most 3');
    out.actors = data.actors.map((item, i) => {
      const a = record(item, ['pose', 'x', 'ground', 'scale', 'facing', 'tone', 'silhouette'], `actor ${i}`);
      return {
        pose: oneOf(POSES, a.pose, 'pose', 'stand'),
        x: unit(a.x, `actor ${i} x`, 0.5),
        ground: unit(a.ground, `actor ${i} ground`, 0.72),
        scale: unit(a.scale, `actor ${i} scale`, 1, 0.4, 1.8),
        facing: a.facing === 'left' ? 'left' : 'right',
        tone: oneOf(['primary', 'secondary', 'accent'] as const, a.tone, 'tone', 'primary'),
        silhouette: Boolean(a.silhouette),
      };
    });
  }

  if (data.props != null) {
    if (!Array.isArray(data.props) || data.props.length > 5) throw new Error('Illustration props must be an array of at most 5');
    out.props = data.props.map((item, i) => {
      const p = record(item, ['kind', 'x', 'y', 'scale'], `prop ${i}`);
      return {
        kind: oneOf(PROP_KINDS, p.kind, 'prop kind', 'star'),
        x: unit(p.x, `prop ${i} x`, 0.5),
        y: unit(p.y, `prop ${i} y`, 0.35),
        scale: unit(p.scale, `prop ${i} scale`, 1, 0.4, 2),
      };
    });
  }

  if (data.fx != null) {
    if (!Array.isArray(data.fx) || data.fx.length > 4) throw new Error('Illustration fx must be an array of at most 4');
    const seen: Effect[] = [];
    for (const item of data.fx) {
      const effect = oneOf(EFFECTS, item, 'fx', 'dust');
      if (!seen.includes(effect)) seen.push(effect);
    }
    out.fx = seen;
  }

  if (data.shots != null) {
    if (!Array.isArray(data.shots) || data.shots.length < 1 || data.shots.length > 4) {
      throw new Error('Illustration shots must be an array of 1..4');
    }
    out.shots = data.shots.map((item, i) => {
      const s = record(item, ['framing', 'camera', 'weight'], `shot ${i}`);
      return {
        framing: oneOf(FRAMINGS, s.framing, 'framing', 'wide'),
        camera: oneOf(CAMERA_MOVES, s.camera, 'camera', 'pushIn'),
        weight: unit(s.weight, `shot ${i} weight`, 1, 0.5, 3),
      };
    });
  }
  return out;
}
