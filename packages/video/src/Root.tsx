import React from 'react';
import {CalculateMetadataFunction, Composition, getInputProps} from 'remotion';
import {TEMPLATE_IDS} from './types';
import type {SceneSpec, StoryboardSpec, ThemeSpec} from './types';
import {resolveTheme} from './themes/brand';
import {Short} from './compositions/Short';
import {Thumbnail} from './compositions/Thumbnail';
import {SCENE_RENDERERS} from './compositions/registry';
import {SAMPLE_STORYBOARD} from './sample/storyboard';
import fixture from '../fixtures/all-templates.json';

const totalFramesOf = (sb: StoryboardSpec): number => Math.max(...sb.scenes.map(s => s.startFrame + s.durationInFrames));
const calculateShortMetadata: CalculateMetadataFunction<{storyboard: StoryboardSpec}> = ({props}) => ({
  durationInFrames: totalFramesOf(props.storyboard), fps: props.storyboard.fps,
  width: props.storyboard.width, height: props.storyboard.height,
});

export const calculateSceneMetadata: CalculateMetadataFunction<{scene: SceneSpec; theme: ThemeSpec; watermark?: string}> = ({props}) => ({
  durationInFrames: props.scene.durationInFrames,
});

export const RemotionRoot: React.FC = () => {
  const input = getInputProps() as {storyboard?: StoryboardSpec} | null;
  const storyboard = input?.storyboard ?? SAMPLE_STORYBOARD;
  const defaults = fixture as unknown as StoryboardSpec;
  return <>
    <Composition id="Short" component={Short} defaultProps={{storyboard}} calculateMetadata={calculateShortMetadata}
      durationInFrames={totalFramesOf(storyboard)} fps={storyboard.fps} width={storyboard.width} height={storyboard.height} />
    <Composition id="Thumbnail" component={Thumbnail}
      defaultProps={{scene: storyboard.scenes[0], theme: resolveTheme(storyboard.theme), headline: 'DEMO', watermark: storyboard.watermark?.text}}
      calculateMetadata={({props}) => ({durationInFrames: props.scene.durationInFrames})} durationInFrames={storyboard.scenes[0].durationInFrames}
      fps={30} width={1080} height={1920} />
    {TEMPLATE_IDS.map(id => {
      const scene = storyboard.scenes.find(s => s.template === id) ?? defaults.scenes.find(s => s.template === id)!;
      return <Composition key={id} id={id} component={SCENE_RENDERERS[id]}
        defaultProps={{scene, theme: resolveTheme(storyboard.theme), watermark: storyboard.watermark?.text}}
        calculateMetadata={calculateSceneMetadata} durationInFrames={scene.durationInFrames}
        fps={30} width={1080} height={1920} />;
    })}
  </>;
};
