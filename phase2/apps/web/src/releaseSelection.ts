import type { Catalog } from './types';

export function catalogReleaseOptions(catalog: Catalog | null, selectedId: string) {
  const published = catalog?.releases.filter(release => release.status === 'published') ?? [];
  const defaultRelease = published.find(release => release.releaseId === catalog?.activeReleaseId);
  return {
    published,
    initialId: selectedId ? '' : defaultRelease?.releaseId ?? '',
    needsChoice: !selectedId && !defaultRelease && published.length > 0,
  };
}
