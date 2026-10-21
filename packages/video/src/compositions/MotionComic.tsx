import React from 'react';
import {Img, interpolate, staticFile, useCurrentFrame} from 'remotion';
import {NarrativeFrame, SceneProps} from '../components/NarrativeFrame';
import {ComicData, localImage, validateSceneData} from '../scene-data';
import {resolveTheme, SPACE, TYPE} from '../themes/brand';

export const MotionComicScene: React.FC<SceneProps> = (props) => {
  const {scene} = props;
  const theme = resolveTheme(props.theme);
  const frame = useCurrentFrame();
  validateSceneData(scene);
  const data = scene.data as unknown as ComicData;
  return <NarrativeFrame {...props} title={data.title}>
    <div style={{display: 'flex', flexDirection: 'column', flex: 1, gap: SPACE.card, minHeight: 0}}>
      {data.panels.map((panel, i) => {
        const progress = interpolate(frame, [i * 10, i * 10 + 18], [0, 1], {extrapolateLeft: 'clamp', extrapolateRight: 'clamp'});
        return <div key={i} style={{position: 'relative', flex: 1, minHeight: 0, display: 'flex', gap: SPACE.card, alignItems: 'center', overflow: 'hidden', padding: SPACE.card, border: `4px solid ${theme.primary}`, borderRadius: SPACE.radius, background: theme.backgroundAccent, opacity: progress, transform: `translateX(${(1 - progress) * (i % 2 ? 48 : -48)}px)`}}>
          {panel.assetRef ? <Img src={staticFile(localImage(panel.assetRef))} style={{width: '34%', height: '100%', objectFit: 'cover', borderRadius: SPACE.radius}} /> : <svg viewBox="0 0 160 220" style={{width: '23%', flexShrink: 0}} aria-label="Ilustrasi geometris orisinal proyek">
            <circle cx="80" cy="64" r="44" fill={theme.accent} />
            <path d="M20 220 Q10 120 80 120 Q150 120 140 220Z" fill={theme.secondary} />
            <path d="M36 50 L124 50 M56 80 L104 80" stroke={theme.background} strokeWidth="8" />
          </svg>}
          <div style={{flex: 1, minWidth: 0}}>
            {panel.speaker ? <div style={{fontSize: TYPE.kicker, fontWeight: 800, color: theme.accent, marginBottom: SPACE.small}}>{panel.speaker}</div> : null}
            <div style={{fontFamily: theme.fontHeading, fontSize: TYPE.body, lineHeight: 1.18, overflowWrap: 'anywhere'}}>{panel.caption}</div>
          </div>
        </div>;
      })}
    </div>
  </NarrativeFrame>;
};
