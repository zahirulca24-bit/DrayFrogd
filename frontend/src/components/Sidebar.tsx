import {
  Activity,
  BookOpen,
  ChevronLeft,
  ChevronRight,
  LayoutDashboard,
  LineChart,
  LogOut,
  Radio,
  Settings,
  ShieldAlert,
  Sliders,
  TrendingUp,
  X,
} from "lucide-react";

interface SidebarProps {
  activeTab: string;
  setActiveTab: (tab: string) => void;
  collapsed: boolean;
  setCollapsed: (collapsed: boolean) => void;
  mobileOpen: boolean;
  setMobileOpen: (open: boolean) => void;
  onLogout: () => void;
}

export default function Sidebar({
  activeTab,
  setActiveTab,
  collapsed,
  setCollapsed,
  mobileOpen,
  setMobileOpen,
  onLogout,
}: SidebarProps) {
  const menuItems = [
    { id: "dashboard", label: "Dashboard", icon: LayoutDashboard },
    { id: "signal-engine", label: "Signal Engine", icon: Radio },
    { id: "active-trades", label: "Active Trades", icon: Activity },
    { id: "journal", label: "Journal / Trade History", icon: BookOpen },
    { id: "performance-strategy", label: "Performance & Strategy", icon: LineChart },
    { id: "control-panel", label: "Control Panel", icon: Sliders },
    { id: "watchdog", label: "Watchdog", icon: ShieldAlert },
    { id: "settings", label: "Settings", icon: Settings },
  ];

  return (
    <>
      <div
        className={`fixed inset-0 z-30 bg-black/60 transition-opacity duration-300 md:hidden ${
          mobileOpen ? "opacity-100" : "pointer-events-none opacity-0"
        }`}
        onClick={() => setMobileOpen(false)}
      />
      <aside
        id="app-sidebar"
        className={`fixed inset-y-0 left-0 z-40 bg-[#12141C] border-r border-slate-800 flex flex-col transition-all duration-300 text-slate-400 select-none md:static md:z-auto ${
          mobileOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"
        } ${collapsed ? "md:w-16" : "md:w-64"} w-[86vw] max-w-[320px]`}
      >
      <div className="p-4 border-b border-slate-800 flex items-center justify-between" id="sidebar-brand-section">
        {!collapsed && (
          <div className="flex items-center space-x-2" id="sidebar-logo-text">
            <TrendingUp className="w-5 h-5 text-rose-500 shrink-0" />
            <span className="font-bold text-white tracking-wider font-sans text-sm uppercase">DayFrogd-ScalpingEngin</span>
          </div>
        )}
        {collapsed && <TrendingUp className="w-5 h-5 text-rose-500 mx-auto" />}
        <button
          id="sidebar-toggle-collapse-btn"
          onClick={() => setCollapsed(!collapsed)}
          className="p-1 rounded-md hover:bg-slate-800 hover:text-white transition-colors cursor-pointer hidden md:block"
          title={collapsed ? "Expand Sidebar" : "Collapse Sidebar"}
        >
          {collapsed ? <ChevronRight className="w-4 h-4" /> : <ChevronLeft className="w-4 h-4" />}
        </button>
        <button
          type="button"
          onClick={() => setMobileOpen(false)}
          className="p-1 rounded-md hover:bg-slate-800 hover:text-white transition-colors cursor-pointer md:hidden"
          title="Close Navigation"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <div className="p-3 border-b border-slate-800/60 bg-[#0F1117]" id="sidebar-security-badge">
        <div className={`flex items-center ${collapsed ? "justify-center" : "space-x-2"}`}>
          <ShieldAlert className="w-4 h-4 text-emerald-400 shrink-0 animate-pulse" />
          {!collapsed && (
            <div className="text-left leading-none">
              <p className="text-[10px] font-mono text-emerald-400 font-semibold">SECURE SESSION</p>
              <p className="text-[8px] text-slate-500 font-mono mt-0.5">LOCAL AGENT MODE</p>
            </div>
          )}
        </div>
      </div>

      <nav className="flex-1 p-3 space-y-1.5 overflow-y-auto" id="sidebar-navigation-items">
        {menuItems.map((item) => {
          const IconComponent = item.icon;
          const isActive = activeTab === item.id;
          return (
            <button
              id={`nav-${item.id}`}
              key={item.id}
              onClick={() => {
                setActiveTab(item.id);
                setMobileOpen(false);
              }}
              className={`w-full flex items-center p-2.5 rounded-lg text-sm font-medium transition-all cursor-pointer group ${
                isActive
                  ? "bg-rose-500/10 text-rose-400 border border-rose-500/20"
                  : "hover:bg-slate-800/30 hover:text-slate-200 border border-transparent"
              } ${collapsed ? "justify-center" : "space-x-3"}`}
              title={collapsed ? item.label : undefined}
            >
              <IconComponent
                className={`w-4 h-4 shrink-0 transition-colors ${
                  isActive ? "text-rose-400" : "text-slate-400 group-hover:text-slate-200"
                }`}
              />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </button>
          );
        })}
      </nav>

      <div className="p-3 border-t border-slate-800" id="sidebar-footer-section">
        <div className="pb-3 text-[10px] font-mono text-slate-500 leading-tight">
          <div className="text-emerald-400 font-semibold uppercase tracking-wider">DayFrogd-ScalpingEngin</div>
          {!collapsed && <div className="mt-1">Frontend control shell</div>}
        </div>
        <button
          id="logout-btn"
          onClick={() => {
            setMobileOpen(false);
            onLogout();
          }}
          className={`w-full flex items-center p-2.5 rounded-lg text-sm font-medium text-slate-500 hover:bg-slate-950 hover:text-rose-400 transition-all cursor-pointer ${
            collapsed ? "justify-center" : "space-x-3"
          }`}
          title={collapsed ? "Logout System" : undefined}
        >
          <LogOut className="w-4 h-4 shrink-0" />
          {!collapsed && <span className="truncate">Exit Session</span>}
        </button>
      </div>
      </aside>
    </>
  );
}
