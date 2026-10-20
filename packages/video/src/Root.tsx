import React from 'react';
import {CalculateMetadataFunction, Composition, getInputProps} from 'remotion';
import type {SceneSpec, StoryboardSpec, ThemeSpec} from './types';
import {resolveTheme} from './themes/brand';
import {Short} from './compositions/Short';
import {KineticTypographyScene} from './compositions/KineticTypography';
import {EducationalExplainerScene} from './compositions/EducationalExplainer';
import {SAMPLE_STORYBOARD} from './sample/storyboard';

const totalFramesOf = (sb: StoryboardSpec): number => {
  const sorted = [...sb.scenes].sort((a, b) => a.startFrame - b.startFrame);
  const last = sorted[sorted.length - 1];
  return last ? last.startFrame + last.durationInFrames : sb.fps * 30;
};

const calculateShortMetadata: CalculateMetadataFunction<{storyboard: StoryboardSpec}> = ({props}) => ({
  durationInFrames: totalFramesOf(props.storyboard),
  fps: props.storyboard.fps,
  width: props.storyboard.width,
  height: props.storyboard.height,
});

/** Single-template compositions exist for preview and per-template QC. */
const calculateSceneMetadata: CalculateMetadataFunction<{scene: SceneSpec; theme: ThemeSpec; watermark?: string}> = ({props}) => ({
  durationInFrames: props.scene.durationInFrames,
});

export const RemotionRoot: React.FC = () => {
  const input = getInputProps() as {storyboard?: StoryboardSpec} | null;
  const storyboard = input?.storyboard ?? SAMPLE_STORYBOARD;

  return (
    <>
      <Composition
        id="Short"
        component={Short}
        defaultProps={{storyboard}}
        calculateMetadata={calculateShortMetadata}
        durationInFrames={totalFramesOf(storyboard)}
        fps={storyboard.fps}
        width={storyboard.width}
        height={storyboard.height}
      />
      <Composition
        id="KineticTypography"
        component={KineticTypographyScene}
        defaultProps={{scene: storyboard.scenes[0], theme: resolveTheme(storyboard.theme), watermark: storyboard.watermark?.text}}
        calculateMetadata={calculateSceneMetadata}
        durationInFrames={storyboard.scenes[0]?.durationInFrames ?? 300}
        fps={storyboard.fps}
        width={storyboard.width}
        height={storyboard.height}
      />
      <Composition
        id="EducationalExplainer"
        component={EducationalExplainerScene}
        defaultProps={{scene: storyboard.scenes[1], theme: resolveTheme(storyboard.theme), watermark: storyboard.watermark?.text}}
        calculateMetadata={calculateSceneMetadata}
        durationInFrames={storyboard.scenes[1]?.durationInFrames ?? 330}
        fps={storyboard.fps}
        width={storyboard.width}
        height={storyboard.height}
      />
    </>
  );
};
