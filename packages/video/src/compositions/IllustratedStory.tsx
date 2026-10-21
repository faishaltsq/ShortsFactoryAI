import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import type {ThemeSpec} from '../types';
import type {IllustrationData} from '../scene-data';
import type {SceneProps} from '../components/NarrativeFrame';
import {validateSceneData} from '../scene-data';
import {resolveTheme} from '../themes/brand';
import {Watermark} from '../components/Chrome';
import {slideUp} from '../components/presets';
import {Camera, cameraAt} from '../art/Camera';
import {Effects} from '../art/Effects';
import {Stage} from '../art/Stage';
import {FRAMING_SCALE, shotAt} from '../art/shots';
import {paletteFor} from '../art/palette';

export const IllustratedStoryScene: React.FC<SceneProps> = ({scene, theme: inputTheme, watermark}) => {
  const theme: ThemeSpec = resolveTheme(inputTheme);
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  validateSceneData(scene);

  const data = scene.data as unknown as IllustrationData;
  const palette = paletteFor(theme, data.timeOfDay ?? 'night');
  const span = shotAt(data.shots, frame, scene.durationInFrames);
  const progress = span.duration <= 1 ? 1 : span.local / (span.duration - 1);
  const camera = cameraAt(span.shot.camera, span.local, span.duration);
  const title = data.title ?? scene.text.find((t) => t.style.role === 'title')?.text ?? '';
  const kicker = scene.text.find((t) => t.style.role === 'kicker')?.text ?? '';
  const entrance = slideUp({frame: span.local, fps, durationInFrames: 16, intensity: 0.4});

  return (
    <div style={{position: 'absolute', inset: 0, overflow: 'hidden', background: palette.skyTop}}>
      <Camera state={camera}>
        <Stage data={data} palette={palette} frame={span.local} progress={progress} scale={FRAMING_SCALE[span.shot.framing]} />
      </Camera>

      <Effects list={data.fx} palette={palette} frame={frame} progress={progress} />

      {watermark ? <Watermark text={watermark} theme={theme} /> : null}

      {title ? (
        <div
          style={{
            ...entrance,
            position: 'absolute',
            top: 300,
            left: 72,
            right: 72,
            fontFamily: theme.fontHeading,
            fontSize: 72,
            lineHeight: 1.08,
            color: theme.primary,
            textShadow: '0 6px 26px rgba(0,0,0,0.65)',
            overflowWrap: 'anywhere',
          }}
        >
          {title}
        </div>
      ) : null}

      {kicker ? (
        <div
          style={{
            position: 'absolute',
            top: 268,
            left: 72,
            fontFamily: theme.fontBody,
            fontSize: 30,
            letterSpacing: 5,
            textTransform: 'uppercase',
            color: theme.accent,
            opacity: Math.min(1, span.local / 10),
          }}
        >
          {kicker}
        </div>
      ) : null}

      {data.caption ? (
        <div
          style={{
            position: 'absolute',
            top: 400,
            left: 72,
            right: 72,
            fontFamily: theme.fontBody,
            fontSize: 40,
            lineHeight: 1.28,
            color: theme.secondary,
            opacity: Math.min(1, span.local / 12) * 0.95,
          }}
        >
          {data.caption}
        </div>
      ) : null}
    </div>
  );
};
