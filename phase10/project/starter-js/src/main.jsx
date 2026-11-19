import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App.jsx';
import { createApi } from './api.js';
import { createMockApi } from './mock.js';
import './style.css';

const root = document.querySelector('#root');
if (!root) throw new Error('لم نجد حاوية التطبيق.');
const demo = import.meta.env.VITE_DATA_SOURCE !== 'api';
const api = demo ? createMockApi() : createApi();
createRoot(root).render(<StrictMode><App api={api} demo={demo} /></StrictMode>);
