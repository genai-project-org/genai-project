import { useEffect, useState } from 'react';
import { Outlet, Navigate, useNavigate } from 'react-router-dom';
import { useDispatch, useSelector } from 'react-redux';
import Sidebar from './Sidebar';
import api from '@/lib/api';
import { setWalletBalance } from '@/store/slices/uiSlice';
import { Menu, Sun, Moon, Monitor } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetTrigger } from '@/components/ui/sheet';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { setTheme } from '@/store/slices/uiSlice';
import { NAV } from '@/constants/testIds';

export default function AppLayout() {
  const dispatch = useDispatch();
  const { access_token } = useSelector((s) => s.auth);
  const theme = useSelector((s) => s.ui.theme);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    if (access_token) {
      api.get('/wallet/').then((r) => dispatch(setWalletBalance(r.data.total))).catch(() => {});
    }
    // eslint-disable-next-line
  }, [access_token]);

  if (!access_token) return <Navigate to="/login" replace />;

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-background">
      {/* Desktop sidebar */}
      <div className="hidden md:block h-full">
        <Sidebar />
      </div>

      {/* Mobile drawer */}
      <div className="md:hidden">
        <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
          <SheetContent side="left" className="p-0 w-[280px]">
            <Sidebar mobile onMobileClose={() => setMobileOpen(false)} />
          </SheetContent>
        </Sheet>
      </div>

      <main className="flex-1 flex flex-col min-w-0">
        {/* Mobile top bar */}
        <div className="md:hidden flex items-center justify-between px-3 h-14 border-b border-border glass sticky top-0 z-30">
          <Button variant="ghost" size="icon" onClick={() => setMobileOpen(true)} data-testid={NAV.mobileMenuBtn}>
            <Menu className="h-5 w-5" />
          </Button>
          <div className="font-display font-semibold">supercreator<span className="text-primary">.</span>ai</div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon" data-testid={NAV.themeToggle}>
                {theme === 'dark' ? <Moon className="h-4 w-4" /> : theme === 'light' ? <Sun className="h-4 w-4" /> : <Monitor className="h-4 w-4" />}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => dispatch(setTheme('light'))}><Sun className="h-4 w-4 mr-2" /> Light</DropdownMenuItem>
              <DropdownMenuItem onClick={() => dispatch(setTheme('dark'))}><Moon className="h-4 w-4 mr-2" /> Dark</DropdownMenuItem>
              <DropdownMenuItem onClick={() => dispatch(setTheme('system'))}><Monitor className="h-4 w-4 mr-2" /> System</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        <div className="flex-1 overflow-y-auto">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
