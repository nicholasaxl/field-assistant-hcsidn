import { motion, useReducedMotion } from "motion/react";

/** Contactless-style arcs: the product's one recurring motif. Draws in once, ripples while `active`. */
function arcPath(cx: number, cy: number, r: number, deg: number) {
  const a = (deg * Math.PI) / 180;
  const x = cx + r * Math.cos(a);
  const dy = r * Math.sin(a);
  return `M ${x.toFixed(2)} ${(cy - dy).toFixed(2)} A ${r.toFixed(2)} ${r.toFixed(2)} 0 0 1 ${x.toFixed(2)} ${(cy + dy).toFixed(2)}`;
}

type Props = {
  count?: number;
  size?: number;
  strokeWidth?: number;
  active?: boolean;
  draw?: boolean;
  className?: string;
};

export function Arcs({ count = 4, size, strokeWidth = 5, active = false, draw = false, className }: Props) {
  const reduce = useReducedMotion();
  const arcs = Array.from({ length: count }, (_, i) => ({
    d: arcPath(20, 60, (80 * (i + 1)) / count, 46),
    rest: 1 - (i / count) * 0.6,
    i,
  }));

  return (
    <svg viewBox="0 0 120 120" width={size} height={size} className={className} aria-hidden="true">
      {arcs.map(({ d, rest, i }) => (
        <motion.path
          key={i}
          d={d}
          fill="none"
          stroke="currentColor"
          strokeWidth={strokeWidth}
          strokeLinecap="round"
          initial={draw && !reduce ? { pathLength: 0, opacity: 0 } : false}
          animate={
            active && !reduce
              ? { pathLength: 1, opacity: [rest * 0.25, rest, rest * 0.25] }
              : { pathLength: 1, opacity: rest }
          }
          transition={
            active && !reduce
              ? { duration: 1.5, repeat: Infinity, delay: i * 0.16, ease: "easeInOut" }
              : { duration: 1, delay: draw ? 0.1 + i * 0.14 : 0, ease: [0.22, 1, 0.36, 1] }
          }
        />
      ))}
    </svg>
  );
}
