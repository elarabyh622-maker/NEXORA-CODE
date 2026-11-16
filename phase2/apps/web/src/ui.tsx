import { Component, type ErrorInfo, type ReactNode } from 'react';

const paths = {
  route: 'M4 19h4V5h8v14h4M4 15v4h4m8-4v4h4',
  home: 'm3 11 9-8 9 8M5 10v11h5v-7h4v7h5V10',
  book: 'M12 6c-3-2-6-2-10-1v14c4-1 7-1 10 1 3-2 6-2 10-1V5c-4-1-7-1-10 1v14',
  chart: 'M4 3v17h17M8 16v-5M13 16V7M18 16v-9',
  arrow: 'M20 12H4m6-6-6 6 6 6',
  leaf: 'M5 20c1-7 4-9 12-14M4 17C0 6 12 2 22 3c0 9-3 17-14 15',
  person: 'M8 7a4 4 0 1 0 8 0 4 4 0 0 0-8 0M4 21v-3a8 8 0 0 1 16 0v3',
};
export function Icon({ name }: { name: keyof typeof paths }) {
  return <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d={paths[name]} /></svg>;
}
export function ErrorBox({ message, retry }: { message: string; retry?: () => void }) {
  if (!message) return null;
  return <div className="notice error" role="alert"><p>{message}</p>{retry && <button className="btn compact" type="button" onClick={retry}>إعادة المحاولة</button>}</div>;
}
export function Loading({ text = 'جارٍ تحميل المحتوى…' }: { text?: string }) {
  return <p className="loading" role="status">{text}</p>;
}
export function Heading({ title, children, eyebrow }: { title: string; children?: ReactNode; eyebrow?: string }) {
  return <header className="page-heading"><div>{eyebrow && <p className="eyebrow">{eyebrow}</p>}<h1>{title}</h1>{children && <p className="muted">{children}</p>}</div></header>;
}
export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) { /* Do not log lesson answers or identity data. */ }
  render() {
    return this.state.failed ? <main className="fatal" dir="rtl"><h1>تعذر عرض هذه الصفحة</h1><p>أعد تحميل الصفحة للمحاولة مجددًا. قد تفقد النص الذي لم تحفظه.</p><button className="btn primary" onClick={() => window.location.reload()}>إعادة التحميل</button></main> : this.props.children;
  }
}
