import { applicationPath } from './api';

export const PRODUCT_NAME = 'NEXORA CODE';
export const PRODUCT_DESCRIPTOR = 'تعلّم البرمجة بالعربية';

export const BRAND_ASSETS = {
  icon: applicationPath('/brand/nexora-code-icon-128.png'),
  iconWebp: applicationPath('/brand/nexora-code-icon-128.webp'),
  wordmark: applicationPath('/brand/nexora-code-logo.png'),
  wordmarkWebp: applicationPath('/brand/nexora-code-logo.webp'),
};

export function BrandWordmark() {
  return <picture className="brand-picture">
    <source srcSet={BRAND_ASSETS.wordmarkWebp} type="image/webp" />
    <img src={BRAND_ASSETS.wordmark} width="1445" height="530" alt={`${PRODUCT_NAME} — Learn to Think. Code to Create.`} lang="en" dir="ltr" />
  </picture>;
}
