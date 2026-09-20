import React, { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { Text, useTheme } from 'react-native-paper';
import type { JourneyReview } from '../lib/tvTripRecap';
import { routeGeometry, type RouteStop } from '../lib/journeyRoutes';
import WorldMap from './WorldMap';

/** Receives only a freshly leased TV projection; owns no requests or media bytes. */
export default function TVTripRecap({ review, paused, hasMedia, scale }: { review: JourneyReview; paused: boolean; hasMedia: boolean; scale: number }) {
  const theme = useTheme(), [page, setPage] = useState(0), route = review.route;
  const pages = Math.max(1, Math.ceil((route?.stops.length || 0) / 8));
  useEffect(() => { setPage(0); }, [review.sourceVersion]);
  useEffect(() => { if (paused || pages <= 1) return; const timer = setInterval(() => setPage(p => (p + 1) % pages), 15000); return () => clearInterval(timer); }, [paused, pages, review.sourceVersion]);
  const shownPage = Math.min(page, pages - 1), stops = route?.stops.slice(shownPage * 8, shownPage * 8 + 8) || [];
  // Geometry reads only index/state/name/coordinates/precision. The TV DTO is
  // deliberately smaller than member Place; no invented owner/ACL fields.
  const map = route ? routeGeometry(route.stops as RouteStop[], route.segments) : null;
  return <View testID="tv-trip-recap" style={[styles.root, { gap: 16 * scale }]}>
    <Text testID="tv-trip-title" numberOfLines={2} style={{ fontSize: 36 * scale, lineHeight: 44 * scale, color: theme.colors.onSurface, fontWeight: '700' }}>{review.journey?.title || '原旅行已不可用'}</Text>
    {review.journey && <Text testID="tv-trip-dates" style={{ fontSize: 24 * scale, lineHeight: 32 * scale, color: theme.colors.onSurfaceVariant }}>{review.journey.start} 至 {review.journey.end}{paused ? ' · 已暂停' : ''}</Text>}
    {route && map ? <View testID="tv-trip-route" style={[styles.route, { flexDirection: hasMedia ? 'column' : 'row', gap: 16 * scale }]}>
      <View style={{ flex: hasMedia ? undefined : 1.2, minWidth: 0 }}><Text numberOfLines={2} style={{ fontSize: 26 * scale, lineHeight: 34 * scale, color: theme.colors.onSurface }}>{route.title}</Text>
        <WorldMap presentation="tv" disabled places={[]} routeMap={map} onSelect={() => {}} onPick={() => {}} /></View>
      <View style={{ flex: hasMedia ? undefined : 1, minWidth: 0, gap: 4 * scale }}>
        <Text testID="tv-trip-route-page" style={{ fontSize: 20 * scale, color: theme.colors.onSurfaceVariant }}>路线站点 {shownPage * 8 + 1}–{Math.min((shownPage + 1) * 8, route.stops.length)} / {route.stops.length} · 第 {shownPage + 1} / {pages} 页{pages > 1 ? paused ? ' · 翻页已暂停' : ' · 自动翻页' : ''}</Text>
        {stops.map(s => <View key={s.index} testID={'tv-trip-stop-' + s.index} style={{ gap: 2 * scale }}>
          <Text numberOfLines={1} style={{ fontSize: 22 * scale, lineHeight: 30 * scale, color: theme.colors.onSurface }}>{s.index + 1}. {s.state === 'available' ? s.place.name : '此站不可展示'}</Text>
          {s.state === 'available' && !hasMedia && <Text numberOfLines={1} style={{ fontSize: 17 * scale, lineHeight: 23 * scale, color: theme.colors.onSurfaceVariant }}>{[s.place.city, s.place.country].filter(Boolean).join(' · ')}{s.place.coordinatePrecision === 'approximate' ? ' · 大致位置' : !s.place.coordinates ? ' · 无共享坐标' : ''} · {{ visited: '已到访', planned: '已计划', wish: '想去' }[s.place.status]}</Text>}
        </View>)}
      </View>
    </View> : <Text testID="tv-trip-route-status" style={{ fontSize: 26 * scale, lineHeight: 36 * scale, color: theme.colors.onSurfaceVariant }}>{review.status === 'journey_unavailable' ? '旅行内容已清除。请在手机核对或返回家庭看板。' : review.routeStatus === 'unavailable' ? '所选路线已不可用，旧路线已清除。' : '未选择路线；不会从照片推断路线或拍摄地点。'}</Text>}
    {!hasMedia && review.status === 'ready' && <Text style={{ fontSize: 20 * scale, color: theme.colors.onSurfaceVariant }}>本趟暂无获这台电视许可的媒体。{route ? '当前仅展示可用路线。' : '请在手机核对或返回家庭看板。'}</Text>}
  </View>;
}
const styles = StyleSheet.create({ root: { flex: 1, minWidth: 0 }, route: { minWidth: 0 } });
