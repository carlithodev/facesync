// Barra de título custom (decorations:false). Idéntica en estilo a FaceSync
// Studio: región arrastrable + minimizar / maximizar / cerrar. Usa la API
// global de Tauri (withGlobalTauri). Los permisos core:window ya están en
// capabilities/default.json.

function appWindow() {
  return window.__TAURI__?.window?.getCurrentWindow?.();
}

function WinButton({ onClick, label, danger, children }) {
  return (
    <button type="button" aria-label={label} onClick={onClick}
      className={`flex h-7 w-9 items-center justify-center rounded-md text-neutral-400 transition-colors hover:text-white ${
        danger ? "hover:bg-red-500/90" : "hover:bg-white/10"
      }`}>
      {children}
    </button>
  );
}

export default function TitleBar() {
  // SIN barra: no reserva espacio en el layout. Una franja superior invisible y
  // arrastrable (para mover la ventana) + los controles flotando arriba a la
  // derecha. El contenido va por debajo y llena hasta arriba.
  return (
    <>
      <div data-tauri-drag-region className="fixed top-0 left-0 right-0 h-9 z-40 select-none" />
      <div className="fixed top-0 right-1 z-50 flex h-9 items-center gap-0.5">
        <WinButton onClick={() => appWindow()?.minimize()} label="Minimizar">
          <svg width="12" height="12" viewBox="0 0 12 12"><line x1="2" y1="6" x2="10" y2="6" stroke="currentColor" strokeWidth="1.3" /></svg>
        </WinButton>
        <WinButton onClick={() => appWindow()?.toggleMaximize()} label="Maximizar">
          <svg width="12" height="12" viewBox="0 0 12 12"><rect x="2.5" y="2.5" width="7" height="7" rx="1" fill="none" stroke="currentColor" strokeWidth="1.3" /></svg>
        </WinButton>
        <WinButton onClick={() => appWindow()?.close()} label="Cerrar" danger>
          <svg width="12" height="12" viewBox="0 0 12 12"><line x1="3" y1="3" x2="9" y2="9" stroke="currentColor" strokeWidth="1.3" /><line x1="9" y1="3" x2="3" y2="9" stroke="currentColor" strokeWidth="1.3" /></svg>
        </WinButton>
      </div>
    </>
  );
}
