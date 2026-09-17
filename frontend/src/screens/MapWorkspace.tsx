import React, { useCallback, useRef, useState } from 'react';
import { useFocusEffect } from 'expo-router';
import type { ScreenProps } from '../lib/types';
import type { MapView } from '../lib/places';
import MapScreen from './MapScreen';
import TripsScreen from './TripsScreen';
import TripPhotosScreen from './TripPhotosScreen';

type Panel = { kind: 'map'; view?: MapView } | {
  kind: 'trip' | 'photos'; view: MapView; journeyId: string; tripId: string; key: number;
};

/** A route-local return path: IDs and filters only, never cached private DTOs. */
export default function MapWorkspace(props: ScreenProps) {
  const [panel, setPanel] = useState<Panel>({ kind: 'map' });
  const active = useRef(false), sequence = useRef(0);
  const reschedulePending = useRef(false);
  const pendingReschedule = (pending: boolean) => { reschedulePending.current = pending; props.onReschedulePending?.(pending); };
  useFocusEffect(useCallback(() => {
    active.current = true;
    return () => { active.current = false; if (!reschedulePending.current) setPanel({ kind: 'map' }); };
  }, []));
  const open = (kind: 'trip' | 'photos', journey: { id: string; tripId: string }, view: MapView) => {
    // MapScreen has freshly checked the place projection and its identity fence.
    // Each destination reads its own current authorization and data on mount.
    if (!active.current || !/^[a-f0-9]{24}$/.test(journey.id) || !/^[a-f0-9]{24}$/.test(journey.tripId)) return;
    setPanel({ kind, journeyId: journey.id, tripId: journey.tripId, view: {
      filters: { ...view.filters }, offset: view.offset, selected: view.selected,
    }, key: ++sequence.current });
  };
  const back = () => { if (active.current) setPanel(current => ({ kind: 'map', view: current.view })); };
  if (panel.kind === 'trip') return <TripsScreen {...props} key={'trip-' + panel.key}
    tripRequest={{ key: panel.key, id: panel.tripId }} onReschedulePending={pendingReschedule} onReturnMap={back} />;
  if (panel.kind === 'photos') return <TripPhotosScreen {...props} key={'photos-' + panel.key}
    journeyId={panel.journeyId} onBack={back} />;
  return <MapScreen {...props} initialView={panel.view}
    onOpenTrip={(journey, view) => open('trip', journey, view)}
    onOpenPhotos={(journey, view) => open('photos', journey, view)} />;
}
