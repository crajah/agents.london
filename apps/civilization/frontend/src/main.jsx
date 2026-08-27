import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { checkAndHandleOidcCallback } from './utils/oidc';

// Handle OAuth2 OIDC callback popup postMessage dispatch
checkAndHandleOidcCallback();

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
