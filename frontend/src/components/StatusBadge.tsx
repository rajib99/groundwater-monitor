interface StatusBadgeProps {
  status: "normal" | "warning" | "critical" | "low" | "medium" | "high";
  label?: string;
  size?: "sm" | "md";
}

const CONFIG = {
  normal:   { dot: "bg-green-500",  text: "text-green-400",  bg: "bg-green-500/10",  border: "border-green-500/30",  label: "Normal"   },
  low:      { dot: "bg-blue-400",   text: "text-blue-400",   bg: "bg-blue-400/10",   border: "border-blue-400/30",   label: "Low"      },
  medium:   { dot: "bg-amber-400",  text: "text-amber-400",  bg: "bg-amber-400/10",  border: "border-amber-400/30",  label: "Medium"   },
  warning:  { dot: "bg-amber-400",  text: "text-amber-400",  bg: "bg-amber-400/10",  border: "border-amber-400/30",  label: "Warning"  },
  high:     { dot: "bg-orange-400", text: "text-orange-400", bg: "bg-orange-400/10", border: "border-orange-400/30", label: "High"     },
  critical: { dot: "bg-red-500",    text: "text-red-400",    bg: "bg-red-500/10",    border: "border-red-500/30",    label: "Critical" },
};

export default function StatusBadge({ status, label, size = "md" }: StatusBadgeProps) {
  const c = CONFIG[status];
  const pad = size === "sm" ? "px-2 py-0.5 text-xs" : "px-2.5 py-1 text-xs";
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full border font-medium ${pad} ${c.bg} ${c.border} ${c.text}`}>
      <span className={`size-1.5 rounded-full ${c.dot}`} />
      {label ?? c.label}
    </span>
  );
}
