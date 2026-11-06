import Icon from "./Icon";

// Rail de navegación "liquid glass" idéntico a FaceSync Studio: colapsado
// (w-16, solo iconos) y se expande al pasar el cursor (w-224, con etiquetas).
// Adaptado a V2: avatar arriba + 3 secciones + cerrar sesión abajo.

const SECTIONS = [
  { id: "workspace", label: "Workspace", icon: "photo" },
  { id: "reportes", label: "Reportes", icon: "chart" },
  { id: "exportaciones", label: "Exportaciones", icon: "export" },
];

function Row({ active, onClick, title, children, danger }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className={`flex w-full items-center rounded-2xl py-2.5 transition-colors duration-200 ${
        active
          ? "bg-white/10 text-white ring-1 ring-white/15"
          : danger
          ? "text-neutral-400 hover:bg-red-500/10 hover:text-red-300"
          : "text-neutral-400 hover:bg-white/[0.06] hover:text-white"
      }`}
    >
      {children}
    </button>
  );
}

export default function SectionsBar({ section, setSection, user, avatar, onLogout }) {
  const name = user?.name || "Usuario";
  const initial = (name || "U").slice(0, 1).toUpperCase();

  return (
    <div className="group absolute left-4 top-1/2 z-20 -translate-y-1/2">
      <div
        style={{
          transition:
            "width 450ms cubic-bezier(0.22,1,0.36,1), scale 520ms cubic-bezier(0.33,1,0.68,1), box-shadow 520ms ease, border-color 450ms ease, background-color 450ms ease",
          willChange: "scale, width",
        }}
        className="relative w-16 origin-left overflow-hidden rounded-[28px] border border-white/12 bg-white/[0.07] p-2 shadow-[0_10px_45px_rgba(0,0,0,0.45)] group-hover:w-[224px] group-hover:scale-[1.08] group-hover:border-white/20 group-hover:bg-white/[0.1] group-hover:shadow-[0_30px_90px_rgba(0,0,0,0.6)]"
      >
        <div className="pointer-events-none absolute inset-x-0 top-0 h-20 bg-gradient-to-b from-white/12 to-transparent" />

        <div className="relative flex flex-col gap-1.5">
          {/* Usuario */}
          <div className="flex w-full items-center rounded-2xl py-2.5">
            <span className="flex w-12 shrink-0 items-center justify-center">
              {avatar ? (
                <img src={avatar} alt="" className="h-8 w-8 rounded-full object-cover" />
              ) : (
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-fuchsia-500 text-sm font-bold text-white">
                  {initial}
                </span>
              )}
            </span>
            <span className="min-w-0 whitespace-nowrap text-sm opacity-0 transition-opacity duration-300 group-hover:opacity-100">
              <span className="block truncate font-semibold text-white">{name}</span>
              <span className="block text-xs text-fuchsia-300/80">Cuenta Pro</span>
            </span>
          </div>

          <div className="mx-2 my-1 h-px bg-white/10" />

          {/* Secciones */}
          {SECTIONS.map((s) => (
            <Row key={s.id} active={section === s.id} onClick={() => setSection(s.id)} title={s.label}>
              <span className="flex w-12 shrink-0 items-center justify-center">
                <Icon name={s.icon} className="h-[22px] w-[22px]" />
              </span>
              <span className="whitespace-nowrap text-sm opacity-0 transition-opacity duration-300 group-hover:opacity-100">
                {s.label}
              </span>
            </Row>
          ))}

          <div className="mx-2 my-1 h-px bg-white/10" />

          {/* Cerrar sesión */}
          <Row onClick={onLogout} title="Cerrar sesión" danger>
            <span className="flex w-12 shrink-0 items-center justify-center">
              <Icon name="logout" className="h-[22px] w-[22px]" />
            </span>
            <span className="whitespace-nowrap text-sm opacity-0 transition-opacity duration-300 group-hover:opacity-100">
              Cerrar sesión
            </span>
          </Row>
        </div>
      </div>
    </div>
  );
}
