import React from 'react';
import {Img, staticFile} from 'remotion';
import type {IllustrationData} from '../scene-data';
import {Environment} from './Environment';
import {Figure} from './Figure';
import {Prop} from './Prop';
import type {ArtPalette} from './palette';

export const Stage: React.FC<{
  data: IllustrationData;
  palette: ArtPalette;
  frame: number;
  progress: number;
  scale: number;
}> = ({data, palette, frame, progress, scale}) => (
  // transformOrigin sits on the subject's ground line, so a tighter framing crops
  // the sky instead of pushing the character's head into the title band.
  <div style={{position: 'absolute', inset: 0, transform: `scale(${scale})`, transformOrigin: '50% 78%'}}>
    {data.imageRef ? (
      <Img
        src={staticFile(data.imageRef)}
        style={{position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover'}}
      />
    ) : null}
    <div style={{position: 'absolute', inset: 0, opacity: data.imageRef ? 0.72 : 1}}>
      <Environment
        setting={data.setting}
        timeOfDay={data.timeOfDay ?? 'night'}
        palette={palette}
        progress={progress}
      />
    </div>
    {data.props.map((prop, i) => (
      <Prop key={`prop-${i}`} prop={prop} palette={palette} frame={frame} index={i} />
    ))}
    {data.actors.map((actor, i) => (
      <Figure key={`actor-${i}`} actor={actor} palette={palette} frame={frame} index={i} />
    ))}
  </div>
);
