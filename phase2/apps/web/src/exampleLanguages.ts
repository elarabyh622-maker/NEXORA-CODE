import type { ExampleLanguage } from './types';

export const exampleLanguageLabels: Record<ExampleLanguage, string> = {
  python: 'Python', javascript: 'JavaScript', csharp: 'C#', cpp: 'C++', java: 'Java', go: 'Go',
};

export function isLocalExampleLanguage(value: string | undefined): value is 'csharp' | 'cpp' | 'java' | 'go' {
  return value === 'csharp' || value === 'cpp' || value === 'java' || value === 'go';
}
