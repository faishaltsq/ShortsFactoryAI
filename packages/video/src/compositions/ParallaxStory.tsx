import React from 'react';
import {Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {NarrativeFrame, SceneProps} from '../components/NarrativeFrame';
import {ParallaxData, localImage, validateSceneData} from '../scene-data';
import {resolveTheme, SPACE, TYPE} from '../themes/brand';

export const ParallaxStoryScene: React.FC<SceneProps> = (props) => {
  const {scene} = props;
  const theme = resolveTheme(props.theme);
  const frame = useCurrentFrame();
  validateSceneData(scene);
  const data = scene.data as unknown as ParallaxData;
  const progress = interpolate(frame, [0, scene.durationInFrames - 1], [-1, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
  return <NarrativeFrame {...props} title={data.title}>
    <div style={{position: 'relative', flex: 1, minHeight: 0, overflow: 'hidden', borderRadius: SPACE.radius, background: theme.backgroundAccent}}>
      {[...data.layers].sort((a, b) => a.depth - b.depth).map((layer, i) => <div key={i} style={{position: 'absolute', inset: -50, transform: `translateX(${progress * layer.depth * 46}px) scale(${1.05 + layer.depth * 0.06})`}}>
        {layer.assetRef ? <Img src={staticFile(localImage(layer.assetRef))} style={{width: '100%', height: '100%', objectFit: 'cover'}} /> : <svg viewBox="0 0 900 1000" preserveAspectRatio="xMidYMid slice" style={{width: '100%', height: '100%'}}>
          {layer.shape === 'circle' ? <circle cx="630" cy="240" r="150" fill={theme.accent} /> : null}
          {layer.shape === 'ridge' ? <path d="M0 1000V650L140 390L280 650L460 310L680 650L800 430L900 650V1000Z" fill={theme.secondary} opacity={0.65} /> : null}
          {layer.shape === 'city' ? <path d="M0 1000V740H100V650H210V790H340V530H440V680H570V760H680V590H780V720H900V1000Z" fill={theme.background} /> : null}
        </svg>}
      </div>)}
      <div style={{position: 'absolute', bottom: SPACE.card, left: SPACE.card, right: SPACE.card, height: 8, background: theme.accent, opacity: 0.8}} />
    </div>
    {data.caption ? <div style={{fontSize: TYPE.body, lineHeight: 1.25, color: theme.secondary}}>{data.caption}</div> : null}
  </NarrativeFrame>;
};
