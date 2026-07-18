import {StrictMode} from 'react';
import {createRoot} from 'react-dom/client';
import App from './App.tsx';
import WebSocketStatusBadge from './components/WebSocketStatusBadge';
import './performanceTruthAdapter';
import './index.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
    <WebSocketStatusBadge />
  </StrictMode>,
);
