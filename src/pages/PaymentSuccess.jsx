import { useEffect, useState } from 'react';
import { useSearchParams, useNavigate } from 'react-router-dom';
import api from '@/lib/api';
import { Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { Button } from '@/components/ui/button';

export default function PaymentSuccess() {
  const [params] = useSearchParams();
  const [status, setStatus] = useState('checking');
  const [detail, setDetail] = useState(null);
  const [attempts, setAttempts] = useState(0);
  const navigate = useNavigate();

  useEffect(() => {
    const linkId = params.get('razorpay_payment_link_id');
    const sessionId = params.get('session_id');  // legacy Stripe support (removed)
    if (!linkId && !sessionId) { setStatus('failed'); return; }
    let cancelled = false;
    const poll = async (n = 0) => {
      if (cancelled) return;
      try {
        const url = linkId
          ? `/payments/razorpay/link-status/${linkId}`
          : `/payments/stripe/status/${sessionId}`;
        const { data } = await api.get(url);
        setDetail(data);
        const paid = data.status === 'paid' || data.payment_status === 'paid';
        const failed = data.status === 'cancelled' || data.status === 'expired';
        if (paid) { setStatus('success'); return; }
        if (failed) { setStatus('failed'); return; }
        if (n >= 8) { setStatus('failed'); return; }
        setAttempts(n + 1);
        setTimeout(() => poll(n + 1), 2000);
      } catch {
        if (n >= 8) { setStatus('failed'); return; }
        setTimeout(() => poll(n + 1), 2000);
      }
    };
    poll(0);
    return () => { cancelled = true; };
  }, [params]);

  return (
    <div className="min-h-screen flex items-center justify-center p-6">
      <div className="max-w-md w-full rounded-2xl border border-border bg-card p-10 text-center">
        {status === 'checking' && (
          <>
            <Loader2 className="h-12 w-12 mx-auto text-primary animate-spin" />
            <h2 className="mt-6 font-display text-2xl font-medium">Confirming your payment…</h2>
            <p className="text-sm text-muted-foreground mt-2">Attempt {attempts + 1}/8. This usually takes a few seconds.</p>
          </>
        )}
        {status === 'success' && (
          <>
            <CheckCircle2 className="h-12 w-12 mx-auto text-emerald-400" />
            <h2 className="mt-6 font-display text-2xl font-medium">Payment successful</h2>
            <p className="text-sm text-muted-foreground mt-2">
              {detail?.credits ? `${Math.floor(detail.credits)} credits added to your wallet.` : 'Your credits have been added.'}
            </p>
            <div className="mt-6 flex gap-2 justify-center">
              <Button onClick={() => navigate('/wallet')}>Go to Wallet</Button>
              <Button variant="outline" onClick={() => navigate('/chat')}>Start chatting</Button>
            </div>
          </>
        )}
        {status === 'failed' && (
          <>
            <XCircle className="h-12 w-12 mx-auto text-destructive" />
            <h2 className="mt-6 font-display text-2xl font-medium">Payment not confirmed</h2>
            <p className="text-sm text-muted-foreground mt-2">If you were charged, your credits will appear shortly.</p>
            <div className="mt-6 flex gap-2 justify-center">
              <Button onClick={() => navigate('/billing')}>Back to Billing</Button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
