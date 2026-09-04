import { useEffect, useState } from 'react';
import api from '@/lib/api';
import { Bell, CheckCheck, Trash2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { format } from 'date-fns';
import { Skeleton } from '@/components/ui/skeleton';

export default function Notifications() {
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(true);

  const load = async () => {
    setLoading(true);
    try {
      const { data } = await api.get('/notifications/');
      setItems(data.items);
    } finally { setLoading(false); }
  };
  useEffect(() => { load(); }, []);

  const markAll = async () => { await api.post('/notifications/mark-all-read'); load(); };
  const del = async (id) => { await api.delete(`/notifications/${id}`); load(); };
  const markRead = async (id) => { await api.post(`/notifications/${id}/read`); load(); };

  return (
    <div className="p-6 md:p-8 max-w-3xl">
      <div className="mb-8 flex items-center justify-between">
        <div>
          <h1 className="font-display text-3xl font-medium tracking-tight">Notifications</h1>
          <p className="text-muted-foreground mt-1">Stay on top of purchases, credits and account activity.</p>
        </div>
        {items.some(n => !n.read) && (
          <Button variant="outline" size="sm" onClick={markAll}><CheckCheck className="h-4 w-4 mr-1" /> Mark all read</Button>
        )}
      </div>

      {loading ? (
        <div className="space-y-2">{[...Array(3)].map((_,i) => <Skeleton key={i} className="h-16 rounded-xl" />)}</div>
      ) : items.length === 0 ? (
        <div className="rounded-xl border border-border bg-card p-16 text-center">
          <Bell className="h-8 w-8 mx-auto text-muted-foreground mb-3" />
          <p className="text-muted-foreground">No notifications yet</p>
        </div>
      ) : (
        <div className="space-y-2">
          {items.map((n) => (
            <div key={n.id} className={`rounded-xl border p-4 flex items-start gap-3 ${n.read ? 'border-border bg-card' : 'border-primary/40 bg-primary/5'}`}>
              <div className={`h-2 w-2 rounded-full mt-2 ${n.read ? 'bg-muted-foreground/50' : 'bg-primary'}`} />
              <div className="flex-1 min-w-0" onClick={() => !n.read && markRead(n.id)}>
                <div className="font-medium">{n.title}</div>
                {n.body && <div className="text-sm text-muted-foreground mt-1">{n.body}</div>}
                <div className="text-xs text-muted-foreground/70 mt-1">{format(new Date(n.created_at), 'PP p')}</div>
              </div>
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={() => del(n.id)}>
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
