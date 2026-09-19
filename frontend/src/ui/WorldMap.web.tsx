import React, { useEffect, useRef, useState } from 'react';
import { View } from 'react-native';
import { Button, Text, useTheme } from 'react-native-paper';
import { coordinatesValid, landPaths, placeLabels, type Coordinates } from '../lib/places';
import { routeMapLayout } from '../lib/journeyRoutes';
import type { WorldMapProps } from './WorldMap';

const project = (point: Coordinates) => ({ x: (point.longitude + 180) * 1000 / 360, y: (90 - point.latitude) * 500 / 180 });
export default function WorldMap({ places, selected, disabled, picking, picked, onSelect, onPick, routeMap, selectedRouteIndex, onRouteSelect }: WorldMapProps) {
  const theme = useTheme();
  const [paths, setPaths] = useState<string[] | null>(null), [failed, setFailed] = useState(false), [cursor, setCursor] = useState<Coordinates>({ latitude: 30, longitude: 110 });
  const [mapWidth, setMapWidth] = useState(320), [fullWorld, setFullWorld] = useState(false);
  const routeKey = routeMap?.markers.map(marker => `${marker.point.latitude}:${marker.point.longitude}:${marker.indices.join(',')}`).join('|');
  useEffect(() => { setFullWorld(false); }, [routeKey]);
  const routeHeight = Math.min(360, Math.max(240, mapWidth * 0.6));
  const layout = routeMap ? routeMapLayout(routeMap, mapWidth, routeHeight, fullWorld) : null;
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
  return <View style={{ gap: 10 }} onLayout={routeMap ? event => { const width = event.nativeEvent.layout.width; if (Number.isFinite(width) && width > 112) setMapWidth(width); } : undefined}>
    {routeMap && <Button compact mode="outlined" style={{ alignSelf: 'flex-start' }} disabled={disabled || !routeMap.markers.length} onPress={() => setFullWorld(!fullWorld)}>{fullWorld ? '聚焦路线' : '查看全图'}</Button>}
    <svg ref={svg} viewBox={layout ? `0 0 ${mapWidth} ${routeHeight}` : '0 0 1000 500'} preserveAspectRatio="none" role={picking ? 'application' : 'group'} aria-label={picking ? '地图选点：方向键移动，Shift 加快，回车确认' : routeMap ? '旅行路线顺序示意；编号对应下方站点列表，不是导航' : '世界足迹地图；所有地点也可在下方列表打开'}
      tabIndex={picking && !disabled ? 0 : -1} onClick={pick} onKeyDown={keyboard}
      style={{ display: 'block', width: '100%', ...(layout ? { height: routeHeight } : { aspectRatio: '2 / 1', minHeight: 145 }), background: theme.colors.surface, borderRadius: 20, overflow: 'hidden', cursor: picking ? 'crosshair' : 'default' }}>
      <title>{routeMap ? '旅行路线顺序示意' : '世界足迹概览'}</title>
      {!routeMap && [125, 250, 375].map(y => <line key={'h' + y} x1="0" x2="1000" y1={y} y2={y} stroke={theme.colors.outlineVariant} strokeWidth="0.6" />)}
      {!routeMap && [250, 500, 750].map(x => <line key={'v' + x} x1={x} x2={x} y1="0" y2="500" stroke={theme.colors.outlineVariant} strokeWidth="0.6" />)}
      {(layout && !layout.global ? [-1000, 0, 1000] : [0]).map(offset => <g key={offset} transform={layout ? `translate(${(offset - layout.viewport.x) * layout.scale} ${-layout.viewport.y * layout.scale}) scale(${layout.scale})` : undefined}>
        {paths?.map((path, index) => <path key={index} d={path} fill={theme.dark ? theme.colors.surfaceVariant : '#e1e4e9'} stroke={theme.dark ? theme.colors.outlineVariant : '#cdd2da'} strokeWidth="0.6" vectorEffect={layout ? 'non-scaling-stroke' : undefined} fillRule="evenodd" />)}
      </g>)}
      {layout?.lines.map((line, i) => {
        const a = line.from, b = line.to;
        return <line key={'route-line-' + i} x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={theme.colors.primary} strokeWidth="2"
          strokeDasharray={line.approximate ? '6 5' : undefined} pointerEvents="none" />;
      })}
      {layout?.markers.map((marker, i) => {
        const point = marker.point, active = marker.indices.includes(selectedRouteIndex ?? -1), label = marker.indices.map(n => n + 1).join('、');
        const select = () => { if (!disabled && onRouteSelect) onRouteSelect(marker.indices.includes(selectedRouteIndex ?? -1) ? marker.indices[(marker.indices.indexOf(selectedRouteIndex!) + 1) % marker.indices.length] : marker.indices[0]); };
        return <g key={'route-marker-' + i} role="button" tabIndex={disabled ? -1 : 0} aria-disabled={!!disabled}
          aria-label={`第 ${label} 站：${Array.from(new Set(marker.names)).join('、')}${marker.approximate ? '，大致位置' : ''}`} onClick={select}
          onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); select(); } }} style={{ cursor: disabled ? 'default' : 'pointer' }}>
          <title>{`第 ${label} 站`}</title><rect x={point.x - marker.width / 2} y={point.y - 18} width={marker.width} height="36" rx="18" fill={theme.colors.surface} stroke={theme.colors.primary} strokeWidth={active ? 4 : 2} strokeDasharray={marker.approximate ? '4 3' : undefined} />
          <text x={point.x} y={point.y} textAnchor="middle" dominantBaseline="central" fontSize="14" fontWeight="600" fill={theme.colors.onSurface}>{marker.label}</text>
        </g>;
      })}
      {!routeMap && places.filter(place => place.coordinates).map(place => {
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
    {picking ? <Text variant="bodySmall" accessibilityLiveRegion="polite">选点仅提供大致位置。光标：{cursor.latitude.toFixed(2)}，{cursor.longitude.toFixed(2)}。方向键移动，回车写入；也可手填经纬度。</Text> : routeMap ? <Text variant="bodySmall">数字对应下方站点；重合或邻近站点合并显示，点按切换。+N 表示另有 N 站。虚线为大致位置，缺少坐标处断开。连线不是导航、实际路径或距离。</Text> : <Text variant="bodySmall">● 已到访　■ 已计划　○ 想去 · 仅显示本页有权查看的坐标</Text>}
    <Text variant="labelSmall" style={{ color: theme.colors.onSurfaceVariant }}>Made with Natural Earth · 世界概览</Text>
  </View>;
}
