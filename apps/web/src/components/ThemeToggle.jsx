import { useDispatch, useSelector } from 'react-redux';
import { Sun, Moon, Monitor } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu';
import { setTheme } from '@/store/slices/uiSlice';
import { NAV } from '@/constants/testIds';

export default function ThemeToggle() {
  const dispatch = useDispatch();
  const theme = useSelector((s) => s.ui.theme);
  return (
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
  );
}
