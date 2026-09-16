import React from 'react';
import { Text } from 'react-native-paper';
import type { Coordinates, Place } from '../lib/places';

export type WorldMapProps = { places: Place[]; selected?: string; disabled?: boolean; picking?: boolean; picked?: Coordinates | null;
  onSelect: (id: string) => void; onPick: (point: Coordinates) => void };
export default function WorldMap(_props: WorldMapProps) {
  return <Text variant="bodyMedium">世界概览可在网页浏览器查看。下方列表与经纬度输入仍可使用。</Text>;
}
