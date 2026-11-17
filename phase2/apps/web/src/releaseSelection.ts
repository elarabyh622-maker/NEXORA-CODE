import type { Catalog } from './types';

export function catalogReleaseOptions(catalog: Catalog | null) {
  const published = catalog?.releases.filter(release => release.status === 'published') ?? [];
  const defaultRelease = published.find(release => release.releaseId === catalog?.activeReleaseId);
  return {
    published,
    activeId: defaultRelease?.releaseId ?? '',
  };
}
