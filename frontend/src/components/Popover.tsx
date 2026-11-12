// A small anchored popover: render it inside a `relative` wrapper next to its trigger. It
// closes on Escape and on a mouse press outside the wrapper.
import { useEffect, useRef, type ReactNode } from "react";

export function Popover({ open, onClose, children, align = "left", above = false, className = "", label }: {
  open: boolean; onClose: () => void; children: ReactNode; align?: "left" | "right"; above?: boolean; className?: string; label?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const down = (e: MouseEvent) => {
      const wrap = ref.current?.parentElement;
      if (wrap && !wrap.contains(e.target as Node)) onClose();
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); onClose(); }
    };
    document.addEventListener("mousedown", down);
    window.addEventListener("keydown", key, true);
    return () => { document.removeEventListener("mousedown", down); window.removeEventListener("keydown", key, true); };
  }, [open, onClose]);
  if (!open) return null;
  return (
    <div ref={ref} role="dialog" aria-label={label}
      className={`absolute z-30 ${align === "right" ? "right-0" : "left-0"} ${above ? "bottom-full mb-1" : "top-full mt-1"} bg-raised border border-line rounded-md shadow-lg text-text ${className}`}>
      {children}
    </div>
  );
}
