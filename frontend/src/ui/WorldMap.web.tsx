import React, { useEffect, useRef, useState } from 'react';
import { View } from 'react-native';
import { Text, useTheme } from 'react-native-paper';
import { coordinatesValid, landPaths, placeLabels, type Coordinates } from '../lib/places';
import type { WorldMapProps } from './WorldMap';

const project = (point: Coordinates) => ({ x: (point.longitude + 180) * 1000 / 360, y: (90 - point.latitude) * 500 / 180 });
export default function WorldMap({ places, selected, disabled, picking, picked, onSelect, onPick }: WorldMapProps) {
  const theme = useTheme();
  const [paths, setPaths] = useState<string[] | null>(null), [failed, setFailed] = useState(false), [cursor, setCursor] = useState<Coordinates>({ latitude: 30, longitude: 110 });
  const svg = useRef<SVGSVGElement>(null);
  useEffect(() => {
    const controller = new AbortController(); let alive = true;
    void (async () => {
      try {
        const response = await fetch('/static/journey-map-land.geojson', { credentials: 'same-origin', cache: 'force-cache', signal: controller.signal });
        if (!response.ok) throw new Error('底图暂时不可用');
        const raw = await response.text(); if (raw.length > 500000) throw new Error('底图超出限制');
        const next = landPaths(JSON.parse(raw)); if (alive) setPaths(next);
      } catch { if (alive) setFailed(true); }
    })();
    return () => { alive = false; controller.abort(); };
  }, []);
  useEffect(() => { if (picked && coordinatesValid(picked)) setCursor(picked); }, [picked?.latitude, picked?.longitude]);
  const pick = (event: React.MouseEvent<SVGSVGElement>) => {
    if (!picking || disabled || !svg.current) return;
    const rect = svg.current.getBoundingClientRect(), x = (event.clientX - rect.left) / rect.width, y = (event.clientY - rect.top) / rect.height;
    const point = { latitude: Number((90 - Math.max(0, Math.min(1, y)) * 180).toFixed(6)), longitude: Number((Math.max(0, Math.min(1, x)) * 360 - 180).toFixed(6)) };
    setCursor(point); onPick(point);
  };
  const keyboard = (event: React.KeyboardEvent<SVGSVGElement>) => {
    if (!picking || disabled || event.target !== event.currentTarget) return;
    const step = event.shiftKey ? 10 : 1;
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown'].includes(event.key)) {
      event.preventDefault(); setCursor(point => ({ latitude: Math.max(-90, Math.min(90, point.latitude + (event.key === 'ArrowUp' ? step : event.key === 'ArrowDown' ? -step : 0))), longitude: Math.max(-180, Math.min(180, point.longitude + (event.key === 'ArrowRight' ? step : event.key === 'ArrowLeft' ? -step : 0))) }));
    } else if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onPick(cursor); }
  };
  const cursorPosition = project(cursor);
  return <View style={{ gap: 10 }}>
    <svg ref={svg} viewBox="0 0 1000 500" preserveAspectRatio="none" role={picking ? 'application' : 'group'} aria-label={picking ? '地图选点：方向键移动，Shift 加快，回车确认' : '世界足迹地图；所有地点也可在下方列表打开'}
      tabIndex={picking && !disabled ? 0 : -1} onClick={pick} onKeyDown={keyboard}
      style={{ display: 'block', width: '100%', aspectRatio: '2 / 1', minHeight: 145, background: theme.colors.surface, borderRadius: 20, overflow: 'hidden', cursor: picking ? 'crosshair' : 'default' }}>
      <title>世界足迹概览</title>
      {[125, 250, 375].map(y => <line key={'h' + y} x1="0" x2="1000" y1={y} y2={y} stroke={theme.colors.outlineVariant} strokeWidth="0.6" />)}
      {[250, 500, 750].map(x => <line key={'v' + x} x1={x} x2={x} y1="0" y2="500" stroke={theme.colors.outlineVariant} strokeWidth="0.6" />)}
      {paths?.map((path, index) => <path key={index} d={path} fill={theme.colors.surfaceVariant} stroke={theme.colors.outlineVariant} strokeWidth="0.6" fillRule="evenodd" />)}
      {places.filter(place => place.coordinates).map(place => {
        const point = project(place.coordinates!), active = place.id === selected;
        return <g key={place.id} role="button" aria-label={`${place.name}，${placeLabels[place.status]}${place.coordinatePrecision === 'approximate' ? '，大致位置' : ''}`} aria-disabled={!!disabled || !!picking} tabIndex={disabled || picking ? -1 : 0}
          onClick={event => { event.stopPropagation(); if (!disabled && !picking) onSelect(place.id); }} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); event.stopPropagation(); if (!disabled && !picking) onSelect(place.id); } }} style={{ cursor: disabled || picking ? 'default' : 'pointer' }}>
          <title>{place.name} · {placeLabels[place.status]}</title><circle cx={point.x} cy={point.y} r={active ? 19 : 15} fill="transparent" />
          {active ? <circle cx={point.x} cy={point.y} r="14" fill="none" stroke={theme.colors.primary} strokeWidth="2" /> : null}
          {place.status === 'planned' ? <rect x={point.x - 6} y={point.y - 6} width="12" height="12" rx="2" fill={theme.colors.primary} stroke={theme.colors.surface} strokeWidth="2" />
            : <circle cx={point.x} cy={point.y} r="6" fill={place.status === 'wish' ? theme.colors.surface : theme.colors.primary} stroke={theme.colors.primary} strokeWidth="2" />}
        </g>;
      })}
      {picking ? <g pointerEvents="none"><circle cx={cursorPosition.x} cy={cursorPosition.y} r="10" fill="none" stroke={theme.colors.primary} strokeWidth="2" /><path d={`M${cursorPosition.x - 18},${cursorPosition.y}h36 M${cursorPosition.x},${cursorPosition.y - 18}v36`} stroke={theme.colors.primary} strokeWidth="2" /></g> : null}
    </svg>
    {failed ? <Text variant="bodySmall">底图暂时无法加载；地点列表和编辑仍可使用。</Text> : !paths ? <Text variant="bodySmall">正在读取世界轮廓…</Text> : null}
    {picking ? <Text variant="bodySmall" accessibilityLiveRegion="polite">选点仅提供大致位置。光标：{cursor.latitude.toFixed(2)}，{cursor.longitude.toFixed(2)}。方向键移动，回车写入；也可手填经纬度。</Text> : <Text variant="bodySmall">● 已到访　■ 已计划　○ 想去 · 仅显示本页有权查看的坐标</Text>}
    <Text variant="labelSmall" style={{ color: theme.colors.onSurfaceVariant }}>Made with Natural Earth · 世界概览</Text>
  </View>;
}
