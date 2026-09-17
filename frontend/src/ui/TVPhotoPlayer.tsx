import type { TVPhotoPlayerProps } from './TVPhotoPlayer.model';
export type { TVPhotoPlayerProps } from './TVPhotoPlayer.model';

// A native surface cannot reuse the browser's TV cookie or Blob authorization.
// Do not fetch, cache or pretend to display authorized photos on that platform.
export default function TVPhotoPlayer(_props: TVPhotoPlayerProps) { return null; }
