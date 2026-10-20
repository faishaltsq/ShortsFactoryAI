import React from 'react';
import {AbsoluteFill, Audio, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import type {SceneSpec, StoryboardSpec, TemplateId} from '../types';
import {DEFAULT_THEME, THEMES} from '../themes/brand';
import {Subtitles} from '../components/Subtitles';
import {KineticTypographyScene} from '../compositions/KineticTypography';
import {EducationalExplainerScene} from '../compositions/EducationalExplainer';

const renderScene = (scene: SceneSpec, theme: StoryboardSpec['theme'], watermark?: string): React.ReactNode => {
  if (scene.template === 'KineticTypography') {
    return <KineticTypographyScene scene={scene} theme={theme} watermark={watermark} />;
  }
  // Data-driven templates fall back to the explainer renderer until their
  // dedicated scene modules land in Phase 4.
  return <EducationalExplainerScene scene={scene} theme={theme} watermark={watermark} />;
};

/** Applies the scene's transition as an in/out opacity (and optional slide) ramp. */
const TransitionedScene: React.FC<{scene: SceneSpec; children: React.ReactNode}> = ({scene, children}) => {
  const frame = useCurrentFrame();
  if (scene.transition.type === 'none' || !scene.transition.durationInFrames) {
    return <>{children}</>;
  }
  const fade = Math.min(scene.transition.durationInFrames, Math.floor(scene.durationInFrames / 2));
  const opacity = interpolate(frame, [0, fade, scene.durationInFrames - fade, scene.durationInFrames], [0, 1, 1, 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  const translateY =
    scene.transition.type === 'slideUp'
      ? interpolate(frame, [0, fade], [60, 0], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'})
      : 0;
  return <AbsoluteFill style={{opacity, transform: `translateY(${translateY}px)`}}>{children}</AbsoluteFill>;
};

const ProgressBar: React.FC<{theme: StoryboardSpec['theme']; totalFrames: number}> = ({theme, totalFrames}) => {
  const frame = useCurrentFrame();
  const pct = interpolate(frame, [0, totalFrames], [0, 100], {extrapolateRight: 'clamp'});
  return (
    <div style={{position: 'absolute', left: 0, bottom: 0, width: `${pct}%`, height: 8, backgroundColor: theme.accent, opacity: 0.85}} />
  );
};

export const Short: React.FC<{storyboard: StoryboardSpec}> = ({storyboard}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const theme = THEMES[storyboard.theme?.id] ?? storyboard.theme ?? DEFAULT_THEME;
  const scenes = [...storyboard.scenes].sort((a, b) => a.startFrame - b.startFrame);
  const last = scenes[scenes.length - 1];
  const totalFrames = last ? last.startFrame + last.durationInFrames : fps * 30;

  return (
    <AbsoluteFill style={{backgroundColor: theme.background}}>
      {scenes.map((scene) => (
        <Sequence key={scene.sceneId} from={scene.startFrame} durationInFrames={scene.durationInFrames} layout="none">
          <TransitionedScene scene={scene}>{renderScene(scene, theme, storyboard.watermark?.text)}</TransitionedScene>
        </Sequence>
      ))}

      {storyboard.narration?.src ? (
        <Audio src={staticFile(storyboard.narration.src)} volume={storyboard.narration.volume ?? 1} />
      ) : null}
      {storyboard.backgroundMusic?.src ? (
        <Audio src={staticFile(storyboard.backgroundMusic.src)} volume={storyboard.backgroundMusic.volume ?? 0.15} />
      ) : null}

      <Subtitles cues={storyboard.subtitles ?? []} theme={theme} currentFrame={frame} fps={fps} />
      <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 4, backgroundColor: theme.accent, opacity: 0.9}} />
      <ProgressBar theme={theme} totalFrames={totalFrames} />
    </AbsoluteFill>
  );
};
