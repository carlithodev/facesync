// Set de iconos minimalistas (trazo fino), estilo FaceSync Studio.
const ICONS = {
  photo: (
    <>
      <rect x="3" y="5" width="18" height="14" rx="2.5" />
      <circle cx="8.5" cy="10" r="1.4" />
      <path d="M5 17.5 9.5 13l3 3 3-3 3.5 3.5" />
    </>
  ),
  chart: (
    <>
      <path d="M4 20h16" />
      <path d="M7 20v-6M12 20v-11M17 20v-4" />
    </>
  ),
  export: (
    <>
      <path d="M12 15V4" />
      <path d="M8.5 7.5L12 4l3.5 3.5" />
      <path d="M5 13v5a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-5" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 3v2.5M12 18.5V21M3 12h2.5M18.5 12H21M5.6 5.6l1.8 1.8M16.6 16.6l1.8 1.8M18.4 5.6l-1.8 1.8M7.4 16.6l-1.8 1.8" />
    </>
  ),
  logout: (
    <>
      <path d="M14 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2v-2" />
      <path d="M18 12H9" />
      <path d="m15 9 3 3-3 3" />
    </>
  ),
  cpu: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <path d="M9 3v3M15 3v3M9 18v3M15 18v3M3 9h3M3 15h3M18 9h3M18 15h3" />
    </>
  ),
  refresh: (
    <>
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 4v5h-5" />
    </>
  ),
  eye: (
    <>
      <path d="M2.8 12s3.3-6 9.2-6 9.2 6 9.2 6-3.3 6-9.2 6-9.2-6-9.2-6z" />
      <circle cx="12" cy="12" r="2.5" />
    </>
  ),
  download: (
    <>
      <path d="M12 4v11" />
      <path d="m8.5 11.5 3.5 3.5 3.5-3.5" />
      <path d="M5 19h14" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  check: <path d="M5 12l4 4L19 7" />,
  chevronDown: <path d="M6 9l6 6 6-6" />,
  folderPlus: (
    <>
      <path d="M3 7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
      <path d="M12 11.5v5M9.5 14h5" />
    </>
  ),
  zoomIn: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M21 21l-5-5M10.5 8v5M8 10.5h5" />
    </>
  ),
  zoomOut: (
    <>
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M21 21l-5-5M8 10.5h5" />
    </>
  ),
  hand: <path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V11m0-1.5a1.5 1.5 0 0 1 3 0V11m0-1a1.5 1.5 0 0 1 3 0v4a6 6 0 0 1-6 6h-1a6 6 0 0 1-5.2-3l-1.6-2.8a1.5 1.5 0 0 1 2.6-1.5L8 14" />,
  rotate: (
    <>
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 4v5h-5" />
    </>
  ),
  sheet: (
    <>
      <rect x="4" y="3" width="16" height="18" rx="2" />
      <path d="M9 8l6 8M15 8l-6 8" />
    </>
  ),
  folder: <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />,
  file: (
    <>
      <path d="M6 3h8l4 4v14H6z" />
      <path d="M14 3v5h4" />
    </>
  ),
  edit: (
    <>
      <path d="M4 20h4L18.5 9.5a2.1 2.1 0 0 0-3-3L5 17z" />
      <path d="M13.5 8.5l3 3" />
    </>
  ),
  trash: (
    <>
      <path d="M4 7h16" />
      <path d="M9 7V5a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" />
      <path d="M6 7l1 13a1 1 0 0 0 1 1h8a1 1 0 0 0 1-1l1-13" />
    </>
  ),
  folderOpen: (
    <>
      <path d="M5 19a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h3.5l2 2H19a2 2 0 0 1 2 2" />
      <path d="M3.4 19l2.3-7a1 1 0 0 1 1-.7H21l-2.3 7a1 1 0 0 1-1 .7z" />
    </>
  ),
  fileePlus: <path d="M14 3v5h5M5 3h9l5 5v11a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1z" />,
  photosCheck: (
    <>
      <rect x="3" y="5" width="13" height="11" rx="2" />
      <circle cx="7.5" cy="9.5" r="1.2" />
      <path d="M3.5 14l4-3.5 3 2.5" />
      <circle cx="17.5" cy="16.5" r="4.5" />
      <path d="M15.7 16.5l1.2 1.2 2.2-2.3" />
    </>
  ),
};

export default function Icon({ name, className = "h-5 w-5" }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      {ICONS[name]}
    </svg>
  );
}
