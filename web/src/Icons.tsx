import type { ReactNode } from "react";
import type { DeviceKind } from "./utils";

type IconProps = { className?: string };

function Svg({ children, className = "" }: IconProps & { children: ReactNode }) {
  return (
    <svg className={`icon ${className}`} viewBox="0 0 24 24" aria-hidden="true">
      {children}
    </svg>
  );
}

export const Sun = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="4" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6 17 7M7 17l-1.4 1.4" />
  </Svg>
);
export const Moon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5Z" />
  </Svg>
);
export const LibraryIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4 5h4v14H4zM10 5h4v14h-4z" />
    <path d="m16.2 6.4 3.6-.9 2 12.7-3.6.9z" transform="translate(-1.2 0)" />
  </Svg>
);
export const SourcesIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M7 4h10a2 2 0 0 1 2 2v14l-4-2.5L11 20l-4-2.5-2 1.2V6a2 2 0 0 1 2-2Z" transform="translate(0 -1)" />
    <path d="M9 9h6M9 12.5h4" />
  </Svg>
);
export const InsightsIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M5 20V11M12 20V4M19 20v-6" />
  </Svg>
);
export const GuideIcon = (p: IconProps) => (
  <Svg {...p}>
    <path d="M9 6h11M9 12h11M9 18h11" />
    <path d="m3.5 6 1 1 2-2M3.5 12l1 1 2-2M3.5 18l1 1 2-2" />
  </Svg>
);
export const ThumbUp =(p: IconProps) => (
  <Svg {...p}>
    <path d="M7 11v9H4v-9h3ZM7 11l3.5-7a2 2 0 0 1 2 2.2L12 9h5.6a2 2 0 0 1 2 2.4l-1.3 6.6a2 2 0 0 1-2 1.6H7" />
  </Svg>
);
export const ThumbDown = (p: IconProps) => (
  <Svg {...p}>
    <path d="M17 13V4h3v9h-3ZM17 13l-3.5 7a2 2 0 0 1-2-2.2L12 15H6.4a2 2 0 0 1-2-2.4l1.3-6.6a2 2 0 0 1 2-1.6H17" />
  </Svg>
);
export const Send =(p: IconProps) => (
  <Svg {...p}>
    <path d="M12 19V5M5.5 11.5 12 5l6.5 6.5" />
  </Svg>
);
export const Stop = (p: IconProps) => (
  <Svg {...p}>
    <rect x="6.5" y="6.5" width="11" height="11" rx="2.5" fill="currentColor" stroke="none" />
  </Svg>
);
export const Close = (p: IconProps) => (
  <Svg {...p}>
    <path d="M6 6l12 12M18 6 6 18" />
  </Svg>
);
export const Check = (p: IconProps) => (
  <Svg {...p}>
    <path d="m5 12.5 4.5 4.5L19 7.5" />
  </Svg>
);
export const Upload = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 16V4M7 9l5-5 5 5M5 20h14" />
  </Svg>
);
export const Trash = (p: IconProps) => (
  <Svg {...p}>
    <path d="M4.5 7h15M9.5 7V4.5h5V7M6.5 7l.8 12.5h9.4L17.5 7M10 11v5M14 11v5" />
  </Svg>
);
export const Chevron = (p: IconProps) => (
  <Svg {...p}>
    <path d="m6 9 6 6 6-6" />
  </Svg>
);
export const Copy = (p: IconProps) => (
  <Svg {...p}>
    <rect x="8.5" y="8.5" width="11" height="11" rx="2.5" />
    <path d="M15.5 8.5V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v7.5a2 2 0 0 0 2 2h2.5" />
  </Svg>
);
export const Alert = (p: IconProps) => (
  <Svg {...p}>
    <path d="M12 4 2.8 19.5h18.4L12 4ZM12 10v4.5M12 17.2v.1" />
  </Svg>
);
export const Info = (p: IconProps) => (
  <Svg {...p}>
    <circle cx="12" cy="12" r="8.5" />
    <path d="M12 11v5M12 8v.1" />
  </Svg>
);

export function DeviceIcon({ kind, className }: { kind: DeviceKind } & IconProps) {
  switch (kind) {
    case "pos":
      return (
        <Svg className={className}>
          <rect x="5.5" y="3" width="13" height="18" rx="2.5" />
          <rect x="8.5" y="6" width="7" height="4" rx="1" />
          <path d="M9 14h.1M12 14h.1M15 14h.1M9 17.5h.1M12 17.5h.1M15 17.5h.1" strokeWidth="2.2" />
        </Svg>
      );
    case "atm":
      return (
        <Svg className={className}>
          <rect x="3.5" y="4" width="17" height="16" rx="2.5" />
          <rect x="7" y="7" width="10" height="5" rx="1" />
          <path d="M7.5 16h9" />
        </Svg>
      );
    case "kiosk":
      return (
        <Svg className={className}>
          <rect x="5.5" y="3" width="13" height="12" rx="2.5" />
          <path d="M12 15v4M8 21h8" />
        </Svg>
      );
    default:
      return (
        <Svg className={className}>
          <rect x="4" y="4" width="6.5" height="6.5" rx="1.8" />
          <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.8" />
          <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.8" />
          <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.8" />
        </Svg>
      );
  }
}
