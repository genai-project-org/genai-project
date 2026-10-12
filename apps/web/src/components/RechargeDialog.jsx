import { useDispatch, useSelector } from 'react-redux';
import { useNavigate } from 'react-router-dom';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { hideRecharge } from '@/store/slices/uiSlice';
import { usePricing, fmtCredits, fmtUsd } from '@/lib/pricing';

/** Friendly prompt shown (instead of an error) whenever an action needs more credits than the wallet has. */
export default function RechargeDialog() {
  const dispatch = useDispatch();
  const navigate = useNavigate();
  const prompt = useSelector((s) => s.ui.rechargePrompt);
  const { pricing } = usePricing();
  const close = () => dispatch(hideRecharge());
  const go = () => { close(); navigate('/billing'); };

  return (
    <Dialog open={!!prompt} onOpenChange={(o) => { if (!o) close(); }}>
      <DialogContent data-testid="recharge-dialog">
        <DialogHeader>
          <DialogTitle>Time for a quick recharge</DialogTitle>
          <DialogDescription>
            You need a few more credits for that.
            {prompt?.needed != null && prompt?.balance != null && (
              <> It costs {fmtCredits(prompt.needed)} and you have {fmtCredits(prompt.balance)}.</>
            )}
            {pricing && <> Add credits from {fmtUsd(pricing.payg.min_usd)}, or pick a pack. They never expire.</>}
            {pricing && pricing.daily_credits > 0 && <> Your {fmtCredits(pricing.daily_credits)} free daily credits refill every day.</>}
          </DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" onClick={close}>Not now</Button>
          <Button onClick={go} data-testid="recharge-go">Recharge</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
