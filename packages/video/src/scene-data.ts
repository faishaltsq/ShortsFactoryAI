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
    default: throw new Error(`Unsupported template: ${scene.template}`);
  }
  for (const ref of scene.assetRefs) localImage(ref);
}
