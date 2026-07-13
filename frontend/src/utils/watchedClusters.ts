import type { WatchedCluster } from '../api/types';

export function watchedClusterNames(items: WatchedCluster[] | null | undefined) {
  return new Set((items || []).filter((item) => item.enabled).map((item) => item.cluster_name.toLowerCase()));
}

export function isWatchedCluster(name: string | null | undefined, watchedNames: Set<string>) {
  return !name || watchedNames.size === 0 ? false : watchedNames.has(name.toLowerCase());
}
