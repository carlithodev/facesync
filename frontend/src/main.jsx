import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import "./styles.css";

// La API de Tauri sigue disponible globalmente (withGlobalTauri: true):
//   const { invoke } = window.__TAURI__.core;
ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
