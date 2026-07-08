interface PageShellProps {
  title: string;
  subtitle: string;
}

export default function PageShell({ title, subtitle }: PageShellProps) {
  return (
    <div className="bg-bento-card border border-slate-800 rounded-2xl p-6 shadow-md" id={`${title.toLowerCase().replace(/\s+/g, "-")}-shell`}>
      <div className="space-y-2">
        <h3 className="text-sm font-semibold text-white tracking-tight font-sans">{title}</h3>
        <p className="text-xs text-slate-500 leading-relaxed max-w-2xl">{subtitle}</p>
      </div>
    </div>
  );
}
