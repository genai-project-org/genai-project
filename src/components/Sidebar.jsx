import { useState } from 'react';
import { useSelector, useDispatch } from 'react-redux';
import { NavLink, useNavigate } from 'react-router-dom';
import { toggleSidebar, setTheme } from '@/store/slices/uiSlice';
import { logout } from '@/store/slices/authSlice';
import {
  MessageSquare, Sparkles, BarChart3, Wallet, CreditCard, Bell,
  User as UserIcon, Settings, Shield, PanelLeftClose,
  Briefcase, Rocket, FileText, GraduationCap, MessagesSquare, Users, Lock, Plus, LogOut,
  Sun, Moon, Monitor, FlaskConical, Heart, Award, MapPin, Wrench, Code2, ChevronDown
} from 'lucide-react';
import { NAV } from '@/constants/testIds';
import { cn } from '@/lib/utils';
import { Button } from '@/components/ui/button';
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';

const SECTIONS = [
  { key: 'ai', title: 'AI', items: [
    { to: '/studio', label: 'AI Studio', Icon: Sparkles, tid: 'nav-studio' },
    { to: '/chat', label: 'AI Workspace', Icon: MessageSquare, tid: NAV.linkChat },
  ] },
  { key: 'build', title: 'Build', items: [
    { label: 'Code Builder', Icon: Code2, children: [
      { to: '/builder', label: 'Static Builder', Icon: FileText, tid: 'nav-builder' },
      { label: 'Dynamic Builder', Icon: Rocket, locked: true },
    ] },
  ] },
  { key: 'learn', title: 'Learn', items: [
    { to: '/counseling', label: 'Counseling', Icon: Heart, tid: 'nav-counseling' },
    { to: '/career', label: 'Career Intelligence', Icon: Briefcase, tid: 'nav-career' },
  ] },
  { key: 'account', title: 'Account', items: [
    { to: '/usage', label: 'Usage', Icon: BarChart3, tid: NAV.linkUsage },
    { to: '/wallet', label: 'Credit Wallet', Icon: Wallet, tid: NAV.linkWallet },
    { to: '/billing', label: 'Billing', Icon: CreditCard, tid: NAV.linkBilling },
    { to: '/notifications', label: 'Notifications', Icon: Bell, tid: NAV.linkNotifications },
    { to: '/profile', label: 'Profile', Icon: UserIcon, tid: NAV.linkProfile },
    { to: '/settings', label: 'Settings', Icon: Settings, tid: NAV.linkSettings },
  ] },
];

const comingSoon = [
  { label: 'Startup Intelligence', Icon: Rocket },
  { label: 'Research Intelligence', Icon: FlaskConical },
  { label: 'Dynamic Course Engine', Icon: GraduationCap },
  { label: 'Resume Intelligence', Icon: FileText },
  { label: 'Mock Interviews', Icon: MessagesSquare },
  { label: 'Scholarships', Icon: Award },
  { label: 'Internships', Icon: MapPin },
  { label: 'Freelance Intelligence', Icon: Wrench },
];

export default function Sidebar({ onMobileClose, mobile = false }) {
  const collapsed = useSelector((s) => s.ui.sidebarCollapsed) && !mobile;
  const wallet = useSelector((s) => s.ui.walletBalance);
  const theme = useSelector((s) => s.ui.theme);
  const user = useSelector((s) => s.auth.user);
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const [open, setOpen] = useState({});  // section/submenu keys default to open

  const handleLogout = () => {
    dispatch(logout());
    navigate('/');
  };

  const linkClass = ({ isActive }) => cn(
    'group flex items-center gap-3 rounded-md px-2.5 py-2 text-sm transition-colors',
    'hover:bg-accent hover:text-accent-foreground',
    collapsed && 'justify-center',
    isActive ? 'bg-accent text-foreground font-medium' : 'text-muted-foreground'
  );

  const renderLeaf = ({ to, label, Icon, tid, locked, indent }) => {
    const pad = indent && !collapsed && 'pl-8';
    if (locked) {
      const el = (
        <div key={label} className={cn('flex items-center gap-3 rounded-md px-2.5 py-2 text-sm text-muted-foreground/60 cursor-not-allowed', collapsed && 'justify-center', pad)}>
          <Icon className="h-4 w-4 flex-shrink-0" strokeWidth={1.5} />
          {!collapsed && <span className="truncate flex-1">{label}</span>}
          {!collapsed && <Lock className="h-3 w-3 opacity-60" strokeWidth={2} />}
        </div>
      );
      return collapsed ? (
        <Tooltip key={label}><TooltipTrigger asChild>{el}</TooltipTrigger><TooltipContent side="right">{label} (locked)</TooltipContent></Tooltip>
      ) : el;
    }
    const link = (
      <NavLink key={to} to={to} className={(s) => cn(linkClass(s), pad)} data-testid={tid} onClick={onMobileClose}>
        <Icon className="h-4 w-4 flex-shrink-0" strokeWidth={1.75} />
        {!collapsed && <span className="truncate">{label}</span>}
      </NavLink>
    );
    return collapsed ? (
      <Tooltip key={to}>
        <TooltipTrigger asChild>{link}</TooltipTrigger>
        <TooltipContent side="right">{label}</TooltipContent>
      </Tooltip>
    ) : link;
  };

  const renderNav = (items) => items.flatMap((item) => {
    if (!item.children) return [renderLeaf(item)];
    if (collapsed) {
      // icon-only: show just the parent icon (linking to its first real route), not sub-items
      const first = item.children.find((c) => c.to) || {};
      return [renderLeaf({ to: first.to, label: item.label, Icon: item.Icon, tid: first.tid })];
    }
    const kids = item.children.map((c) => renderLeaf({ ...c, indent: true }));
    const isOpen = open[item.label] !== false;  // default expanded
    const parent = (
      <button
        key={item.label}
        type="button"
        onClick={() => setOpen((o) => ({ ...o, [item.label]: o[item.label] === false }))}
        className={cn(linkClass({ isActive: false }), 'w-full text-left')}
      >
        <item.Icon className="h-4 w-4 flex-shrink-0" strokeWidth={1.75} />
        <span className="truncate flex-1">{item.label}</span>
        <ChevronDown className={cn('h-3.5 w-3.5 transition-transform', !isOpen && '-rotate-90')} strokeWidth={2} />
      </button>
    );
    return isOpen ? [parent, ...kids] : [parent];
  });

  const renderSection = (key, title, items) => {
    if (collapsed) return renderNav(items);  // icon-only: no headers, always shown
    const isOpen = open[key] !== false;  // default expanded
    return (
      <>
        <button
          type="button"
          onClick={() => setOpen((o) => ({ ...o, [key]: o[key] === false }))}
          className="flex items-center gap-1 w-full px-2.5 pb-2 text-[11px] uppercase tracking-wider text-muted-foreground/70 font-medium hover:text-muted-foreground"
        >
          <ChevronDown className={cn('h-3 w-3 transition-transform', !isOpen && '-rotate-90')} strokeWidth={2.5} />
          <span>{title}</span>
        </button>
        {isOpen && renderNav(items)}
      </>
    );
  };

  return (
    <TooltipProvider delayDuration={200}>
      <aside
        data-testid={NAV.sidebar}
        className={cn(
          'flex flex-col h-full bg-[hsl(var(--surface))] border-r border-border transition-[width] duration-200 ease-out',
          collapsed ? 'w-[64px]' : 'w-[260px]',
          mobile && 'w-[280px]'
        )}
      >
        {/* Top: Logo + Collapse */}
        <div className={cn('flex items-center h-14 border-b border-border px-3', collapsed ? 'justify-center' : 'justify-between')}>
          {collapsed ? (
            <button
              data-testid={NAV.sidebarToggle}
              onClick={() => dispatch(toggleSidebar())}
              title="Expand sidebar"
              className="h-8 w-8 rounded-md bg-primary flex items-center justify-center"
            >
              <Sparkles className="h-4 w-4 text-primary-foreground" strokeWidth={2} />
            </button>
          ) : (
            <>
              <NavLink to="/chat" data-testid={NAV.logo} className="flex items-center gap-2 min-w-0" onClick={onMobileClose}>
                <div className="h-7 w-7 rounded-md bg-primary flex items-center justify-center flex-shrink-0">
                  <Sparkles className="h-4 w-4 text-primary-foreground" strokeWidth={2} />
                </div>
                <span className="font-display font-semibold text-[15px] tracking-tight">supercreator<span className="text-primary">.</span>ai</span>
              </NavLink>
              {!mobile && (
                <Button
                  data-testid={NAV.sidebarToggle}
                  variant="ghost" size="icon"
                  className="h-7 w-7 flex-shrink-0"
                  onClick={() => dispatch(toggleSidebar())}
                >
                  <PanelLeftClose className="h-4 w-4" />
                </Button>
              )}
            </>
          )}
        </div>

        {/* New chat */}
        <div className="p-2">
          <NavLink
            to="/chat?new=1"
            data-testid={NAV.newChatBtn}
            onClick={onMobileClose}
            className={cn(
              'flex items-center gap-2 w-full rounded-md border border-border bg-background px-3 py-2 text-sm font-medium',
              'hover:bg-accent hover:border-border transition-colors',
              collapsed && 'justify-center'
            )}
          >
            <Plus className="h-4 w-4" strokeWidth={2} />
            {!collapsed && <span>New Chat</span>}
          </NavLink>
        </div>

        {/* Main nav */}
        <nav className="flex-1 overflow-y-auto px-2 pb-2 space-y-0.5">
          {SECTIONS.map((s, i) => (
            <div key={s.key} className={cn(i > 0 && !collapsed && 'pt-4')}>
              {renderSection(s.key, s.title, s.items)}
            </div>
          ))}

          {user?.role === 'admin' && (
            <NavLink to="/admin" className={linkClass} data-testid={NAV.linkAdmin} onClick={onMobileClose}>
              <Shield className="h-4 w-4 flex-shrink-0" strokeWidth={1.75} />
              {!collapsed && <span>Admin</span>}
            </NavLink>
          )}

          {!collapsed && (
            <div className="pt-6">
              <div className="px-2.5 pb-2 text-[11px] uppercase tracking-wider text-muted-foreground/70 font-medium">
                Coming Soon
              </div>
              {comingSoon.map(({ label, Icon }) => (
                <div key={label} className="flex items-center gap-3 px-2.5 py-2 text-sm text-muted-foreground/60 cursor-not-allowed">
                  <Icon className="h-4 w-4 flex-shrink-0" strokeWidth={1.5} />
                  <span className="truncate flex-1">{label}</span>
                  <Lock className="h-3 w-3 opacity-60" strokeWidth={2} />
                </div>
              ))}
            </div>
          )}
        </nav>

        {/* Footer: wallet + user */}
        <div className="border-t border-border p-2 space-y-1">
          {!collapsed && wallet !== null && (
            <div className="rounded-md bg-background border border-border p-3">
              <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Credits</div>
              <div className="font-display font-semibold text-lg" data-testid="sidebar-wallet-total">
                {Math.floor(wallet).toLocaleString()}
              </div>
              <NavLink to="/billing" className="text-xs text-primary hover:underline">Recharge →</NavLink>
            </div>
          )}
          <div className={cn('flex items-center gap-2 rounded-md hover:bg-accent transition-colors p-2', collapsed && 'justify-center')}>
            <div className="h-8 w-8 rounded-full bg-primary/15 flex items-center justify-center text-primary text-sm font-semibold flex-shrink-0">
              {(user?.name || user?.email || '?').charAt(0).toUpperCase()}
            </div>
            {!collapsed && (
              <>
                <div className="min-w-0 flex-1">
                  <div className="text-sm truncate font-medium">{user?.name}</div>
                  <div className="text-xs truncate text-muted-foreground">{user?.email}</div>
                </div>
                <Button
                  variant="ghost" size="icon" className="h-7 w-7"
                  onClick={handleLogout}
                  data-testid="auth-logout-btn"
                  title="Logout"
                >
                  <LogOut className="h-4 w-4" />
                </Button>
              </>
            )}
          </div>
          {!collapsed && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="w-full justify-start gap-2 text-muted-foreground" data-testid={NAV.themeToggle}>
                  {theme === 'dark' ? <Moon className="h-4 w-4" /> : theme === 'light' ? <Sun className="h-4 w-4" /> : <Monitor className="h-4 w-4" />}
                  <span className="capitalize">{theme} theme</span>
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start">
                <DropdownMenuItem onClick={() => dispatch(setTheme('light'))}><Sun className="h-4 w-4 mr-2" /> Light</DropdownMenuItem>
                <DropdownMenuItem onClick={() => dispatch(setTheme('dark'))}><Moon className="h-4 w-4 mr-2" /> Dark</DropdownMenuItem>
                <DropdownMenuItem onClick={() => dispatch(setTheme('system'))}><Monitor className="h-4 w-4 mr-2" /> System</DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </aside>
    </TooltipProvider>
  );
}
