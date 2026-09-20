import React, { useCallback, useRef, useState } from 'react';
import { useFocusEffect } from 'expo-router';
import type { ScreenProps } from '../lib/types';
import { emptyFilters, isPlaceId, type MapView } from '../lib/places';
import { useHousehold } from '../lib/household';
import MapScreen from './MapScreen';
import TripsScreen from './TripsScreen';
import TripPhotosScreen from './TripPhotosScreen';

type Panel = { kind: 'map'; view?: MapView } | {
  kind: 'trip' | 'photos'; view: MapView; journeyId: string; tripId: string; key: number;
};

/** A route-local return path: IDs and filters only, never cached private DTOs. */
type Props = ScreenProps & { initialPlaceId?: string; onBack?: () => void };
export default function MapWorkspace(props: Props) {
  const household = useHousehold();
  return <Workspace key={household.identityKey} {...props} />;
}

function Workspace(props: Props) {
  const [panel, setPanel] = useState<Panel>(() => ({ kind: 'map', view: isPlaceId(props.initialPlaceId)
    ? { filters: emptyFilters(), offset: 0, selected: props.initialPlaceId } : undefined }));
  const active = useRef(false), sequence = useRef(0);
  const reschedulePending = useRef(false);
  const documentsPending = useRef(false);
  const segmentsPending = useRef(false);
  const tripImportPending = useRef(false);
  const pendingReschedule = (pending: boolean) => { reschedulePending.current = pending; props.onReschedulePending?.(pending); };
  const pendingDocuments = useCallback((pending: boolean) => { documentsPending.current = pending; props.onDocumentsPending?.(pending); }, [props.onDocumentsPending]);
  const pendingSegments = useCallback((pending: boolean) => { segmentsPending.current = pending; props.onSegmentsPending?.(pending); }, [props.onSegmentsPending]);
  const pendingTripImport = useCallback((pending: boolean) => { tripImportPending.current = pending; props.onTripImportPending?.(pending); }, [props.onTripImportPending]);
  useFocusEffect(useCallback(() => {
    active.current = true;
    return () => { active.current = false; if (!reschedulePending.current && !documentsPending.current && !segmentsPending.current && !tripImportPending.current) setPanel({ kind: 'map' }); };
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
    tripRequest={{ key: panel.key, id: panel.tripId }} onReschedulePending={pendingReschedule} onDocumentsPending={pendingDocuments} onSegmentsPending={pendingSegments} onTripImportPending={pendingTripImport} onReturnMap={back} />;
  if (panel.kind === 'photos') return <TripPhotosScreen {...props} key={'photos-' + panel.key}
    journeyId={panel.journeyId} onBack={back} />;
  return <MapScreen {...props} initialView={panel.view} onBack={props.onBack} backLabel="返回地点搜索"
    onOpenTrip={(journey, view) => open('trip', journey, view)}
    onOpenPhotos={(journey, view) => open('photos', journey, view)} />;
}
