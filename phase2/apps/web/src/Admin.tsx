import { useState, type FormEvent } from 'react';
import { AccessAdmin } from './Access';
import { errorText, request, segment, type SessionScope } from './api';
import { useResource } from './hooks';
import type { Release, User } from './types';
import { ErrorBox, Heading, Loading } from './ui';

const labels: Record<string, string> = { draft: 'مسودة', technical_review: 'مراجعة تقنية', learning_review: 'مراجعة تعليمية', published: 'منشور', retired: 'متقاعد' };
const next: Record<string, string> = { draft: 'technical_review', technical_review: 'learning_review', learning_review: 'published', published: 'retired' };
export function Admin({ user, scope, onPublished, commercial = false }: { user: User; scope: SessionScope; onPublished: () => void; commercial?: boolean }) {
  const releases = useResource<{ releases: Release[]; activeReleaseId: string | null }>('/admin/releases', 0, false, scope);
  const [bundle, setBundle] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const author = user.role === 'Author' || user.role === 'Admin';
  const reviewer = user.role === 'Reviewer' || user.role === 'Admin';
  async function create(event: FormEvent) {
    event.preventDefault(); setError(''); setNotice('');
    let parsed: unknown;
    try { parsed = JSON.parse(bundle); }
    catch { setError('صيغة JSON غير صحيحة. راجع الملف؛ لم نرسل المحتوى.'); return; }
    setBusy(true);
    try {
      const result = await request<Release>('/admin/releases', { method: 'POST', scope, body: { bundle: parsed } });
      if (scope.signal.aborted) return;
      setNotice(`تم إنشاء مسودة الإصدار ${result.releaseId}.`);
      setBundle('');
      releases.reload();
    }
    catch (cause) { if (!scope.signal.aborted) setError(errorText(cause)); }
    finally { setBusy(false); }
  }
  async function updateRelease(release: Release, action: 'transition' | 'activate') {
    if (release.version === undefined) return;
    setBusy(true); setError(''); setNotice('');
    const body = action === 'activate'
      ? { expectedVersion: release.version }
      : { status: next[release.status], expectedVersion: release.version };
    try {
      await request(`/admin/releases/${segment(release.id)}/${action}`, { method: 'POST', scope, body });
      if (scope.signal.aborted) return;
      setNotice(action === 'activate' ? `أصبح ${release.title} إصدار البداية.` : 'تم تحديث حالة الإصدار.');
      releases.reload();
      onPublished();
    }
    catch (cause) {
      if (scope.signal.aborted) return;
      setError(errorText(cause));
      releases.reload();
    }
    finally { setBusy(false); }
  }
  return <><Heading title="إصدارات المحتوى" eyebrow="مساحة فريق المحتوى">المحتوى يمر بالمراجعة قبل النشر. لإجراء تغيير، أنشئ إصدارًا جديدًا.</Heading><ErrorBox message={error} />{notice && <p role="status" className="feedback success">{notice}</p>}
    {commercial && user.role === 'Admin' && <AccessAdmin scope={scope} />}
    <section className="panel">
      <h2>الإصدارات والمراجعات</h2>
      <ErrorBox message={releases.error} retry={releases.reload} />
      {releases.loading && <Loading />}
      {releases.data?.activeReleaseId === null && <p className="notice">لا يوجد إصدار بداية محدد. يمكن للمتعلم اختيار إصدار منشور من القائمة.</p>}
      <ul className="revision-list">{releases.data?.releases.map(release => {
        const active = releases.data?.activeReleaseId === release.releaseId;
        const canTransition = next[release.status] && (release.status === 'draft' ? author : reviewer);
        const canActivate = reviewer && release.status === 'published' && !active;
        return <li key={release.id}>
          <div>
            <h3>{release.title}</h3>
            <p><bdi>{release.releaseId}</bdi> · {labels[release.status] ?? release.status}</p>
            <p className="field-help">نسخة الحالة {release.version ?? 'غير متاحة'}</p>
            {active && <span className="pill sample">إصدار البداية</span>}
          </div>
          {(canActivate || canTransition) && <div className="actions">
            {canActivate && <button className="btn compact" disabled={busy || release.version === undefined} onClick={() => updateRelease(release, 'activate')}>اختيار كإصدار البداية</button>}
            {canTransition && <button className="btn compact" disabled={busy || release.version === undefined} onClick={() => updateRelease(release, 'transition')}>نقل إلى {labels[next[release.status]]}</button>}
          </div>}
        </li>;
      })}</ul>
      {releases.data?.releases.length === 0 && <p>لا توجد إصدارات بعد.</p>}
    </section>
    {author && <section className="panel history"><h2>إضافة إصدار للمراجعة</h2><p className="muted">الصق حزمة المحتوى التي تحتوي sample وgraph. يبقى الإصدار مسودة حتى اكتمال مراجعته.</p><form className="stack" onSubmit={create}><label>حزمة المحتوى (JSON)<textarea dir="ltr" rows={12} required value={bundle} maxLength={2000000} onChange={event => setBundle(event.target.value)} /></label><button className="btn primary" disabled={busy || !bundle.trim()}>{busy ? 'جارٍ الحفظ…' : 'إنشاء إصدار مسودة'}</button></form></section>}
  </>;
}
